"""Technische Absicherung: Transaktionen, Speichern, DB-Regeln, Invarianten, Mengen."""

import random
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas.db import erstelle_engine, init_db
from dikas.db.models import Buchung, Buchungsart as Art, Konto, KontoTyp, MitgliedStatus as St

from conftest import Verein, ct


def anzahl_buchungen(session) -> int:
    return session.scalar(select(func.count()).select_from(Buchung))


# --- Transaktionen --------------------------------------------------------

class TestTransaktionen:
    def test_beitragslauf_ist_alles_oder_nichts(self, engine, monkeypatch):
        """Scheitert eine Buchung im Lauf, wird keine einzige gespeichert."""
        Sitzung = sessionmaker(engine)
        with Sitzung.begin() as s:
            kasse = bh.konto_anlegen(s, "Beitragskasse", KontoTyp.KASSE).id
            for n in ("A", "B", "C"):
                bh.konto_anlegen(s, n, KontoTyp.PRIVAT, St.AKTIVER, eintrittsdatum=date(2020, 1, 1))

        original = bh.buchen

        def buchen_mit_fehler(session, art, konto_id, *args, **kwargs):
            if session.get(Konto, konto_id).name == "C":
                raise bh.BuchhaltungsFehler("Simulierter Fehler")
            return original(session, art, konto_id, *args, **kwargs)

        monkeypatch.setattr(bh, "buchen", buchen_mit_fehler)
        with pytest.raises(bh.BuchhaltungsFehler, match="Simulierter"):
            with Sitzung.begin() as s:
                bh.beitraege_abbuchen(s, {St.AKTIVER: 6000}, 2026, kasse, "Beitrag")

        with Sitzung() as s:
            assert anzahl_buchungen(s) == 0

    def test_fehlgeschlagene_buchung_hinterlaesst_nichts(self, engine):
        Sitzung = sessionmaker(engine)
        with Sitzung.begin() as s:
            tom = bh.konto_anlegen(s, "Tom", KontoTyp.PRIVAT, St.AKTIVER).id
        with pytest.raises(bh.BuchhaltungsFehler):
            with Sitzung.begin() as s:
                bh.buchen(s, Art.EINZAHLUNG, tom, 100, "ok")
                bh.buchen(s, Art.EINZAHLUNG, tom, -1, "kaputt")
        with Sitzung() as s:
            assert anzahl_buchungen(s) == 0


# --- Speichern in Datei ---------------------------------------------------

class TestDatei:
    def test_daten_bleiben_nach_neustart_erhalten(self, tmp_path):
        pfad = tmp_path / "verein.db"
        engine = erstelle_engine(pfad)
        init_db(engine)
        with Session(engine) as s, s.begin():
            v = Verein(s)
            tom = v.mitglied("Tom", St.FUX)
            kasse = v.kasse("Beitragskasse")
            v.beitrag(tom, kasse, "30")
            v.einzahlung(tom, "50")
            erwartet = bh.salden(s)
        engine.dispose()

        engine = erstelle_engine(pfad)
        init_db(engine)  # zweiter Start darf nichts doppelt anlegen
        with Session(engine) as s:
            assert bh.salden(s) == erwartet
            assert len(bh.konten(s)) == 3
            assert s.scalar(select(func.count()).where(Konto.typ == KontoTyp.KW)) == 1
            tom = s.scalar(select(Konto).where(Konto.name == "Tom"))
            assert tom.status == St.FUX
        engine.dispose()

    def test_ordner_wird_angelegt(self, tmp_path):
        pfad = tmp_path / "neu" / "unterordner" / "verein.db"
        engine = erstelle_engine(pfad)
        init_db(engine)
        assert pfad.exists()
        engine.dispose()

    def test_fremdschluessel_sind_aktiv(self, session):
        with pytest.raises(IntegrityError):
            session.add(Buchung(
                datum=date.today(), art=Art.EINZAHLUNG, betrag_cent=100,
                soll_konto_id=1, haben_konto_id=9999, text="x",
            ))
            session.flush()


# --- Datenbank-Regeln (letzte Verteidigungslinie) -------------------------

