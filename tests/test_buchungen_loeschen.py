"""Buchungen endgültig löschen (inkl. Storno-Paare) und Update-Menüpunkt."""

import sys
from datetime import date

import pytest
from PySide6.QtCore import QItemSelectionModel, QProcess
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas import sicherung
from dikas.db import erstelle_engine, init_db
from dikas.db.models import Buchungsart as Art, MitgliedStatus as St
from dikas.ui.hauptfenster import Hauptfenster

from conftest import Verein, ct

D = date


class TestLogik:
    def test_einzelne_buchung(self, verein, session):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "10")
        bleibt = verein.einzahlung(tom, "5")
        assert bh.buchungen_loeschen(session, [b.id]) == 1
        assert [x.id for x in bh.buchungen(session)] == [bleibt.id]
        assert verein.saldo(tom) == verein.saldo(verein.kw) == ct(5)
        verein.pruefe_abstimmung()

    @pytest.mark.parametrize("waehle", ["original", "storno", "beide"])
    def test_storno_paar_immer_zusammen(self, verein, session, waehle):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "100", "Tippfehler")
        s = verein.storno(b)
        ids = {"original": [b.id], "storno": [s.id], "beide": [b.id, s.id]}[waehle]
        assert bh.buchungen_loeschen(session, ids) == 2
        assert bh.buchungen(session) == []
        assert verein.saldo(tom) == 0
        verein.pruefe_abstimmung()

    def test_korrektur_paar_aufraeumen(self, verein, session):
        """Nach einer Korrektur bleiben Original, Storno und neue Buchung – die alten zwei weg."""
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "100", "Ueberweisung", D(2026, 3, 1))
        neu = bh.buchung_korrigieren(session, b.id, Art.EINZAHLUNG, tom.id, ct(10), "Überweisung", D(2026, 3, 1))
        bh.buchungen_loeschen(session, [b.id])
        assert [x.id for x in bh.buchungen(session)] == [neu.id]
        assert verein.saldo(tom) == ct(10)

    def test_mehrere_auf_einmal(self, verein, session):
        tom, anna = verein.mitglied("Tom"), verein.mitglied("Anna")
        a = verein.einzahlung(tom, "1")
        b = verein.einzahlung(anna, "2")
        c = verein.storno(verein.einzahlung(tom, "3"))
        bleibt = verein.einzahlung(anna, "4")
        assert bh.buchungen_loeschen(session, [a.id, b.id, c.id]) == 4
        assert [x.id for x in bh.buchungen(session)] == [bleibt.id]
        verein.pruefe_abstimmung()

    def test_beitrag_loeschen_gibt_jahr_frei(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        (b,) = verein.beitragslauf(kasse, aktiver="60", jahr=2026)
        bh.buchungen_loeschen(session, [b.id])
        assert [m.name for m, _ in bh.beitrag_vorschau(session, {St.AKTIVER: 6000}, 2026).faellig] == ["Tom"]

    def test_vorschau_zeigt_partner(self, verein, session):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "1")
        s = verein.storno(b)
        assert [x.id for x in bh.zu_loeschende_buchungen(session, [s.id])] == [b.id, s.id]

    def test_unbekannte_buchung(self, session):
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.buchungen_loeschen(session, [999])

    def test_leere_auswahl(self, session):
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.buchungen_loeschen(session, [])

    def test_geloeschtes_konto_geschuetzt(self, verein, session):
        tom = verein.mitglied("Tom")
        verein.einzahlung(tom, "10")
        raus = verein.auszahlung(tom, "10")
        bh.konto_loeschen(session, tom.id)
        with pytest.raises(bh.BuchhaltungsFehler, match="wiederherstellen"):
            bh.buchungen_loeschen(session, [raus.id])  # Tom stünde sonst bei +10 €

    def test_paar_auf_geloeschtem_konto_erlaubt(self, verein, session):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "10")
        verein.storno(b)
        bh.konto_loeschen(session, tom.id)
        assert bh.buchungen_loeschen(session, [b.id]) == 2  # hebt sich auf, Saldo bleibt 0

    def test_konto_danach_wirklich_loeschbar(self, verein, session):
        tom = verein.mitglied("Tom")
        verein.storno(verein.einzahlung(tom, "10"))
        bh.buchungen_loeschen(session, [b.id for b in bh.buchungen(session, tom.id)])
        assert bh.konto_loeschen(session, tom.id) is True  # ohne Buchungen: ganz entfernt


# --- Oberfläche -----------------------------------------------------------

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fenster(app, tmp_path):
    pfad = tmp_path / "daten" / "verein.db"
    engine = erstelle_engine(pfad)
    init_db(engine)
    with Session(engine) as s, s.begin():
        v = Verein(s)
        tom = v.mitglied("Tom Becker")
        b = v.einzahlung(tom, "100", "Tippfehler", D(2026, 1, 1))
        v.storno(b)
        v.einzahlung(tom, "10", "Richtig", D(2026, 2, 1))
    w = Hauptfenster(sessionmaker(engine, expire_on_commit=False), str(pfad))
    w.pfad = pfad
    yield w
    w.close()
    engine.dispose()


