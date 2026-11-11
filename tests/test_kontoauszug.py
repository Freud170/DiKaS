"""Kontoauszug per E-Mail: Einstellungen, Texte, Versand (mit Test-SMTP-Server) und Oberfläche."""

import smtplib
import socket
import socketserver
import threading
from dataclasses import replace
from datetime import date, datetime
from email import message_from_bytes, policy

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas import einstellungen as es
from dikas import kontoauszug as ka
from dikas.db.models import Mailversand, MitgliedStatus as St
from dikas.ui.einstellungen_dialog import EinstellungenDialog
from dikas.ui.versand_dialog import SPALTE_SENDEN, VersandDialog

from conftest import Verein, ct

D = date
STICHTAG = D(2026, 12, 31)

EINST = es.Einstellungen(
    smtp_anbieter="Gmail", smtp_benutzer="kassenwart@example.com",
    absender_name="Max (Kassenwart)", absender_email="kassenwart@example.com",
    kontoinhaber="Verein e. V.", iban="DE02120300000000202051", bic="BYLADEM1001", bank="DKB",
)


# --- Testhilfen: falscher und echter Mailserver ----------------------------

class FalscheVerbindung:
    """Merkt sich gesendete Mails; kann für bestimmte Empfänger Fehler werfen."""

    def __init__(self, fehler_bei=(), trennen_bei=()):
        self.gesendet = []
        self.fehler_bei = set(fehler_bei)
        self.trennen_bei = set(trennen_bei)
        self.beendet = False

    def send_message(self, nachricht):
        an = nachricht["To"]
        if an in self.trennen_bei:
            self.trennen_bei.discard(an)
            raise smtplib.SMTPServerDisconnected("Verbindung weg")
        if an in self.fehler_bei:
            raise smtplib.SMTPRecipientsRefused({an: (550, b"Unbekannter Empfaenger")})
        self.gesendet.append(nachricht)

    def quit(self):
        self.beendet = True


class FalscherVerbinder:
    def __init__(self, **kwargs):
        self.verbindung = FalscheVerbindung(**kwargs)
        self.aufrufe = []

    def __call__(self, einstellungen, passwort):
        self.aufrufe.append(passwort)
        return self.verbindung

    @property
    def gesendet(self):
        return self.verbindung.gesendet


class _SmtpHandler(socketserver.StreamRequestHandler):
    """Minimaler SMTP-Server (nur für Tests): nimmt Mails an und legt sie in server.mails ab."""

    def _sag(self, text):
        self.wfile.write(f"{text}\r\n".encode())

    def handle(self):
        self._sag("220 test ESMTP")
        while line := self.rfile.readline():
            befehl = line.decode().strip().upper()
            if befehl.startswith("EHLO"):
                self._sag("250-test")
                self._sag("250-AUTH PLAIN LOGIN")
                self._sag("250 8BITMIME")
            elif befehl.startswith("AUTH PLAIN"):
                self._sag("235 ok" if self.server.passwort_ok else "535 falsch")
            elif befehl.startswith(("MAIL", "RCPT", "RSET", "NOOP")):
                self._sag("250 ok")
            elif befehl == "DATA":
                self._sag("354 los")
                daten = b""
                while (zeile := self.rfile.readline()) != b".\r\n":
                    daten += zeile[1:] if zeile.startswith(b"..") else zeile
                self.server.mails.append(message_from_bytes(daten, policy=policy.default))
                self._sag("250 angenommen")
            elif befehl == "QUIT":
                self._sag("221 tschuess")
                return
            else:
                self._sag("502 unbekannt")


@pytest.fixture
def smtp_server():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SmtpHandler)
    server.daemon_threads = True
    server.mails = []
    server.passwort_ok = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def lokal(server) -> es.Einstellungen:
    return replace(EINST, smtp_server="127.0.0.1", smtp_port=server.server_address[1],
                   smtp_verschluesselung=es.KEINE)


@pytest.fixture
def mitglieder(verein):
    kasse = verein.kasse("Beitragskasse")
    m = {
        "schulden": verein.mitglied("Tom Becker", St.AKTIVER),
        "guthaben": verein.mitglied("Anna Schulz", St.ALUMNI),
        "null": verein.mitglied("Ben Wagner", St.FUX),
        "ohne_mail": verein.mitglied("Bernd Koch", St.ALUMNI),
        "ausgetreten": verein.mitglied("Alt Herr", St.ALUMNI),
    }
    for schluessel, konto in m.items():
        konto.email = "" if schluessel == "ohne_mail" else f"{schluessel}@example.org"
    m["schulden"].bierspitz = "Tommy"
    verein.beitrag(m["schulden"], kasse, "45,50", datum=D(2026, 1, 1))
    verein.einzahlung(m["guthaben"], "20", datum=D(2026, 3, 1))
    verein.beitrag(m["ohne_mail"], kasse, "10", datum=D(2026, 1, 1))
    verein.einzahlung(m["schulden"], "100", datum=D(2027, 1, 5))  # nach dem Stichtag
    m["ausgetreten"].aktiv = False
    verein.s.flush()
    return m


