"""Automatische Sicherung: anlegen, nur bei Änderung, die letzten 10 behalten, wiederherstellen."""

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy.orm import Session

from dikas import buchhaltung as bh
from dikas import sicherung
from dikas.db import erstelle_engine, init_db
from dikas.db.models import KontoTyp, MitgliedStatus as St
from dikas.ui.sicherungen_dialog import SicherungenDialog

T0 = datetime(2026, 10, 29, 20, 0, 0)


@pytest.fixture
def db(tmp_path):
    """Echte Datenbankdatei mit einem Mitglied; liefert (Pfad, Engine)."""
    pfad = tmp_path / "daten" / "verein.db"
    engine = erstelle_engine(pfad)
    init_db(engine)
    with Session(engine) as s, s.begin():
        bh.konto_anlegen(s, "Tom", KontoTyp.PRIVAT, St.AKTIVER)
    yield pfad, engine
    engine.dispose()


def mitglied_anlegen(engine, name):
    with Session(engine) as s, s.begin():
        bh.konto_anlegen(s, name, KontoTyp.PRIVAT, St.AKTIVER)


def namen(engine):
    with Session(engine) as s:
        return sorted(k.name for k in bh.konten(s) if k.typ == KontoTyp.PRIVAT)


class TestSichern:
    def test_erste_sicherung(self, db):
        pfad, _ = db
        s = sicherung.sichern(pfad, T0)
        assert s.pfad == pfad.parent / "sicherung" / "verein_2026-10-29_20-00-00.db"
        assert s.pfad.exists() and s.zeitpunkt == T0
        sicherung.pruefen(s.pfad)

    def test_ohne_datenbank_keine_sicherung(self, tmp_path):
        assert sicherung.sichern(tmp_path / "gibtsnicht.db", T0) is None
        assert not (tmp_path / "sicherung").exists()

    def test_unveraendert_keine_neue_sicherung(self, db):
        pfad, _ = db
        sicherung.sichern(pfad, T0)
        assert sicherung.sichern(pfad, T0 + timedelta(hours=1)) is None
        assert len(sicherung.sicherungen(pfad)) == 1

    def test_nach_aenderung_neue_sicherung(self, db):
        pfad, engine = db
        sicherung.sichern(pfad, T0)
        mitglied_anlegen(engine, "Anna")
        assert sicherung.sichern(pfad, T0 + timedelta(hours=1)) is not None
        assert len(sicherung.sicherungen(pfad)) == 2

    def test_sicherung_bei_offener_verbindung_konsistent(self, db):
        """Die Datenbank ist während der Sicherung geöffnet – die Kopie muss trotzdem intakt sein."""
        pfad, engine = db
        with engine.connect():
            s = sicherung.sichern(pfad, T0)
        sicherung.pruefen(s.pfad)
        kopie = erstelle_engine(s.pfad)
        assert namen(kopie) == ["Tom"]
        kopie.dispose()

    def test_gleiche_sekunde(self, db):
        pfad, engine = db
        sicherung.sichern(pfad, T0)
        mitglied_anlegen(engine, "Anna")
        zweite = sicherung.sichern(pfad, T0)
        assert zweite.pfad.name == "verein_2026-10-29_20-00-00_2.db"

    def test_letzte_zehn_bleiben(self, db):
        pfad, engine = db
        for i in range(13):
            mitglied_anlegen(engine, f"M{i}")
            sicherung.sichern(pfad, T0 + timedelta(days=i))
        liste = sicherung.sicherungen(pfad)
        assert len(liste) == 10
        assert liste[0].zeitpunkt == T0 + timedelta(days=12)  # neueste zuerst
        assert liste[-1].zeitpunkt == T0 + timedelta(days=3)  # die drei ältesten sind weg

    def test_fremde_dateien_im_ordner_bleiben(self, db):
        pfad, _ = db
        ordner = sicherung.sicherungs_ordner(pfad)
        ordner.mkdir(parents=True)
        (ordner / "notiz.txt").write_text("bitte nicht löschen")
        (ordner / "verein_kaputt.db").write_text("x")
        sicherung.sichern(pfad, T0)
        sicherung.aufraeumen(pfad, behalten=0)
        assert (ordner / "notiz.txt").exists() and (ordner / "verein_kaputt.db").exists()

    def test_liegt_neben_der_datenbank(self, db):
        pfad, _ = db
        assert sicherung.sicherungs_ordner(pfad) == pfad.parent / "sicherung"


