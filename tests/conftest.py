import os
from datetime import date

import pytest
from sqlalchemy.orm import Session

from dikas import buchhaltung as bh
from dikas.db import erstelle_engine, init_db
from dikas.db.models import Buchungsart as Art, Konto, KontoTyp, MitgliedStatus as St
from dikas.geld import text_zu_cent

# UI-Tests ohne sichtbares Fenster
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def keine_offenen_meldungen(monkeypatch):
    """Meldungsfenster würden einen Test endlos blockieren – stattdessen sofort fehlschlagen.

    Tests, die Meldungen erwarten, ersetzen diese Funktionen selbst (überschreibt dies hier).
    """
    from PySide6.QtWidgets import QMessageBox

    def unerwartet(*args):
        raise AssertionError(f"Unerwartete Meldung: {args[2] if len(args) > 2 else args}")

    for name in ("warning", "information", "question", "critical"):
        monkeypatch.setattr(QMessageBox, name, unerwartet)


@pytest.fixture(autouse=True)
def qt_aufraeumen():
    """Nach jedem Test alle Fenster schließen und löschen, solange Qt noch läuft.

    Sonst räumt Python sie erst beim Programmende auf – nach der QApplication – und der
    Prozess stürzt beim Beenden ab (Windows-Fehler 0xC0000409), obwohl alle Tests grün sind.
    """
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        return
    for fenster in QApplication.topLevelWidgets():
        fenster.close()
        fenster.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def engine():
    engine = erstelle_engine(":memory:")
    init_db(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def ct(betrag: str | int) -> int:
    """'12,50' -> 1250, damit Tests in Euro lesbar bleiben."""
    return text_zu_cent(str(betrag))


class Verein:
    """Kleine Testhilfe, um Vereinsabläufe lesbar aufzuschreiben (Beträge in Euro)."""

    def __init__(self, session: Session):
        self.s = session

    @property
    def kw(self) -> Konto:
        return bh.kw_konto(self.s)

    def mitglied(self, name: str, status: St = St.AKTIVER, eintritt: date | None = date(2000, 1, 1)) -> Konto:
        return bh.konto_anlegen(self.s, name, KontoTyp.PRIVAT, status, eintrittsdatum=eintritt)

    def kasse(self, name: str) -> Konto:
        return bh.konto_anlegen(self.s, name, KontoTyp.KASSE)

    def geldort(self, name: str) -> Konto:
        return bh.konto_anlegen(self.s, name, KontoTyp.KW)

    def _buche(self, art, konto, betrag, text, datum, gegen=None):
        return bh.buchen(
            self.s, art, konto.id, ct(betrag), text or art.anzeige, datum,
            gegenkonto_id=gegen.id if gegen else None,
        )

    # `ort`: Geldort, ohne Angabe der Standard-Geldort
    def einzahlung(self, m, betrag, text="", datum: date | None = None, ort=None):
        return self._buche(Art.EINZAHLUNG, m, betrag, text, datum, gegen=ort)

    def auszahlung(self, m, betrag, text="", datum: date | None = None, ort=None):
        return self._buche(Art.AUSZAHLUNG, m, betrag, text, datum, gegen=ort)

    def einnahme(self, kasse, betrag, text="", datum: date | None = None, ort=None):
        return self._buche(Art.KASSE_EINNAHME, kasse, betrag, text, datum, gegen=ort)

    def ausgabe(self, kasse, betrag, text="", datum: date | None = None, ort=None):
        return self._buche(Art.KASSE_AUSGABE, kasse, betrag, text, datum, gegen=ort)

    def geldtransfer(self, von, nach, betrag, text="", datum: date | None = None):
        return self._buche(Art.GELDTRANSFER, von, betrag, text, datum, gegen=nach)

    def umbuchung(self, von, nach, betrag, text="", datum: date | None = None):
        return self._buche(Art.UMBUCHUNG, von, betrag, text, datum, gegen=nach)

    def beitrag(self, m, kasse, betrag, text="", datum: date | None = None):
        return self._buche(Art.BEITRAG, m, betrag, text, datum, gegen=kasse)

    def beitragslauf(self, kasse, fux="0", aktiver="0", alumni="0", text="Jahresbeitrag", datum=None, jahr=2026):
        betraege = {St.FUX: ct(fux), St.AKTIVER: ct(aktiver), St.ALUMNI: ct(alumni)}
        return bh.beitraege_abbuchen(self.s, betraege, jahr, kasse.id, text, datum)

    def storno(self, buchung):
        return bh.stornieren(self.s, buchung.id)

    def saldo(self, konto) -> int:
        return bh.saldo(self.s, konto.id)

    def pruefe_abstimmung(self):
        """KW (alle Geldorte) muss immer der Summe aller Privatkonten und Kassen entsprechen."""
        a = bh.abstimmung(self.s)
        assert a.stimmt, f"KW {a.kw_cent} != verteilt {a.verteilt_cent}"


@pytest.fixture
def verein(session) -> Verein:
    return Verein(session)