def texte(w):
    return sorted(w.buchungen_tabelle.item(r, 3).text() for r in range(w.buchungen_tabelle.rowCount()))


def zeile(w, text):
    return next(r for r in range(w.buchungen_tabelle.rowCount()) if w.buchungen_tabelle.item(r, 3).text() == text)


class TestOberflaeche:
    def test_paar_loeschen_mit_bestaetigung_und_sicherung(self, fenster, monkeypatch):
        fragen = []
        monkeypatch.setattr(QMessageBox, "question", lambda *a: fragen.append(a[2]) or QMessageBox.Yes)
        fenster.buchungen_tabelle.selectRow(zeile(fenster, "Storno: Tippfehler"))
        fenster.loesche_auswahl()
        assert "2 Buchung(en)" in fragen[-1]
        assert "1 weitere Buchung(en) werden mitgelöscht" in fragen[-1]  # hier: das Original
        assert texte(fenster) == ["Richtig"]
        assert len(sicherung.sicherungen(fenster.pfad)) == 1  # vorher gesichert

    def test_mehrfachauswahl(self, fenster, monkeypatch):
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
        t = fenster.buchungen_tabelle
        auswahl = t.selectionModel()
        for text in ("Richtig", "Tippfehler"):
            auswahl.select(t.model().index(zeile(fenster, text), 0),
                           QItemSelectionModel.Select | QItemSelectionModel.Rows)
        fenster.loesche_auswahl()
        assert texte(fenster) == []

    def test_abbrechen(self, fenster, monkeypatch):
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.No)
        fenster.buchungen_tabelle.selectRow(0)
        fenster.loesche_auswahl()
        assert len(texte(fenster)) == 3

    def test_ohne_auswahl(self, fenster, monkeypatch):
        meldungen = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a: meldungen.append(a[2]))
        fenster.buchungen_tabelle.clearSelection()
        fenster.loesche_auswahl()
        assert "auswählen" in meldungen[-1]


def markiere(w, *texte_):
    t = w.buchungen_tabelle
    t.clearSelection()
    for text in texte_:
        t.selectionModel().select(t.model().index(zeile(w, text), 0),
                                  QItemSelectionModel.Select | QItemSelectionModel.Rows)


