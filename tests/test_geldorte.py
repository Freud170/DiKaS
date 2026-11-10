"""Mehrere Geldorte: wo das Geld liegt (Bargeld, Bank, vorübergehend bei einer Person)."""

from datetime import date as D

import pytest
from PySide6.QtWidgets import QApplication
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas.db.models import Buchungsart as Art, KontoTyp
from dikas.ui.auswertung import AuswertungDialog, gruppiere
from dikas.ui.dialoge import BuchungDialog, KontoDialog
from conftest import Verein, ct


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# --- Fachlogik --------------------------------------------------------------

def test_einzahlung_auf_gewaehlten_geldort(verein):
    tom, bei_max = verein.mitglied("Tom"), verein.geldort("Bei Max")
    verein.einzahlung(tom, "50", ort=bei_max)
    verein.einzahlung(tom, "20")  # ohne Angabe: Standard-Geldort
    assert verein.saldo(bei_max) == ct("50")
    assert verein.saldo(verein.kw) == ct("20")
    assert verein.saldo(tom) == ct("70")
    verein.pruefe_abstimmung()


def test_kassenbuchungen_mit_geldort(verein):
    kasse, bei_max = verein.kasse("Festkasse"), verein.geldort("Bei Max")
    verein.einnahme(kasse, "100", ort=bei_max)
    verein.ausgabe(kasse, "30", ort=bei_max)
    assert verein.saldo(bei_max) == ct("70")
    assert verein.saldo(kasse) == ct("70")
    verein.pruefe_abstimmung()


def test_geldtransfer_aendert_nur_den_ort(verein):
    tom, bank = verein.mitglied("Tom"), verein.geldort("Bankkonto")
    verein.einzahlung(tom, "500")
    a_vorher = bh.abstimmung(verein.s)
    verein.geldtransfer(verein.kw, bank, "400")
    assert verein.saldo(verein.kw) == ct("100")
    assert verein.saldo(bank) == ct("400")
    assert verein.saldo(tom) == ct("500")
    assert bh.abstimmung(verein.s) == a_vorher
    verein.pruefe_abstimmung()


def test_geldtransfer_storno(verein):
    tom, bank = verein.mitglied("Tom"), verein.geldort("Bankkonto")
    verein.einzahlung(tom, "500")
    transfer = verein.geldtransfer(verein.kw, bank, "400")
    verein.storno(transfer)
    assert verein.saldo(bank) == 0 and verein.saldo(verein.kw) == ct("500")
    verein.pruefe_abstimmung()


def test_geldort_darf_ins_minus(verein):
    """Wie bisher beim KW-Konto: kein Schutz, die Abstimmung bleibt trotzdem stimmig."""
    tom, bei_max = verein.mitglied("Tom"), verein.geldort("Bei Max")
    verein.auszahlung(tom, "10", ort=bei_max)
    assert verein.saldo(bei_max) == ct("-10")
    verein.pruefe_abstimmung()


@pytest.mark.parametrize(
    "art, konto, gegen",
    [
        (Art.GELDTRANSFER, "kw", "kw"),  # gleicher Ort
        (Art.GELDTRANSFER, "kw", "kasse"),  # Kasse ist kein Geldort
        (Art.GELDTRANSFER, "tom", "kw"),
        (Art.EINZAHLUNG, "tom", "kasse"),  # Gegenkonto muss ein Geldort sein
        (Art.UMBUCHUNG, "kw", "kasse"),  # Geldorte nie umbuchen, dafür gibt es den Geldtransfer
    ],
)
def test_ungueltige_kombinationen(verein, art, konto, gegen):
    k = {"kw": verein.kw, "kasse": verein.kasse("K"), "tom": verein.mitglied("Tom")}
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.buchen(verein.s, art, k[konto].id, 100, "x", gegenkonto_id=k[gegen].id)


def test_geldtransfer_braucht_ziel(verein):
    with pytest.raises(bh.BuchhaltungsFehler, match="Nach"):
        bh.buchen(verein.s, Art.GELDTRANSFER, verein.kw.id, 100, "x")


def test_doppelter_name_verboten(verein):
    verein.geldort("Bankkonto")
    with pytest.raises(bh.BuchhaltungsFehler):
        verein.geldort("Bankkonto")


# --- Deaktivieren -----------------------------------------------------------

def deaktivieren(verein, konto):
    bh.konto_bearbeiten(verein.s, konto.id, konto.name, None, "", False)


def test_deaktivieren_nur_bei_saldo_null(verein):
    tom, bei_max = verein.mitglied("Tom"), verein.geldort("Bei Max")
    verein.einzahlung(tom, "50", ort=bei_max)
    with pytest.raises(bh.BuchhaltungsFehler, match="Saldo 0"):
        deaktivieren(verein, bei_max)
    verein.geldtransfer(bei_max, verein.kw, "50")  # Max gibt das Geld zurück
    deaktivieren(verein, bei_max)
    assert not bei_max.aktiv
    with pytest.raises(bh.BuchhaltungsFehler, match="deaktiviert"):
        verein.einzahlung(tom, "5", ort=bei_max)