# --- Einstellungen ---------------------------------------------------------

class TestEinstellungen:
    def test_standard_ohne_gespeicherte_werte(self, session):
        e = es.laden(session)
        assert e == es.Einstellungen()
        assert (e.smtp_server, e.smtp_port, e.smtp_verschluesselung) == ("smtp.gmail.com", 587, es.STARTTLS)

    def test_speichern_und_laden(self, session):
        es.speichern(session, EINST)
        assert es.laden(session) == EINST
        geaendert = replace(EINST, smtp_port=465, iban="DE89370400440532013000")
        es.speichern(session, geaendert)
        assert es.laden(session) == geaendert

    def test_fehlende_angaben(self):
        assert set(es.Einstellungen().fehlende_angaben()) == {
            "Absender-E-Mail", "Absendername", "Kontoinhaber", "IBAN"}
        assert EINST.fehlende_angaben() == []

    @pytest.mark.parametrize("vorlage, ok", [
        ("Hallo {anrede}, {saldo} zum {stichtag}", True),
        ("Ohne Platzhalter", True),
        ("Hallo {spitzname}", False),
        ("Hallo {vorname} {nachname}", True),
        ("Kaputt {", False),
        ("Kaputt }", False),
        ("Stand {saldo:>12}", True),  # Formatangaben sind erlaubt
        ("Stand {saldo:Q}", False),
        ("Hallo {}", False),
        ("Hallo {0}", False),
        # Zusätze am Platzhalter: früher ein Absturz bzw. Unsinn in der Mail
        ("Hallo {name.foo}", False),
        ("Hallo {name.upper}", False),
        ("Hallo {name[0]}", False),
    ])
    def test_vorlage_pruefen(self, vorlage, ok):
        assert (es.pruefe_vorlage(vorlage) is None) == ok

    def test_gesperrter_platzhalter(self):
        assert es.pruefe_vorlage("Zweck {verwendungszweck}") is None
        meldung = es.pruefe_vorlage("Zweck {verwendungszweck}", gesperrt=("verwendungszweck",))
        assert "{verwendungszweck}" in meldung and "nicht verwendet" in meldung

    def test_alle_standardtexte_gueltig(self):
        e = es.Einstellungen()
        for vorlage in (e.betreff, e.text_negativ, e.text_positiv, e.text_null, e.verwendungszweck):
            assert es.pruefe_vorlage(vorlage) is None

    def test_anbieter_vollstaendig(self):
        for a in es.ANBIETER:
            assert a.verschluesselung in es.VERSCHLUESSELUNGEN
            assert a.server or a.name == es.EIGENER_SERVER
        assert es.anbieter("Gmail").server == "smtp.gmail.com"
        assert es.anbieter("gibt es nicht") is None


# --- Texte -----------------------------------------------------------------

class TestAuszug:
    def _auszug(self, konto, saldo):
        return ka.erstelle_auszug(konto, saldo, STICHTAG, EINST)

    def test_negativ_mit_bankdaten(self, mitglieder):
        a = self._auszug(mitglieder["schulden"], ct("-45,50"))
        assert a.art == "offen"
        assert a.betreff == "Dein Kontostand zum 31.12.2026"
        for teil in ("Hallo Tommy,", "-45,50 €", "offenen Betrag von 45,50 €", "DE02120300000000202051",
                     "Verein e. V.", "BYLADEM1001", "Ausgleich Privatkonto Tom Becker", "Max (Kassenwart)"):
            assert teil in a.text

    def test_positiv_auf_mich_zukommen(self, mitglieder):
        a = self._auszug(mitglieder["guthaben"], ct(20))
        assert a.art == "Guthaben"
        assert "20,00 € im Plus" in a.text
        assert "melde dich" in a.text
        assert "IBAN" not in a.text

    def test_null_gut_gewirtschaftet(self, mitglieder):
        a = self._auszug(mitglieder["null"], 0)
        assert a.art == "ausgeglichen"
        assert "Gut gewirtschaftet" in a.text

    def test_anrede_ohne_bierspitz_ist_vorname(self, mitglieder):
        assert "Hallo Anna," in self._auszug(mitglieder["guthaben"], 1).text

    def test_eigene_vorlagen(self, mitglieder):
        e = replace(EINST, betreff="Kasse {stichtag}: {saldo}", text_negativ="Zahl {betrag}, {bierspitz}!",
                    verwendungszweck="{bierspitz}/{name}")
        a = ka.erstelle_auszug(mitglieder["schulden"], -100, STICHTAG, e)
        assert a.betreff == "Kasse 31.12.2026: -1,00 €"
        assert a.text == "Zahl 1,00 €, Tommy!"
        assert ka.platzhalter(mitglieder["schulden"], -100, STICHTAG, e)["verwendungszweck"] == "Tommy/Tom Becker"

    def test_verwendungszweck_der_sich_selbst_enthaelt_stuerzt_nicht_ab(self, mitglieder):
        """Stand so in älteren Einstellungen: Der Kontoauszüge-Dialog ließ sich nicht mehr öffnen."""
        e = replace(EINST, verwendungszweck="Konto {name} {verwendungszweck}")
        a = ka.erstelle_auszug(mitglieder["schulden"], -100, STICHTAG, e)
        assert "Verwendungszweck: Konto Tom Becker \n" in a.text

    def test_als_email(self, mitglieder):
        n = ka.als_email(self._auszug(mitglieder["schulden"], -100), EINST)
        assert n["To"] == "schulden@example.org"
        assert "Max (Kassenwart)" in n["From"] and "kassenwart@example.com" in n["From"]
        assert n["Message-ID"]
        # Ohne Datum verwerfen Spamfilter die Mail, obwohl der Server sie annimmt
        assert abs((datetime.now().astimezone() - n["Date"].datetime).total_seconds()) < 60
        test = ka.als_email(self._auszug(mitglieder["schulden"], -100), EINST, an="ich@example.net", betreff_zusatz="[TEST] ")
        assert test["To"] == "ich@example.net" and test["Subject"].startswith("[TEST] ")


