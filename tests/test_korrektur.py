"""Buchungen korrigieren und Beitragslauf für im Jahr eingetretene Mitglieder."""

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas.db.models import Buchungsart as Art, MitgliedStatus as St
from dikas.ui.dialoge import BuchungDialog
from dikas.ui.hauptfenster import NAME_ROLLE, SALDO, Hauptfenster

from conftest import Verein, ct

D = date


def gueltige(session, konto):
    """Nicht stornierte, nicht-Storno-Buchungen eines Kontos."""
    return [b for b in bh.buchungen(session, konto.id) if not b.ist_storno and not b.ist_storniert]


class TestKorrigieren:
    def test_nur_text_und_beleg_direkt(self, verein, session):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "10", "Ueberweisng", D(2026, 3, 1))
        ergebnis = bh.buchung_korrigieren(session, b.id, Art.EINZAHLUNG, tom.id, ct(10), "Überweisung",
                                          D(2026, 3, 1), "B-7")
        assert ergebnis.id == b.id and (b.text, b.beleg) == ("Überweisung", "B-7")
        assert len(bh.buchungen(session)) == 1  # kein Storno nötig

    def test_betrag_aendern_storno_und_neu(self, verein, session):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "100", "Überweisung", D(2026, 3, 1))
        neu = bh.buchung_korrigieren(session, b.id, Art.EINZAHLUNG, tom.id, ct(10), "Überweisung", D(2026, 3, 1))
        assert neu.id != b.id and b.ist_storniert
        assert b.storniert_durch.datum == D(2026, 3, 1)  # Storno mit dem Datum der Originalbuchung
        assert verein.saldo(tom) == verein.saldo(verein.kw) == ct(10)
        verein.pruefe_abstimmung()

    def test_falsches_mitglied(self, verein, session):
        tom, tim = verein.mitglied("Tom"), verein.mitglied("Tim")
        b = verein.einzahlung(tim, "60")
        bh.buchung_korrigieren(session, b.id, Art.EINZAHLUNG, tom.id, ct(60), "Beitrag", b.datum)
        assert (verein.saldo(tim), verein.saldo(tom)) == (0, ct(60))

    def test_falsche_buchungsart(self, verein, session):
        tom = verein.mitglied("Tom")
        b = verein.auszahlung(tom, "50")
        bh.buchung_korrigieren(session, b.id, Art.EINZAHLUNG, tom.id, ct(50), "Einzahlung", b.datum)
        assert verein.saldo(tom) == ct(50)

    def test_datum_aendern(self, verein, session):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "10", datum=D(2026, 3, 1))
        neu = bh.buchung_korrigieren(session, b.id, Art.EINZAHLUNG, tom.id, ct(10), "x", D(2025, 12, 31))
        assert neu.datum == D(2025, 12, 31)
        assert bh.salden(session, bis=D(2026, 1, 31))[tom.id] == ct(10)

    def test_umbuchung_gegenkonto_aendern(self, verein, session):
        tom = verein.mitglied("Tom")
        a, b_kasse = verein.kasse("A"), verein.kasse("B")
        b = verein.umbuchung(tom, a, "5")
        bh.buchung_korrigieren(session, b.id, Art.UMBUCHUNG, tom.id, ct(5), "x", b.datum, gegenkonto_id=b_kasse.id)
        assert (verein.saldo(a), verein.saldo(b_kasse)) == (0, ct(5))

    def test_beitrag_betrag_korrigieren_behaelt_beitragsjahr(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom", St.FUX)
        (b,) = verein.beitragslauf(kasse, fux="150", jahr=2026)
        neu = bh.buchung_korrigieren(session, b.id, Art.BEITRAG, tom.id, ct(75), b.text, b.datum,
                                     gegenkonto_id=kasse.id)
        assert neu.beitragsjahr == 2026
        assert verein.saldo(tom) == ct(-75)
        v = bh.beitrag_vorschau(session, {St.FUX: 15000}, 2026)
        assert [m.name for m in v.bereits_abgebucht] == ["Tom"]  # Doppelschutz greift weiter

    def test_beitrag_zu_anderer_art_verliert_beitragsjahr(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        (b,) = verein.beitragslauf(kasse, aktiver="60", jahr=2026)
        neu = bh.buchung_korrigieren(session, b.id, Art.UMBUCHUNG, tom.id, ct(60), "x", b.datum,
                                     gegenkonto_id=kasse.id)
        assert neu.beitragsjahr is None
        assert bh.beitrag_vorschau(session, {St.AKTIVER: 6000}, 2026).faellig  # wieder fällig

    @pytest.mark.parametrize("fall", ["storno", "storniert"])
    def test_storno_nicht_korrigierbar(self, verein, session, fall):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "10")
        s = verein.storno(b)
        ziel = s if fall == "storno" else b
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.buchung_korrigieren(session, ziel.id, Art.EINZAHLUNG, tom.id, ct(5), "x", ziel.datum)

    def test_fehler_laesst_alles_unveraendert(self, engine):
        Sitzung = sessionmaker(engine)
        with Sitzung.begin() as s:
            v = Verein(s)
            tom = v.mitglied("Tom")
            b_id, tom_id = v.einzahlung(tom, "10").id, tom.id
        with pytest.raises(bh.BuchhaltungsFehler):
            with Sitzung.begin() as s:
                bh.buchung_korrigieren(s, b_id, Art.EINZAHLUNG, tom_id, -5, "x", D(2026, 1, 1))
        with Sitzung() as s:
            assert len(bh.buchungen(s)) == 1 and not bh.buchungen(s)[0].ist_storniert

    def test_eingabe_aus_buchung(self, verein):
        tom = verein.mitglied("Tom")
        kasse = verein.kasse("K")
        b = verein.beitrag(tom, kasse, "60", "Beitrag", D(2026, 1, 1))
        assert bh.eingabe_aus_buchung(b) == {
            "art": Art.BEITRAG, "konto_id": tom.id, "gegenkonto_id": kasse.id, "betrag_cent": ct(60),
            "text": "Beitrag", "datum": D(2026, 1, 1), "beleg": "",
        }
        e = verein.einzahlung(tom, "5")
        # Seit es mehrere Geldorte gibt, gehört der Geldort zur Eingabe
        assert bh.eingabe_aus_buchung(e)["konto_id"] == tom.id and bh.eingabe_aus_buchung(e)["gegenkonto_id"] == verein.kw.id


class TestImJahrEingetreten:
    """Ricos Fall: Mitglieder, die im Laufe des Jahres eingetreten sind und deren Status sich änderte."""

    @pytest.fixture
    def lage(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        a = verein.mitglied("Anna", St.FUX, eintritt=D(2026, 3, 15))
        bh.status_wechseln(session, a.id, St.AKTIVER, D(2026, 6, 14))
        e = verein.mitglied("Emil", St.FUX, eintritt=D(2026, 3, 15))
        bh.status_wechseln(session, e.id, St.EHREN, D(2026, 7, 21))
        return kasse, a, e

    def test_status_zum_jahresende_bzw_heute(self, lage):
        _, anna, emil = lage
        assert bh.beitragsstatus(anna, 2026, heute=D(2026, 11, 3)) == St.AKTIVER
        assert bh.beitragsstatus(emil, 2026, heute=D(2026, 11, 3)) == St.EHREN
        assert bh.beitragsstatus(anna, 2026, heute=D(2026, 5, 1)) == St.FUX  # Jahr läuft noch

    def test_bei_eintritt_vor_stichtag_bleibt_01_01(self, verein, session):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2025, 10, 1))
        bh.status_wechseln(session, tom.id, St.AKTIVER, D(2026, 6, 1))
        assert bh.beitragsstatus(tom, 2026, heute=D(2026, 11, 3)) == St.FUX

    def test_wahl_nach_storno_wieder_moeglich(self, verein, session, lage):
        kasse, anna, emil = lage
        betraege = {St.FUX: ct(150), St.AKTIVER: ct(75), St.EHREN: 0}
        v = bh.beitrag_vorschau(session, betraege, 2026, heute=D(2026, 11, 3))
        assert [m.name for m in v.spaeter_eingetreten] == ["Anna"]  # als Aktive wählbar
        assert v.betrag_je_konto[anna.id] == ct(75)
        assert [m.name for m in v.ohne_beitrag] == ["Emil"]  # Ehrenmitglied: 0 € → sichtbar mit Grund
        assert v.status_je_konto[emil.id] == St.EHREN

    def test_ohne_beitrag_nicht_buchbar(self, verein, session, lage):
        kasse, _, emil = lage
        with pytest.raises(bh.BuchhaltungsFehler, match="kann kein Beitrag"):
            bh.beitraege_abbuchen(session, {St.EHREN: 0, St.AKTIVER: 7500}, 2026, kasse.id, "x",
                                  konto_ids=[emil.id])


