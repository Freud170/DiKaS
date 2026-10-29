"""Statusverlauf: Wechsel mit Datum, Status am Stichtag, Beitragslauf nach damaligem Status."""

from datetime import date, timedelta

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas.db import erstelle_engine, init_db
from dikas.db.models import Konto, KontoTyp, MitgliedStatus as St, Statuswechsel
from dikas.ui.dialoge import KontoDialog, StatusverlaufEditor

from conftest import ct

D = date


def verlauf(konto):
    return [(w.status, w.gueltig_ab) for w in konto.statusverlauf]


# --- Logik ----------------------------------------------------------------

class TestVerlauf:
    def test_neues_mitglied_bekommt_ersten_eintrag(self, verein):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        assert verlauf(tom) == [(St.FUX, D(2024, 10, 15))]

    def test_ohne_eintrittsdatum_ab_heute(self, verein):
        tom = verein.mitglied("Tom", St.FUX, eintritt=None)
        assert verlauf(tom) == [(St.FUX, date.today())]

    def test_kasse_hat_keinen_verlauf(self, verein):
        assert verein.kasse("K").statusverlauf == []

    def test_status_wechseln(self, verein, session):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        bh.status_wechseln(session, tom.id, St.AKTIVER, D(2025, 11, 1))
        assert verlauf(tom) == [(St.FUX, D(2024, 10, 15)), (St.AKTIVER, D(2025, 11, 1))]
        assert tom.status == St.AKTIVER

    def test_rueckwirkender_wechsel_dazwischen(self, verein, session):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2020, 10, 1))
        bh.status_wechseln(session, tom.id, St.ALUMNI, D(2025, 7, 1))
        bh.status_wechseln(session, tom.id, St.AKTIVER, D(2021, 11, 1))  # vergessen, nachgetragen
        assert [s for s, _ in verlauf(tom)] == [St.FUX, St.AKTIVER, St.ALUMNI]
        assert tom.status == St.ALUMNI  # aktueller = neuester

    def test_gleiches_datum_wird_ueberschrieben(self, verein, session):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        bh.status_wechseln(session, tom.id, St.ALUMNI, D(2025, 11, 1))  # vertippt
        bh.status_wechseln(session, tom.id, St.AKTIVER, D(2025, 11, 1))
        assert verlauf(tom) == [(St.FUX, D(2024, 10, 15)), (St.AKTIVER, D(2025, 11, 1))]

    def test_verlauf_setzen(self, verein, session):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        bh.statusverlauf_setzen(session, tom.id, [(St.ALUMNI, D(2025, 3, 1)), (St.FUX, D(2023, 1, 1))])
        assert verlauf(tom) == [(St.FUX, D(2023, 1, 1)), (St.ALUMNI, D(2025, 3, 1))]
        assert tom.status == St.ALUMNI
        assert len(session.scalars(select(Statuswechsel)).all()) == 2  # alte Einträge entfernt

    @pytest.mark.parametrize(
        "eintraege, meldung",
        [
            ([], "mindestens einen"),
            ([(St.FUX, D(2024, 1, 1)), (St.AKTIVER, D(2024, 1, 1))], "nur ein Statuswechsel"),
            ([(St.FUX, date.today() + timedelta(days=1))], "Zukunft"),
        ],
    )
    def test_ungueltiger_verlauf(self, verein, session, eintraege, meldung):
        tom = verein.mitglied("Tom")
        vorher = verlauf(tom)
        with pytest.raises(bh.BuchhaltungsFehler, match=meldung):
            bh.statusverlauf_setzen(session, tom.id, eintraege)
        assert verlauf(tom) == vorher

    def test_nur_fuer_privatkonten(self, verein, session):
        kasse = verein.kasse("K")
        with pytest.raises(bh.BuchhaltungsFehler, match="Privatkonten"):
            bh.status_wechseln(session, kasse.id, St.FUX, D(2024, 1, 1))

    def test_konto_bearbeiten_mit_verlauf(self, verein, session):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        bh.konto_bearbeiten(
            session, tom.id, "Tom", St.FUX, "", True,
            statusverlauf=[(St.FUX, D(2024, 10, 15)), (St.AKTIVER, D(2025, 11, 1))],
        )
        assert tom.status == St.AKTIVER  # Status kommt aus dem Verlauf
        assert len(verlauf(tom)) == 2

    def test_konto_bearbeiten_mit_neuem_status_wechselt_ab_heute(self, verein, session):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        bh.konto_bearbeiten(session, tom.id, "Tom", St.AKTIVER, "", True)
        assert verlauf(tom)[-1] == (St.AKTIVER, date.today())

    def test_konto_bearbeiten_ohne_statusaenderung_ohne_eintrag(self, verein, session):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        bh.konto_bearbeiten(session, tom.id, "Thomas", St.FUX, "", True)
        assert len(verlauf(tom)) == 1

    def test_loeschen_entfernt_verlauf(self, verein, session):
        tom = verein.mitglied("Tom")
        bh.konto_loeschen(session, tom.id)
        assert session.scalars(select(Statuswechsel)).all() == []


