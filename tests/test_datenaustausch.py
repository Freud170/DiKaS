"""Daten zwischen PCs weitergeben: Export, Import, Warnungen, Datenordner der installierten Version."""

import sys
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas import datenaustausch as da
from dikas import einstellungen as es
from dikas import sicherung
from dikas.db import database, erstelle_engine, init_db
from dikas.db.models import KontoTyp, MitgliedStatus as St
from dikas.ui.hauptfenster import NAME_ROLLE, Hauptfenster


class PC:
    """Ein Rechner mit eigener Datenbank (für Tests mit zwei PCs)."""

    def __init__(self, ordner: Path):
        self.db = ordner / "daten" / "verein.db"
        self.engine = erstelle_engine(self.db)
        init_db(self.engine)

    def mitglied(self, name):
        with Session(self.engine) as s, s.begin():
            bh.konto_anlegen(s, name, KontoTyp.PRIVAT, St.AKTIVER)

    def namen(self):
        with Session(self.engine) as s:
            return sorted(k.name for k in bh.konten(s) if k.typ == KontoTyp.PRIVAT)

    def importiere(self, datei):
        self.engine.dispose()
        vorher = da.importieren(datei, self.db)
        init_db(self.engine)
        return vorher


@pytest.fixture
def pcs(tmp_path):
    a, b = PC(tmp_path / "pc_a"), PC(tmp_path / "pc_b")
    yield a, b
    a.engine.dispose()
    b.engine.dispose()


def warte_sekunde():
    time.sleep(1.05)  # Zeitstempel sind sekundengenau


class TestAenderungsMerker:
    def test_aenderung_wird_gemerkt(self, pcs):
        a, _ = pcs
        assert da.datenstand(a.db).letzte_aenderung is not None  # KW-Konto beim Anlegen
        vorher = da.datenstand(a.db).letzte_aenderung
        warte_sekunde()
        a.mitglied("Tom")
        assert da.datenstand(a.db).letzte_aenderung > vorher

    def test_nur_lesen_aendert_nichts(self, pcs):
        a, _ = pcs
        vorher = da.datenstand(a.db).letzte_aenderung
        warte_sekunde()
        a.namen()
        assert da.datenstand(a.db).letzte_aenderung == vorher

    def test_einstellungen_zaehlen_als_aenderung(self, pcs):
        a, _ = pcs
        vorher = da.datenstand(a.db).letzte_aenderung
        warte_sekunde()
        with Session(a.engine) as s, s.begin():
            es.speichern(s, es.Einstellungen(iban="DE02120300000000202051"))
        assert da.datenstand(a.db).letzte_aenderung > vorher

    def test_zaehler(self, pcs):
        a, _ = pcs
        a.mitglied("Tom")
        stand = da.datenstand(a.db)
        assert (stand.mitglieder, stand.buchungen) == (1, 0)
        assert "1 Mitglieder" in stand.beschreibung()


