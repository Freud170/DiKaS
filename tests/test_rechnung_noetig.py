"""Welche Buchungen brauchen eine Rechnung? Standard nach Buchungsart, Ausnahmen, Filter „Ohne Rechnung“."""

import sqlite3
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dikas import anhaenge as an
from dikas import buchhaltung as bh
from dikas.db import erstelle_engine, init_db
from dikas.db.models import Buchung
from dikas.ui.hauptfenster import NAME_ROLLE, Hauptfenster

from conftest import Verein

D = date(2026, 3, 1)
PDF = an.Datei("Rechnung.pdf", an.PDF, b"%PDF-1.4\n%%EOF\n")


@pytest.fixture
def alles(verein):
    """Je eine Buchung jeder Sorte."""
    v = verein
    kasse, kasse2 = v.kasse("Getränkekasse"), v.kasse("Festkasse")
    tom, anna = v.mitglied("Tom Becker"), v.mitglied("Anna Schulz")
    bank = v.geldort("Bank")
    return {
        "ausgabe": v.ausgabe(kasse, "30", "Getränke", datum=D),
        "auslage": v.umbuchung(kasse, tom, "12", "Auslage Tom", datum=D),
        "einnahme": v.einnahme(kasse, "50", "Spende", datum=D),
        "kasse_kasse": v.umbuchung(kasse, kasse2, "5", "Wechselgeld", datum=D),
        "mitglied_kasse": v.umbuchung(tom, kasse, "8", "Stammtisch", datum=D),
        "mitglied_mitglied": v.umbuchung(tom, anna, "3", "Bier", datum=D),
        "beitrag": v.beitrag(tom, kasse, "60", datum=D),
        "einzahlung": v.einzahlung(tom, "100", datum=D),
        "auszahlung": v.auszahlung(anna, "10", datum=D),
        "transfer": v.geldtransfer(v.kw, bank, "20", datum=D),
    }


class TestStandard:
    @pytest.mark.parametrize("name, noetig", [
        ("ausgabe", True), ("auslage", True),
        ("einnahme", False), ("kasse_kasse", False), ("mitglied_kasse", False),
        ("mitglied_mitglied", False), ("beitrag", False), ("einzahlung", False),
        ("auszahlung", False), ("transfer", False),
    ])
    def test_nach_buchungsart(self, alles, name, noetig):
        assert bh.braucht_rechnung(alles[name]) is noetig
        assert bh.rechnung_fehlt(alles[name]) is noetig

    def test_mit_rechnung_fehlt_nichts(self, session, alles):
        an.anhaengen(session, alles["ausgabe"].id, PDF)
        assert bh.braucht_rechnung(alles["ausgabe"]) and not bh.rechnung_fehlt(alles["ausgabe"])

    def test_storno_und_storniert_nie(self, verein, alles):
        storno = verein.storno(alles["ausgabe"])
        assert not bh.braucht_rechnung(alles["ausgabe"]) and not bh.braucht_rechnung(storno)


class TestAusnahmen:
    def test_keine_rechnung_noetig(self, session, alles):
        assert bh.rechnung_noetig_setzen(session, [alles["ausgabe"].id], False) == 1
        assert alles["ausgabe"].rechnung_noetig is False
        assert not bh.rechnung_fehlt(alles["ausgabe"])

    def test_rechnung_noetig_obwohl_art_nicht(self, session, alles):
        bh.rechnung_noetig_setzen(session, [alles["einnahme"].id], True)
        assert bh.rechnung_fehlt(alles["einnahme"])

    def test_wert_wie_standard_wird_nicht_gespeichert(self, session, alles):
        assert bh.rechnung_noetig_setzen(session, [alles["ausgabe"].id], True) == 0
        assert alles["ausgabe"].rechnung_noetig is None

    def test_zurueck_auf_standard(self, session, alles):
        ids = [alles["ausgabe"].id, alles["beitrag"].id]
        bh.rechnung_noetig_setzen(session, ids, False)
        assert bh.rechnung_noetig_setzen(session, ids, None) == 1
        assert bh.rechnung_fehlt(alles["ausgabe"])

    def test_storno_wird_uebersprungen(self, session, verein, alles):
        storno = verein.storno(alles["ausgabe"])
        assert bh.rechnung_noetig_setzen(session, [storno.id], True) == 0

    def test_unbekannte_buchung(self, session):
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.rechnung_noetig_setzen(session, [999], False)

    def test_bleibt_bei_korrektur_mit_neubuchung(self, session, alles):
        ausgabe = alles["ausgabe"]
        bh.rechnung_noetig_setzen(session, [ausgabe.id], False)
        neu = bh.buchung_korrigieren(session, ausgabe.id, **(bh.eingabe_aus_buchung(ausgabe) | {"betrag_cent": 3100}))
        assert neu.id != ausgabe.id and neu.rechnung_noetig is False

    def test_bestehende_datenbank_bekommt_spalte(self, tmp_path):
        pfad = tmp_path / "alt.db"
        engine = erstelle_engine(pfad)
        init_db(engine)
        with Session(engine) as s, s.begin():
            v = Verein(s)
            v.ausgabe(v.kasse("Kasse"), "5", "Kauf")
        engine.dispose()
        with sqlite3.connect(pfad) as con:
            con.execute("ALTER TABLE buchungen DROP COLUMN rechnung_noetig")
        con.close()
        engine = erstelle_engine(pfad)
        init_db(engine)
        with Session(engine) as s:
            b = s.scalars(select(Buchung)).one()
            assert b.rechnung_noetig is None and bh.rechnung_fehlt(b)
        engine.dispose()


