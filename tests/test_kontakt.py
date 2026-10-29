"""Bierspitz und E-Mail-Adresse bei Privatkonten."""

import sqlite3
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas.db import erstelle_engine, init_db
from dikas.db.models import KontoTyp, MitgliedStatus as St
from dikas.ui.dialoge import KontoDialog
from dikas.ui.hauptfenster import Hauptfenster


def mitglied(session, name="Tom", **kwargs):
    return bh.konto_anlegen(session, name, KontoTyp.PRIVAT, St.AKTIVER, **kwargs)


class TestLogik:
    def test_speichern(self, session):
        tom = mitglied(session, bierspitz="  Tommy  ", email=" tom@example.org ")
        assert (tom.bierspitz, tom.email) == ("Tommy", "tom@example.org")

    def test_standard_leer(self, session):
        tom = mitglied(session)
        assert (tom.bierspitz, tom.email) == ("", "")

    @pytest.mark.parametrize("email", ["tom@example.org", "t.b+verein@mail.example.de", "a@b.example"])
    def test_gueltige_adressen(self, session, email):
        assert mitglied(session, email=email).email == email

    @pytest.mark.parametrize("email", ["tom", "tom@", "@example.org", "tom@example", "tom @example.org",
                                       "tom@@example.org", "tom@example.org extra"])
    def test_ungueltige_adressen(self, session, email):
        with pytest.raises(bh.BuchhaltungsFehler, match="E-Mail"):
            mitglied(session, email=email)

    def test_nur_privatkonten(self, session):
        with pytest.raises(bh.BuchhaltungsFehler, match="Nur Privatkonten"):
            bh.konto_anlegen(session, "Kasse", KontoTyp.KASSE, email="kasse@example.org")
        with pytest.raises(bh.BuchhaltungsFehler, match="Nur Privatkonten"):
            bh.konto_anlegen(session, "Kasse", KontoTyp.KASSE, bierspitz="Kässchen")

    def test_bearbeiten(self, session):
        tom = mitglied(session, bierspitz="Tommy", email="tom@example.org")
        bh.konto_bearbeiten(session, tom.id, "Tom", St.AKTIVER, "", True, bierspitz="Tomate", email="neu@example.org")
        assert (tom.bierspitz, tom.email) == ("Tomate", "neu@example.org")

    def test_bearbeiten_ohne_angabe_bleibt_unveraendert(self, session):
        tom = mitglied(session, bierspitz="Tommy", email="tom@example.org")
        bh.konto_bearbeiten(session, tom.id, "Thomas", St.AKTIVER, "", True)
        assert (tom.bierspitz, tom.email) == ("Tommy", "tom@example.org")

    def test_bearbeiten_ungueltige_email(self, session):
        tom = mitglied(session, email="tom@example.org")
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.konto_bearbeiten(session, tom.id, "Tom", St.AKTIVER, "", True, email="kaputt")
        assert tom.email == "tom@example.org"

    def test_gleicher_bierspitz_erlaubt(self, session):
        mitglied(session, "Tom", bierspitz="Bär")
        mitglied(session, "Ben", bierspitz="Bär")

    def test_alte_datenbank_bekommt_spalten(self, tmp_path):
        pfad = tmp_path / "verein.db"
        engine = erstelle_engine(pfad)
        init_db(engine)
        with Session(engine) as s, s.begin():
            mitglied(s)
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE konten DROP COLUMN bierspitz")
            conn.exec_driver_sql("ALTER TABLE konten DROP COLUMN email")
        engine.dispose()

        engine = erstelle_engine(pfad)
        init_db(engine)
        with Session(engine) as s:
            tom = next(k for k in bh.konten(s) if k.name == "Tom")
            assert (tom.bierspitz, tom.email) == ("", "")
        engine.dispose()
        spalten = {z[1] for z in sqlite3.connect(pfad).execute("PRAGMA table_info(konten)")}
        assert {"bierspitz", "email"} <= spalten


# --- Oberfläche -----------------------------------------------------------

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def meldungen(monkeypatch):
    liste = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: liste.append(a[2]))
    return liste


