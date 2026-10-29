"""Auswertung über einen Zeitraum: Logik, Dialog und PDF-Export."""

from datetime import date

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from sqlalchemy.orm import Session, sessionmaker

from dikas import buchhaltung as bh
from dikas.db.models import Buchungsart as Art, KontoTyp, MitgliedStatus as St
from dikas.ui.auswertung import AuswertungDialog, als_html, speichere_pdf, zeitraum_vorlage

from conftest import Verein, ct

D = date


@pytest.fixture
def jahr(verein):
    """Zwei Vereinsjahre mit Buchungen vor, im und nach dem Auswertungszeitraum 2026."""
    v = verein
    k = {
        "beitrag": v.kasse("Beitragskasse"),
        "getraenke": v.kasse("Getränkekasse"),
        "leer": v.kasse("Unbenutzte Kasse"),
        "tom": v.mitglied("Tom"),
        "fritz": v.mitglied("Fritz", St.FUX),
        "alfred": v.mitglied("Alfred", St.ALUMNI),
    }
    # 2025: Vorjahr
    v.beitrag(k["tom"], k["beitrag"], "60", datum=D(2025, 1, 10))
    v.einzahlung(k["tom"], "60", datum=D(2025, 2, 1))
    v.einnahme(k["getraenke"], "100", datum=D(2025, 12, 31))
    # 2026: Auswertungsjahr
    v.beitrag(k["tom"], k["beitrag"], "60", datum=D(2026, 1, 1))
    v.beitrag(k["fritz"], k["beitrag"], "30", datum=D(2026, 1, 1))
    v.einzahlung(k["tom"], "100", datum=D(2026, 3, 15))
    v.ausgabe(k["getraenke"], "40", datum=D(2026, 6, 1))
    v.umbuchung(k["fritz"], k["getraenke"], "12,50", datum=D(2026, 6, 2))
    falsch = v.einzahlung(k["alfred"], "500", "Tippfehler", datum=D(2026, 7, 1))
    bh.stornieren(v.s, falsch.id, D(2026, 7, 1))
    v.auszahlung(k["tom"], "40", datum=D(2026, 12, 31))
    # 2027: nach dem Zeitraum
    v.einzahlung(k["fritz"], "42,50", datum=D(2027, 1, 1))
    return k


def bewegung(session, konto, von=D(2026, 1, 1), bis=D(2026, 12, 31)):
    return next(b for b in bh.kontobewegungen(session, von, bis) if b.konto.id == konto.id)


# --- Logik ----------------------------------------------------------------

