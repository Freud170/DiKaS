"""Programmeinstellungen: Mailserver, Absender, Bankdaten und Textvorlagen für den Kontoauszug.

Gespeichert als Schlüssel/Wert in der Tabelle `einstellungen`. Passwörter werden bewusst
NICHT gespeichert – sie werden beim Versand abgefragt.
"""

from dataclasses import dataclass, fields, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from dikas.db.models import Einstellung

# Verschlüsselung der Verbindung zum Mailserver
STARTTLS = "STARTTLS"
SSL = "SSL"
KEINE = "keine"
VERSCHLUESSELUNGEN = [STARTTLS, SSL, KEINE]


@dataclass(frozen=True)
class Anbieter:
    name: str
    server: str
    port: int
    verschluesselung: str
    hinweis: str = ""


EIGENER_SERVER = "Eigener Server"

ANBIETER = [
    Anbieter("Gmail", "smtp.gmail.com", 587, STARTTLS,
             "Gmail braucht ein App-Passwort (Google-Konto → Sicherheit → Bestätigung in zwei "
             "Schritten → App-Passwörter). Das normale Passwort funktioniert nicht."),
    Anbieter("GMX", "mail.gmx.net", 587, STARTTLS,
             "Bei GMX muss der Versand über externe Programme (POP3/IMAP) in den Einstellungen "
             "des Postfachs erlaubt sein."),
    Anbieter("web.de", "smtp.web.de", 587, STARTTLS,
             "Bei web.de muss der Versand über externe Programme (POP3/IMAP) in den Einstellungen "
             "des Postfachs erlaubt sein."),
    Anbieter("T-Online", "securesmtp.t-online.de", 587, STARTTLS,
             "T-Online braucht ein eigenes E-Mail-Passwort (nicht das Kundencenter-Passwort)."),
    Anbieter("iCloud", "smtp.mail.me.com", 587, STARTTLS,
             "iCloud braucht ein app-spezifisches Passwort (appleid.apple.com)."),
    Anbieter("IONOS", "smtp.ionos.de", 587, STARTTLS),
    Anbieter("Strato", "smtp.strato.de", 465, SSL),
    Anbieter(EIGENER_SERVER, "", 587, STARTTLS,
             "Serverdaten stehen meist in der Hilfe deines Mail-Anbieters unter „SMTP“."),
]


def anbieter(name: str) -> Anbieter | None:
    return next((a for a in ANBIETER if a.name == name), None)


# --- Standardtexte --------------------------------------------------------

STANDARD_BETREFF = "Dein Kontostand zum {stichtag}"

STANDARD_TEXT_NEGATIV = """Hallo {anrede},

dein Privatkonto steht zum {stichtag} bei {saldo}.

Bitte überweise den offenen Betrag von {betrag} auf folgendes Konto:

Kontoinhaber: {kontoinhaber}
IBAN: {iban}
BIC: {bic}
Bank: {bank}
Verwendungszweck: {verwendungszweck}

Vielen Dank!

Viele Grüße
{absender}"""

STANDARD_TEXT_POSITIV = """Hallo {anrede},

gute Nachrichten: Dein Privatkonto steht zum {stichtag} mit {saldo} im Plus.

Wenn du dir dein Guthaben auszahlen lassen möchtest, melde dich einfach bei mir. \
Ansonsten bleibt es stehen und wird mit künftigen Beiträgen verrechnet.

Viele Grüße
{absender}"""

STANDARD_TEXT_NULL = """Hallo {anrede},

dein Privatkonto steht zum {stichtag} bei glatten 0,00 €.

Gut gewirtschaftet! 🍻 Keine Schulden, kein Guthaben – so hat es der Kassenwart am liebsten.

Viele Grüße
{absender}"""

STANDARD_VERWENDUNGSZWECK = "Ausgleich Privatkonto {name}"

# Platzhalter, die in Betreff, Texten und Verwendungszweck erlaubt sind
PLATZHALTER = {
    "anrede": "Bierspitz, falls vorhanden, sonst der Vorname",
    "name": "Vor- und Nachname des Mitglieds",
    "vorname": "Vorname",
    "nachname": "Nachname",
    "bierspitz": "Bierspitz (kann leer sein)",
    "stichtag": "Stichtag, z. B. 31.12.2026",
    "saldo": "Kontostand mit Vorzeichen, z. B. -45,00 €",
    "betrag": "Betrag ohne Vorzeichen, z. B. 45,00 €",
    "kontoinhaber": "Kontoinhaber (Bankdaten)",
    "iban": "IBAN (Bankdaten)",
    "bic": "BIC (Bankdaten)",
    "bank": "Name der Bank (Bankdaten)",
    "verwendungszweck": "Verwendungszweck (eigene Vorlage)",
    "absender": "Absendername",
}


@dataclass(frozen=True)
class Einstellungen:
    # Mailserver
    smtp_anbieter: str = "Gmail"
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_verschluesselung: str = STARTTLS
    smtp_benutzer: str = ""  # meist die E-Mail-Adresse
    # Absender
    absender_name: str = ""
    absender_email: str = ""
    # Bankdaten für offene Beträge
    kontoinhaber: str = ""
    iban: str = ""
    bic: str = ""
    bank: str = ""
    # Texte
    betreff: str = STANDARD_BETREFF
    text_negativ: str = STANDARD_TEXT_NEGATIV
    text_positiv: str = STANDARD_TEXT_POSITIV
    text_null: str = STANDARD_TEXT_NULL
    verwendungszweck: str = STANDARD_VERWENDUNGSZWECK

    def fehlende_angaben(self) -> list[str]:
        """Was für den Versand noch fehlt (leer = alles da)."""
        pflicht = {
            "Mailserver": self.smtp_server,
            "Absender-E-Mail": self.absender_email,
            "Absendername": self.absender_name,
            "Kontoinhaber": self.kontoinhaber,
            "IBAN": self.iban,
        }
        return [name for name, wert in pflicht.items() if not str(wert).strip()]


def laden(session: Session) -> Einstellungen:
    gespeichert = dict(session.execute(select(Einstellung.schluessel, Einstellung.wert)).all())
    werte = {}
    for feld in fields(Einstellungen):
        if feld.name in gespeichert:
            roh = gespeichert[feld.name]
            werte[feld.name] = int(roh) if feld.type in (int, "int") else roh
    return replace(Einstellungen(), **werte)


def speichern(session: Session, einstellungen: Einstellungen) -> None:
    for feld in fields(Einstellungen):
        wert = str(getattr(einstellungen, feld.name))
        eintrag = session.get(Einstellung, feld.name)
        if eintrag is None:
            session.add(Einstellung(schluessel=feld.name, wert=wert))
        else:
            eintrag.wert = wert
    session.flush()


def pruefe_vorlage(vorlage: str) -> str | None:
    """Fehlermeldung, wenn die Vorlage unbekannte Platzhalter oder kaputte Klammern enthält."""
    try:
        vorlage.format_map({name: "" for name in PLATZHALTER})
    except KeyError as fehler:
        return f"Unbekannter Platzhalter {{{fehler.args[0]}}}"
    except (ValueError, IndexError):
        return "Geschweifte Klammern { } sind nur für Platzhalter erlaubt."
    return None