class TestExportImport:
    def test_export_und_import(self, pcs, tmp_path):
        a, b = pcs
        a.mitglied("Tom")
        datei = da.exportieren(a.db, tmp_path / "stick" / da.export_dateiname())
        assert datei.exists()
        assert not da.datenstand(a.db).ungesicherte_aenderungen
        assert da.import_warnungen(datei, b.db) == []  # B hat noch nichts eingetragen

        b.importiere(datei)

        assert b.namen() == ["Tom"]
        assert not da.datenstand(b.db).ungesicherte_aenderungen

    def test_import_sichert_vorher(self, pcs, tmp_path):
        a, b = pcs
        b.mitglied("Nur auf B")
        a.mitglied("Tom")
        datei = da.exportieren(a.db, tmp_path / "x.db")
        vorher = b.importiere(datei)
        assert vorher is not None
        gesichert = erstelle_engine(vorher.pfad)
        with Session(gesichert) as s:
            assert [k.name for k in bh.konten(s) if k.typ == KontoTyp.PRIVAT] == ["Nur auf B"]
        gesichert.dispose()

    def test_hin_und_zurueck_ohne_warnung(self, pcs, tmp_path):
        """Der normale Ablauf: A → B, auf B arbeiten, B → A."""
        a, b = pcs
        a.mitglied("Tom")
        b.importiere(da.exportieren(a.db, tmp_path / "hin.db"))
        warte_sekunde()
        b.mitglied("Anna")
        zurueck = da.exportieren(b.db, tmp_path / "zurueck.db")
        assert da.import_warnungen(zurueck, a.db) == []
        a.importiere(zurueck)
        assert a.namen() == ["Anna", "Tom"]

    def test_warnung_aeltere_datei(self, pcs, tmp_path):
        """Ricos Fall: Ein alter Stand soll einen neueren überschreiben."""
        a, b = pcs
        alt = da.exportieren(a.db, tmp_path / "alt.db")
        b.importiere(alt)
        warte_sekunde()
        b.mitglied("Neu auf B")
        warnungen = da.import_warnungen(alt, b.db)
        assert any("ÄLTER" in w for w in warnungen)
        assert any("weitergearbeitet" in w for w in warnungen)

    def test_warnung_getrennt_veraendert(self, pcs, tmp_path):
        """Beide PCs haben nach dem Austausch gebucht – der Import würde B's Arbeit ersetzen."""
        a, b = pcs
        b.importiere(da.exportieren(a.db, tmp_path / "start.db"))
        warte_sekunde()
        b.mitglied("Auf B")
        warte_sekunde()
        a.mitglied("Auf A")
        neuer = da.exportieren(a.db, tmp_path / "a.db")
        warnungen = da.import_warnungen(neuer, b.db)
        assert len(warnungen) == 1 and "weitergearbeitet" in warnungen[0]

    def test_hinweis_gleicher_stand(self, pcs, tmp_path):
        a, b = pcs
        datei = da.exportieren(a.db, tmp_path / "x.db")
        b.importiere(datei)
        assert any("denselben Stand" in w for w in da.import_warnungen(datei, b.db))

    def test_import_in_neue_installation(self, pcs, tmp_path):
        a, _ = pcs
        a.mitglied("Tom")
        datei = da.exportieren(a.db, tmp_path / "x.db")
        neu = tmp_path / "frisch" / "daten" / "verein.db"
        assert da.import_warnungen(datei, neu) == []
        da.importieren(datei, neu)
        assert da.datenstand(neu).mitglieder == 1

    def test_export_nicht_auf_sich_selbst(self, pcs):
        a, _ = pcs
        with pytest.raises(ValueError):
            da.exportieren(a.db, a.db)

    def test_import_nicht_von_sich_selbst(self, pcs):
        a, _ = pcs
        with pytest.raises(ValueError):
            da.importieren(a.db, a.db)

    def test_kaputte_datei(self, pcs, tmp_path):
        a, _ = pcs
        kaputt = tmp_path / "kaputt.db"
        kaputt.write_bytes(b"keine datenbank" * 100)
        with pytest.raises(ValueError):
            da.import_warnungen(kaputt, a.db)
        with pytest.raises(ValueError):
            da.importieren(kaputt, a.db)

    def test_alte_datei_ohne_merker(self, pcs, tmp_path):
        """Dateien aus älteren Versionen haben noch keine Merker – Import muss trotzdem gehen."""
        import sqlite3
        a, b = pcs
        a.mitglied("Tom")
        a.engine.dispose()
        alt = tmp_path / "alt.db"
        sicherung.kopiere_datenbank(a.db, alt)
        with sqlite3.connect(alt) as con:
            con.execute("DROP TABLE einstellungen")
        con.close()
        assert da.datenstand(alt).letzte_aenderung is None
        b.importiere(alt)
        assert b.namen() == ["Tom"]

    def test_dateiname(self):
        from datetime import datetime
        assert da.export_dateiname(datetime(2026, 11, 3, 19, 30)) == "DiKaS_2026-11-03_19-30.db"


class TestDatenordner:
    def test_entwicklung_im_projekt(self):
        assert database.daten_verzeichnis() == Path(database.__file__).resolve().parents[2] / "daten"

    def test_installiert_in_appdata(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
        assert database.daten_verzeichnis() == tmp_path / "AppData" / "Local" / "DiKaS" / "daten"
        assert database.standard_db_pfad().name == "verein.db"


# --- Oberfläche -----------------------------------------------------------

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class TestOberflaeche:
    @pytest.fixture
    def fenster(self, app, pcs):
        a, _ = pcs
        a.mitglied("Tom")
        w = Hauptfenster(sessionmaker(a.engine, expire_on_commit=False), str(a.db))
        yield w
        w.close()

    def test_export(self, fenster, tmp_path, monkeypatch):
        ziel = tmp_path / "stick" / "export.db"
        meldungen = []
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(ziel), ""))
        monkeypatch.setattr(QMessageBox, "information", lambda *a: meldungen.append(a[2]))
        fenster.daten_exportieren()
        assert ziel.exists() and "gespeichert" in meldungen[-1]

    def test_import_mit_bestaetigung(self, fenster, pcs, tmp_path, monkeypatch):
        _, b = pcs
        b.mitglied("Anna")
        b.mitglied("Ben")
        datei = da.exportieren(b.db, tmp_path / "von_b.db")
        fragen = []
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(datei), ""))
        monkeypatch.setattr(QMessageBox, "question", lambda *a: fragen.append(a[2]) or QMessageBox.Yes)
        fenster.daten_importieren()
        assert "2 Mitglieder" in fragen[-1] and "Dieser PC" in fragen[-1]
        namen = {fenster.konten_tabelle.item(r, 0).data(NAME_ROLLE) for r in range(fenster.konten_tabelle.rowCount())}
        assert {"Anna", "Ben"} <= namen and "Tom" not in namen

    def test_import_abgebrochen(self, fenster, pcs, tmp_path, monkeypatch):
        _, b = pcs
        b.mitglied("Anna")
        datei = da.exportieren(b.db, tmp_path / "von_b.db")
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(datei), ""))
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.No)
        fenster.daten_importieren()
        namen = {fenster.konten_tabelle.item(r, 0).data(NAME_ROLLE) for r in range(fenster.konten_tabelle.rowCount())}
        assert "Tom" in namen and "Anna" not in namen

    def test_import_kaputte_datei(self, fenster, tmp_path, monkeypatch):
        kaputt = tmp_path / "kaputt.db"
        kaputt.write_bytes(b"x" * 1000)
        meldungen = []
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(kaputt), ""))
        monkeypatch.setattr(QMessageBox, "warning", lambda *a: meldungen.append(a[2]))
        fenster.daten_importieren()
        assert "keine gültige Datenbank" in meldungen[-1]