class TestKontobewegungen:
    def test_kw_konto(self, session, verein, jahr):
        b = bewegung(session, verein.kw)
        assert b.anfang == ct(160)  # 60 Tom + 100 Getränke im Vorjahr
        assert b.zugang == ct(100) + ct(500)  # Tom + Tippfehler
        assert b.abgang == ct(40) + ct(500) + ct(40)  # Getränke, Storno, Auszahlung Tom
        assert b.ende == ct(180)

    def test_privatkonto(self, session, jahr):
        tom = bewegung(session, jahr["tom"])
        assert (tom.anfang, tom.zugang, tom.abgang, tom.ende) == (0, ct(100), ct(100), 0)
        fritz = bewegung(session, jahr["fritz"])
        assert (fritz.anfang, fritz.zugang, fritz.abgang, fritz.ende) == (0, 0, ct("42,50"), ct("-42,50"))

    def test_kasse(self, session, jahr):
        g = bewegung(session, jahr["getraenke"])
        assert (g.anfang, g.zugang, g.abgang, g.ende) == (ct(100), ct("12,50"), ct(40), ct("72,50"))

    def test_storno_im_zeitraum_hebt_sich_auf(self, session, jahr):
        a = bewegung(session, jahr["alfred"])
        assert a.zugang == a.abgang == ct(500)
        assert a.veraenderung == 0

    def test_konto_ohne_bewegung(self, session, jahr):
        assert not bewegung(session, jahr["leer"]).hat_werte

    def test_endbestand_entspricht_saldo_am_stichtag(self, session, jahr):
        """Ende eines Zeitraums = Saldo aller Buchungen bis einschließlich Enddatum."""
        for b in bh.kontobewegungen(session, D(2026, 1, 1), D(2026, 12, 31)):
            erwartet = sum(x.wirkung_auf(b.konto) for x in bh.buchungen(session, b.konto.id, bis=D(2026, 12, 31)))
            assert b.ende == erwartet, b.konto.name

    def test_ende_ist_anfang_des_folgezeitraums(self, session, jahr):
        h1 = {b.konto.id: b for b in bh.kontobewegungen(session, D(2026, 1, 1), D(2026, 6, 30))}
        h2 = {b.konto.id: b for b in bh.kontobewegungen(session, D(2026, 7, 1), D(2026, 12, 31))}
        ganz = {b.konto.id: b for b in bh.kontobewegungen(session, D(2026, 1, 1), D(2026, 12, 31))}
        for konto_id in ganz:
            assert h1[konto_id].ende == h2[konto_id].anfang
            assert h1[konto_id].zugang + h2[konto_id].zugang == ganz[konto_id].zugang
            assert h1[konto_id].abgang + h2[konto_id].abgang == ganz[konto_id].abgang

    def test_abstimmung_gilt_am_anfang_und_ende(self, session, jahr):
        for b_liste in (bh.kontobewegungen(session, D(2026, 1, 1), D(2026, 12, 31)),
                        bh.kontobewegungen(session, D(2026, 3, 1), D(2026, 3, 31))):
            kw = next(b for b in b_liste if b.konto.typ == KontoTyp.KW)
            rest = [b for b in b_liste if b.konto.typ != KontoTyp.KW]
            assert kw.anfang == sum(b.anfang for b in rest)
            assert kw.ende == sum(b.ende for b in rest)

    def test_grenzen_inklusive(self, session, verein):
        tom = verein.mitglied("Tom")
        verein.einzahlung(tom, "1", datum=D(2026, 1, 1))
        verein.einzahlung(tom, "2", datum=D(2026, 1, 31))
        b = bewegung(session, tom, D(2026, 1, 1), D(2026, 1, 31))
        assert (b.anfang, b.zugang) == (0, ct(3))

    def test_ein_tag(self, session, verein):
        tom = verein.mitglied("Tom")
        verein.einzahlung(tom, "1", datum=D(2026, 5, 4))
        verein.einzahlung(tom, "2", datum=D(2026, 5, 5))
        verein.einzahlung(tom, "4", datum=D(2026, 5, 6))
        b = bewegung(session, tom, D(2026, 5, 5), D(2026, 5, 5))
        assert (b.anfang, b.zugang, b.ende) == (ct(1), ct(2), ct(3))

    def test_zeitraum_vor_allen_buchungen(self, session, jahr):
        assert not any(b.hat_werte for b in bh.kontobewegungen(session, D(2000, 1, 1), D(2000, 12, 31)))

    def test_zeitraum_nach_allen_buchungen(self, session, jahr):
        for b in bh.kontobewegungen(session, D(2030, 1, 1), D(2030, 12, 31)):
            assert b.zugang == b.abgang == 0
            assert b.anfang == bh.saldo(session, b.konto.id)

    def test_falscher_zeitraum(self, session):
        with pytest.raises(bh.BuchhaltungsFehler, match="Startdatum"):
            bh.kontobewegungen(session, D(2026, 2, 1), D(2026, 1, 1))
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.summen_nach_art(session, D(2026, 2, 1), D(2026, 1, 1))

    def test_geloeschtes_konto_bleibt_in_auswertung(self, session, verein):
        tom = verein.mitglied("Tom")
        verein.einzahlung(tom, "10", datum=D(2026, 1, 1))
        verein.auszahlung(tom, "10", datum=D(2026, 2, 1))
        bh.konto_loeschen(session, tom.id)
        b = bewegung(session, tom)
        assert b.zugang == b.abgang == ct(10)


class TestSummenNachArt:
    def test_summen(self, session, jahr):
        arten = {a.art: (a.anzahl, a.summe) for a in bh.summen_nach_art(session, D(2026, 1, 1), D(2026, 12, 31))}
        assert arten == {
            Art.EINZAHLUNG: (2, ct(600)),
            Art.AUSZAHLUNG: (1, ct(40)),
            Art.KASSE_AUSGABE: (1, ct(40)),
            Art.UMBUCHUNG: (1, ct("12,50")),
            Art.BEITRAG: (2, ct(90)),
            Art.STORNO: (1, ct(500)),
        }

    def test_reihenfolge_wie_buchungsarten(self, session, jahr):
        arten = [a.art for a in bh.summen_nach_art(session, D(2026, 1, 1), D(2026, 12, 31))]
        assert arten == sorted(arten, key=list(Art).index)

    def test_leerer_zeitraum(self, session, jahr):
        assert bh.summen_nach_art(session, D(2000, 1, 1), D(2000, 1, 2)) == []