def test_letzter_geldort_bleibt_aktiv(verein):
    with pytest.raises(bh.BuchhaltungsFehler, match="Mindestens ein Geldort"):
        deaktivieren(verein, verein.kw)


def test_standard_wechselt_wenn_erster_deaktiviert(verein):
    erster = verein.kw
    bank = verein.geldort("Bankkonto")
    deaktivieren(verein, erster)
    assert verein.kw.id == bank.id
    tom = verein.mitglied("Tom")
    verein.einzahlung(tom, "10")
    assert verein.saldo(bank) == ct("10")


def test_alter_geldort_bleibt_bearbeitbar(verein):
    """Umbenennen eines deaktivierten Geldorts darf nicht an der Saldo-Prüfung scheitern."""
    bei_max = verein.geldort("Bei Max")
    deaktivieren(verein, bei_max)
    bh.konto_bearbeiten(verein.s, bei_max.id, "Bei Max (erledigt)", None, "", False)
    assert bei_max.name == "Bei Max (erledigt)"


# --- Oberfläche -------------------------------------------------------------

def test_konto_dialog_kann_geldort_anlegen(app):
    d = KontoDialog()
    d.typ.setCurrentIndex(d.typ.findData(KontoTyp.KW))
    d.name.setText("Bei Max")
    d._pruefen()
    assert d.result() == KontoDialog.Accepted
    w = d.werte()
    assert w["typ"] == KontoTyp.KW and w["status"] is None and w["eintrittsdatum"] is None


def test_buchung_dialog_ein_geldort_ohne_auswahl(app, verein):
    verein.mitglied("Tom")
    d = BuchungDialog(bh.konten(verein.s))
    d.art.setCurrentIndex(d.art.findData(Art.EINZAHLUNG))
    assert not d.form.isRowVisible(d.gegen)


def test_buchung_dialog_mehrere_geldorte(app, verein):
    tom = verein.mitglied("Tom")
    standard = verein.kw
    bei_max = verein.geldort("Aaa bei Max")  # alphabetisch vor „KW“, trotzdem nicht vorausgewählt
    d = BuchungDialog(bh.konten(verein.s))
    d.art.setCurrentIndex(d.art.findData(Art.EINZAHLUNG))
    assert d.form.isRowVisible(d.gegen)
    assert d.form.labelForField(d.gegen).text() == "Geldort:"
    assert d.gegen.currentData() == standard.id
    d.gegen.setCurrentIndex(d.gegen.findData(bei_max.id))
    d.betrag.setText("5")
    d.text.setText("bar an Max")
    d._pruefen()
    assert d.result() == BuchungDialog.Accepted
    bh.buchen(verein.s, **d.werte())
    assert verein.saldo(bei_max) == ct("5") and verein.saldo(tom) == ct("5")


def test_buchung_dialog_geldtransfer(app, verein):
    bank = verein.geldort("Bankkonto")
    d = BuchungDialog(bh.konten(verein.s))
    d.art.setCurrentIndex(d.art.findData(Art.GELDTRANSFER))
    assert d.konto.count() == 2 and d.gegen.count() == 2
    assert d.form.isRowVisible(d.gegen)
    d.gegen.setCurrentIndex(d.gegen.findData(bank.id))
    d.betrag.setText("5")
    d.text.setText("zur Bank")
    d._pruefen()
    assert d.result() == BuchungDialog.Accepted
    assert d.werte()["gegenkonto_id"] == bank.id


def test_auswertung_kennzahlen_ohne_interne_transfers(app, engine, monkeypatch):
    """Ein Geldtransfer ist weder Einnahme noch Ausgabe – auch nicht als Storno."""
    with Session(engine) as s, s.begin():
        v = Verein(s)
        tom, bank = v.mitglied("Tom"), v.geldort("Bankkonto")
        v.einzahlung(tom, "100", datum=D(2026, 3, 1))
        v.geldtransfer(v.kw, bank, "80", datum=D(2026, 4, 1))
        v.storno(v.geldtransfer(bank, v.kw, "30", datum=D(2026, 5, 1)))
        v.auszahlung(tom, "10", datum=D(2026, 6, 1), ort=bank)
    d = AuswertungDialog(sessionmaker(engine), heute=D(2026, 10, 29))
    assert d.karte_einnahmen.wert.text() == "100,00 €"
    assert d.karte_ausgaben.wert.text() == "10,00 €"
    assert d.karte_ende.wert.text() == "90,00 €"
    gruppen = {titel: mit_summe for titel, _, mit_summe in gruppiere(d.bewegungen)}
    assert gruppen["Geldorte"] is True  # Summenzeile bei mehreren Geldorten
    d.close()