class TestDialog:
    def _ausfuellen(self, d, email="tom@example.org"):
        d.name.setText("Tom")
        d.email.setText(email)

    def test_felder_nur_bei_privatkonto(self, app):
        d = KontoDialog()
        assert d.form.isRowVisible(d.bierspitz) and d.form.isRowVisible(d.email)
        d.typ.setCurrentIndex(d.typ.findData(KontoTyp.KASSE))
        assert not d.form.isRowVisible(d.bierspitz) and not d.form.isRowVisible(d.email)
        assert (d.werte()["bierspitz"], d.werte()["email"]) == ("", "")

    @pytest.mark.parametrize("email", ["", "   "])
    def test_email_optional(self, app, meldungen, email):
        d = KontoDialog()
        self._ausfuellen(d, email=email)
        d._pruefen()
        assert d.result() == KontoDialog.Accepted
        assert meldungen == []
        assert d.werte()["email"].strip() == ""

    def test_email_nachtragen(self, app, session):
        tom = mitglied(session, eintrittsdatum=date(2020, 1, 1))  # ohne E-Mail angelegt
        d = KontoDialog(None, tom)
        d.email.setText("tom@example.org")
        d._pruefen()
        assert d.result() == KontoDialog.Accepted
        w = d.werte()
        bh.konto_bearbeiten(session, tom.id, w["name"], w["status"], w["bemerkung"], w["aktiv"],
                            email=w["email"])
        assert tom.email == "tom@example.org"

    def test_email_wieder_entfernen(self, session):
        tom = mitglied(session, email="tom@example.org")
        bh.konto_bearbeiten(session, tom.id, "Tom", St.AKTIVER, "", True, email="")
        assert tom.email == ""

    def test_email_ungueltig(self, app, meldungen):
        d = KontoDialog()
        self._ausfuellen(d, email="tom(at)example.org")
        d._pruefen()
        assert d.result() != KontoDialog.Accepted
        assert "keine gültige" in meldungen[-1]

    def test_kasse_braucht_keine_email(self, app):
        d = KontoDialog()
        d.name.setText("Kasse")
        d.typ.setCurrentIndex(d.typ.findData(KontoTyp.KASSE))
        d._pruefen()
        assert d.result() == KontoDialog.Accepted

    def test_gueltig(self, app):
        d = KontoDialog()
        self._ausfuellen(d)
        d.bierspitz.setText("Tommy")
        d._pruefen()
        assert d.result() == KontoDialog.Accepted
        assert (d.werte()["bierspitz"], d.werte()["email"]) == ("Tommy", "tom@example.org")

    def test_bearbeiten_fuellt_felder(self, app, session):
        tom = mitglied(session, bierspitz="Tommy", email="tom@example.org")
        d = KontoDialog(None, tom)
        assert (d.bierspitz.text(), d.email.text()) == ("Tommy", "tom@example.org")


class TestHauptfenster:
    @pytest.fixture
    def fenster(self, app, engine):
        with Session(engine) as s, s.begin():
            mitglied(s, "Tom Becker", bierspitz="Tommy", email="tom@example.org")
            mitglied(s, "Anna Schulz", bierspitz="Ännchen", email="anna@verein.example")
        w = Hauptfenster(sessionmaker(engine, expire_on_commit=False), "test")
        yield w
        w.close()

    def namen(self, w):
        return {w.konten_tabelle.item(r, 0).text() for r in range(w.konten_tabelle.rowCount())}

    def test_bierspitz_spalte(self, fenster):
        t = fenster.konten_tabelle
        zeile = next(r for r in range(t.rowCount()) if t.item(r, 0).text() == "Tom Becker")
        assert t.item(zeile, 1).text() == "Tommy"

    @pytest.mark.parametrize("suche, erwartet", [
        ("tommy", {"Tom Becker"}), ("ÄNNCHEN", {"Anna Schulz"}), ("verein.example", {"Anna Schulz"}),
        ("schulz", {"Anna Schulz"}),
    ])
    def test_suche(self, fenster, suche, erwartet):
        fenster.suche.setText(suche)
        assert self.namen(fenster) == erwartet