class TestBuchungenImZeitraum:
    def test_filter(self, session, jahr):
        assert len(bh.buchungen(session, von=D(2026, 1, 1), bis=D(2026, 12, 31))) == 8
        assert len(bh.buchungen(session, von=D(2027, 1, 1))) == 1
        assert len(bh.buchungen(session, bis=D(2025, 12, 31))) == 3
        assert len(bh.buchungen(session, jahr["tom"].id, D(2026, 1, 1), D(2026, 12, 31))) == 3


@pytest.mark.parametrize(
    "name, heute, erwartet",
    [
        ("Dieses Jahr", D(2026, 10, 29), (D(2026, 1, 1), D(2026, 12, 31))),
        ("Letztes Jahr", D(2026, 10, 29), (D(2025, 1, 1), D(2025, 12, 31))),
        ("Dieser Monat", D(2026, 10, 29), (D(2026, 10, 1), D(2026, 10, 31))),
        ("Dieser Monat", D(2028, 2, 10), (D(2028, 2, 1), D(2028, 2, 29))),  # Schaltjahr
        ("Dieser Monat", D(2026, 12, 31), (D(2026, 12, 1), D(2026, 12, 31))),
        ("Letzter Monat", D(2026, 10, 29), (D(2026, 9, 1), D(2026, 9, 30))),
        ("Letzter Monat", D(2026, 1, 15), (D(2025, 12, 1), D(2025, 12, 31))),
        ("Benutzerdefiniert", D(2026, 1, 1), None),
    ],
)
def test_zeitraum_vorlagen(name, heute, erwartet):
    assert zeitraum_vorlage(name, heute) == erwartet


# --- PDF ------------------------------------------------------------------

class TestPdf:
    def _html(self, session, von=D(2026, 1, 1), bis=D(2026, 12, 31)):
        return als_html(
            von, bis,
            [b for b in bh.kontobewegungen(session, von, bis) if b.hat_werte],
            bh.summen_nach_art(session, von, bis),
            bh.buchungen(session, von=von, bis=bis),
        )

    def test_html_inhalt(self, session, jahr):
        html = self._html(session)
        assert "Auswertung 01.01.2026 – 31.12.2026" in html
        for text in ("Summe Kassen", "Summe Privatkonten", "Getränkekasse", "Tippfehler", "72,50 €"):
            assert text in html
        assert "Summe KW" not in html  # nur ein KW-Konto, keine Summenzeile
        assert "Unbenutzte Kasse" not in html  # ohne Bewegung ausgeblendet

    def test_html_escaping(self, session, verein):
        tom = verein.mitglied("Tom <b>&</b>")
        verein.einzahlung(tom, "1", "<script>", datum=D(2026, 1, 1))
        html = self._html(session)
        assert "<script>" not in html and "&lt;script&gt;" in html

    def test_pdf_wird_erzeugt(self, app, session, jahr, tmp_path):
        pfad = tmp_path / "auswertung.pdf"
        speichere_pdf(self._html(session), pfad, "Test")
        inhalt = pfad.read_bytes()
        assert inhalt.startswith(b"%PDF") and len(inhalt) > 2000

    def test_pdf_mit_vielen_buchungen(self, app, session, verein, tmp_path):
        tom = verein.mitglied("Tom")
        for i in range(400):
            verein.einzahlung(tom, "1", f"Buchung {i}", datum=D(2026, 1, 1 + i % 28))
        pfad = tmp_path / "gross.pdf"
        speichere_pdf(self._html(session), pfad, "Test")
        assert pfad.read_bytes().count(b"/Type /Page") > 3  # mehrere Seiten


# --- Dialog ---------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app, engine, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    with Session(engine) as s, s.begin():
        jahr_daten(Verein(s))
    d = AuswertungDialog(sessionmaker(engine), heute=D(2026, 10, 29))
    yield d
    d.close()


def jahr_daten(v: Verein):
    kasse = v.kasse("Beitragskasse")
    leer = v.kasse("Leer")
    tom, fritz = v.mitglied("Tom"), v.mitglied("Fritz", St.FUX)
    v.einzahlung(tom, "100", datum=D(2025, 12, 1))
    v.beitrag(tom, kasse, "60", datum=D(2026, 1, 1))
    v.beitrag(fritz, kasse, "30", datum=D(2026, 1, 1))
    v.ausgabe(kasse, "20", datum=D(2026, 9, 15))
    v.einzahlung(fritz, "30", datum=D(2026, 10, 2))