# --- Oberfläche ------------------------------------------------------------

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fenster(app, engine, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    with Session(engine) as s, s.begin():
        v = Verein(s)
        kasse = v.kasse("Getränkekasse")
        tom = v.mitglied("Tom Becker")
        v.ausgabe(kasse, "30", "Getränke", datum=D)
        v.ausgabe(kasse, "7", "Kassenbon fehlt", datum=D)
        v.umbuchung(kasse, tom, "12", "Auslage Tom", datum=D)
        v.beitrag(tom, kasse, "60", datum=D)
        v.einzahlung(tom, "100", datum=D)
    w = Hauptfenster(sessionmaker(engine, expire_on_commit=False), "test")
    yield w
    w.close()


def texte(w) -> list[str]:
    t = w.buchungen_tabelle
    return sorted(t.item(z, 3).text() for z in range(t.rowCount()))


def zeile(w, text) -> int:
    t = w.buchungen_tabelle
    return next(z for z in range(t.rowCount()) if t.item(z, 3).text() == text)


class TestFilter:
    def test_knopf_zeigt_anzahl_und_filtert(self, fenster):
        assert fenster.ohne_rechnung.text() == "Ohne Rechnung (3)"
        assert len(texte(fenster)) == 5
        fenster.ohne_rechnung.setChecked(True)
        assert texte(fenster) == ["Auslage Tom", "Getränke", "Kassenbon fehlt"]
        assert fenster.buchungen_titel.text() == "Alle Buchungen ohne Rechnung"
        assert "3 von 5" in fenster.buchungen_info.text()

    def test_status_spalte(self, fenster):
        t = fenster.buchungen_tabelle
        assert t.item(zeile(fenster, "Getränke"), 7).text() == "Rechnung fehlt"
        assert t.item(zeile(fenster, "Beitrag"), 7).text() == ""

    def test_einschalten_hebt_kontoauswahl_auf_und_alle_anzeigen_schaltet_aus(self, fenster):
        k = fenster.konten_tabelle
        k.selectRow(next(z for z in range(k.rowCount()) if k.item(z, 0).data(NAME_ROLLE) == "Tom Becker"))
        fenster.ohne_rechnung.setChecked(True)
        assert not k.selectionModel().hasSelection()
        assert len(texte(fenster)) == 3
        fenster.zeige_alle_buchungen()
        assert not fenster.ohne_rechnung.isChecked() and len(texte(fenster)) == 5

    def test_konto_waehlen_bei_aktivem_filter(self, fenster):
        fenster.ohne_rechnung.setChecked(True)
        k = fenster.konten_tabelle
        k.selectRow(next(z for z in range(k.rowCount()) if k.item(z, 0).data(NAME_ROLLE) == "Tom Becker"))
        assert texte(fenster) == ["Auslage Tom"]

    def test_suche_im_filter(self, fenster):
        fenster.ohne_rechnung.setChecked(True)
        fenster.buchungssuche.setText("Kassenbon")
        assert texte(fenster) == ["Kassenbon fehlt"]

    def test_keine_rechnung_noetig_per_rechtsklick(self, fenster):
        fenster.ohne_rechnung.setChecked(True)
        fenster.buchungen_tabelle.selectRow(zeile(fenster, "Kassenbon fehlt"))
        fenster.rechnung_noetig_setzen(False)
        assert texte(fenster) == ["Auslage Tom", "Getränke"]
        assert fenster.ohne_rechnung.text() == "Ohne Rechnung (2)"
        assert "braucht keine Rechnung" in fenster.statusBar().currentMessage()

    def test_rechnung_anhaengen_nimmt_aus_liste(self, fenster):
        with fenster.Session.begin() as s:
            b = s.scalars(select(Buchung).where(Buchung.text == "Getränke")).one()
            an.anhaengen(s, b.id, PDF)
        fenster.aktualisieren()
        fenster.ohne_rechnung.setChecked(True)
        assert texte(fenster) == ["Auslage Tom", "Kassenbon fehlt"]
