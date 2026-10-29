from datetime import date

import pytest

from dikas import buchhaltung as bh
from dikas.db.models import Buchungsart as Art, KontoTyp, MitgliedStatus as St


@pytest.fixture
def konten(session):
    """KW, zwei Kassen und je ein Mitglied pro Status."""
    return {
        "kw": bh.kw_konto(session),
        "beitrag": bh.konto_anlegen(session, "Beitragskasse", KontoTyp.KASSE),
        "getraenke": bh.konto_anlegen(session, "Getränkekasse", KontoTyp.KASSE),
        "tom": bh.konto_anlegen(session, "Tom", KontoTyp.PRIVAT, St.AKTIVER),
        "fritz": bh.konto_anlegen(session, "Fritz", KontoTyp.PRIVAT, St.FUX),
        "alfred": bh.konto_anlegen(session, "Alfred", KontoTyp.PRIVAT, St.ALUMNI),
    }


def assert_abstimmung(session):
    a = bh.abstimmung(session)
    assert a.stimmt, a


# --- Konten ---------------------------------------------------------------

def test_kw_konto_wird_automatisch_angelegt(session):
    assert bh.kw_konto(session).typ == KontoTyp.KW


def test_kein_zweites_kw_konto(session):
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.konto_anlegen(session, "KW 2", KontoTyp.KW)


def test_doppelter_kontoname_verboten(session):
    bh.konto_anlegen(session, "Max", KontoTyp.PRIVAT, St.FUX)
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.konto_anlegen(session, "Max", KontoTyp.PRIVAT, St.AKTIVER)
    # Gleicher Name bei anderem Typ ist erlaubt
    bh.konto_anlegen(session, "Max", KontoTyp.KASSE)


def test_status_nur_bei_privatkonten(session):
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.konto_anlegen(session, "Max", KontoTyp.PRIVAT)
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.konto_anlegen(session, "Kasse", KontoTyp.KASSE, St.FUX)


def test_konto_bearbeiten(session, konten):
    fritz = konten["fritz"]
    bh.konto_bearbeiten(session, fritz.id, "Fritz B.", St.AKTIVER, "geburscht", True)
    assert (fritz.name, fritz.status, fritz.bemerkung) == ("Fritz B.", St.AKTIVER, "geburscht")
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.konto_bearbeiten(session, fritz.id, "Tom", St.AKTIVER, "", True)
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.konto_bearbeiten(session, konten["kw"].id, "KW", None, "", False)


# --- Buchungsarten --------------------------------------------------------

@pytest.mark.parametrize(
    "art, konto, gegen, erwartet",
    [
        # Tom überweist 10 €: Privatkonto UND KW steigen
        (Art.EINZAHLUNG, "tom", None, {"tom": 1000, "kw": 1000}),
        (Art.AUSZAHLUNG, "tom", None, {"tom": -1000, "kw": -1000}),
        (Art.KASSE_EINNAHME, "getraenke", None, {"getraenke": 1000, "kw": 1000}),
        (Art.KASSE_AUSGABE, "getraenke", None, {"getraenke": -1000, "kw": -1000}),
        (Art.UMBUCHUNG, "tom", "getraenke", {"tom": -1000, "getraenke": 1000}),
        (Art.UMBUCHUNG, "getraenke", "beitrag", {"getraenke": -1000, "beitrag": 1000}),
        (Art.BEITRAG, "tom", "beitrag", {"tom": -1000, "beitrag": 1000}),
    ],
)
def test_wirkung_der_buchungsarten(session, konten, art, konto, gegen, erwartet):
    gegen_id = konten[gegen].id if gegen else None
    b = bh.buchen(session, art, konten[konto].id, 1000, "Test", gegenkonto_id=gegen_id)

    salden = bh.salden(session)
    for name, k in konten.items():
        assert salden[k.id] == erwartet.get(name, 0), name
        assert b.wirkung_auf(k) == erwartet.get(name, 0), name
    assert_abstimmung(session)


