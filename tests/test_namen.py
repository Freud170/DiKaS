"""Vor- und Nachname bei Mitgliedern."""

import sqlite3
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas import einstellungen as es
from dikas import kontoauszug as ka
from dikas.db import erstelle_engine, init_db
from dikas.db.database import teile_namen
from dikas.db.models import KontoTyp, MitgliedStatus as St
from dikas.ui.dialoge import KontoDialog
from dikas.ui.hauptfenster import NAME_ROLLE, Hauptfenster


def mitglied(session, vorname, nachname, **kwargs):
    return bh.konto_anlegen(session, "", KontoTyp.PRIVAT, St.AKTIVER, vorname=vorname, nachname=nachname, **kwargs)


class TestLogik:
    def test_name_wird_gebildet(self, session):
        tom = mitglied(session, " Tom ", " Becker ")
        assert (tom.vorname, tom.nachname, tom.name) == ("Tom", "Becker", "Tom Becker")

    def test_mehrere_vornamen_und_nachnamen(self, session):
        k = mitglied(session, "Karl Heinz", "von der Heide")
        assert k.name == "Karl Heinz von der Heide"
        assert (k.vorname, k.nachname) == ("Karl Heinz", "von der Heide")

    def test_nachname_pflicht(self, session):
        with pytest.raises(bh.BuchhaltungsFehler, match="Nachnamen"):
            mitglied(session, "Tom", "  ")

    def test_ohne_vorname_erlaubt_im_backend(self, session):
        assert mitglied(session, "", "Becker").name == "Becker"

    def test_name_wird_aufgeteilt_wenn_nur_name(self, session):
        k = bh.konto_anlegen(session, "Max von Müller", KontoTyp.PRIVAT, St.AKTIVER)
        assert (k.vorname, k.nachname) == ("Max von", "Müller")

    def test_doppelter_name_verboten(self, session):
        mitglied(session, "Tom", "Becker")
        with pytest.raises(bh.BuchhaltungsFehler, match="bereits"):
            mitglied(session, "Tom", "Becker")
        mitglied(session, "Tim", "Becker")

    def test_kasse_ohne_vor_und_nachname(self, session):
        k = bh.konto_anlegen(session, "Getränkekasse", KontoTyp.KASSE)
        assert (k.vorname, k.nachname) == ("", "")
        with pytest.raises(bh.BuchhaltungsFehler, match="Nur Privatkonten"):
            bh.konto_anlegen(session, "Kasse", KontoTyp.KASSE, vorname="Kas", nachname="Se")

    def test_bearbeiten(self, session):
        tom = mitglied(session, "Tom", "Becker")
        bh.konto_bearbeiten(session, tom.id, "", St.AKTIVER, "", True, vorname="Thomas", nachname="Becker-Huber")
        assert (tom.vorname, tom.nachname, tom.name) == ("Thomas", "Becker-Huber", "Thomas Becker-Huber")

    def test_bearbeiten_ohne_namensangabe_behaelt_aufteilung(self, session):
        k = mitglied(session, "Karl Heinz", "von der Heide")
        bh.konto_bearbeiten(session, k.id, "Karl Heinz von der Heide", St.AKTIVER, "neu", True)
        assert (k.vorname, k.nachname) == ("Karl Heinz", "von der Heide")

    def test_umbenennen_behaelt_buchungen(self, session):
        tom = mitglied(session, "Tom", "Becker")
        bh.buchen(session, bh.Buchungsart.EINZAHLUNG, tom.id, 1000, "x")
        bh.konto_bearbeiten(session, tom.id, "", St.AKTIVER, "", True, vorname="Tom", nachname="Schulz")
        assert bh.buchungen(session, tom.id)[0].haben_konto.name == "Tom Schulz"
        assert bh.saldo(session, tom.id) == 1000


