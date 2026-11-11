"""Kontenliste mit Vor-/Nachname/Bierspitz und Sortierung; Suche in den Buchungen."""

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas.db.models import Buchungsart as Art, KontoTyp, MitgliedStatus as St
from dikas.ui.hauptfenster import (
    BIERSPITZ, KONTEN_SORTIERUNG, KONTEN_SPALTEN, NACHNAME, NAME_ROLLE, SALDO, VORNAME, Hauptfenster,
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

def sichtbare_spalten(w):
    """Überschriften in der angezeigten Reihenfolge, ohne ausgeblendete Spalten."""
    kopf = w.konten_tabelle.horizontalHeader()
    return [KONTEN_SPALTEN[kopf.logicalIndex(v)] for v in range(kopf.count())
            if not kopf.isSectionHidden(kopf.logicalIndex(v))]


def test_spalten_nachname_vorname_bierspitz(fenster):
    t = fenster.konten_tabelle
    assert sichtbare_spalten(fenster) == [
        "Nachname", "Vorname", "Bierspitz", "Typ", "Status", "Eintritt", "Saldo"]
    z = namen(fenster).index("Ben von Ärmel")
    assert [t.item(z, i).text() for i in (NACHNAME, VORNAME, BIERSPITZ)] == ["von Ärmel", "Ben", "Bärchen"]


def test_kasse_in_der_namensspalte(fenster):
    t = fenster.konten_tabelle
    z = namen(fenster).index("Getränkekasse")
    assert (t.item(z, NACHNAME).text(), t.item(z, VORNAME).text()) == ("Getränkekasse", "")


# --- Spalten verschieben / ausblenden (pro PC gemerkt) ------------------------

def neues_fenster(fenster):
    return Hauptfenster(fenster.Session, "test")


def test_spalte_ausblenden_und_merken(fenster):
    menue = fenster.spalten_menue()
    aktionen = {a.text(): a for a in menue.actions() if a.text()}
    assert not aktionen["Nachname"].isEnabled()  # bleibt immer sichtbar
    aktionen["Typ"].setChecked(False)
    assert "Typ" not in sichtbare_spalten(fenster)
    w2 = neues_fenster(fenster)
    assert "Typ" not in sichtbare_spalten(w2)
    w2.close()


def test_spalte_verschieben_und_merken(fenster):
    kopf = fenster.konten_tabelle.horizontalHeader()
    kopf.moveSection(kopf.visualIndex(SALDO), 1)  # Saldo direkt hinter Nachname
    assert sichtbare_spalten(fenster)[:3] == ["Nachname", "Saldo", "Vorname"]
    w2 = neues_fenster(fenster)
    assert sichtbare_spalten(w2)[:3] == ["Nachname", "Saldo", "Vorname"]
    # Sortieren per Klick nutzt trotzdem die richtige Spalte
    w2.konten_tabelle.horizontalHeader().sectionClicked.emit(SALDO)
    assert w2.sortierung.currentText() == "Saldo: niedrigster zuerst"
    w2.close()


def test_standardansicht(fenster):
    kopf = fenster.konten_tabelle.horizontalHeader()
    kopf.moveSection(kopf.visualIndex(SALDO), 0)
    fenster.spalte_zeigen(BIERSPITZ, False)
    fenster.spalten_zuruecksetzen()
    assert sichtbare_spalten(fenster) == KONTEN_SPALTEN
    w2 = neues_fenster(fenster)
    assert sichtbare_spalten(w2) == KONTEN_SPALTEN
    w2.close()


def test_kaputte_einstellung_wird_ignoriert(fenster):
    e = fenster._einstellungen()
    e.setValue("konten/reihenfolge", "3,x,1")
    e.setValue("konten/ausgeblendet", "0,99")
    w2 = neues_fenster(fenster)
    assert sichtbare_spalten(w2) == KONTEN_SPALTEN
    w2.close()


# --- Spaltenbreiten passen sich der Fenstergröße an ---------------------------

@pytest.mark.parametrize("tabelle", ["konten_tabelle", "buchungen_tabelle"])
def test_spalten_fuellen_breites_fenster(app, fenster, tabelle):
    fenster.resize(2400, 900)
    fenster.show()
    app.processEvents()
    t = getattr(fenster, tabelle)
    kopf = t.horizontalHeader()
    sichtbar = [s for s in range(t.columnCount()) if not kopf.isSectionHidden(s)]
    belegt = sum(kopf.sectionSize(s) for s in sichtbar)
    inhalt = sum(max(t.sizeHintForColumn(s), kopf.sectionSizeHint(s)) for s in sichtbar)
    # Füllt die ganze Breite – außer der Inhalt ist breiter, dann waagerecht scrollen
    assert belegt == max(t.viewport().width(), inhalt)


def test_schmales_fenster_quetscht_keine_spalte(app, fenster):
    fenster.resize(2400, 900)
    fenster.show()
    app.processEvents()
    fenster.resize(900, 700)
    app.processEvents()
    t = fenster.konten_tabelle
    kopf = t.horizontalHeader()
    for s in range(t.columnCount()):
        assert kopf.sectionSize(s) >= max(t.sizeHintForColumn(s), kopf.sectionSizeHint(s))


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


def test_suchen_liest_nicht_bei_jedem_tastendruck_aus_der_datenbank(fenster, monkeypatch):
    """Suche, Filter und Sortierung arbeiten auf den geladenen Daten (bleibt auch nach Jahren flott)."""
    gelesen = []
    for name in ("buchungen", "salden", "konten"):
        original = getattr(bh, name)
        monkeypatch.setattr(
            bh, name, lambda *a, _original=original, _name=name, **k: (gelesen.append(_name), _original(*a, **k))[1]
        )
    for text in ("g", "gr", "gri", "grill"):
        fenster.buchungssuche.setText(text)
    assert buchungstexte(fenster) == ["Auslage Grillfleisch"]
    fenster.buchungssuche.clear()
    fenster.suche.setText("zim")
    assert namen(fenster) == ["Anna Zimmer"]
    fenster.suche.clear()
    sortiere(fenster, "Saldo: höchster zuerst")
    fenster.filter.setCurrentText("Kassen")
    assert namen(fenster) == ["Getränkekasse"]
    assert gelesen == []

    # Ein anderes Konto wählen lädt genau dessen Buchungen
    fenster.filter.setCurrentText("Alle Konten")
    fenster.konten_tabelle.selectRow(namen(fenster).index("Zoe Adler"))
    assert gelesen == ["buchungen"]
    assert buchungstexte(fenster) == ["Bierkasse Sommerfest"]


def test_nach_einer_buchung_sind_liste_und_saldo_aktuell(fenster):
    fenster.konten_tabelle.selectRow(namen(fenster).index("Zoe Adler"))
    assert "Saldo <b>25,00 €</b>" in fenster.buchungen_info.text()
    with fenster.Session() as s:
        zoe_id = _drei(s)[0].id
    fenster.buchungssuche.setText("spende")
    assert buchungstexte(fenster) == []

    assert fenster._ausfuehren(lambda s: bh.buchen(s, Art.EINZAHLUNG, zoe_id, 500, "Spende"))

    assert buchungstexte(fenster) == ["Spende"]
    assert fenster.buchungen_info.text() == "1 von 2 Buchungen · Saldo <b>30,00 €</b>"


def test_tausenderpunkt_in_der_betragssuche(verein):
    tom = verein.mitglied("Tom Becker")
    gross = verein.einzahlung(tom, "1.000", "Erbschaft")
    klein = verein.einzahlung(tom, "1", "Pfand")
    assert gross.betrag_cent == 100000
    assert bh.buchung_passt(gross, "1.000") and not bh.buchung_passt(klein, "1.000")
    assert not bh.buchung_passt(gross, "9" * 40)  # kein Absturz bei unsinnig langen Zahlen


def test_zahl_findet_nur_ganze_zahlen_im_text(verein):
    tom = verein.mitglied("Tom Becker")
    b2025 = verein.einzahlung(tom, "75", "Jahresbeitrag 2025")
    b25 = verein.einzahlung(tom, "3", "Runde für 25 Leute")
    betrag25 = verein.einzahlung(tom, "25", "Spende")
    treffer = {b.text for b in (b2025, b25, betrag25) if bh.buchung_passt(b, "25")}
    assert treffer == {"Runde für 25 Leute", "Spende"}
    assert bh.buchung_passt(b2025, "2025")
    assert bh.buchung_passt(b2025, "75,00 €")


def test_vollbild_gibt_buchungen_mehr_platz(app, fenster):
    fenster.show()
    fenster.resize(2400, 1000)
    app.processEvents()
    links, rechts = fenster.splitter.sizes()
    gesamt = fenster.splitter.width() - fenster.splitter.handleWidth()
    assert links == int(gesamt * 0.45)
    assert rechts > links


def test_eigene_aufteilung_bleibt(app, fenster):
    fenster.show()
    app.processEvents()
    fenster.splitter.splitterMoved.emit(500, 1)  # wie beim Ziehen des Trenners
    fenster.splitter.setSizes([500, 800])
    fenster.resize(2400, 1000)
    app.processEvents()
    gesamt = fenster.splitter.width() - fenster.splitter.handleWidth()
    assert fenster.splitter.sizes()[0] != int(gesamt * 0.45)
