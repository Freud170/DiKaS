"""Kontenliste mit Vor-/Nachname/Bierspitz und Sortierung; Suche in den Buchungen."""

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas.db.models import KontoTyp, MitgliedStatus as St
from dikas.ui.hauptfenster import (
    BIERSPITZ, KONTEN_SORTIERUNG, NACHNAME, NAME_ROLLE, VORNAME, Hauptfenster,
)

from conftest import Verein


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fenster(app, engine):
    with Session(engine) as s, s.begin():
        v = Verein(s)
        for vorname, nachname, spitz, status, eintritt in (
            ("Zoe", "Adler", "Spatz", St.AKTIVER, date(2020, 1, 1)),
            ("Anna", "Zimmer", "", St.FUX, date(2025, 10, 1)),
            ("Ben", "von Ärmel", "Bärchen", St.ALUMNI, date(1990, 5, 1)),
        ):
            bh.konto_anlegen(s, "", KontoTyp.PRIVAT, status, eintrittsdatum=eintritt,
                             bierspitz=spitz, vorname=vorname, nachname=nachname)
        kasse = v.kasse("Getränkekasse")
        zoe, anna, ben = _drei(s)
        v.einzahlung(zoe, "25", "Bierkasse Sommerfest")
        v.einzahlung(anna, "12,50", "Jahresbeitrag 2026")
        v.auszahlung(ben, "100", "Auslage Grillfleisch")
        v.einnahme(kasse, "37,40", "Getränke Stammtisch")
    w = Hauptfenster(sessionmaker(engine, expire_on_commit=False), "test")
    yield w
    w.close()


def _drei(s):
    alle = {k.name: k for k in bh.konten(s)}
    return alle["Zoe Adler"], alle["Anna Zimmer"], alle["Ben von Ärmel"]


def namen(w):
    t = w.konten_tabelle
    return [t.item(r, 0).data(NAME_ROLLE) for r in range(t.rowCount())]


def sortiere(w, text):
    assert text in KONTEN_SORTIERUNG
    w.sortierung.setCurrentText(text)


# --- Kontenliste ------------------------------------------------------------

def test_spalten_vorname_nachname_bierspitz(fenster):
    t = fenster.konten_tabelle
    kopf = [t.horizontalHeaderItem(i).text() for i in range(t.columnCount())]
    assert kopf[:3] == ["Vorname", "Nachname", "Bierspitz"]
    z = namen(fenster).index("Ben von Ärmel")
    assert [t.item(z, i).text() for i in (VORNAME, NACHNAME, BIERSPITZ)] == ["Ben", "von Ärmel", "Bärchen"]


def test_kasse_ueber_beide_namensspalten(fenster):
    t = fenster.konten_tabelle
    z = namen(fenster).index("Getränkekasse")
    assert t.item(z, VORNAME).text() == "Getränkekasse"
    assert t.columnSpan(z, VORNAME) == 2
    assert t.columnSpan(namen(fenster).index("Zoe Adler"), VORNAME) == 1


def test_standard_nach_typ_dann_nachname(fenster):
    # Zusatz „von“ zählt nicht, Ä wie A: Adler, (von) Ärmel, Zimmer
    assert namen(fenster) == ["KW", "Getränkekasse", "Zoe Adler", "Ben von Ärmel", "Anna Zimmer"]
    assert not fenster.konten_tabelle.horizontalHeader().isSortIndicatorShown()


@pytest.mark.parametrize("sortierung, erwartet", [
    ("Nachname A–Z", ["Zoe Adler", "Ben von Ärmel", "Anna Zimmer"]),
    ("Nachname Z–A", ["Anna Zimmer", "Ben von Ärmel", "Zoe Adler"]),
    ("Vorname A–Z", ["Anna Zimmer", "Ben von Ärmel", "Zoe Adler"]),
    ("Vorname Z–A", ["Zoe Adler", "Ben von Ärmel", "Anna Zimmer"]),
    ("Bierspitz A–Z", ["Ben von Ärmel", "Zoe Adler", "Anna Zimmer"]),  # ohne Bierspitz unten
    ("Bierspitz Z–A", ["Zoe Adler", "Ben von Ärmel", "Anna Zimmer"]),  # … auch rückwärts
    ("Status (Fux zuerst)", ["Anna Zimmer", "Zoe Adler", "Ben von Ärmel"]),
    ("Eintritt: älteste zuerst", ["Ben von Ärmel", "Zoe Adler", "Anna Zimmer"]),
    ("Eintritt: neueste zuerst", ["Anna Zimmer", "Zoe Adler", "Ben von Ärmel"]),
    ("Saldo: niedrigster zuerst", ["Ben von Ärmel", "Anna Zimmer", "Zoe Adler"]),
])
def test_sortierung_mitglieder(fenster, sortierung, erwartet):
    fenster.filter.setCurrentText("Privatkonten")
    sortiere(fenster, sortierung)
    assert namen(fenster) == erwartet