def tabellen_text(tabelle, spalte=0):
    return [tabelle.item(r, spalte).text() for r in range(tabelle.rowCount())]


class TestDialog:
    def test_standard_dieses_jahr(self, dialog):
        assert dialog.vorlage.currentText() == "Dieses Jahr"
        assert dialog.zeitraum == (D(2026, 1, 1), D(2026, 12, 31))

    def test_kennzahlen(self, dialog):
        assert dialog.karte_anfang.wert.text() == "100,00 €"
        assert dialog.karte_einnahmen.wert.text() == "30,00 €"
        assert dialog.karte_ausgaben.wert.text() == "20,00 €"
        assert dialog.karte_ende.wert.text() == "110,00 €"

    def test_kontentabelle_mit_summen(self, dialog):
        namen = tabellen_text(dialog.konten_tabelle)
        assert namen == ["KW", "Beitragskasse", "Summe Kassen", "Fritz", "Tom", "Summe Privatkonten"]
        assert "Leer" not in namen

    def test_konten_ohne_bewegung(self, dialog):
        dialog.ohne_bewegung.setChecked(True)
        assert "Leer" in tabellen_text(dialog.konten_tabelle)

    def test_kontoart_filter(self, dialog):
        dialog.kontoart.setCurrentText("Füxe")
        assert tabellen_text(dialog.konten_tabelle) == ["Fritz", "Summe Privatkonten"]

    def test_abgaenge_negativ_angezeigt(self, dialog):
        t = dialog.konten_tabelle
        zeile = tabellen_text(t).index("Beitragskasse")
        assert t.item(zeile, 4).text() == "-20,00 €"
        assert t.item(zeile, 6).text() == "70,00 €"

    def test_vorlage_wechsel(self, dialog):
        dialog.vorlage.setCurrentText("Letztes Jahr")
        assert dialog.zeitraum == (D(2025, 1, 1), D(2025, 12, 31))
        assert dialog.karte_ende.wert.text() == "100,00 €"

    def test_eigenes_datum_wird_benutzerdefiniert(self, dialog):
        dialog.von.setDate(QDate(2026, 9, 1))
        assert dialog.vorlage.currentText() == "Benutzerdefiniert"
        assert dialog.karte_einnahmen.wert.text() == "30,00 €"
        assert dialog.karte_ausgaben.wert.text() == "20,00 €"

    def test_datum_passend_zu_vorlage(self, dialog):
        dialog.von.setDate(QDate(2026, 10, 1))
        dialog.bis.setDate(QDate(2026, 10, 31))
        assert dialog.vorlage.currentText() == "Dieser Monat"

    def test_falscher_zeitraum_zeigt_fehler(self, dialog):
        dialog.von.setDate(QDate(2027, 1, 1))
        assert dialog.fehler.isVisibleTo(dialog)
        assert dialog.konten_tabelle.rowCount() == 0
        dialog.von.setDate(QDate(2026, 1, 1))
        assert not dialog.fehler.isVisibleTo(dialog)

    def test_buchungsarten(self, dialog):
        assert tabellen_text(dialog.arten_tabelle) == ["Einzahlung", "Kassen-Ausgabe", "Beitrag", "Gesamt"]

    def test_buchungen_reiter_und_kontofilter(self, dialog):
        assert dialog.buchungen_tabelle.rowCount() == 4
        assert dialog.reiter.tabText(2) == "Buchungen (4)"
        dialog.buchungen_konto.setCurrentText("Fritz")
        assert dialog.buchungen_tabelle.rowCount() == 2
        dialog.vorlage.setCurrentText("Dieser Monat")  # Auswahl bleibt erhalten
        assert dialog.buchungen_konto.currentText() == "Fritz"
        assert dialog.buchungen_tabelle.rowCount() == 1

    def test_pdf_speichern(self, dialog, tmp_path, monkeypatch):
        ziel = tmp_path / "bericht.pdf"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(ziel), ""))
        dialog.pdf_speichern()
        assert ziel.read_bytes().startswith(b"%PDF")

    def test_pdf_abbrechen(self, dialog, tmp_path, monkeypatch):
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
        dialog.pdf_speichern()
        assert list(tmp_path.iterdir()) == []
