"""Eintrittsdatum, Beitragslauf je Jahr, Nachholen alter Jahre und DB-Update."""

import sqlite3
from datetime import date

import pytest
from sqlalchemy.orm import Session

from dikas import buchhaltung as bh
from dikas.db import erstelle_engine, init_db
from dikas.db.models import KontoTyp, MitgliedStatus as St

from conftest import ct

D = date


class TestEintrittsdatum:
    def test_wird_gespeichert(self, verein):
        assert verein.mitglied("Tom", eintritt=D(2019, 10, 1)).eintrittsdatum == D(2019, 10, 1)

    def test_optional(self, verein):
        assert verein.mitglied("Alt", eintritt=None).eintrittsdatum is None

    def test_nur_bei_privatkonten(self, session):
        with pytest.raises(bh.BuchhaltungsFehler, match="Eintrittsdatum"):
            bh.konto_anlegen(session, "Kasse", KontoTyp.KASSE, eintrittsdatum=D(2020, 1, 1))

    def test_nachtragen(self, verein, session):
        alt = verein.mitglied("Alt", eintritt=None)
        bh.konto_bearbeiten(session, alt.id, "Alt", St.AKTIVER, "", True, D(2015, 4, 1))
        assert alt.eintrittsdatum == D(2015, 4, 1)

    def test_bearbeiten_ohne_datum_laesst_es_unveraendert(self, verein, session):
        tom = verein.mitglied("Tom", eintritt=D(2019, 10, 1))
        bh.konto_bearbeiten(session, tom.id, "Thomas", St.AKTIVER, "", True)
        assert tom.eintrittsdatum == D(2019, 10, 1)


