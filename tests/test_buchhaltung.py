from datetime import date

import pytest

from dikas import buchhaltung as bh
from dikas.db.models import KontoTyp


def test_kw_konto_wird_automatisch_angelegt(session):
    kw = bh.kw_konto(session)
    assert kw.typ == KontoTyp.KW


def test_kein_zweites_kw_konto(session):
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.konto_anlegen(session, "KW 2", KontoTyp.KW)


def test_doppelter_kontoname_verboten(session):
    bh.konto_anlegen(session, "Max", KontoTyp.PRIVAT)
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.konto_anlegen(session, "Max", KontoTyp.PRIVAT)
    # Gleicher Name bei anderem Typ ist erlaubt
    bh.konto_anlegen(session, "Max", KontoTyp.KASSE)


def test_buchung_veraendert_salden(session):
    kw = bh.kw_konto(session)
    kasse = bh.konto_anlegen(session, "Getränkekasse", KontoTyp.KASSE)
    max_ = bh.konto_anlegen(session, "Max", KontoTyp.PRIVAT)

    bh.buchen(session, kasse.id, kw.id, 5000, "Bargeld eingezahlt", date(2026, 10, 1))
    bh.buchen(session, max_.id, kasse.id, 350, "2 Getränke")

    salden = bh.salden(session)
    assert salden[kw.id] == 5000
    assert salden[kasse.id] == -5000 + 350
    assert salden[max_.id] == -350
    assert sum(salden.values()) == 0  # doppelte Buchführung: Summe immer 0
    for konto_id, wert in salden.items():
        assert bh.saldo(session, konto_id) == wert


@pytest.mark.parametrize(
    "betrag, text, gleich",
    [(0, "x", False), (-5, "x", False), (100, "  ", False), (100, "x", True)],
)
def test_ungueltige_buchungen(session, betrag, text, gleich):
    kw = bh.kw_konto(session)
    kasse = bh.konto_anlegen(session, "Kasse", KontoTyp.KASSE)
    nach = kw.id if gleich else kasse.id
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.buchen(session, kw.id, nach, betrag, text)


def test_buchung_auf_deaktiviertes_konto(session):
    kw = bh.kw_konto(session)
    kasse = bh.konto_anlegen(session, "Alt", KontoTyp.KASSE)
    kasse.aktiv = False
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.buchen(session, kw.id, kasse.id, 100, "Test")


def test_storno(session):
    kw = bh.kw_konto(session)
    kasse = bh.konto_anlegen(session, "Kasse", KontoTyp.KASSE)
    b = bh.buchen(session, kasse.id, kw.id, 1000, "Einzahlung")

    storno = bh.stornieren(session, b.id)

    assert storno.storno_von_id == b.id
    assert b.ist_storniert and storno.ist_storno
    assert bh.saldo(session, kw.id) == 0
    assert bh.saldo(session, kasse.id) == 0
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.stornieren(session, b.id)
    with pytest.raises(bh.BuchhaltungsFehler):
        bh.stornieren(session, storno.id)


def test_buchungen_filter(session):
    kw = bh.kw_konto(session)
    a = bh.konto_anlegen(session, "A", KontoTyp.PRIVAT)
    b = bh.konto_anlegen(session, "B", KontoTyp.PRIVAT)
    bh.buchen(session, a.id, kw.id, 100, "a")
    bh.buchen(session, b.id, kw.id, 200, "b")

    assert len(bh.buchungen(session)) == 2
    assert [x.text for x in bh.buchungen(session, a.id)] == ["a"]
    assert len(bh.buchungen(session, kw.id)) == 2
