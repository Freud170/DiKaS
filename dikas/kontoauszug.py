"""Jährlicher Kontoauszug per E-Mail: Mails erzeugen, per SMTP versenden, Versand protokollieren."""

import smtplib
import socket
import ssl
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Callable, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from dikas import buchhaltung
from dikas.db.models import Konto, KontoTyp, Mailversand
from dikas.einstellungen import SSL, STARTTLS, Einstellungen
from dikas.geld import cent_zu_text


class VersandFehler(Exception):
    """Verbindung oder Anmeldung beim Mailserver ist fehlgeschlagen."""


@dataclass(frozen=True)
class Kontoauszug:
    konto: Konto
    saldo: int  # Cent zum Stichtag
    stichtag: date
    empfaenger: str
    betreff: str
    text: str

    @property
    def art(self) -> str:
        if self.saldo < 0:
            return "offen"
        return "Guthaben" if self.saldo > 0 else "ausgeglichen"


def platzhalter(konto: Konto, saldo: int, stichtag: date, e: Einstellungen) -> dict[str, str]:
    werte = {
        "anrede": konto.bierspitz or konto.vorname or konto.name,
        "name": konto.name,
        "vorname": konto.vorname,
        "nachname": konto.nachname,
        "bierspitz": konto.bierspitz,
        "stichtag": stichtag.strftime("%d.%m.%Y"),
        "saldo": cent_zu_text(saldo),
        "betrag": cent_zu_text(abs(saldo)),
        "kontoinhaber": e.kontoinhaber,
        "iban": e.iban,
        "bic": e.bic,
        "bank": e.bank,
        "absender": e.absender_name,
    }
    werte["verwendungszweck"] = e.verwendungszweck.format_map(werte)
    return werte


def erstelle_auszug(konto: Konto, saldo: int, stichtag: date, e: Einstellungen) -> Kontoauszug:
    werte = platzhalter(konto, saldo, stichtag, e)
    vorlage = e.text_negativ if saldo < 0 else e.text_positiv if saldo > 0 else e.text_null
    return Kontoauszug(
        konto=konto,
        saldo=saldo,
        stichtag=stichtag,
        empfaenger=konto.email,
        betreff=e.betreff.format_map(werte),
        text=vorlage.format_map(werte),
    )


def empfaenger_liste(session: Session, stichtag: date) -> list[tuple[Konto, int]]:
    """Alle nicht gelöschten Privatkonten mit Saldo zum Stichtag, nach Nach- und Vorname sortiert."""
    salden = buchhaltung.salden(session, bis=stichtag)
    konten = session.scalars(
        select(Konto)
        .where(Konto.typ == KontoTyp.PRIVAT, ~Konto.geloescht)
        .order_by(Konto.nachname, Konto.vorname)
    )
    return [(k, salden[k.id]) for k in konten]


def bereits_versendet(session: Session, stichtag: date) -> set[int]:
    """IDs der Konten, die für diesen Stichtag schon erfolgreich eine Mail bekommen haben."""
    return set(session.scalars(
        select(Mailversand.konto_id).where(Mailversand.stichtag == stichtag, Mailversand.erfolgreich)
    ))


def letzter_versand(session: Session) -> dict[int, Mailversand]:
    """Letzter erfolgreicher Versand je Konto."""
    ergebnis: dict[int, Mailversand] = {}
    for v in session.scalars(
        select(Mailversand).where(Mailversand.erfolgreich).order_by(Mailversand.gesendet_am)
    ):
        ergebnis[v.konto_id] = v
    return ergebnis


def als_email(auszug: Kontoauszug, e: Einstellungen, an: str | None = None, betreff_zusatz: str = "") -> EmailMessage:
    nachricht = EmailMessage()
    nachricht["From"] = formataddr((e.absender_name, e.absender_email))
    nachricht["To"] = an or auszug.empfaenger
    nachricht["Subject"] = betreff_zusatz + auszug.betreff
    nachricht["Message-ID"] = make_msgid(domain=e.absender_email.split("@")[-1] or None)
    nachricht.set_content(auszug.text)
    return nachricht


# --- SMTP -----------------------------------------------------------------

class Verbindung(Protocol):
    def send_message(self, nachricht: EmailMessage) -> object: ...
    def quit(self) -> object: ...