class TestStichtag:
    @pytest.mark.parametrize(
        "eintritt, faellig",
        [
            (D(2025, 12, 31), True),
            (D(2026, 1, 1), True),  # am Stichtag eingetreten: zahlt
            (D(2026, 1, 2), False),
            (D(2026, 10, 1), False),
            (D(1980, 5, 5), True),
        ],
    )
    def test_dabei_am_01_01(self, verein, session, eintritt, faellig):
        verein.mitglied("Tom", eintritt=eintritt)
        v = bh.beitrag_vorschau(session, {St.AKTIVER: 6000}, 2026)
        assert bool(v.faellig) == faellig
        assert bool(v.spaeter_eingetreten) != faellig

    def test_ohne_eintrittsdatum_wird_ausgelassen(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        alt = verein.mitglied("Alt", eintritt=None)
        verein.mitglied("Tom")
        v = bh.beitrag_vorschau(session, {St.AKTIVER: 6000}, 2026)
        assert [m.name for m in v.ohne_eintrittsdatum] == ["Alt"]
        verein.beitragslauf(kasse, aktiver="60")
        assert verein.saldo(alt) == 0

    def test_nur_mitglieder_mit_betrag_tauchen_auf(self, verein, session):
        verein.mitglied("Spät", St.ALUMNI, eintritt=D(2026, 6, 1))
        v = bh.beitrag_vorschau(session, {St.AKTIVER: 6000, St.ALUMNI: 0}, 2026)
        assert v.spaeter_eingetreten == []  # Alumni zahlen 0 → gar nicht relevant


class TestDoppelschutz:
    def test_zweiter_lauf_im_selben_jahr_bucht_nur_neue(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        verein.beitragslauf(kasse, aktiver="60", jahr=2026)
        nachzuegler = verein.mitglied("Nachzügler", eintritt=D(2025, 6, 1))  # vergessen

        gebucht = verein.beitragslauf(kasse, aktiver="60", jahr=2026)

        assert [b.soll_konto_id for b in gebucht] == [nachzuegler.id]
        assert verein.saldo(tom) == ct(-60)
        v = bh.beitrag_vorschau(session, {St.AKTIVER: 6000}, 2026)
        assert {m.name for m in v.bereits_abgebucht} == {"Tom", "Nachzügler"}

    def test_storno_gibt_jahr_wieder_frei(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        (b,) = verein.beitragslauf(kasse, aktiver="600", jahr=2026)
        storno = verein.storno(b)
        assert storno.beitragsjahr == 2026
        verein.beitragslauf(kasse, aktiver="60", jahr=2026)
        assert verein.saldo(tom) == ct(-60)

    def test_manueller_beitrag_zaehlt_nicht_als_jahresbeitrag(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        verein.beitrag(tom, kasse, "15", "Sonderumlage")
        assert len(bh.beitrag_vorschau(session, {St.AKTIVER: 6000}, 2026).faellig) == 1

    def test_jahre_sind_unabhaengig(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        for jahr in (2024, 2025, 2026):
            verein.beitragslauf(kasse, aktiver="60", jahr=jahr)
        assert verein.saldo(tom) == ct(-180)

    def test_status_eines_anderen_mitglieds_unberuehrt(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Tom", St.AKTIVER)
        fritz = verein.mitglied("Fritz", St.FUX)
        verein.beitragslauf(kasse, aktiver="60", jahr=2026)  # Füxe noch ohne Betrag
        gebucht = verein.beitragslauf(kasse, fux="30", aktiver="60", jahr=2026)
        assert [b.soll_konto_id for b in gebucht] == [fritz.id]


class TestNachholen:
    def test_drei_jahre_nachholen(self, verein, session):
        """Neues System: Beiträge 2024–2026 nachbuchen, Mitglieder unterschiedlich lang dabei."""
        kasse = verein.kasse("Beitragskasse")
        alt = verein.mitglied("Alfred", St.ALUMNI, eintritt=D(1995, 10, 1))
        tom = verein.mitglied("Tom", St.AKTIVER, eintritt=D(2023, 10, 1))
        anna = verein.mitglied("Anna", St.AKTIVER, eintritt=D(2024, 10, 15))
        fritz = verein.mitglied("Fritz", St.FUX, eintritt=D(2025, 10, 20))
        betraege = dict(fux="30", aktiver="60", alumni="100")

        for jahr in (2024, 2025, 2026):
            verein.beitragslauf(kasse, **betraege, jahr=jahr, text=f"Jahresbeitrag {jahr}")

        assert verein.saldo(alt) == ct(-300)  # 2024, 2025, 2026
        assert verein.saldo(tom) == ct(-180)  # 2024, 2025, 2026
        assert verein.saldo(anna) == ct(-120)  # 2025, 2026
        assert verein.saldo(fritz) == ct(-30)  # nur 2026
        verein.pruefe_abstimmung()

    def test_buchungsdatum_ist_01_01_des_jahres(self, verein):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Tom")
        (b,) = verein.beitragslauf(kasse, aktiver="60", jahr=2024)
        assert (b.datum, b.beitragsjahr) == (D(2024, 1, 1), 2024)

    def test_nachgeholte_beitraege_in_auswertung_des_jahres(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Tom")
        verein.beitragslauf(kasse, aktiver="60", jahr=2024)
        verein.beitragslauf(kasse, aktiver="70", jahr=2025)
        b2024 = next(b for b in bh.kontobewegungen(session, D(2024, 1, 1), D(2024, 12, 31))
                     if b.konto.id == kasse.id)
        assert b2024.zugang == ct(60)

    def test_eigenes_buchungsdatum(self, verein):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Tom")
        (b,) = verein.beitragslauf(kasse, aktiver="60", jahr=2024, datum=D(2026, 10, 29))
        assert (b.datum, b.beitragsjahr) == (D(2026, 10, 29), 2024)

    @pytest.mark.parametrize("jahr", [1800, 3000])
    def test_unsinniges_jahr(self, verein, jahr):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Tom")
        with pytest.raises(bh.BuchhaltungsFehler, match="Beitragsjahr"):
            verein.beitragslauf(kasse, aktiver="60", jahr=jahr)


class TestDatenbankUpdate:
    def _alte_db(self, pfad):
        """Datenbank im Stand vor Eintrittsdatum/Beitragsjahr mit etwas Inhalt."""
        con = sqlite3.connect(pfad)
        con.executescript("""
            CREATE TABLE konten (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, typ VARCHAR(10) NOT NULL,
                status VARCHAR(10), aktiv BOOLEAN NOT NULL, geloescht BOOLEAN NOT NULL,
                bemerkung VARCHAR(500) NOT NULL, erstellt_am DATETIME NOT NULL);
            CREATE TABLE buchungen (id INTEGER PRIMARY KEY, datum DATE NOT NULL, art VARCHAR(20) NOT NULL,
                betrag_cent INTEGER NOT NULL, soll_konto_id INTEGER NOT NULL, haben_konto_id INTEGER NOT NULL,
                text VARCHAR(200) NOT NULL, beleg VARCHAR(50) NOT NULL, erstellt_am DATETIME NOT NULL,
                storno_von_id INTEGER);
            INSERT INTO konten VALUES (1, 'KW', 'KW', NULL, 1, 0, '', '2026-10-29 20:00:00');
            INSERT INTO konten VALUES (2, 'Tom', 'PRIVAT', 'AKTIVER', 1, 0, '', '2026-10-29 20:00:00');
            INSERT INTO buchungen VALUES (1, '2026-10-01', 'EINZAHLUNG', 1000, 1, 2, 'Alt', '', '2026-10-29 20:00:00', NULL);
        """)
        con.commit()
        con.close()

    def test_alte_datenbank_wird_ergaenzt(self, tmp_path):
        pfad = tmp_path / "verein.db"
        self._alte_db(pfad)

        engine = erstelle_engine(pfad)
        init_db(engine)
        init_db(engine)  # zweiter Start: nichts doppelt

        with Session(engine) as s:
            tom = next(k for k in bh.konten(s) if k.name == "Tom")
            assert tom.eintrittsdatum is None
            assert bh.saldo(s, tom.id) == 1000  # alte Daten unverändert
            assert bh.buchungen(s)[0].beitragsjahr is None
            bh.konto_bearbeiten(s, tom.id, "Tom", St.AKTIVER, "", True, D(2020, 1, 1))
            s.commit()
        engine.dispose()

        spalten = {z[1] for z in sqlite3.connect(pfad).execute("PRAGMA table_info(konten)")}
        assert "eintrittsdatum" in spalten