# --- Oberfläche -----------------------------------------------------------

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class TestOberflaeche:
    @pytest.fixture
    def fenster(self, app, engine, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
        with Session(engine) as s, s.begin():
            v = Verein(s)
            tom = v.mitglied("Tom Becker")
            v.einzahlung(tom, "100", "Überweisung", D(2026, 3, 1))
        w = Hauptfenster(sessionmaker(engine, expire_on_commit=False), "test")
        yield w
        w.close()

    def test_dialog_ist_vorbefuellt(self, app, verein):
        tom = verein.mitglied("Tom")
        kasse = verein.kasse("K")
        b = verein.beitrag(tom, kasse, "60,50", "Beitrag", D(2026, 1, 1))
        d = BuchungDialog(bh.konten(verein.s, True), vorlage=bh.eingabe_aus_buchung(b))
        assert d.windowTitle() == "Buchung korrigieren"
        assert d.art.currentData() == Art.BEITRAG
        assert (d.konto.currentData(), d.gegen.currentData()) == (tom.id, kasse.id)
        assert (d.betrag.text(), d.text.text()) == ("60,50", "Beitrag")
        assert d.datum.date().toPython() == D(2026, 1, 1)

    def test_korrigieren_ueber_oberflaeche(self, fenster, monkeypatch):
        def dialog_ausfuellen(dialog):
            dialog.betrag.setText("10")
            dialog._pruefen()
            return dialog.result()
        monkeypatch.setattr(BuchungDialog, "exec", dialog_ausfuellen)
        fenster.buchungen_tabelle.selectRow(0)
        fenster.korrigiere_auswahl()
        t = fenster.konten_tabelle
        zeile = next(r for r in range(t.rowCount()) if t.item(r, 0).data(NAME_ROLLE) == "Tom Becker")
        assert t.item(zeile, SALDO).text() == "10,00 €"
        assert fenster.buchungen_tabelle.rowCount() == 3  # Original, Storno, neue Buchung

    def test_korrigieren_ohne_auswahl(self, fenster, monkeypatch):
        meldungen = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a: meldungen.append(a[2]))
        fenster.buchungen_tabelle.clearSelection()
        fenster.korrigiere_auswahl()
        assert "auswählen" in meldungen[-1]

    def test_stornierte_nicht_korrigierbar(self, fenster, monkeypatch):
        fenster.buchungen_tabelle.selectRow(0)
        fenster.storniere_auswahl()
        meldungen = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a: meldungen.append(a[2]))
        fenster.buchungen_tabelle.selectRow(0)
        fenster.korrigiere_auswahl()
        assert "nicht korrigiert" in meldungen[-1]

    def test_stornieren_nicht_mehr_in_werkzeugleiste(self, fenster):
        from PySide6.QtWidgets import QToolBar
        leiste = fenster.findChild(QToolBar)
        assert "Stornieren" not in [a.text() for a in leiste.actions()]
