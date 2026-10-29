"""Privatkonten löschen (nur bei Saldo 0) und wiederherstellen."""

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy.orm import sessionmaker

from dikas import buchhaltung as bh
from dikas.db.models import Buchungsart as Art, Konto, KontoTyp, MitgliedStatus as St
from dikas.ui.hauptfenster import Hauptfenster

from conftest import ct


class TestLoeschen:
    def test_konto_ohne_buchungen_wird_entfernt(self, verein, session):
        tom = verein.mitglied("Tom")
        tom_id = tom.id
        assert bh.konto_loeschen(session, tom_id) is True
        assert session.get(Konto, tom_id) is None
        verein.mitglied("Tom")  # Name ist wieder frei

    def test_konto_mit_buchungen_und_saldo_null_wird_archiviert(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        verein.beitrag(tom, kasse, "60")
        verein.einzahlung(tom, "60")

        assert bh.konto_loeschen(session, tom.id) is False

        assert tom.geloescht and not tom.aktiv
        assert len(bh.buchungen(session, tom.id)) == 2  # Historie bleibt
        assert verein.saldo(kasse) == ct(60)
        assert verein.saldo(verein.kw) == ct(60)
        verein.pruefe_abstimmung()

    @pytest.mark.parametrize("schuld", [True, False])
    def test_nicht_null_saldo_verhindert_loeschen(self, verein, session, schuld):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        if schuld:
            verein.beitrag(tom, kasse, "60")
        else:
            verein.einzahlung(tom, "0,01")  # Guthaben, auch nur 1 Cent
        with pytest.raises(bh.BuchhaltungsFehler, match="Saldo 0"):
            bh.konto_loeschen(session, tom.id)
        assert not tom.geloescht

    def test_saldo_null_nach_storno(self, verein, session):
        tom = verein.mitglied("Tom")
        verein.storno(verein.einzahlung(tom, "10"))
        assert bh.konto_loeschen(session, tom.id) is False

    def test_deaktiviertes_konto_kann_geloescht_werden(self, verein, session):
        tom = verein.mitglied("Tom")
        tom.aktiv = False
        assert bh.konto_loeschen(session, tom.id) is True

    @pytest.mark.parametrize("typ", [KontoTyp.KASSE, KontoTyp.KW])
    def test_nur_privatkonten(self, verein, session, typ):
        konto = verein.kw if typ == KontoTyp.KW else verein.kasse("K")
        with pytest.raises(bh.BuchhaltungsFehler, match="Nur Privatkonten"):
            bh.konto_loeschen(session, konto.id)

    def test_doppelt_loeschen(self, verein, session):
        tom = verein.mitglied("Tom")
        verein.storno(verein.einzahlung(tom, "1"))
        bh.konto_loeschen(session, tom.id)
        with pytest.raises(bh.BuchhaltungsFehler, match="bereits gelöscht"):
            bh.konto_loeschen(session, tom.id)

    def test_unbekanntes_konto(self, session):
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.konto_loeschen(session, 9999)


class TestGeloeschtesKonto:
    @pytest.fixture
    def tom(self, verein, session):
        tom = verein.mitglied("Tom")
        self.buchung = verein.einzahlung(tom, "10")
        verein.auszahlung(tom, "10")
        bh.konto_loeschen(session, tom.id)
        return tom

    def test_keine_neuen_buchungen(self, verein, tom):
        with pytest.raises(bh.BuchhaltungsFehler, match="gelöscht"):
            verein.einzahlung(tom, "5")

    def test_keine_umbuchung_darauf(self, verein, tom):
        kasse = verein.kasse("K")
        with pytest.raises(bh.BuchhaltungsFehler, match="gelöscht"):
            verein.umbuchung(kasse, tom, "5")

    def test_kein_storno_alter_buchungen(self, verein, tom):
        """Sonst stünde das unsichtbare Konto plötzlich nicht mehr auf 0."""
        with pytest.raises(bh.BuchhaltungsFehler, match="wiederherstellen"):
            verein.storno(self.buchung)

    def test_nicht_im_beitragslauf(self, verein, tom):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Fritz")
        gebucht = verein.beitragslauf(kasse, aktiver="60")
        assert len(gebucht) == 1
        assert verein.saldo(tom) == 0

    def test_nicht_bearbeitbar(self, session, tom):
        with pytest.raises(bh.BuchhaltungsFehler, match="wiederherstellen"):
            bh.konto_bearbeiten(session, tom.id, "Tom", St.AKTIVER, "", True)

    def test_name_bleibt_belegt_mit_hinweis(self, verein, tom):
        with pytest.raises(bh.BuchhaltungsFehler, match="wiederherstellen"):
            verein.mitglied("Tom")

    def test_bleibt_in_salden_und_abstimmung(self, verein, session, tom):
        assert bh.salden(session)[tom.id] == 0
        verein.pruefe_abstimmung()

    def test_wiederherstellen(self, verein, session, tom):
        bh.konto_wiederherstellen(session, tom.id)
        assert not tom.geloescht and tom.aktiv
        verein.einzahlung(tom, "5")
        verein.storno(self.buchung)
        assert verein.saldo(tom) == ct("-5")
        verein.pruefe_abstimmung()

    def test_wiederherstellen_nicht_geloeschtes(self, verein, session):
        with pytest.raises(bh.BuchhaltungsFehler, match="nicht gelöscht"):
            bh.konto_wiederherstellen(session, verein.mitglied("Fritz").id)


def test_szenario_austritt_bis_loeschung(verein, session):
    """Mitglied tritt mit Schulden aus, zahlt später, Konto wird gelöscht."""
    kasse = verein.kasse("Beitragskasse")
    tom = verein.mitglied("Tom", St.ALUMNI)
    verein.beitrag(tom, kasse, "100")
    bh.konto_bearbeiten(session, tom.id, "Tom", St.ALUMNI, "ausgetreten", False)

    with pytest.raises(bh.BuchhaltungsFehler):
        bh.konto_loeschen(session, tom.id)  # Schulden offen

    bh.konto_bearbeiten(session, tom.id, "Tom", St.ALUMNI, "ausgetreten", True)
    verein.einzahlung(tom, "100", "Restzahlung")
    assert bh.konto_loeschen(session, tom.id) is False

    assert verein.saldo(kasse) == verein.saldo(verein.kw) == ct(100)
    verein.pruefe_abstimmung()


# --- Oberfläche -----------------------------------------------------------

@pytest.fixture
def fenster(engine, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    meldungen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: meldungen.append(a[2]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: meldungen.append(a[2]))
    Sitzung = sessionmaker(engine, expire_on_commit=False)
    with Sitzung.begin() as s:
        kasse = bh.konto_anlegen(s, "Beitragskasse", KontoTyp.KASSE)
        tom = bh.konto_anlegen(s, "Tom", KontoTyp.PRIVAT, St.AKTIVER)
        bh.konto_anlegen(s, "Neu", KontoTyp.PRIVAT, St.FUX)
        schuldner = bh.konto_anlegen(s, "Schuldner", KontoTyp.PRIVAT, St.AKTIVER)
        bh.buchen(s, Art.EINZAHLUNG, tom.id, 500, "x")
        bh.buchen(s, Art.AUSZAHLUNG, tom.id, 500, "y")
        bh.buchen(s, Art.BEITRAG, schuldner.id, 500, "z", gegenkonto_id=kasse.id)
    w = Hauptfenster(Sitzung, "test")
    w.meldungen = meldungen
    yield w
    w.close()


def waehle(w, name):
    t = w.konten_tabelle
    for r in range(t.rowCount()):
        if t.item(r, 0).text() == name:
            t.selectRow(r)
            return
    raise AssertionError(f"{name} nicht sichtbar")


def namen(w):
    return {w.konten_tabelle.item(r, 0).text() for r in range(w.konten_tabelle.rowCount())}


def test_ui_loeschen_und_wiederherstellen(fenster):
    waehle(fenster, "Tom")
    fenster.konto_loeschen()
    assert "Tom" not in namen(fenster)

    fenster.filter.setCurrentText("Gelöschte")
    assert namen(fenster) == {"Tom"}

    waehle(fenster, "Tom")
    fenster.konto_wiederherstellen()
    assert namen(fenster) == set()
    fenster.filter.setCurrentText("Alle Konten")
    assert "Tom" in namen(fenster)


def test_ui_konto_ohne_buchungen_verschwindet_ganz(fenster):
    waehle(fenster, "Neu")
    fenster.konto_loeschen()
    fenster.filter.setCurrentText("Gelöschte")
    assert "Neu" not in namen(fenster)


def test_ui_saldo_ungleich_null(fenster):
    waehle(fenster, "Schuldner")
    fenster.konto_loeschen()
    assert "Saldo 0" in fenster.meldungen[-1]
    assert "Schuldner" in namen(fenster)


def test_ui_loeschen_ohne_auswahl(fenster):
    fenster.konto_loeschen()
    assert "auswählen" in fenster.meldungen[-1]