class TestEmpfaenger:
    def test_saldo_zum_stichtag(self, session, mitglieder):
        salden = {k.name: s for k, s in ka.empfaenger_liste(session, STICHTAG)}
        assert salden["Tom Becker"] == ct("-45,50")  # Einzahlung 2027 zählt noch nicht
        assert salden["Anna Schulz"] == ct(20)
        assert salden["Ben Wagner"] == 0
        assert {k.name for k, _ in ka.empfaenger_liste(session, D(2027, 12, 31))} >= {"Tom Becker"}
        assert dict((k.name, s) for k, s in ka.empfaenger_liste(session, D(2027, 12, 31)))["Tom Becker"] == ct("54,50")

    def test_keine_kassen_und_keine_geloeschten(self, session, verein, mitglieder):
        weg = verein.mitglied("Gelöscht")
        bh.konto_loeschen(session, weg.id)
        namen = [k.name for k, _ in ka.empfaenger_liste(session, STICHTAG)]
        assert "Beitragskasse" not in namen and "KW" not in namen and "Gelöscht" not in namen
        assert namen == sorted(namen, key=lambda n: n.split()[-1])  # nach Nachname

    def test_salden_bis(self, session, mitglieder):
        assert bh.salden(session, bis=D(2025, 12, 31))[mitglieder["schulden"].id] == 0
        assert bh.salden(session)[mitglieder["schulden"].id] == ct("54,50")


# --- Versand ---------------------------------------------------------------

def auszuege(session, mitglieder, *schluessel):
    salden = bh.salden(session, bis=STICHTAG)
    return [ka.erstelle_auszug(mitglieder[s], salden[mitglieder[s].id], STICHTAG, EINST) for s in schluessel]