class TestDatenbankRegeln:
    def _roh(self, session, **werte):
        kw = bh.kw_konto(session)
        kasse = bh.konto_anlegen(session, "K", KontoTyp.KASSE)
        daten = dict(
            datum=date.today(), art=Art.KASSE_EINNAHME, betrag_cent=100,
            soll_konto_id=kw.id, haben_konto_id=kasse.id, text="x",
        )
        daten.update(werte)
        session.add(Buchung(**daten))
        session.flush()

    @pytest.mark.parametrize("betrag", [0, -100])
    def test_betrag_muss_positiv_sein(self, session, betrag):
        with pytest.raises(IntegrityError):
            self._roh(session, betrag_cent=betrag)

    def test_soll_und_haben_verschieden(self, session):
        with pytest.raises(IntegrityError):
            self._roh(session, haben_konto_id=bh.kw_konto(session).id)

    def test_privatkonto_ohne_status(self, session):
        with pytest.raises(IntegrityError):
            session.add(Konto(name="X", typ=KontoTyp.PRIVAT))
            session.flush()

    def test_kasse_mit_status(self, session):
        with pytest.raises(IntegrityError):
            session.add(Konto(name="X", typ=KontoTyp.KASSE, status=St.FUX))
            session.flush()

    def test_doppelter_name_gleicher_typ(self, session):
        session.add(Konto(name="X", typ=KontoTyp.KASSE))
        session.add(Konto(name="X", typ=KontoTyp.KASSE))
        with pytest.raises(IntegrityError):
            session.flush()

    def test_buchung_nur_einmal_stornierbar(self, session):
        kw = bh.kw_konto(session)
        kasse = bh.konto_anlegen(session, "K", KontoTyp.KASSE)
        b = bh.buchen(session, Art.KASSE_EINNAHME, kasse.id, 100, "x")
        for _ in range(2):
            session.add(Buchung(
                datum=date.today(), art=Art.STORNO, betrag_cent=100, soll_konto_id=kasse.id,
                haben_konto_id=kw.id, text="Storno", storno_von_id=b.id,
            ))
        with pytest.raises(IntegrityError):
            session.flush()


# --- Invarianten bei zufälligen Abläufen ----------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_zufaellige_ablaeufe_bleiben_stimmig(session, seed):
    """Egal welche Buchungen in welcher Reihenfolge: Die Bücher müssen immer aufgehen."""
    rnd = random.Random(seed)
    v = Verein(session)
    mitglieder = [v.mitglied(f"M{i}", rnd.choice(list(St))) for i in range(8)]
    kassen = [v.kasse(f"K{i}") for i in range(3)]
    passiv = mitglieder + kassen
    gebucht: list[Buchung] = []

    for schritt in range(150):
        betrag = str(rnd.randint(1, 50000) / 100).replace(".", ",")
        aktion = rnd.randrange(8)
        if aktion == 0:
            gebucht.append(v.einzahlung(rnd.choice(mitglieder), betrag))
        elif aktion == 1:
            gebucht.append(v.auszahlung(rnd.choice(mitglieder), betrag))
        elif aktion == 2:
            gebucht.append(v.einnahme(rnd.choice(kassen), betrag))
        elif aktion == 3:
            gebucht.append(v.ausgabe(rnd.choice(kassen), betrag))
        elif aktion == 4:
            von, nach = rnd.sample(passiv, 2)
            gebucht.append(v.umbuchung(von, nach, betrag))
        elif aktion == 5:
            gebucht.append(v.beitrag(rnd.choice(mitglieder), rnd.choice(kassen), betrag))
        elif aktion == 6 and schritt % 25 == 0:
            gebucht += v.beitragslauf(
                rnd.choice(kassen), fux="30", aktiver="60", alumni="100", jahr=2000 + schritt
            )
        elif aktion == 7:
            offen = [b for b in gebucht if not b.ist_storno and not b.ist_storniert]
            if offen:
                gebucht.append(v.storno(rnd.choice(offen)))

    v.pruefe_abstimmung()
    salden = bh.salden(session)
    for konto in bh.konten(session):
        # Saldo = Summe der Wirkungen aller Buchungen dieses Kontos
        assert salden[konto.id] == sum(b.wirkung_auf(konto) for b in bh.buchungen(session, konto.id))
    # Doppelte Buchführung: Summe Soll == Summe Haben (je Buchung gleich)
    assert all(b.wirkung_auf(b.soll_konto) != 0 for b in gebucht)


@pytest.mark.parametrize("seed", range(5))
def test_alles_storniert_ergibt_null(session, seed):
    rnd = random.Random(seed)
    v = Verein(session)
    m = [v.mitglied(f"M{i}") for i in range(4)]
    k = [v.kasse(f"K{i}") for i in range(2)]
    gebucht = []
    for _ in range(40):
        betrag = str(rnd.randint(1, 9999))
        gebucht.append(rnd.choice([
            lambda: v.einzahlung(rnd.choice(m), betrag),
            lambda: v.ausgabe(rnd.choice(k), betrag),
            lambda: v.umbuchung(rnd.choice(m), rnd.choice(k), betrag),
            lambda: v.beitrag(rnd.choice(m), rnd.choice(k), betrag),
        ])())
    for b in gebucht:
        v.storno(b)
    assert all(wert == 0 for wert in bh.salden(session).values())