def test_nachname_sortierung_kassen_unten(fenster):
    sortiere(fenster, "Nachname Z–A")
    assert namen(fenster)[-2:] == ["KW", "Getränkekasse"]


def test_klick_auf_spaltenkopf(fenster):
    fenster.filter.setCurrentText("Privatkonten")
    kopf = fenster.konten_tabelle.horizontalHeader()
    kopf.sectionClicked.emit(NACHNAME)
    assert fenster.sortierung.currentText() == "Nachname A–Z"
    assert (kopf.sortIndicatorSection(), kopf.sortIndicatorOrder()) == (NACHNAME, Qt.AscendingOrder)
    kopf.sectionClicked.emit(NACHNAME)
    assert fenster.sortierung.currentText() == "Nachname Z–A"
    assert kopf.sortIndicatorOrder() == Qt.DescendingOrder
    kopf.sectionClicked.emit(VORNAME)
    assert fenster.sortierung.currentText() == "Vorname A–Z"
    assert namen(fenster)[0] == "Anna Zimmer"


def test_auswahl_bleibt_beim_umsortieren(fenster):
    t = fenster.konten_tabelle
    t.selectRow(namen(fenster).index("Anna Zimmer"))
    sortiere(fenster, "Vorname Z–A")
    zeile = t.selectionModel().selectedRows()[0].row()
    assert namen(fenster)[zeile] == "Anna Zimmer"
    assert fenster.buchungen_titel.text() == "Buchungen – Anna Zimmer"


# --- Buchungssuche ----------------------------------------------------------

def buchungstexte(w):
    t = w.buchungen_tabelle
    return sorted(t.item(r, 3).text() for r in range(t.rowCount()))


@pytest.mark.parametrize("suche, erwartet", [
    ("", ["Auslage Grillfleisch", "Bierkasse Sommerfest", "Getränke Stammtisch", "Jahresbeitrag 2026"]),
    ("grill", ["Auslage Grillfleisch"]),
    ("GETRANKE", ["Getränke Stammtisch"]),  # Umlaute und Groß-/Kleinschreibung egal
    ("kasse sommer", ["Bierkasse Sommerfest"]),  # alle Wörter müssen vorkommen
    ("Zimmer", ["Jahresbeitrag 2026"]),  # Kontoname
    ("25", ["Bierkasse Sommerfest"]),  # Betrag
    ("25,00 €", ["Bierkasse Sommerfest"]),
    ("12,50", ["Jahresbeitrag 2026"]),
    ("-100", ["Auslage Grillfleisch"]),  # Vorzeichen egal
    ("2026", ["Jahresbeitrag 2026"]),  # Zahl im Text
    ("37,4", ["Getränke Stammtisch"]),
    ("inf", []),  # kein Absturz durch Decimal('inf')
    ("1.2.3", []),
])
def test_buchungssuche(fenster, suche, erwartet):
    fenster.buchungssuche.setText(suche)
    assert buchungstexte(fenster) == erwartet


def test_suche_zeigt_trefferzahl_und_gilt_im_konto(fenster):
    fenster.buchungssuche.setText("grill")
    assert fenster.buchungen_info.text() == "1 von 4 Buchungen"
    t = fenster.konten_tabelle
    t.selectRow(namen(fenster).index("Zoe Adler"))
    assert buchungstexte(fenster) == []
    assert fenster.buchungen_info.text().startswith("0 von 1 Buchungen")
    fenster.buchungssuche.clear()
    assert buchungstexte(fenster) == ["Bierkasse Sommerfest"]


def test_zahl_findet_nur_ganze_zahlen_im_text(verein):
    tom = verein.mitglied("Tom Becker")
    b2025 = verein.einzahlung(tom, "75", "Jahresbeitrag 2025")
    b25 = verein.einzahlung(tom, "3", "Runde für 25 Leute")
    betrag25 = verein.einzahlung(tom, "25", "Spende")
    treffer = {b.text for b in (b2025, b25, betrag25) if bh.buchung_passt(b, "25")}
    assert treffer == {"Runde für 25 Leute", "Spende"}
    assert bh.buchung_passt(b2025, "2025")
    assert bh.buchung_passt(b2025, "75,00 €")