class TestVersand:
    def test_alle_gesendet_und_protokolliert(self, session, mitglieder):
        verbinder = FalscherVerbinder()
        liste = auszuege(session, mitglieder, "schulden", "guthaben", "null")
        ergebnisse = ka.versenden(session, liste, EINST, "geheim", verbinder)
        assert all(e.erfolgreich for e in ergebnisse)
        assert [n["To"] for n in verbinder.gesendet] == ["schulden@example.org", "guthaben@example.org", "null@example.org"]
        assert verbinder.aufrufe == ["geheim"]  # eine Verbindung für alle
        assert verbinder.verbindung.beendet
        protokoll = session.scalars(select(Mailversand)).all()
        assert len(protokoll) == 3 and all(p.erfolgreich and p.stichtag == STICHTAG for p in protokoll)
        assert ka.bereits_versendet(session, STICHTAG) == {mitglieder[s].id for s in ("schulden", "guthaben", "null")}
        assert ka.bereits_versendet(session, D(2027, 12, 31)) == set()

    def test_einzelner_fehler_bricht_nicht_ab(self, session, mitglieder):
        verbinder = FalscherVerbinder(fehler_bei={"guthaben@example.org"})
        ergebnisse = ka.versenden(session, auszuege(session, mitglieder, "schulden", "guthaben", "null"),
                                  EINST, "x", verbinder)
        assert [e.erfolgreich for e in ergebnisse] == [True, False, True]
        assert "Unbekannter" in ergebnisse[1].fehler
        fehlgeschlagen = session.scalars(select(Mailversand).where(~Mailversand.erfolgreich)).one()
        assert fehlgeschlagen.konto_id == mitglieder["guthaben"].id
        assert mitglieder["guthaben"].id not in ka.bereits_versendet(session, STICHTAG)

    def test_verbindungsabbruch_wird_neu_verbunden(self, session, mitglieder):
        verbinder = FalscherVerbinder(trennen_bei={"guthaben@example.org"})
        ergebnisse = ka.versenden(session, auszuege(session, mitglieder, "schulden", "guthaben"), EINST, "x", verbinder)
        assert all(e.erfolgreich for e in ergebnisse)
        assert len(verbinder.aufrufe) == 2

    def test_abbruch_ueber_fortschritt(self, session, mitglieder):
        verbinder = FalscherVerbinder()
        ergebnisse = ka.versenden(session, auszuege(session, mitglieder, "schulden", "guthaben", "null"),
                                  EINST, "x", verbinder, fortschritt=lambda i, a: i < 1)
        assert len(ergebnisse) == 1 and len(verbinder.gesendet) == 1

    def test_testmail_geht_an_mich_und_wird_nicht_protokolliert(self, session, mitglieder):
        verbinder = FalscherVerbinder()
        (a,) = auszuege(session, mitglieder, "schulden")
        ka.testmail_senden(a, EINST, "x", verbinder)
        assert verbinder.gesendet[0]["To"] == "kassenwart@example.com"
        assert verbinder.gesendet[0]["Subject"].startswith("[TEST]")
        assert session.scalars(select(Mailversand)).all() == []

    def test_protokoll_ueberlebt_abbruch_mittendrin(self, session, mitglieder):
        """Bricht der Lauf nach der ersten Mail ab, bleibt deren Protokoll gespeichert –
        sonst bekäme das Mitglied seinen Kontoauszug beim nächsten Lauf doppelt."""
        class Absturz(Exception):
            pass

        def fortschritt(i, _auszug):
            if i == 1:
                raise Absturz
            return True

        verbinder = FalscherVerbinder()
        with pytest.raises(Absturz):
            ka.versenden(session, auszuege(session, mitglieder, "schulden", "guthaben", "null"),
                         EINST, "x", verbinder, fortschritt)
        session.rollback()  # das passiert, wenn die Transaktion nach einem Fehler verlassen wird

        assert len(verbinder.gesendet) == 1 and verbinder.verbindung.beendet
        assert ka.bereits_versendet(session, STICHTAG) == {mitglieder["schulden"].id}

    def test_nicht_aufbaubare_mail_zaehlt_als_fehlgeschlagen(self, session, mitglieder):
        """Eine unzulässige Adresse bricht den Lauf nicht ab und wird als Fehler protokolliert."""
        mitglieder["guthaben"].email = "anna\n@example.org"
        verbinder = FalscherVerbinder()
        ergebnisse = ka.versenden(session, auszuege(session, mitglieder, "schulden", "guthaben", "null"),
                                  EINST, "x", verbinder)
        assert [e.erfolgreich for e in ergebnisse] == [True, False, True]
        assert ergebnisse[1].fehler
        assert len(verbinder.gesendet) == 2

    def test_letzter_versand(self, session, mitglieder):
        ka.versenden(session, auszuege(session, mitglieder, "schulden"), EINST, "x", FalscherVerbinder())
        assert ka.letzter_versand(session)[mitglieder["schulden"].id].stichtag == STICHTAG