class TestStatusAm:
    @pytest.fixture
    def tom(self, verein, session):
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        bh.status_wechseln(session, tom.id, St.AKTIVER, D(2025, 11, 1))
        bh.status_wechseln(session, tom.id, St.ALUMNI, D(2026, 6, 30))
        return tom

    @pytest.mark.parametrize(
        "stichtag, status",
        [
            (D(2024, 10, 15), St.FUX),
            (D(2025, 1, 1), St.FUX),
            (D(2025, 10, 31), St.FUX),
            (D(2025, 11, 1), St.AKTIVER),  # gilt ab dem Tag selbst
            (D(2026, 1, 1), St.AKTIVER),
            (D(2026, 6, 30), St.ALUMNI),
            (D(2030, 1, 1), St.ALUMNI),
            (D(2020, 1, 1), St.FUX),  # vor dem ersten Eintrag: erster Eintrag
        ],
    )
    def test_status_am(self, tom, stichtag, status):
        assert bh.status_am(tom, stichtag) == status

    def test_kasse(self, verein):
        assert bh.status_am(verein.kasse("K"), D(2026, 1, 1)) is None


class TestAltesKontoOhneVerlauf:
    """Konten, die vor Einführung des Verlaufs angelegt wurden."""

    @pytest.fixture
    def alt(self, session):
        konto = Konto(name="Alt", typ=KontoTyp.PRIVAT, status=St.AKTIVER, eintrittsdatum=D(2019, 10, 1))
        session.add(konto)
        session.flush()
        return konto

    def test_status_am_nutzt_aktuellen_status(self, alt):
        assert alt.statusverlauf == []
        assert bh.status_am(alt, D(2020, 1, 1)) == St.AKTIVER

    def test_erster_wechsel_haelt_bisherigen_status_fest(self, session, alt):
        bh.status_wechseln(session, alt.id, St.ALUMNI, D(2025, 7, 1))
        assert verlauf(alt) == [(St.AKTIVER, D(2019, 10, 1)), (St.ALUMNI, D(2025, 7, 1))]

    def test_ohne_eintrittsdatum(self, session, alt):
        alt.eintrittsdatum = None
        bh.status_wechseln(session, alt.id, St.ALUMNI, D(2025, 7, 1))
        assert verlauf(alt)[0][0] == St.AKTIVER
        assert bh.status_am(alt, D(2024, 1, 1)) == St.AKTIVER

    def test_alte_datenbank_bekommt_tabelle(self, tmp_path):
        pfad = tmp_path / "verein.db"
        engine = erstelle_engine(pfad)
        init_db(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE statuswechsel")  # Stand vor dem Verlauf
        init_db(engine)
        with Session(engine) as s, s.begin():
            tom = bh.konto_anlegen(s, "Tom", KontoTyp.PRIVAT, St.FUX, eintrittsdatum=D(2024, 1, 1))
            assert len(tom.statusverlauf) == 1
        engine.dispose()


# --- Beitragslauf nach damaligem Status ------------------------------------

class TestBeitragNachDamaligemStatus:
    def test_nachholen_mit_statuswechseln(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2023, 10, 15))
        bh.status_wechseln(session, tom.id, St.AKTIVER, D(2024, 11, 1))  # Burschung
        bh.status_wechseln(session, tom.id, St.ALUMNI, D(2025, 12, 15))  # Philistrierung

        for jahr in (2024, 2025, 2026):
            verein.beitragslauf(kasse, fux="30", aktiver="60", alumni="100", jahr=jahr)

        # 2024: Fux (30), 2025: Aktiver (60), 2026: Alumni (100)
        assert verein.saldo(tom) == ct(-190)
        assert [b.betrag_cent for b in sorted(bh.buchungen(session, tom.id), key=lambda b: b.datum)] == [
            ct(30), ct(60), ct(100)
        ]

    def test_wechsel_genau_am_01_01(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        bh.status_wechseln(session, tom.id, St.AKTIVER, D(2026, 1, 1))
        (b,) = verein.beitragslauf(kasse, fux="30", aktiver="60", jahr=2026)
        assert b.betrag_cent == ct(60)

    def test_wechsel_im_laufenden_jahr_zaehlt_erst_naechstes_jahr(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom", St.FUX, eintritt=D(2024, 10, 15))
        bh.status_wechseln(session, tom.id, St.AKTIVER, D(2026, 1, 2))
        (b,) = verein.beitragslauf(kasse, fux="30", aktiver="60", jahr=2026)
        assert b.betrag_cent == ct(30)

    def test_damaliger_status_ohne_beitrag(self, verein, session):
        """Alumni zahlen 0 € – wer am Stichtag Alumnus war, wird nicht abgebucht."""
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom", St.ALUMNI, eintritt=D(2010, 1, 1))
        bh.status_wechseln(session, tom.id, St.AKTIVER, D(2025, 3, 1))  # reaktiviert
        with pytest.raises(bh.BuchhaltungsFehler):
            verein.beitragslauf(kasse, aktiver="60", alumni="0", jahr=2025)
        assert len(verein.beitragslauf(kasse, aktiver="60", alumni="0", jahr=2026)) == 1


# --- Oberfläche -----------------------------------------------------------

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def meldungen(monkeypatch):
    liste = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: liste.append(a[2]))
    return liste


class TestEditor:
    def test_zeigt_verlauf_sortiert(self, app):
        e = StatusverlaufEditor([(St.AKTIVER, D(2025, 11, 1)), (St.FUX, D(2024, 10, 15))])
        assert e.werte() == [(St.FUX, D(2024, 10, 15)), (St.AKTIVER, D(2025, 11, 1))]
        assert e.aktueller_status() == St.AKTIVER

    def test_neuer_wechsel_schlaegt_naechsten_status_vor(self, app):
        e = StatusverlaufEditor([(St.FUX, D(2024, 10, 15))])
        e.neuer_wechsel()
        assert e.werte()[-1] == (St.AKTIVER, date.today())
        e.neuer_wechsel()
        assert e.werte()[-1][0] == St.ALUMNI

    def test_entfernen_laesst_mindestens_einen(self, app):
        e = StatusverlaufEditor([(St.FUX, D(2024, 10, 15))])
        assert not e.entfernen.isEnabled()
        e.ausgewaehlten_entfernen()
        assert len(e.werte()) == 1
        e.neuer_wechsel()
        assert e.entfernen.isEnabled()
        e.ausgewaehlten_entfernen()
        assert e.werte() == [(St.FUX, D(2024, 10, 15))]

    def test_doppeltes_datum_ist_fehler(self, app):
        e = StatusverlaufEditor([(St.FUX, date.today())])
        e.neuer_wechsel()
        assert "dasselbe Datum" in e.fehler()

    def test_kein_datum_in_der_zukunft(self, app):
        e = StatusverlaufEditor([(St.FUX, D(2024, 10, 15))])
        datum = e.tabelle.cellWidget(0, 1)
        assert datum.maximumDate().toPython() == date.today()


class TestKontoDialogMitVerlauf:
    @pytest.fixture
    def tom(self, engine):
        with Session(engine, expire_on_commit=False) as s, s.begin():
            tom = bh.konto_anlegen(s, "", KontoTyp.PRIVAT, St.FUX, eintrittsdatum=D(2024, 10, 15),
                                   email="tom@example.org", vorname="Tom", nachname="Becker")
            bh.status_wechseln(s, tom.id, St.AKTIVER, D(2025, 11, 1))
        with sessionmaker(engine)() as s:
            return s.get(Konto, tom.id)  # Verlauf wird mitgeladen

    def test_neues_konto_ohne_verlaufseditor(self, app):
        d = KontoDialog()
        assert d.verlauf is None
        assert d.form.isRowVisible(d.status)
        assert d.werte()["statusverlauf"] is None

    def test_kasse_ohne_verlaufseditor(self, app, verein, session):
        assert KontoDialog(None, verein.kasse("K")).verlauf is None

    def test_bearbeiten_zeigt_verlauf_statt_status(self, app, tom):
        d = KontoDialog(None, tom)
        assert not d.form.isRowVisible(d.status)
        assert d.verlauf.werte() == [(St.FUX, D(2024, 10, 15)), (St.AKTIVER, D(2025, 11, 1))]
        assert d.werte()["status"] == St.AKTIVER

    def test_neuer_wechsel_wird_gespeichert(self, app, engine, tom):
        d = KontoDialog(None, tom)
        d.verlauf.neuer_wechsel()
        d._pruefen()
        assert d.result() == KontoDialog.Accepted
        w = d.werte()
        with Session(engine) as s, s.begin():
            bh.konto_bearbeiten(s, tom.id, w["name"], w["status"], w["bemerkung"], w["aktiv"],
                                w["eintrittsdatum"], statusverlauf=w["statusverlauf"])
            konto = s.get(Konto, tom.id)
            assert konto.status == St.ALUMNI
            assert len(konto.statusverlauf) == 3

    def test_doppeltes_datum_wird_abgelehnt(self, app, tom, meldungen):
        d = KontoDialog(None, tom)
        d.verlauf.neuer_wechsel()
        d.verlauf.neuer_wechsel()
        d._pruefen()
        assert d.result() != KontoDialog.Accepted
        assert "dasselbe Datum" in meldungen[-1]

    def test_altes_konto_ohne_verlauf(self, app, session):
        alt = Konto(name="Alt", typ=KontoTyp.PRIVAT, status=St.ALUMNI, eintrittsdatum=D(2000, 4, 1))
        session.add(alt)
        session.flush()
        d = KontoDialog(None, alt)
        assert d.verlauf.werte() == [(St.ALUMNI, D(2000, 4, 1))]