def verbinden(e: Einstellungen, passwort: str, timeout: float = 30) -> smtplib.SMTP:
    """Verbindung zum Mailserver aufbauen und anmelden. Wirft VersandFehler mit verständlicher Meldung."""
    kontext = ssl.create_default_context()
    try:
        if e.smtp_verschluesselung == SSL:
            smtp = smtplib.SMTP_SSL(e.smtp_server, e.smtp_port, timeout=timeout, context=kontext)
        else:
            smtp = smtplib.SMTP(e.smtp_server, e.smtp_port, timeout=timeout)
            smtp.ehlo()
            if e.smtp_verschluesselung == STARTTLS:
                smtp.starttls(context=kontext)
                smtp.ehlo()
        if e.smtp_benutzer:
            smtp.login(e.smtp_benutzer, passwort)
        return smtp
    except smtplib.SMTPAuthenticationError:
        hinweis = " Bei Gmail wird ein App-Passwort benötigt." if "gmail" in e.smtp_server else ""
        raise VersandFehler(f"Anmeldung fehlgeschlagen: Benutzername oder Passwort falsch.{hinweis}") from None
    except (socket.gaierror, ConnectionRefusedError, TimeoutError, socket.timeout):
        raise VersandFehler(
            f"Mailserver {e.smtp_server}:{e.smtp_port} nicht erreichbar. "
            "Internetverbindung und Servereinstellungen prüfen."
        ) from None
    except ssl.SSLError as fehler:
        raise VersandFehler(f"Verschlüsselung fehlgeschlagen ({fehler.reason}). Port/Verschlüsselung prüfen.") from None
    except (smtplib.SMTPException, OSError) as fehler:
        raise VersandFehler(f"Verbindung zum Mailserver fehlgeschlagen: {fehler}") from None


Verbinder = Callable[[Einstellungen, str], Verbindung]


@dataclass(frozen=True)
class Ergebnis:
    auszug: Kontoauszug
    erfolgreich: bool
    fehler: str = ""


def testmail_senden(auszug: Kontoauszug, e: Einstellungen, passwort: str, verbinder: Verbinder = verbinden) -> None:
    """Schickt den Auszug zur Kontrolle an die eigene Absenderadresse (wird nicht protokolliert)."""
    verbindung = verbinder(e, passwort)
    try:
        verbindung.send_message(als_email(auszug, e, an=e.absender_email, betreff_zusatz="[TEST] "))
    except (smtplib.SMTPException, OSError) as fehler:
        raise VersandFehler(f"Testmail konnte nicht gesendet werden: {fehler}") from None
    finally:
        _beenden(verbindung)


def versenden(
    session: Session,
    auszuege: list[Kontoauszug],
    e: Einstellungen,
    passwort: str,
    verbinder: Verbinder = verbinden,
    fortschritt: Callable[[int, Kontoauszug], bool] | None = None,
) -> list[Ergebnis]:
    """Versendet alle Auszüge über eine Verbindung und protokolliert jeden Versuch.

    `fortschritt(i, auszug)` wird vor jeder Mail aufgerufen; gibt sie False zurück, wird abgebrochen.
    Scheitert eine einzelne Mail, geht es mit der nächsten weiter (bei Verbindungsabbruch
    wird einmal neu verbunden). Verbindungs-/Anmeldefehler am Anfang werfen VersandFehler.
    """
    verbindung = verbinder(e, passwort)
    ergebnisse = []
    try:
        for i, auszug in enumerate(auszuege):
            if fortschritt and fortschritt(i, auszug) is False:
                break
            try:
                try:
                    verbindung.send_message(als_email(auszug, e))
                except smtplib.SMTPServerDisconnected:
                    verbindung = verbinder(e, passwort)
                    verbindung.send_message(als_email(auszug, e))
                ergebnis = Ergebnis(auszug, True)
            except (smtplib.SMTPException, OSError, VersandFehler) as fehler:
                ergebnis = Ergebnis(auszug, False, str(fehler)[:500])
            ergebnisse.append(ergebnis)
            session.add(Mailversand(
                konto_id=auszug.konto.id, stichtag=auszug.stichtag, saldo_cent=auszug.saldo,
                empfaenger=auszug.empfaenger, erfolgreich=ergebnis.erfolgreich, fehler=ergebnis.fehler,
            ))
            session.flush()
    finally:
        _beenden(verbindung)
    return ergebnisse


def _beenden(verbindung: Verbindung) -> None:
    try:
        verbindung.quit()
    except (smtplib.SMTPException, OSError):
        pass