class TestReviewPunkte:
    """Absicherung der Befunde aus dem Code-Review vom 03.11.2026."""

    def test_nur_eine_sicherung_pro_sitzung(self, fenster, monkeypatch):
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
        for text in ("Richtig", "Tippfehler"):
            markiere(fenster, text)
            fenster.loesche_auswahl()
        assert texte(fenster) == []
        assert len(sicherung.sicherungen(fenster.pfad)) == 1

    def test_warnung_bei_gueltigem_jahresbeitrag(self, fenster, monkeypatch):
        with fenster.Session.begin() as s:
            v = Verein(s)
            kasse = v.kasse("Beitragskasse")
            v.mitglied("Anna Schulz")
            v.beitragslauf(kasse, aktiver="60", jahr=2026, text="Jahresbeitrag 2026")
        fenster.aktualisieren()
        fragen = []
        monkeypatch.setattr(QMessageBox, "question", lambda *a: fragen.append(a[2]) or QMessageBox.No)
        markiere(fenster, "Jahresbeitrag 2026")
        fenster.loesche_auswahl()
        assert "gültige Jahresbeiträge" in fragen[-1] and "2026" in fragen[-1]

    def test_veraltete_liste_meldet_fehler(self, fenster, monkeypatch):
        meldungen = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a: meldungen.append(a[2]))
        markiere(fenster, "Richtig")
        with fenster.Session.begin() as s:  # Buchung verschwindet „hinter dem Rücken“ der Liste
            bh.buchungen_loeschen(s, [b.id for b in bh.buchungen(s) if b.text == "Richtig"])
        fenster.loesche_auswahl()
        assert "existiert nicht" in meldungen[-1]
        assert "Richtig" not in texte(fenster)  # Liste neu geladen

    def test_mehrere_stornieren(self, fenster, monkeypatch):
        with fenster.Session.begin() as s:
            v = Verein(s)
            tom = next(k for k in bh.konten(s) if k.name == "Tom Becker")
            v.einzahlung(tom, "1", "Zweite")
        fenster.aktualisieren()
        fragen = []
        monkeypatch.setattr(QMessageBox, "question", lambda *a: fragen.append(a[2]) or QMessageBox.Yes)
        markiere(fenster, "Richtig", "Zweite", "Tippfehler")  # Tippfehler ist schon storniert
        fenster.storniere_auswahl()
        assert "2 Buchungen wirklich stornieren" in fragen[-1] and "übersprungen" in fragen[-1]
        with fenster.Session() as s:
            assert {b.text for b in bh.buchungen(s) if b.ist_storniert} == {"Richtig", "Zweite", "Tippfehler"}

    def test_stornieren_nur_bereits_stornierte(self, fenster, monkeypatch):
        meldungen = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a: meldungen.append(a[2]))
        markiere(fenster, "Tippfehler")
        fenster.storniere_auswahl()
        assert "bereits storniert" in meldungen[-1]

    def test_korrigieren_bei_mehrfachauswahl(self, fenster, monkeypatch):
        meldungen = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a: meldungen.append(a[2]))
        markiere(fenster, "Richtig", "Tippfehler")
        fenster.korrigiere_auswahl()
        assert "genau eine Buchung" in meldungen[-1]

    def test_doppelklick_korrigiert_angeklickte_zeile(self, fenster, monkeypatch):
        from dikas.ui.dialoge import BuchungDialog
        geoeffnet = []
        monkeypatch.setattr(BuchungDialog, "exec", lambda d: geoeffnet.append(d.text.text()) or 0)
        markiere(fenster, "Tippfehler")  # andere Zeile markiert …
        item = fenster.buchungen_tabelle.item(zeile(fenster, "Richtig"), 3)
        fenster.korrigiere_auswahl(item)  # … aber „Richtig“ doppelt angeklickt
        assert geoeffnet == ["Richtig"]

    def gewaehlt(self, w):
        t = w.buchungen_tabelle
        return sorted(t.item(z.row(), 3).text() for z in t.selectionModel().selectedRows())

    def test_rechtsklick_waehlt_angeklickte_zeile(self, fenster):
        markiere(fenster, "Tippfehler")
        fenster._auswahl_fuer_rechtsklick(zeile(fenster, "Richtig"))
        assert self.gewaehlt(fenster) == ["Richtig"]

    def test_rechtsklick_in_mehrfachauswahl_behaelt_auswahl(self, fenster):
        markiere(fenster, "Tippfehler", "Richtig")
        fenster._auswahl_fuer_rechtsklick(zeile(fenster, "Richtig"))
        assert self.gewaehlt(fenster) == ["Richtig", "Tippfehler"]


class TestUpdate:
    @pytest.mark.parametrize("rueckgabe, startet", [((False, -1), False), ((True, 4711), True), (False, False), (True, True)])
    def test_startergebnis_wird_ausgewertet(self, fenster, monkeypatch, tmp_path, rueckgabe, startet):
        """PySide6 liefert (erfolgreich, pid) – bei Fehlstart darf DiKaS nicht schließen."""
        warnungen, beendet = [], []
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(tmp_path / "DiKaS-Setup-9.exe"), ""))
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnungen.append(a[2]))
        monkeypatch.setattr(QProcess, "startDetached", lambda *a: rueckgabe)
        monkeypatch.setattr(QApplication, "quit", lambda *a: beendet.append(True))
        fenster.update_installieren()
        assert bool(beendet) == startet
        assert bool(warnungen) == (not startet)

    def test_echter_fehlstart(self, fenster, monkeypatch, tmp_path):
        """Ohne Nachbildung: eine nicht vorhandene Datei lässt sich wirklich nicht starten."""
        warnungen, beendet = [], []
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(tmp_path / "gibt-es-nicht.exe"), ""))
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnungen.append(a[2]))
        monkeypatch.setattr(QApplication, "quit", lambda *a: beendet.append(True))
        fenster.update_installieren()
        assert warnungen and not beendet

    def test_nur_in_installierter_version(self, fenster, monkeypatch):
        meldungen = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a: meldungen.append(a[2]))
        fenster.update_installieren()
        assert "installierten Version" in meldungen[-1]

    def test_startet_installer_still_und_beendet(self, fenster, monkeypatch, tmp_path):
        setup = tmp_path / "DiKaS-Setup-9.9.9.exe"
        aufrufe, beendet = [], []
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(setup), ""))
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
        monkeypatch.setattr(QProcess, "startDetached", lambda *a: aufrufe.append(a) or True)
        monkeypatch.setattr(QApplication, "quit", lambda *a: beendet.append(True))
        fenster.update_installieren()
        assert aufrufe == [(str(setup), Hauptfenster.UPDATE_PARAMETER)]
        assert "/SILENT" in Hauptfenster.UPDATE_PARAMETER and beendet

    def test_abgebrochen(self, fenster, monkeypatch):
        aufrufe = []
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: ("", ""))
        monkeypatch.setattr(QProcess, "startDetached", lambda *a: aufrufe.append(a) or True)
        fenster.update_installieren()
        assert aufrufe == []