class TestWiederherstellen:
    def test_alter_stand_kommt_zurueck(self, db):
        pfad, engine = db
        alt = sicherung.sichern(pfad, T0)
        mitglied_anlegen(engine, "Anna")
        engine.dispose()

        vorher = sicherung.wiederherstellen(alt, pfad, T0 + timedelta(hours=1))

        assert namen(engine) == ["Tom"]
        assert vorher is not None  # Stand mit Anna wurde vorher gesichert
        zurueck = erstelle_engine(vorher.pfad)
        assert namen(zurueck) == ["Anna", "Tom"]
        zurueck.dispose()

    def test_wiederherstellen_rueckgaengig_machen(self, db):
        pfad, engine = db
        alt = sicherung.sichern(pfad, T0)
        mitglied_anlegen(engine, "Anna")
        engine.dispose()
        vorher = sicherung.wiederherstellen(alt, pfad, T0 + timedelta(hours=1))
        engine.dispose()
        sicherung.wiederherstellen(vorher, pfad, T0 + timedelta(hours=2))
        assert namen(engine) == ["Anna", "Tom"]

    def test_aelteste_sicherung_bleibt_beim_wiederherstellen_erhalten(self, db):
        pfad, engine = db
        for i in range(10):
            mitglied_anlegen(engine, f"M{i}")
            sicherung.sichern(pfad, T0 + timedelta(days=i))
        aelteste = sicherung.sicherungen(pfad)[-1]
        mitglied_anlegen(engine, "Neu")
        engine.dispose()
        sicherung.wiederherstellen(aelteste, pfad, T0 + timedelta(days=20))
        assert aelteste.pfad.exists()

    def test_kaputte_sicherung_wird_abgelehnt(self, db):
        pfad, engine = db
        ordner = sicherung.sicherungs_ordner(pfad)
        ordner.mkdir(parents=True)
        kaputt = ordner / "verein_2026-01-01_00-00-00.db"
        kaputt.write_bytes(b"das ist keine datenbank" * 100)
        engine.dispose()
        with pytest.raises(ValueError, match="keine gültige Datenbank"):
            sicherung.wiederherstellen(sicherung.sicherungen(pfad)[0], pfad)
        assert namen(engine) == ["Tom"]  # aktuelle DB unangetastet

    def test_fremde_sqlite_datei_wird_abgelehnt(self, tmp_path):
        import sqlite3
        fremd = tmp_path / "fremd.db"
        with sqlite3.connect(fremd) as con:
            con.execute("CREATE TABLE irgendwas (x)")
        con.close()
        with pytest.raises(ValueError, match="keine Vereinsdatenbank"):
            sicherung.pruefen(fremd)

    def test_alte_sicherung_bekommt_neue_spalten(self, db):
        pfad, engine = db
        alt = sicherung.sichern(pfad, T0)
        with __import__("sqlite3").connect(alt.pfad) as con:
            con.execute("ALTER TABLE konten DROP COLUMN email")  # Stand vor dem E-Mail-Feld
        con.close()
        engine.dispose()
        sicherung.wiederherstellen(alt, pfad, T0 + timedelta(hours=1))
        init_db(engine)
        with Session(engine) as s:
            assert next(k for k in bh.konten(s) if k.name == "Tom").email == ""


class TestNurLokal:
    def test_sicherungen_werden_von_git_ignoriert(self):
        """Sicherungen dürfen nie ins Repo gelangen."""
        wurzel = Path(__file__).resolve().parents[1]
        for pfad in ("daten/sicherung/verein_2026-10-29_20-00-00.db", "sicherung/verein.db", "daten/verein.db"):
            ergebnis = subprocess.run(["git", "check-ignore", "-q", pfad], cwd=wurzel)
            assert ergebnis.returncode == 0, f"{pfad} würde nicht ignoriert!"


# --- Oberfläche -----------------------------------------------------------

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class TestDialog:
    @pytest.fixture
    def meldungen(self, monkeypatch):
        liste = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a: liste.append(a[2]))
        monkeypatch.setattr(QMessageBox, "warning", lambda *a: liste.append(a[2]))
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
        return liste

    def test_liste(self, app, db):
        pfad, engine = db
        sicherung.sichern(pfad, T0)
        mitglied_anlegen(engine, "Anna")
        sicherung.sichern(pfad, T0 + timedelta(days=1))
        d = SicherungenDialog(engine, pfad)
        assert d.tabelle.rowCount() == 2
        assert d.tabelle.item(0, 0).text() == "30.10.2026"  # neueste oben
        assert d.tabelle.item(0, 1).text() == "20:00:00"
        assert d.info.text() == "2 von 10"

    def test_leer(self, app, db):
        pfad, engine = db
        d = SicherungenDialog(engine, pfad)
        assert d.tabelle.rowCount() == 0
        assert not d.wiederherstellen_knopf.isEnabled()

    def test_jetzt_sichern(self, app, db, meldungen):
        pfad, engine = db
        d = SicherungenDialog(engine, pfad)
        d.jetzt_sichern()
        assert d.tabelle.rowCount() == 1
        d.jetzt_sichern()
        assert "nichts geändert" in meldungen[-1]
        assert d.tabelle.rowCount() == 1

    def test_wiederherstellen(self, app, db, meldungen):
        pfad, engine = db
        sicherung.sichern(pfad, T0)
        mitglied_anlegen(engine, "Anna")
        d = SicherungenDialog(engine, pfad)
        d.tabelle.selectRow(0)
        d.wiederherstellen()
        assert d.wiederhergestellt
        assert namen(engine) == ["Tom"]  # Engine funktioniert nach dem Austausch weiter
        assert d.tabelle.rowCount() == 2  # plus Sicherung des Stands vor dem Wiederherstellen
        assert "wiederhergestellt" in meldungen[-1]

    def test_wiederherstellen_abgebrochen(self, app, db, monkeypatch):
        pfad, engine = db
        sicherung.sichern(pfad, T0)
        mitglied_anlegen(engine, "Anna")
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.No)
        d = SicherungenDialog(engine, pfad)
        d.wiederherstellen()
        assert not d.wiederhergestellt
        assert namen(engine) == ["Anna", "Tom"]