# --- Mengen und Grenzwerte ------------------------------------------------

class TestMengen:
    def test_grosser_verein(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        status = list(St)
        for i in range(300):
            verein.mitglied(f"Mitglied {i:03d}", status[i % 3])
        buchungen = verein.beitragslauf(kasse, fux="30", aktiver="60", alumni="100")
        assert len(buchungen) == 300
        assert verein.saldo(kasse) == ct(100 * (30 + 60 + 100))
        verein.pruefe_abstimmung()

    def test_viele_buchungen_eines_kontos(self, verein, session):
        tom = verein.mitglied("Tom")
        for i in range(500):
            verein.einzahlung(tom, "0,01", datum=date(2026, 1, 1) + timedelta(days=i % 365))
        assert verein.saldo(tom) == 500
        assert len(bh.buchungen(session, tom.id)) == 500

    def test_kleinster_betrag(self, verein):
        tom = verein.mitglied("Tom")
        verein.einzahlung(tom, "0,01")
        assert verein.saldo(tom) == 1

    def test_sehr_grosser_betrag(self, verein):
        kasse = verein.kasse("Bau")
        verein.einnahme(kasse, "9.999.999,99", "Zuschuss Hausrenovierung")
        assert verein.saldo(kasse) == 999_999_999

    def test_keine_rundungsfehler_bei_drittelung(self, verein):
        kasse = verein.kasse("K")
        for _ in range(3):
            verein.einnahme(kasse, "33,33")
        verein.einnahme(kasse, "0,01")
        assert verein.saldo(kasse) == ct(100)

    def test_viele_kleine_betraege(self, verein):
        kasse = verein.kasse("K")
        for _ in range(1000):
            verein.einnahme(kasse, "0,10")
        assert verein.saldo(kasse) == ct(100)


# --- Abfragen -------------------------------------------------------------

class TestAbfragen:
    def test_buchungen_neueste_zuerst(self, verein, session):
        tom = verein.mitglied("Tom")
        for tag in (5, 1, 20, 10):
            verein.einzahlung(tom, "1", f"Tag {tag}", date(2026, 3, tag))
        assert [b.datum.day for b in bh.buchungen(session, tom.id)] == [20, 10, 5, 1]

    def test_gleiches_datum_nach_reihenfolge_der_eingabe(self, verein, session):
        tom = verein.mitglied("Tom")
        for text in ("erste", "zweite", "dritte"):
            verein.einzahlung(tom, "1", text, date(2026, 3, 1))
        assert [b.text for b in bh.buchungen(session, tom.id)] == ["dritte", "zweite", "erste"]

    def test_rueckdatierte_buchung(self, verein, session):
        tom = verein.mitglied("Tom")
        verein.einzahlung(tom, "1", "heute")
        verein.einzahlung(tom, "1", "nachgetragen", date(2025, 12, 31))
        assert bh.buchungen(session, tom.id)[-1].text == "nachgetragen"

    def test_standarddatum_ist_heute(self, verein):
        tom = verein.mitglied("Tom")
        assert verein.einzahlung(tom, "1").datum == date.today()

    def test_konten_sortiert_und_gefiltert(self, verein, session):
        verein.mitglied("Zoe")
        verein.mitglied("Anna")
        weg = verein.mitglied("Bernd")
        weg.aktiv = False
        verein.kasse("Kasse")
        alle = bh.konten(session)
        assert [k.name for k in alle if k.typ == KontoTyp.PRIVAT] == ["Anna", "Bernd", "Zoe"]
        assert "Bernd" not in [k.name for k in bh.konten(session, nur_aktive=True)]

    def test_salden_enthalten_konten_ohne_buchungen(self, verein, session):
        tom = verein.mitglied("Tom")
        assert bh.salden(session)[tom.id] == 0

    def test_buchungen_eines_kontos_ohne_buchungen(self, verein, session):
        assert bh.buchungen(session, verein.mitglied("Tom").id) == []

    def test_wirkung_auf_unbeteiligtes_konto(self, verein):
        tom, fritz = verein.mitglied("Tom"), verein.mitglied("Fritz")
        assert verein.einzahlung(tom, "5").wirkung_auf(fritz) == 0

    def test_texte_werden_getrimmt(self, verein, session):
        tom = verein.mitglied("Tom")
        b = bh.buchen(session, Art.EINZAHLUNG, tom.id, 100, "  Beitrag  ", beleg="  B-1 ")
        assert (b.text, b.beleg) == ("Beitrag", "B-1")

    def test_unbekanntes_konto(self, session):
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.buchen(session, Art.EINZAHLUNG, 9999, 100, "x")