@pytest.mark.parametrize("name, erwartet", [
    ("Tom Becker", ("Tom", "Becker")),
    ("Tom", ("", "Tom")),
    ("  Max   von  Müller ", ("Max von", "Müller")),
    ("", ("", "")),
])
def test_teile_namen(name, erwartet):
    assert teile_namen(name) == erwartet


class TestAlteDatenbank:
    def test_namen_werden_beim_start_aufgeteilt(self, tmp_path):
        pfad = tmp_path / "verein.db"
        engine = erstelle_engine(pfad)
        init_db(engine)
        with Session(engine) as s, s.begin():
            mitglied(s, "Tom", "Becker")
            bh.konto_anlegen(s, "Kasse", KontoTyp.KASSE)
        engine.dispose()
        with sqlite3.connect(pfad) as con:  # Stand vor Vor-/Nachname
            con.execute("ALTER TABLE konten DROP COLUMN vorname")
            con.execute("ALTER TABLE konten DROP COLUMN nachname")
            con.execute("UPDATE konten SET name = 'Anna Maria Schulz' WHERE name = 'Tom Becker'")
        con.close()

        engine = erstelle_engine(pfad)
        init_db(engine)
        init_db(engine)  # zweiter Start ändert nichts mehr
        with Session(engine) as s:
            konten = {k.name: k for k in bh.konten(s)}
            assert (konten["Anna Maria Schulz"].vorname, konten["Anna Maria Schulz"].nachname) == ("Anna Maria", "Schulz")
            assert (konten["Kasse"].vorname, konten["Kasse"].nachname) == ("", "")
        engine.dispose()


class TestKontoauszug:
    def test_anrede_vorname_ohne_bierspitz(self, session):
        tom = mitglied(session, "Tom", "Becker")
        a = ka.erstelle_auszug(tom, 0, date(2026, 12, 31), es.Einstellungen(absender_name="Max"))
        assert a.text.startswith("Hallo Tom,")

    def test_anrede_bierspitz_vor_vorname(self, session):
        tom = mitglied(session, "Tom", "Becker", bierspitz="Tommy")
        a = ka.erstelle_auszug(tom, 0, date(2026, 12, 31), es.Einstellungen())
        assert a.text.startswith("Hallo Tommy,")

    def test_platzhalter_vor_und_nachname(self, session):
        tom = mitglied(session, "Tom", "Becker")
        e = es.Einstellungen(betreff="{nachname}, {vorname}: {saldo}")
        assert ka.erstelle_auszug(tom, -100, date(2026, 12, 31), e).betreff == "Becker, Tom: -1,00 €"

    def test_empfaenger_nach_nachname_sortiert(self, session):
        for vorname, nachname in (("Zoe", "Adler"), ("Anna", "Zimmer"), ("Ben", "Adler")):
            mitglied(session, vorname, nachname)
        assert [k.name for k, _ in ka.empfaenger_liste(session, date(2026, 12, 31))] == [
            "Ben Adler", "Zoe Adler", "Anna Zimmer"]


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
    def test_privatkonto_zeigt_vor_und_nachname(self, app):
        d = KontoDialog()
        assert d.form.isRowVisible(d.vorname) and d.form.isRowVisible(d.nachname)
        assert not d.form.isRowVisible(d.name)

    def test_kasse_zeigt_name(self, app):
        d = KontoDialog()
        d.typ.setCurrentIndex(d.typ.findData(KontoTyp.KASSE))
        assert d.form.isRowVisible(d.name)
        assert not d.form.isRowVisible(d.vorname) and not d.form.isRowVisible(d.nachname)
        d.name.setText("Festkasse")
        w = d.werte()
        assert (w["name"], w["vorname"], w["nachname"]) == ("Festkasse", None, None)

    @pytest.mark.parametrize("vorname, nachname, meldung", [
        ("", "Becker", "Vornamen"), ("Tom", "", "Nachnamen"), ("  ", "  ", "Vornamen"),
    ])
    def test_pflichtfelder(self, app, meldungen, vorname, nachname, meldung):
        d = KontoDialog()
        d.vorname.setText(vorname)
        d.nachname.setText(nachname)
        d._pruefen()
        assert d.result() != KontoDialog.Accepted
        assert meldung in meldungen[-1]

    def test_werte(self, app):
        d = KontoDialog()
        d.vorname.setText(" Tom ")
        d.nachname.setText(" Becker ")
        d._pruefen()
        assert d.result() == KontoDialog.Accepted
        w = d.werte()
        assert (w["name"], w["vorname"], w["nachname"]) == ("Tom Becker", "Tom", "Becker")

    def test_bearbeiten_fuellt_felder(self, app, session):
        k = mitglied(session, "Karl Heinz", "von der Heide")
        d = KontoDialog(None, k)
        assert (d.vorname.text(), d.nachname.text()) == ("Karl Heinz", "von der Heide")


