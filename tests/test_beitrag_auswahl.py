"""Neue Status (Fördermitglied, Ehrenmitglied) und manuelle Auswahl im Beitragslauf."""

from datetime import date

import pytest

from dikas import buchhaltung as bh
from dikas.db.models import MitgliedStatus as St

from conftest import ct

D = date


def lauf(verein, kasse, konto_ids=None, jahr=2026, **betraege):
    werte = {St[k.upper()]: ct(v) for k, v in betraege.items()}
    return bh.beitraege_abbuchen(verein.s, werte, jahr, kasse.id, "Jahresbeitrag", konto_ids=konto_ids)


class TestNeueStatus:
    def test_anzeige(self):
        assert St.FOERDER.anzeige == "Fördermitglied (FM)"
        assert St.EHREN.anzeige == "Ehrenmitglied (EM)"
        assert (St.FOERDER.mehrzahl, St.EHREN.mehrzahl) == ("Fördermitglieder", "Ehrenmitglieder")

    def test_naechster_status(self):
        assert St.FUX.naechster == St.AKTIVER
        assert St.AKTIVER.naechster == St.ALUMNI
        assert St.ALUMNI.naechster == St.ALUMNI
        assert St.FOERDER.naechster == St.FOERDER
        assert St.EHREN.naechster == St.EHREN

    def test_beitragslauf_mit_allen_status(self, verein):
        kasse = verein.kasse("Beitragskasse")
        m = {s: verein.mitglied(f"Mitglied {s.value}", s) for s in St}
        gebucht = lauf(verein, kasse, fux="30", aktiver="60", alumni="100", foerder="50", ehren="10")
        assert len(gebucht) == 5
        assert verein.saldo(m[St.FOERDER]) == ct(-50)
        assert verein.saldo(m[St.EHREN]) == ct(-10)
        verein.pruefe_abstimmung()

    def test_ehrenmitglieder_beitragsfrei(self, verein):
        kasse = verein.kasse("Beitragskasse")
        em = verein.mitglied("Ehre", St.EHREN)
        verein.mitglied("Aktiv", St.AKTIVER)
        gebucht = lauf(verein, kasse, aktiver="60", ehren="0")
        assert len(gebucht) == 1
        assert verein.saldo(em) == 0

    def test_wechsel_zu_foerdermitglied(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom", St.ALUMNI, eintritt=D(2010, 1, 1))
        bh.status_wechseln(session, tom.id, St.FOERDER, D(2025, 6, 1))
        lauf(verein, kasse, jahr=2025, alumni="100", foerder="50")
        lauf(verein, kasse, jahr=2026, alumni="100", foerder="50")
        assert verein.saldo(tom) == ct(-150)  # 2025 noch Alumni, 2026 Fördermitglied

    def test_konto_mit_neuem_status_anlegen(self, verein):
        assert verein.mitglied("Gönner", St.FOERDER).status == St.FOERDER


class TestManuelleAuswahl:
    @pytest.fixture
    def setup(self, verein):
        kasse = verein.kasse("Beitragskasse")
        return {
            "kasse": kasse,
            "alt": verein.mitglied("Alt", St.AKTIVER, eintritt=D(2020, 1, 1)),
            "neu": verein.mitglied("Neu", St.FUX, eintritt=D(2026, 1, 2)),  # einen Tag zu spät
            "ohne": verein.mitglied("Ohne", St.AKTIVER, eintritt=None),
        }

    def test_vorschau_listet_waehlbare(self, verein, setup):
        v = bh.beitrag_vorschau(verein.s, {St.FUX: 3000, St.AKTIVER: 6000}, 2026)
        assert [m.name for m, _ in v.faellig] == ["Alt"]
        assert [m.name for m in v.zusaetzlich_waehlbar] == ["Neu", "Ohne"]
        assert v.betrag_je_konto[setup["neu"].id] == 3000

    def test_ohne_auswahl_nur_faellige(self, verein, setup):
        gebucht = lauf(verein, setup["kasse"], fux="30", aktiver="60")
        assert [b.soll_konto_id for b in gebucht] == [setup["alt"].id]

    def test_spaeter_eingetretenen_dazunehmen(self, verein, setup):
        ids = [setup["alt"].id, setup["neu"].id]
        gebucht = lauf(verein, setup["kasse"], konto_ids=ids, fux="30", aktiver="60")
        assert sorted(b.soll_konto_id for b in gebucht) == sorted(ids)
        assert verein.saldo(setup["neu"]) == ct(-30)
        assert all(b.beitragsjahr == 2026 for b in gebucht)

    def test_ohne_eintrittsdatum_dazunehmen(self, verein, setup):
        lauf(verein, setup["kasse"], konto_ids=[setup["ohne"].id], aktiver="60")
        assert verein.saldo(setup["ohne"]) == ct(-60)
        assert verein.saldo(setup["alt"]) == 0  # nicht ausgewählt

    def test_faelligen_abwaehlen(self, verein, setup):
        with pytest.raises(bh.BuchhaltungsFehler, match="keine Mitglieder"):
            lauf(verein, setup["kasse"], konto_ids=[], aktiver="60")

    def test_doppelschutz_auch_bei_auswahl(self, verein, setup):
        lauf(verein, setup["kasse"], aktiver="60")
        with pytest.raises(bh.BuchhaltungsFehler, match="Bereits für 2026 abgebucht: Alt"):
            lauf(verein, setup["kasse"], konto_ids=[setup["alt"].id], aktiver="60")
        assert verein.saldo(setup["alt"]) == ct(-60)

    def test_nachtraeglich_dazunehmen(self, verein, setup):
        """Erst normaler Lauf, später den neuen Fux für dasselbe Jahr nachbuchen."""
        lauf(verein, setup["kasse"], fux="30", aktiver="60")
        lauf(verein, setup["kasse"], konto_ids=[setup["neu"].id], fux="30", aktiver="60")
        v = bh.beitrag_vorschau(verein.s, {St.FUX: 3000, St.AKTIVER: 6000}, 2026)
        assert {m.name for m in v.bereits_abgebucht} == {"Alt", "Neu"}

    @pytest.mark.parametrize("grund", ["inaktiv", "kasse", "ohne_betrag"])
    def test_nicht_waehlbar(self, verein, setup, grund):
        if grund == "inaktiv":
            setup["alt"].aktiv = False
            konto = setup["alt"]
        elif grund == "kasse":
            konto = setup["kasse"]
        else:
            konto = verein.mitglied("Ehre", St.EHREN)
        with pytest.raises(bh.BuchhaltungsFehler, match="kann kein Beitrag"):
            lauf(verein, setup["kasse"], konto_ids=[konto.id], fux="30", aktiver="60")
        assert bh.buchungen(verein.s) == []  # nichts gebucht
