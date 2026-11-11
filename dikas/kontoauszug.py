"""Jährlicher Kontoauszug per E-Mail: Mails erzeugen, per SMTP versenden, Versand protokollieren."""

import re
import smtplib
import socket
import ssl
from dataclasses import dataclass, replace
from datetime import date, datetime
from email.errors import MessageError
from html import escape
from email.message import EmailMessage
from email.utils import formataddr, localtime, make_msgid
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
class PdfAnhang:
    dateiname: str
    inhalt: bytes


@dataclass(frozen=True)
class Kontoauszug:
    konto: Konto
    saldo: int  # Cent zum Stichtag
    stichtag: date
    empfaenger: str
    betreff: str
    text: str
    pdf: PdfAnhang | None = None  # Umsätze des Jahres als PDF

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
        # Der Verwendungszweck kann sich nicht selbst enthalten. Die Einstellungen lehnen das
        # ab; steht es in älteren Daten trotzdem drin, bleibt die Stelle leer statt abzustürzen.
        "verwendungszweck": "",
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
    konten = sorted(
        session.scalars(select(Konto).where(Konto.typ == KontoTyp.PRIVAT, ~Konto.geloescht)),
        key=buchhaltung.sortierschluessel,
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
    # Pflicht laut RFC 5322. Python setzt das Datum nicht selbst; ohne nehmen Mailserver die
    # Mail zwar an, Spamfilter verwerfen sie aber oft stillschweigend.
    nachricht["Date"] = localtime()
    nachricht["Message-ID"] = make_msgid(domain=e.absender_email.split("@")[-1] or None)
    nachricht.set_content(auszug.text)
    if auszug.pdf is not None:
        nachricht.add_attachment(
            auszug.pdf.inhalt, maintype="application", subtype="pdf", filename=auszug.pdf.dateiname
        )
    return nachricht


# --- Umsätze als PDF ------------------------------------------------------

def umsatz_zeitraum(stichtag: date) -> tuple[date, date]:
    """Vom 01.01. des Stichtagsjahres bis zum Stichtag."""
    return date(stichtag.year, 1, 1), stichtag


def pdf_dateiname(konto: Konto, stichtag: date) -> str:
    name = "_".join(t for t in (konto.nachname, konto.vorname) if t) or konto.name
    name = re.sub(r"[^\w-]+", "_", name).strip("_") or "Mitglied"
    return f"Kontoauszug_{stichtag.year}_{name}.pdf"


def umsaetze_html(u: buchhaltung.Umsaetze, verein: str = "") -> str:
    """Kontoauszug eines Mitglieds als HTML (Grundlage für das PDF)."""
    grau, rot = "#5f6b7a", "#b3261e"

    def euro(cent: int, fett: bool = False) -> str:
        stil = f"color:{rot};" if cent < 0 else ""
        stil += "font-weight:bold;" if fett else ""
        return f"<td align='right' nowrap style='{stil}'>{cent_zu_text(cent)}</td>"

    teile = [
        "<html><body style='font-family:Segoe UI; font-size:9pt'>",
        f"<p style='color:{grau}; margin:0'>{escape(verein)}</p>" if verein else "",
        f"<h2 style='margin:0'>Kontoauszug {escape(u.konto.name)}</h2>",
        f"<p style='color:{grau}'>Zeitraum {u.von:%d.%m.%Y} – {u.bis:%d.%m.%Y} · "
        f"erstellt am {datetime.now():%d.%m.%Y}</p>",
        "<table width='100%' cellspacing='0' cellpadding='4' border='0'>",
        f"<tr bgcolor='#e8f0fa' style='color:{grau}'><th align='left'>Datum</th><th align='left'>Art</th>"
        "<th align='left'>Text</th><th align='left'>Gegenkonto</th>"
        "<th align='right'>Betrag</th><th align='right'>Kontostand</th></tr>",
        f"<tr bgcolor='#f3f5f8'><td colspan='5'><b>Kontostand am {u.von:%d.%m.%Y}</b></td>"
        f"{euro(u.anfang, fett=True)}</tr>",
    ]
    for i, z in enumerate(u.zeilen):
        b = z.buchung
        hintergrund = " bgcolor='#f7f9fb'" if i % 2 else ""
        text = escape(b.text) + (f" <span style='color:{grau}'>(Beleg {escape(b.beleg)})</span>" if b.beleg else "")
        teile.append(
            f"<tr{hintergrund}><td nowrap>{b.datum:%d.%m.%Y}</td><td nowrap>{b.art.anzeige}</td>"
            f"<td>{text}</td><td>{escape(z.gegenkonto.name)}</td>{euro(z.betrag)}{euro(z.saldo)}</tr>"
        )
    if not u.zeilen:
        teile.append(f"<tr><td colspan='6' style='color:{grau}'>Keine Buchungen in diesem Zeitraum.</td></tr>")
    teile += [
        f"<tr bgcolor='#f3f5f8'><td colspan='5'><b>Kontostand am {u.bis:%d.%m.%Y}</b></td>"
        f"{euro(u.ende, fett=True)}</tr>",
        "</table>",
        f"<p style='color:{grau}'>Positiver Kontostand = Guthaben, negativer Kontostand = offener Betrag. "
        "Stornierte Buchungen erscheinen mit ihrer Gegenbuchung (Storno) und heben sich auf.</p>",
        "</body></html>",
    ]
    return "".join(teile)


def mit_pdf(session: Session, auszug: Kontoauszug, e: Einstellungen) -> Kontoauszug:
    """Der Auszug mit den Umsätzen vom 01.01. bis zum Stichtag als PDF-Anhang."""
    from dikas.pdf import html_zu_pdf  # Qt erst hier laden: braucht eine laufende QApplication

    von, bis = umsatz_zeitraum(auszug.stichtag)
    u = buchhaltung.umsaetze(session, auszug.konto.id, von, bis)
    html = umsaetze_html(u, e.absender_name)
    inhalt = html_zu_pdf(html, f"Kontoauszug {auszug.konto.name} {bis.year}")
    return replace(auszug, pdf=PdfAnhang(pdf_dateiname(auszug.konto, auszug.stichtag), inhalt))


# --- SMTP -----------------------------------------------------------------

class Verbindung(Protocol):
    def send_message(self, nachricht: EmailMessage, /) -> object: ...
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

    Anders als sonst wird hier nach jeder Mail gespeichert (commit): Eine verschickte Mail lässt
    sich nicht zurückholen. Bricht der Lauf mittendrin ab (Absturz, Stromausfall), wäre sonst
    das ganze Protokoll weg und alle bekämen ihren Kontoauszug beim nächsten Lauf doppelt.
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
            except (smtplib.SMTPException, OSError, VersandFehler, MessageError, ValueError) as fehler:
                # MessageError/ValueError: Die Mail ließ sich gar nicht erst aufbauen (z. B. unzulässige Adresse)
                ergebnis = Ergebnis(auszug, False, str(fehler)[:500])
            ergebnisse.append(ergebnis)
            session.add(Mailversand(
                konto_id=auszug.konto.id, stichtag=auszug.stichtag, saldo_cent=auszug.saldo,
                empfaenger=auszug.empfaenger, erfolgreich=ergebnis.erfolgreich, fehler=ergebnis.fehler,
            ))
            session.commit()
    finally:
        _beenden(verbindung)
    return ergebnisse


def _beenden(verbindung: Verbindung) -> None:
    try:
        verbindung.quit()
    except (smtplib.SMTPException, OSError):
        pass