class TestSortierungMitNamenszusatz:
    """„von Hahn“ steht unter H, Umlaute wie im Telefonbuch."""

    NAMEN = [("Gerda", "von Hahn"), ("Ida", "Imhof"), ("Hans", "Haas"), ("Karl Heinz", "von der Heide"),
             ("Jan", "de Vries"), ("Ute", "Ärmel"), ("Otto", "Abel"), ("Max", "Zu"), ("Eva", "van Dyk")]

    @pytest.fixture
    def namen_session(self, session):
        for vorname, nachname in self.NAMEN:
            mitglied(session, vorname, nachname)
        return session

    def test_konten(self, namen_session):
        namen = [k.name for k in bh.konten(namen_session) if k.typ == KontoTyp.PRIVAT]
        assert namen == ["Otto Abel", "Ute Ärmel", "Eva van Dyk", "Hans Haas", "Gerda von Hahn",
                         "Karl Heinz von der Heide", "Ida Imhof", "Jan de Vries", "Max Zu"]

    def test_nachname_nur_aus_zusatz_bleibt(self, namen_session):
        """Ein Nachname, der selbst wie ein Zusatz aussieht („Zu“), wird nicht weggekürzt."""
        zu = next(k for k in bh.konten(namen_session) if k.nachname == "Zu")
        assert bh.sortierschluessel(zu)[0] == "zu"

    def test_beitragsvorschau(self, namen_session):
        v = bh.beitrag_vorschau(namen_session, {St.AKTIVER: 100}, 2026)
        alle = [m.name for m, _ in v.faellig] + [m.name for m in v.zusaetzlich_waehlbar]
        assert alle.index("Gerda von Hahn") < alle.index("Ida Imhof")
        assert alle.index("Hans Haas") < alle.index("Gerda von Hahn")

    def test_kontoauszug(self, namen_session):
        namen = [k.name for k, _ in ka.empfaenger_liste(namen_session, date(2026, 12, 31))]
        assert namen.index("Hans Haas") < namen.index("Gerda von Hahn") < namen.index("Ida Imhof")

    def test_kassen_nach_namen(self, session):
        for name in ("Zeltkasse", "Ärger-Kasse", "Beitragskasse"):
            bh.konto_anlegen(session, name, KontoTyp.KASSE)
        assert [k.name for k in bh.konten(session) if k.typ == KontoTyp.KASSE] == [
            "Ärger-Kasse", "Beitragskasse", "Zeltkasse"]


def test_kontenliste_nach_nachname_sortiert(app, engine):
    with Session(engine) as s, s.begin():
        for vorname, nachname in (("Zoe", "Adler"), ("Anna", "Zimmer"), ("Ben", "Adler")):
            mitglied(s, vorname, nachname)
    w = Hauptfenster(sessionmaker(engine, expire_on_commit=False), "test")
    w.filter.setCurrentText("Privatkonten")
    namen = [w.konten_tabelle.item(r, 0).data(NAME_ROLLE) for r in range(w.konten_tabelle.rowCount())]
    assert namen == ["Ben Adler", "Zoe Adler", "Anna Zimmer"]
    w.close()