class TestEchterSmtpServer:
    def test_mail_kommt_vollstaendig_an(self, session, mitglieder, smtp_server):
        ka.versenden(session, auszuege(session, mitglieder, "schulden", "null"), lokal(smtp_server), "geheim")
        schulden, null = smtp_server.mails
        assert schulden["To"] == "schulden@example.org"
        assert schulden["Subject"] == "Dein Kontostand zum 31.12.2026"
        text = schulden.get_content()
        assert "Hallo Tommy," in text and "DE02120300000000202051" in text and "45,50 €" in text
        assert "Gut gewirtschaftet! 🍻" in null.get_content()  # Emoji und Umlaute korrekt
        assert "Max (Kassenwart)" in str(schulden["From"])
        # Pflichtangaben, die beim Server ankommen müssen (RFC 5322)
        for mail in (schulden, null):
            assert mail["Date"] and mail["Message-ID"] and mail["From"]

    def test_falsches_passwort(self, smtp_server):
        smtp_server.passwort_ok = False
        with pytest.raises(ka.VersandFehler, match="Anmeldung fehlgeschlagen"):
            ka.verbinden(lokal(smtp_server), "falsch")

    def test_gmail_hinweis_bei_falschem_passwort(self, monkeypatch):
        class AblehnenderServer:
            def __init__(self, *a, **k): pass
            def ehlo(self): pass
            def starttls(self, **k): pass
            def login(self, *a): raise smtplib.SMTPAuthenticationError(535, b"nope")
        monkeypatch.setattr(smtplib, "SMTP", AblehnenderServer)
        with pytest.raises(ka.VersandFehler, match="App-Passwort"):
            ka.verbinden(EINST, "x")

    def test_server_nicht_erreichbar(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            freier_port = s.getsockname()[1]
        e = replace(EINST, smtp_server="127.0.0.1", smtp_port=freier_port, smtp_verschluesselung=es.KEINE)
        with pytest.raises(ka.VersandFehler, match="nicht erreichbar"):
            ka.verbinden(e, "x", timeout=2)

    def test_unbekannter_server(self, monkeypatch):
        def kein_dns(*a, **k):
            raise socket.gaierror("Name nicht auflösbar")
        monkeypatch.setattr(smtplib, "SMTP", kein_dns)
        with pytest.raises(ka.VersandFehler, match="nicht erreichbar"):
            ka.verbinden(replace(EINST, smtp_server="gibtsnicht.invalid"), "x")


class TestVerbindungsarten:
    """Prüft, dass je nach Einstellung SSL, STARTTLS oder unverschlüsselt verbunden wird."""

    @pytest.fixture
    def protokoll(self, monkeypatch):
        aufrufe = []

        class Fake:
            def __init__(self, server, port, **kwargs):
                aufrufe.append((type(self).__name__, server, port))
            def ehlo(self): aufrufe.append("ehlo")
            def starttls(self, context): aufrufe.append("starttls")
            def login(self, benutzer, passwort): aufrufe.append(("login", benutzer, passwort))

        class SMTP(Fake): pass
        class SMTP_SSL(Fake): pass
        monkeypatch.setattr(smtplib, "SMTP", SMTP)
        monkeypatch.setattr(smtplib, "SMTP_SSL", SMTP_SSL)
        return aufrufe

    def test_starttls(self, protokoll):
        ka.verbinden(EINST, "pw")
        assert protokoll == [("SMTP", "smtp.gmail.com", 587), "ehlo", "starttls", "ehlo",
                             ("login", "kassenwart@example.com", "pw")]

    def test_ssl(self, protokoll):
        ka.verbinden(replace(EINST, smtp_server="smtp.strato.de", smtp_port=465, smtp_verschluesselung=es.SSL), "pw")
        assert protokoll[0] == ("SMTP_SSL", "smtp.strato.de", 465)
        assert "starttls" not in protokoll

    def test_ohne_anmeldung(self, protokoll):
        ka.verbinden(replace(EINST, smtp_benutzer="", smtp_verschluesselung=es.KEINE), "")
        assert not any(isinstance(a, tuple) and a[0] == "login" for a in protokoll)
        assert "starttls" not in protokoll


# --- Umsätze als PDF -------------------------------------------------------

class TestUmsaetze:
    @pytest.fixture
    def tom(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom Becker")
        anna = verein.mitglied("Anna Schulz")
        verein.einzahlung(tom, "20", "Altes Guthaben", datum=D(2025, 6, 1))
        verein.beitrag(tom, kasse, "60", "Beitrag 2026", datum=D(2026, 1, 1))
        falsch = verein.einzahlung(tom, "99", "Tippfehler", datum=D(2026, 2, 1))
        bh.stornieren(verein.s, falsch.id, D(2026, 2, 2))
        verein.umbuchung(anna, tom, "15", "Anna gibt Bier aus", datum=D(2026, 5, 1))
        verein.einzahlung(anna, "500", "Fremdes Geld", datum=D(2026, 5, 2))  # nicht Toms Konto
        verein.einzahlung(tom, "10", "Nach dem Stichtag", datum=D(2027, 1, 2))
        return tom

    def test_anfang_zeilen_ende(self, session, tom):
        u = bh.umsaetze(session, tom.id, D(2026, 1, 1), D(2026, 12, 31))
        assert u.anfang == ct(20)
        texte = [z.buchung.text for z in u.zeilen]
        assert texte[0] == "Beitrag 2026" and texte[-1] == "Anna gibt Bier aus"
        assert "Fremdes Geld" not in texte and "Nach dem Stichtag" not in texte
        assert [z.betrag for z in u.zeilen] == [ct(-60), ct(99), ct(-99), ct(15)]
        assert [z.saldo for z in u.zeilen] == [ct(-40), ct(59), ct(-40), ct(-25)]
        assert u.ende == ct(-25) == bh.salden(session, bis=D(2026, 12, 31))[tom.id]
        assert u.zeilen[0].gegenkonto.name == "Beitragskasse"
        assert u.zeilen[-1].gegenkonto.name == "Anna Schulz"

    def test_ohne_buchungen(self, session, verein):
        m = verein.mitglied("Neu Ling")
        u = bh.umsaetze(session, m.id, D(2026, 1, 1), D(2026, 12, 31))
        assert (u.anfang, u.zeilen, u.ende) == (0, [], 0)
        assert "Keine Buchungen" in ka.umsaetze_html(u)

    def test_zeitraum_falsch(self, session, tom):
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.umsaetze(session, tom.id, D(2026, 12, 31), D(2026, 1, 1))

    def test_html(self, session, tom):
        html = ka.umsaetze_html(bh.umsaetze(session, tom.id, D(2026, 1, 1), D(2026, 6, 30)), "Max <Kassenwart>")
        assert "Kontoauszug Tom Becker" in html and "01.01.2026 – 30.06.2026" in html
        assert "Max &lt;Kassenwart&gt;" in html
        assert "Kontostand am 01.01.2026" in html and "20,00 €" in html
        assert "Kontostand am 30.06.2026" in html and "-25,00 €" in html
        assert "Storno: Tippfehler" in html
        assert "Fremdes Geld" not in html

    @pytest.mark.parametrize("vorname, nachname, name", [
        ("Tom", "Becker", "Kontoauszug_2026_Becker_Tom.pdf"),
        ("Jörg", "von Müller", "Kontoauszug_2026_von_Müller_Jörg.pdf"),
        ("", "", "Kontoauszug_2026_Mitglied.pdf"),
    ])
    def test_dateiname(self, vorname, nachname, name):
        from dikas.db.models import Konto
        konto = Konto(name=f"{vorname} {nachname}".strip(), vorname=vorname, nachname=nachname)
        assert ka.pdf_dateiname(konto, STICHTAG) == name

    def test_zeitraum_aus_stichtag(self):
        assert ka.umsatz_zeitraum(D(2026, 8, 15)) == (D(2026, 1, 1), D(2026, 8, 15))

    def test_mit_pdf_und_als_email(self, app, session, tom):
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        tom.email = "tom@example.org"
        auszug = ka.mit_pdf(session, ka.erstelle_auszug(tom, ct(-25), STICHTAG, EINST), EINST)
        assert auszug.pdf.dateiname == "Kontoauszug_2026_Becker_Tom.pdf"
        puffer = QBuffer()
        puffer.setData(QByteArray(auszug.pdf.inhalt))
        puffer.open(QIODevice.ReadOnly)
        dokument = QPdfDocument()
        dokument.load(puffer)
        assert dokument.status() == QPdfDocument.Status.Ready and dokument.pageCount() >= 1

        mail = ka.als_email(auszug, EINST)
        assert mail.get_body(("plain",)).get_content().startswith("Hallo Tom")
        anhang = next(mail.iter_attachments())
        assert anhang.get_filename() == "Kontoauszug_2026_Becker_Tom.pdf"
        assert anhang.get_content() == auszug.pdf.inhalt

    def test_pdf_kommt_beim_echten_server_an(self, app, session, tom, smtp_server):
        tom.email = "tom@example.org"
        auszug = ka.mit_pdf(session, ka.erstelle_auszug(tom, ct(-25), STICHTAG, EINST), EINST)
        ergebnis = ka.versenden(session, [auszug], lokal(smtp_server), "geheim")
        assert ergebnis[0].erfolgreich
        anhang = next(smtp_server.mails[0].iter_attachments())
        assert anhang.get_content() == auszug.pdf.inhalt


# --- Oberfläche ------------------------------------------------------------

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def meldungen(monkeypatch):
    liste = []
    for name in ("warning", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, n=name: liste.append((n, a[2])))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    return liste


class TestEinstellungenDialog:
    def test_zeigt_gespeicherte_werte(self, app):
        d = EinstellungenDialog(EINST)
        assert d.werte() == EINST
        assert "App-Passwort" in d.anbieter_hinweis.text()

    @pytest.mark.parametrize("name, server, port, art", [
        ("GMX", "mail.gmx.net", 587, es.STARTTLS), ("Strato", "smtp.strato.de", 465, es.SSL),
        ("web.de", "smtp.web.de", 587, es.STARTTLS),
    ])
    def test_anbieter_fuellt_server(self, app, name, server, port, art):
        d = EinstellungenDialog(EINST)
        d.anbieter.setCurrentText(name)
        w = d.werte()
        assert (w.smtp_server, w.smtp_port, w.smtp_verschluesselung) == (server, port, art)

    def test_eigener_server_behaelt_werte(self, app):
        e = replace(EINST, smtp_anbieter=es.EIGENER_SERVER, smtp_server="mail.verein.example", smtp_port=2525)
        d = EinstellungenDialog(e)
        assert (d.server.text(), d.port.value()) == ("mail.verein.example", 2525)
        d.anbieter.setCurrentText(es.EIGENER_SERVER)
        assert d.server.text() == "mail.verein.example"

    def test_benutzer_standard_ist_absender(self, app):
        d = EinstellungenDialog(replace(EINST, smtp_benutzer=""))
        assert d.werte().smtp_benutzer == "kassenwart@example.com"

    @pytest.mark.parametrize("feld, wert, meldung", [
        ("absender_email", "kaputt", "E-Mail"),
        ("iban", "12345", "IBAN"),
        ("betreff", "Stand {datum}", "Unbekannter Platzhalter"),
        ("betreff", "", "leer"),
        ("betreff", "Stand {name.foo}", "Unbekannter Platzhalter"),
        ("verwendungszweck", "Zweck {verwendungszweck}", "Verwendungszweck: Der Platzhalter"),
    ])
    def test_fehler(self, app, feld, wert, meldung):
        d = EinstellungenDialog(EINST)
        getattr(d, feld).setText(wert)
        assert meldung in d.fehler()

    def test_fehler_im_text(self, app):
        d = EinstellungenDialog(EINST)
        d.texte["text_null"].setPlainText("Hallo {spitzname}")
        assert "Text Saldo 0" in d.fehler()

    def test_standardtexte(self, app):
        d = EinstellungenDialog(replace(EINST, text_null="eigener Text", betreff="x"))
        d._standardtexte()
        assert d.werte().text_null == es.STANDARD_TEXT_NULL
        assert d.werte().betreff == es.STANDARD_BETREFF

    def test_iban_gross(self, app):
        d = EinstellungenDialog(EINST)
        d.iban.setText("de02 1203 0000 0000 2020 51")
        assert d.werte().iban == "DE02 1203 0000 0000 2020 51"
        assert d.fehler() is None


class TestVersandDialog:
    @pytest.fixture
    def Sitzung(self, engine):
        with Session(engine) as s, s.begin():
            v = Verein(s)
            kasse = v.kasse("Beitragskasse")
            tom = v.mitglied("Tom Becker")
            tom.email, tom.bierspitz = "tom@example.org", "Tommy"
            anna = v.mitglied("Anna Schulz", St.ALUMNI)
            anna.email = "anna@example.org"
            v.mitglied("Bernd Koch")  # ohne E-Mail
            alt = v.mitglied("Alt Herr", St.ALUMNI)
            alt.email, alt.aktiv = "alt@example.org", False
            schuldner = v.mitglied("Ex Schuldner")
            v.beitrag(schuldner, kasse, "5", datum=D(2026, 1, 1))
            schuldner.email, schuldner.aktiv = "ex@example.org", False
            v.beitrag(tom, kasse, "60", datum=D(2026, 1, 1))
            v.einzahlung(anna, "15", datum=D(2026, 2, 1))
            es.speichern(s, EINST)
        return sessionmaker(engine, expire_on_commit=False)

    @pytest.fixture
    def verbinder(self):
        return FalscherVerbinder()

    @pytest.fixture
    def dialog(self, app, Sitzung, verbinder, meldungen):
        self.passwort_fragen = 0

        def passwort(*_):
            self.passwort_fragen += 1
            return "geheim"

        d = VersandDialog(Sitzung, heute=STICHTAG, verbinder=verbinder, passwort_quelle=passwort)
        yield d
        d.close()

    def zeile(self, d, name):
        return next(z for z in range(d.tabelle.rowCount()) if d.tabelle.item(z, 1).text() == name)

    def angehakt(self, d):
        return {k.name for k, _ in d.ausgewaehlte()}

    def test_vorauswahl(self, dialog):
        # ohne E-Mail nicht; deaktiviert mit Saldo 0 nicht; deaktiviert mit Schulden schon
        assert self.angehakt(dialog) == {"Tom Becker", "Anna Schulz", "Ex Schuldner"}
        assert "Bernd Koch" in dialog.hinweis.text()
        assert dialog.senden_knopf.text() == "3 Mails senden"

    def test_ohne_email_nicht_anhakbar(self, dialog):
        item = dialog.tabelle.item(self.zeile(dialog, "Bernd Koch"), SPALTE_SENDEN)
        assert not item.flags() & Qt.ItemIsUserCheckable

    def test_alle_und_keine(self, dialog):
        dialog._auswahl_setzen(True)
        assert "Bernd Koch" not in self.angehakt(dialog) and "Alt Herr" in self.angehakt(dialog)
        dialog._auswahl_setzen(False)
        assert self.angehakt(dialog) == set()
        assert not dialog.senden_knopf.isEnabled()

    def test_vorschau(self, dialog):
        dialog.tabelle.selectRow(self.zeile(dialog, "Tom Becker"))
        text = dialog.vorschau.toPlainText()
        assert "An: tom@example.org" in text and "Hallo Tommy" in text and "DE02120300000000202051" in text
        dialog.tabelle.selectRow(self.zeile(dialog, "Anna Schulz"))
        assert "im Plus" in dialog.vorschau.toPlainText()

    def test_senden(self, dialog, verbinder, meldungen, Sitzung):
        dialog.senden()
        assert sorted(n["To"] for n in verbinder.gesendet) == ["anna@example.org", "ex@example.org", "tom@example.org"]
        assert meldungen[-1] == ("information", "3 von 3 Mails wurden gesendet.")
        # Danach sind die Versendeten für diesen Stichtag abgewählt und markiert
        assert self.angehakt(dialog) == set()
        assert "schon versendet" in dialog.hinweis.text()
        assert dialog.tabelle.item(self.zeile(dialog, "Tom Becker"), 6).text().startswith(date.today().strftime("%d.%m.%Y"))

    def test_anderer_stichtag_wieder_ausgewaehlt(self, dialog):
        dialog.senden()
        dialog.stichtag.setDate(QDate(2027, 12, 31))
        assert "Tom Becker" in self.angehakt(dialog)

    def test_passwort_nur_einmal(self, dialog):
        dialog.testmail()
        dialog.senden()
        assert self.passwort_fragen == 1

    def test_passwort_abgebrochen(self, app, Sitzung, verbinder, meldungen):
        d = VersandDialog(Sitzung, heute=STICHTAG, verbinder=verbinder, passwort_quelle=lambda *_: None)
        d.senden()
        assert verbinder.gesendet == []

    def test_testmail(self, dialog, verbinder, meldungen):
        dialog.tabelle.selectRow(self.zeile(dialog, "Tom Becker"))
        dialog.testmail()
        assert verbinder.gesendet[0]["To"] == "kassenwart@example.com"
        assert "Tom Becker" in meldungen[-1][1]

    def test_teilweise_fehlgeschlagen(self, app, Sitzung, meldungen):
        verbinder = FalscherVerbinder(fehler_bei={"anna@example.org"})
        d = VersandDialog(Sitzung, heute=STICHTAG, verbinder=verbinder, passwort_quelle=lambda *_: "x")
        d.senden()
        art, text = meldungen[-1]
        assert art == "warning" and "2 von 3" in text and "Anna Schulz" in text
        assert self.angehakt(d) == {"Anna Schulz"}  # Fehlgeschlagene bleiben ausgewählt

    def test_anmeldung_fehlgeschlagen(self, app, Sitzung, meldungen):
        def kaputt(*_):
            raise ka.VersandFehler("Anmeldung fehlgeschlagen")
        fragen = []
        d = VersandDialog(Sitzung, heute=STICHTAG, verbinder=kaputt,
                          passwort_quelle=lambda *_: fragen.append(1) or "falsch")
        d.senden()
        assert meldungen[-1] == ("warning", "Anmeldung fehlgeschlagen")
        d.senden()
        assert len(fragen) == 2  # falsches Passwort wird nicht gemerkt

    def test_mails_haben_eigenes_pdf(self, dialog, verbinder):
        dialog.senden()
        for nachricht in verbinder.gesendet:
            anhaenge = list(nachricht.iter_attachments())
            assert len(anhaenge) == 1
            assert anhaenge[0].get_content_type() == "application/pdf"
            assert anhaenge[0].get_content().startswith(b"%PDF")
        namen = sorted(next(n.iter_attachments()).get_filename() for n in verbinder.gesendet)
        assert namen == ["Kontoauszug_2026_Becker_Tom.pdf", "Kontoauszug_2026_Schuldner_Ex.pdf",
                         "Kontoauszug_2026_Schulz_Anna.pdf"]

    def test_ohne_pdf(self, dialog, verbinder):
        dialog.mit_pdf.setChecked(False)
        dialog.senden()
        assert all(list(n.iter_attachments()) == [] for n in verbinder.gesendet)

    def test_testmail_mit_pdf(self, dialog, verbinder):
        dialog.tabelle.selectRow(self.zeile(dialog, "Tom Becker"))
        dialog.testmail()
        assert next(verbinder.gesendet[0].iter_attachments()).get_filename() == "Kontoauszug_2026_Becker_Tom.pdf"

    def test_vorschau_nennt_anhang(self, dialog):
        dialog.tabelle.selectRow(self.zeile(dialog, "Tom Becker"))
        assert "Anhang: Kontoauszug_2026_Becker_Tom.pdf (Umsätze 01.01. – 31.12.2026)" in dialog.vorschau.toPlainText()
        dialog.mit_pdf.setChecked(False)
        assert "Anhang" not in dialog.vorschau.toPlainText()
        assert not dialog.pdf_knopf.isEnabled()

    def test_pdf_ansehen(self, app, Sitzung, verbinder, meldungen, tmp_path, monkeypatch):
        from dikas import anhaenge
        monkeypatch.setattr(anhaenge, "ansichtsordner", lambda: tmp_path)
        geoeffnet = []
        d = VersandDialog(Sitzung, heute=STICHTAG, verbinder=verbinder, passwort_quelle=lambda *_: "x",
                          oeffner=geoeffnet.append)
        d.tabelle.selectRow(self.zeile(d, "Tom Becker"))
        d.pdf_ansehen()
        pfad = geoeffnet[0].toLocalFile()
        assert pfad.endswith("Kontoauszug_2026_Becker_Tom.pdf")
        assert (tmp_path / "Kontoauszug_2026_Becker_Tom.pdf").read_bytes().startswith(b"%PDF")

    def test_einstellungen_unvollstaendig(self, app, engine, meldungen):
        with Session(engine) as s, s.begin():
            v = Verein(s)
            v.mitglied("Tom").email = "tom@example.org"
        verbinder = FalscherVerbinder()
        d = VersandDialog(sessionmaker(engine), heute=STICHTAG, verbinder=verbinder, passwort_quelle=lambda *_: "x")
        assert "fehlt noch" in d.hinweis.text()
        d.senden()
        assert meldungen[-1][0] == "warning" and "IBAN" in meldungen[-1][1]
        assert verbinder.gesendet == []
