"""Oberflächentests (laufen ohne sichtbares Fenster)."""

from datetime import date

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy.orm import sessionmaker

from dikas import buchhaltung as bh
from dikas.db.models import Buchungsart as Art, KontoTyp, MitgliedStatus as St
from dikas.ui import stil
from dikas.ui.dialoge import UNBEKANNT, BeitragDialog, BuchungDialog, KontoDialog
from dikas.ui.hauptfenster import Hauptfenster


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def keine_meldungen(monkeypatch):
    """Meldungsfenster nicht anzeigen, sondern mitschreiben."""
    meldungen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: meldungen.append(a[2]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: meldungen.append(a[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    return meldungen


@pytest.fixture
def Sitzung(engine):
    Sitzung = sessionmaker(engine, expire_on_commit=False)
    with Sitzung.begin() as s:
        bh.konto_anlegen(s, "Beitragskasse", KontoTyp.KASSE)
        bh.konto_anlegen(s, "Getränkekasse", KontoTyp.KASSE)
        tom = bh.konto_anlegen(s, "Tom", KontoTyp.PRIVAT, St.AKTIVER, eintrittsdatum=date(2020, 10, 1))
        bh.konto_anlegen(s, "Fritz", KontoTyp.PRIVAT, St.FUX, eintrittsdatum=date(2025, 10, 15))
        bh.konto_anlegen(s, "Alfred", KontoTyp.PRIVAT, St.ALUMNI, eintrittsdatum=date(1990, 4, 1))
        bh.buchen(s, Art.EINZAHLUNG, tom.id, 1000, "Überweisung")
    return Sitzung


@pytest.fixture
def fenster(app, Sitzung):
    w = Hauptfenster(Sitzung, "test")
    yield w
    w.close()


def zeile_von(tabelle, name):
    for r in range(tabelle.rowCount()):
        if tabelle.item(r, 0).text() == name:
            return r
    raise AssertionError(f"{name} nicht in Tabelle")


def konten(Sitzung):
    with Sitzung() as s:
        return bh.konten(s, nur_aktive=True)


# --- Hauptfenster ---------------------------------------------------------

class TestHauptfenster:
    def test_zeigt_alle_konten_und_salden(self, fenster):
        t = fenster.konten_tabelle
        assert t.rowCount() == 6
        assert t.item(zeile_von(t, "Tom"), 4).text() == "10,00 €"
        assert t.item(zeile_von(t, "KW"), 4).text() == "10,00 €"
        assert t.item(zeile_von(t, "Fritz"), 2).text() == "Fux"

    def test_abstimmung_in_statusleiste(self, fenster):
        assert "stimmt" in fenster.abstimmung.text()

    @pytest.mark.parametrize(
        "filter_, anzahl", [("Alle Konten", 6), ("Privatkonten", 3), ("Füxe", 1),
                            ("Aktive", 1), ("Alumni", 1), ("Kassen", 2)]
    )
    def test_filter(self, fenster, filter_, anzahl):
        fenster.filter.setCurrentText(filter_)
        assert fenster.konten_tabelle.rowCount() == anzahl

    def test_auswahl_zeigt_buchungen_des_kontos(self, fenster):
        t = fenster.konten_tabelle
        t.selectRow(zeile_von(t, "Fritz"))
        assert fenster.buchungen_tabelle.rowCount() == 0
        assert "Fritz" in fenster.buchungen_titel.text()
        t.selectRow(zeile_von(t, "Tom"))
        assert fenster.buchungen_tabelle.rowCount() == 1
        fenster.zeige_alle_buchungen()
        assert "Alle" in fenster.buchungen_titel.text()

    def test_betrag_aus_sicht_des_kontos(self, fenster, Sitzung):
        with Sitzung.begin() as s:
            tom = next(k for k in bh.konten(s) if k.name == "Tom")
            bh.buchen(s, Art.AUSZAHLUNG, tom.id, 300, "Erstattung")
        fenster.aktualisieren()
        t = fenster.konten_tabelle
        t.selectRow(zeile_von(t, "Tom"))
        betraege = {fenster.buchungen_tabelle.item(r, 3).text(): fenster.buchungen_tabelle.item(r, 6).text()
                    for r in range(fenster.buchungen_tabelle.rowCount())}
        assert betraege == {"Erstattung": "-3,00 €", "Überweisung": "10,00 €"}

    def test_stornieren_ueber_oberflaeche(self, fenster):
        fenster.buchungen_tabelle.selectRow(0)
        fenster.storniere_auswahl()
        t = fenster.konten_tabelle
        assert t.item(zeile_von(t, "Tom"), 4).text() == "0,00 €"
        assert fenster.buchungen_tabelle.rowCount() == 2
        status = {fenster.buchungen_tabelle.item(r, 7).text() for r in range(2)}
        assert status == {"storniert", ""}

    def test_stornieren_ohne_auswahl(self, fenster, keine_meldungen):
        fenster.buchungen_tabelle.clearSelection()
        fenster.storniere_auswahl()
        assert "auswählen" in keine_meldungen[-1]

    def test_doppeltes_storno_zeigt_fehler(self, fenster, keine_meldungen):
        fenster.buchungen_tabelle.selectRow(0)
        fenster.storniere_auswahl()
        zeile = next(r for r in range(2) if fenster.buchungen_tabelle.item(r, 7).text() == "storniert")
        fenster.buchungen_tabelle.selectRow(zeile)
        fenster.storniere_auswahl()
        assert "bereits storniert" in keine_meldungen[-1]

    def test_konto_bearbeiten_ohne_auswahl(self, fenster, keine_meldungen):
        fenster.konto_bearbeiten()
        assert "auswählen" in keine_meldungen[-1]

    def test_deaktiviertes_konto_grau(self, fenster, Sitzung):
        with Sitzung.begin() as s:
            fritz = next(k for k in bh.konten(s) if k.name == "Fritz")
            fritz.aktiv = False
        fenster.aktualisieren()
        t = fenster.konten_tabelle
        assert t.item(zeile_von(t, "Fritz"), 0).foreground().color().name() == stil.INAKTIV

    def test_negativer_saldo_rot(self, fenster, Sitzung):
        with Sitzung.begin() as s:
            ids = {k.name: k.id for k in bh.konten(s)}
            bh.buchen(s, Art.BEITRAG, ids["Fritz"], 3000, "Beitrag", gegenkonto_id=ids["Beitragskasse"])
        fenster.aktualisieren()
        t = fenster.konten_tabelle
        assert t.item(zeile_von(t, "Fritz"), 4).foreground().color().name() == stil.NEGATIV


# --- Konto-Dialog ---------------------------------------------------------

class TestKontoDialog:
    def test_status_nur_bei_privatkonto(self, app):
        d = KontoDialog()
        assert d.form.isRowVisible(d.status)
        d.typ.setCurrentIndex(d.typ.findData(KontoTyp.KASSE))
        assert not d.form.isRowVisible(d.status)
        assert d.werte()["status"] is None

    def test_standardstatus_aktiver(self, app):
        assert KontoDialog().werte()["status"] == St.AKTIVER

    def test_leerer_name_wird_abgelehnt(self, app, keine_meldungen):
        d = KontoDialog()
        d._pruefen()
        assert d.result() != KontoDialog.Accepted
        assert keine_meldungen

    def test_bearbeiten_fuellt_felder(self, app, Sitzung):
        fritz = next(k for k in konten(Sitzung) if k.name == "Fritz")
        d = KontoDialog(None, fritz)
        assert d.werte() == {"name": "Fritz", "typ": KontoTyp.PRIVAT, "status": St.FUX,
                             "eintrittsdatum": date(2025, 10, 15), "bemerkung": "", "aktiv": True,
                             "statusverlauf": [(St.FUX, date(2025, 10, 15))]}
        assert not d.typ.isEnabled()

    def test_eintrittsdatum_standard_heute(self, app):
        assert KontoDialog().werte()["eintrittsdatum"] == date.today()

    def test_eintrittsdatum_nur_bei_privatkonto(self, app):
        d = KontoDialog()
        d.typ.setCurrentIndex(d.typ.findData(KontoTyp.KASSE))
        assert not d.form.isRowVisible(d.eintritt)
        assert d.werte()["eintrittsdatum"] is None

    def test_konto_ohne_eintrittsdatum_zeigt_unbekannt(self, app, Sitzung):
        with Sitzung.begin() as s:
            bh.konto_anlegen(s, "Alt", KontoTyp.PRIVAT, St.AKTIVER)
        alt = next(k for k in konten(Sitzung) if k.name == "Alt")
        d = KontoDialog(None, alt)
        assert d.eintritt.text() == "unbekannt"
        assert d.werte()["eintrittsdatum"] is None

    def test_eintrittsdatum_pflicht(self, app, Sitzung, keine_meldungen):
        d = KontoDialog()
        d.name.setText("Neu")
        d.eintritt.setDate(UNBEKANNT)
        d._pruefen()
        assert d.result() != KontoDialog.Accepted
        assert "Eintrittsdatum" in keine_meldungen[-1]


# --- Buchungs-Dialog ------------------------------------------------------

class TestBuchungDialog:
    @pytest.mark.parametrize(
        "art, konten_anzahl, gegen_anzahl",
        [(Art.EINZAHLUNG, 3, None), (Art.AUSZAHLUNG, 3, None), (Art.KASSE_EINNAHME, 2, None),
         (Art.KASSE_AUSGABE, 2, None), (Art.UMBUCHUNG, 5, 5), (Art.BEITRAG, 3, 2)],
    )
    def test_passende_konten_je_art(self, app, Sitzung, art, konten_anzahl, gegen_anzahl):
        d = BuchungDialog(konten(Sitzung))
        d.art.setCurrentIndex(d.art.findData(art))
        assert d.konto.count() == konten_anzahl
        assert d.form.isRowVisible(d.gegen) == (gegen_anzahl is not None)
        if gegen_anzahl:
            assert d.gegen.count() == gegen_anzahl

    def test_storno_nicht_waehlbar(self, app, Sitzung):
        assert BuchungDialog(konten(Sitzung)).art.findData(Art.STORNO) == -1

    @pytest.mark.parametrize("betrag", ["", "abc", "0", "-5", "1,234"])
    def test_ungueltiger_betrag(self, app, Sitzung, betrag):
        d = BuchungDialog(konten(Sitzung))
        d.betrag.setText(betrag)
        d.text.setText("x")
        d._pruefen()
        assert d.result() != BuchungDialog.Accepted

    def test_fehlender_text(self, app, Sitzung):
        d = BuchungDialog(konten(Sitzung))
        d.betrag.setText("5")
        d._pruefen()
        assert d.result() != BuchungDialog.Accepted

    def test_umbuchung_gleiche_konten(self, app, Sitzung):
        d = BuchungDialog(konten(Sitzung))
        d.art.setCurrentIndex(d.art.findData(Art.UMBUCHUNG))
        d.gegen.setCurrentIndex(d.gegen.findData(d.konto.currentData()))
        d.betrag.setText("5")
        d.text.setText("x")
        d._pruefen()
        assert d.result() != BuchungDialog.Accepted

    def test_gueltige_eingabe_wird_gebucht(self, app, Sitzung):
        d = BuchungDialog(konten(Sitzung))
        d.art.setCurrentIndex(d.art.findData(Art.EINZAHLUNG))
        d.betrag.setText("12,50")
        d.text.setText("Beitrag")
        d.beleg.setText("B-7")
        d._pruefen()
        assert d.result() == BuchungDialog.Accepted
        werte = d.werte()
        assert werte["betrag_cent"] == 1250 and werte["gegenkonto_id"] is None
        with Sitzung.begin() as s:
            b = bh.buchen(s, **werte)
            assert b.beleg == "B-7"

    def test_gegenkonto_nach_artwechsel_nicht_uebergeben(self, app, Sitzung):
        d = BuchungDialog(konten(Sitzung))
        d.art.setCurrentIndex(d.art.findData(Art.UMBUCHUNG))
        d.art.setCurrentIndex(d.art.findData(Art.EINZAHLUNG))
        assert d.werte()["gegenkonto_id"] is None


class TestBeitragDialog:
    @pytest.fixture
    def dialog(self, app, Sitzung):
        kassen = [k for k in konten(Sitzung) if k.typ == KontoTyp.KASSE]

        def vorschau(betraege, jahr):
            with Sitzung() as s:
                return bh.beitrag_vorschau(s, betraege, jahr)

        return BeitragDialog(kassen, vorschau, heute=date(2026, 10, 29))

    def test_vorschau_aktualisiert_sich(self, dialog):
        assert dialog.tabelle.rowCount() == 0
        dialog.felder[St.FUX].setText("30")
        assert dialog.tabelle.rowCount() == 1
        dialog.felder[St.AKTIVER].setText("60")
        dialog.felder[St.ALUMNI].setText("100,50")
        assert dialog.tabelle.rowCount() == 3
        assert "190,50 €" in dialog.summe.text()

    def test_ungueltige_eingabe_in_vorschau(self, dialog):
        dialog.felder[St.FUX].setText("abc")
        assert "Ungültig" in dialog.summe.text()

    def test_ohne_betraege_wird_abgelehnt(self, dialog, keine_meldungen):
        dialog._pruefen()
        assert dialog.result() != BeitragDialog.Accepted
        assert "kein Mitglied" in keine_meldungen[-1]

    def test_standard_aktuelles_jahr(self, dialog):
        assert dialog.jahr.value() == 2026
        assert dialog.text.text() == "Jahresbeitrag 2026"
        assert dialog.datum.date() == QDate(2026, 1, 1)
        assert "2026" in dialog.vorschau_titel.text()

    def test_jahreswechsel_passt_datum_und_text_an(self, dialog):
        dialog.jahr.setValue(2024)
        assert dialog.text.text() == "Jahresbeitrag 2024"
        assert dialog.datum.date() == QDate(2024, 1, 1)

    def test_eigener_text_bleibt_bei_jahreswechsel(self, dialog):
        dialog.text.setText("Beitrag Nachzahlung")
        dialog.jahr.setValue(2024)
        assert dialog.text.text() == "Beitrag Nachzahlung"

    def test_spaeter_eingetretene_werden_ausgelassen(self, dialog):
        dialog.felder[St.FUX].setText("30")
        dialog.felder[St.AKTIVER].setText("60")
        dialog.jahr.setValue(2025)  # Fritz erst am 15.10.2025 eingetreten
        namen = [dialog.tabelle.item(r, 0).text() for r in range(dialog.tabelle.rowCount())]
        assert namen == ["Tom"]
        assert "Erst nach dem 01.01.2025 eingetreten" in dialog.ausgelassen.text()
        assert "Fritz" in dialog.ausgelassen.text()

    def test_bereits_abgebuchte_werden_angezeigt(self, dialog, Sitzung):
        with Sitzung.begin() as s:
            kasse = next(k for k in bh.konten(s) if k.name == "Beitragskasse")
            bh.beitraege_abbuchen(s, {St.AKTIVER: 6000}, 2026, kasse.id, "Beitrag")
        dialog.felder[St.AKTIVER].setText("60")
        assert dialog.tabelle.rowCount() == 0
        assert "Bereits für 2026 abgebucht" in dialog.ausgelassen.text()

    def test_kompletter_beitragslauf(self, dialog, Sitzung):
        dialog.jahr.setValue(2025)
        dialog.felder[St.FUX].setText("30")
        dialog.felder[St.AKTIVER].setText("60")
        dialog.kasse.setCurrentIndex(dialog.kasse.findText("Beitragskasse"))
        dialog._pruefen()
        assert dialog.result() == BeitragDialog.Accepted
        assert dialog.werte()["jahr"] == 2025
        with Sitzung.begin() as s:
            gebucht = bh.beitraege_abbuchen(s, **dialog.werte())
            assert [(b.beitragsjahr, b.datum) for b in gebucht] == [(2025, date(2025, 1, 1))]
            assert bh.abstimmung(s).stimmt