@pytest.mark.parametrize(
    "art, konto, gegen",
    [
        (Art.EINZAHLUNG, "getraenke", None),  # Einzahlung nur für Mitglieder
        (Art.KASSE_EINNAHME, "tom", None),  # Kassen-Einnahme nur für Kassen
        (Art.EINZAHLUNG, "kw", None),
        (Art.UMBUCHUNG, "tom", None),  # Gegenkonto fehlt
        (Art.UMBUCHUNG, "tom", "tom"),
        (Art.UMBUCHUNG, "tom", "kw"),  # KW nie direkt umbuchen
        (Art.BEITRAG, "tom", "fritz"),  # Beitrag nur auf Kasse
        (Art.STORNO, "tom", None),  # Storno nur über stornieren()
    ],
)
def test_unzulaessige_konten(session, konten, art, konto, gegen):
    gegen_id = konten[gegen].id if gegen else None
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.buchen(session, art, konten[konto].id, 1000, "Test", gegenkonto_id=gegen_id)


@pytest.mark.parametrize("betrag, text", [(0, "x"), (-5, "x"), (100, "  ")])
def test_ungueltige_eingaben(session, konten, betrag, text):
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.buchen(session, Art.EINZAHLUNG, konten["tom"].id, betrag, text)


def test_buchung_auf_deaktiviertes_konto(session, konten):
    konten["tom"].aktiv = False
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.buchen(session, Art.EINZAHLUNG, konten["tom"].id, 100, "Test")


def test_typischer_ablauf(session, konten):
    tom, kw, beitrag = konten["tom"], konten["kw"], konten["beitrag"]
    bh.buchen(session, Art.BEITRAG, tom.id, 5000, "Jahresbeitrag", gegenkonto_id=beitrag.id)
    bh.buchen(session, Art.EINZAHLUNG, tom.id, 5000, "Überweisung Tom", date(2026, 11, 2))
    bh.buchen(session, Art.KASSE_AUSGABE, beitrag.id, 1200, "Druckkosten")

    assert bh.saldo(session, tom.id) == 0  # Beitrag beglichen
    assert bh.saldo(session, beitrag.id) == 3800
    assert bh.saldo(session, kw.id) == 3800
    assert_abstimmung(session)


# --- Storno ---------------------------------------------------------------

def test_storno(session, konten):
    tom, kw = konten["tom"], konten["kw"]
    b = bh.buchen(session, Art.EINZAHLUNG, tom.id, 1000, "Einzahlung")

    storno = bh.stornieren(session, b.id)

    assert storno.art == Art.STORNO and storno.storno_von_id == b.id
    assert b.ist_storniert and storno.ist_storno
    assert bh.saldo(session, kw.id) == 0
    assert bh.saldo(session, tom.id) == 0
    assert_abstimmung(session)
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.stornieren(session, b.id)
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.stornieren(session, storno.id)


def test_buchungen_filter(session, konten):
    tom, fritz, kw = konten["tom"], konten["fritz"], konten["kw"]
    bh.buchen(session, Art.EINZAHLUNG, tom.id, 100, "a")
    bh.buchen(session, Art.EINZAHLUNG, fritz.id, 200, "b")

    assert len(bh.buchungen(session)) == 2
    assert [x.text for x in bh.buchungen(session, tom.id)] == ["a"]
    assert len(bh.buchungen(session, kw.id)) == 2


# --- Beitragslauf ---------------------------------------------------------

def test_beitraege_abbuchen(session, konten):
    bh.konto_anlegen(session, "Ehemalig", KontoTyp.PRIVAT, St.AKTIVER).aktiv = False
    betraege = {St.FUX: 3000, St.AKTIVER: 6000, St.ALUMNI: 0}

    vorschau = bh.beitrag_vorschau(session, betraege)
    assert sorted((k.name, c) for k, c in vorschau) == [("Fritz", 3000), ("Tom", 6000)]

    gebucht = bh.beitraege_abbuchen(
        session, betraege, konten["beitrag"].id, "Jahresbeitrag 2026", date(2026, 11, 1)
    )

    assert len(gebucht) == 2
    assert all(b.art == Art.BEITRAG for b in gebucht)
    salden = bh.salden(session)
    assert salden[konten["fritz"].id] == -3000
    assert salden[konten["tom"].id] == -6000
    assert salden[konten["alfred"].id] == 0
    assert salden[konten["beitrag"].id] == 9000
    assert salden[konten["kw"].id] == 0  # es ist noch kein Geld geflossen
    assert_abstimmung(session)


def test_beitraege_ohne_faellige_mitglieder(session, konten):
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.beitraege_abbuchen(session, {}, konten["beitrag"].id, "Beitrag")


def test_beitraege_nur_auf_kasse(session, konten):
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.beitraege_abbuchen(session, {St.FUX: 100}, konten["kw"].id, "Beitrag")
