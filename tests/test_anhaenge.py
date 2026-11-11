"""Rechnungen (Bilder/PDFs) an Buchungen: Prüfen, Verkleinern, Speichern, Korrektur, Löschen, Oberfläche."""

from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage, QImageReader
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from dikas import anhaenge as an
from dikas import buchhaltung as bh
from dikas import sicherung
from dikas.db import erstelle_engine, init_db
from dikas.db.models import Anhang, Buchung, Buchungsart as Art
from dikas.ui.anhaenge_dialog import AnhaengeDialog
from dikas.ui.dialoge import BuchungDialog
from dikas.ui.hauptfenster import Hauptfenster

from conftest import Verein

PDF_DATEN = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def bild(breite: int, hoehe: int, format_: str = "JPG", alpha: bool = False) -> bytes:
    img = QImage(breite, hoehe, QImage.Format_ARGB32 if alpha else QImage.Format_RGB32)
    img.fill(QColor(0, 0, 0, 0) if alpha else QColor("#3366aa"))
    daten = QByteArray()
    puffer = QBuffer(daten)
    puffer.open(QIODevice.WriteOnly)
    assert img.save(puffer, format_)
    return bytes(daten.data())


def bildgroesse(daten: bytes) -> tuple[int, int]:
    puffer = QBuffer()
    puffer.setData(QByteArray(daten))
    puffer.open(QIODevice.ReadOnly)
    img = QImageReader(puffer).read()
    return img.width(), img.height()


def pdf_datei(name="Rechnung.pdf") -> an.Datei:
    return an.Datei(name, an.PDF, PDF_DATEN)


@pytest.fixture
def ausgabe(verein):
    kasse = verein.kasse("Getränkekasse")
    return verein.ausgabe(kasse, "35,90", "Einkauf Getränke", datum=date(2026, 3, 4))


# --- Datei prüfen und vorbereiten ------------------------------------------

class TestVorbereiten:
    def test_pdf_bleibt_unveraendert(self):
        d = an.vorbereiten("Rechnung März.pdf", PDF_DATEN)
        assert d == an.Datei("Rechnung März.pdf", an.PDF, PDF_DATEN)

    def test_kleines_jpg_bleibt_unveraendert(self, app):
        daten = bild(800, 600)
        d = an.vorbereiten("foto.JPG", daten)
        assert (d.inhalt, d.mime_typ, d.dateiname) == (daten, "image/jpeg", "foto.JPG")

    def test_grosses_foto_wird_verkleinert(self, app):
        daten = bild(4000, 3000)
        d = an.vorbereiten("IMG_1234.jpg", daten)
        assert bildgroesse(d.inhalt) == (2000, 1500)
        assert d.mime_typ == "image/jpeg" and d.dateiname == "IMG_1234.jpg"

    def test_hochformat_wird_verkleinert(self, app):
        d = an.vorbereiten("scan.png", bild(1500, 3000, "PNG"))
        assert bildgroesse(d.inhalt) == (1000, 2000)
        assert d.dateiname == "scan.jpg" and d.mime_typ == "image/jpeg"

    def test_andere_bildformate_werden_jpg(self, app):
        d = an.vorbereiten("quittung.bmp", bild(300, 200, "BMP"))
        assert d.dateiname == "quittung.jpg" and d.mime_typ == "image/jpeg"
        assert bildgroesse(d.inhalt) == (300, 200)

    def test_transparenz_wird_weiss(self, app):
        d = an.vorbereiten("logo.png", bild(3000, 100, "PNG", alpha=True))
        puffer = QBuffer()
        puffer.setData(QByteArray(d.inhalt))
        puffer.open(QIODevice.ReadOnly)
        farbe = QImageReader(puffer).read().pixelColor(10, 10)
        assert farbe.lightness() > 240  # weiß statt schwarz

    @pytest.mark.parametrize("name, daten, meldung", [
        ("Foto.HEIC", b"x", "HEIC"),
        ("notiz.txt", b"hallo", "Nur PDFs und Bilder"),
        ("leer.pdf", b"", "leer"),
        ("falsch.pdf", b"<html>", "keine gültige PDF"),
        ("kaputt.jpg", b"kein bild", "nicht als Bild lesen"),
        ("kaputt.bmp", b"kein bild", "nicht als Bild lesen"),
    ])
    def test_abgelehnt(self, app, name, daten, meldung):
        with pytest.raises(an.AnhangFehler, match=meldung):
            an.vorbereiten(name, daten)

    def test_zu_grosses_pdf(self, monkeypatch):
        monkeypatch.setattr(an, "MAX_PDF", 10)
        with pytest.raises(an.AnhangFehler, match="zu groß"):
            an.vorbereiten("gross.pdf", PDF_DATEN)

    def test_unerlaubte_zeichen_im_namen(self):
        assert an.vorbereiten('a:b*c?.pdf', PDF_DATEN).dateiname == "a_b_c_.pdf"
        assert an.vorbereiten("C:\\Pfad\\zu\\R.pdf", PDF_DATEN).dateiname == "R.pdf"

    def test_aus_datei(self, tmp_path):
        pfad = tmp_path / "R.pdf"
        pfad.write_bytes(PDF_DATEN)
        assert an.datei_vorbereiten(pfad).inhalt == PDF_DATEN
        with pytest.raises(an.AnhangFehler, match="kann nicht gelesen werden"):
            an.datei_vorbereiten(tmp_path / "fehlt.pdf")

    @pytest.mark.parametrize("byte, text", [(500, "500 Byte"), (2048, "2 KB"), (3_500_000, "3,3 MB")])
    def test_groesse_text(self, byte, text):
        assert an.groesse_text(byte) == text


# --- Speichern an Buchungen ---------------------------------------------------

class TestAnBuchung:
    def test_anhaengen_und_lesen(self, session, ausgabe):
        an.anhaengen(session, ausgabe.id, pdf_datei())
        an.anhaengen(session, ausgabe.id, pdf_datei("Kassenbon.pdf"))
        session.commit()
        session.expire_all()
        b = session.get(Buchung, ausgabe.id)
        assert [a.dateiname for a in b.anhaenge] == ["Rechnung.pdf", "Kassenbon.pdf"]
        assert b.anhaenge[0].groesse == len(PDF_DATEN)
        assert b.anhaenge[0].inhalt == PDF_DATEN

    def test_liste_laedt_keine_dateiinhalte(self, session, ausgabe):
        an.anhaengen(session, ausgabe.id, pdf_datei())
        session.commit()
        session.expire_all()
        b = next(b for b in bh.buchungen(session) if b.id == ausgabe.id)
        assert len(b.anhaenge) == 1
        assert "inhalt" in inspect(b.anhaenge[0]).unloaded  # erst bei Bedarf

    def test_nicht_an_stornobuchung(self, session, verein, ausgabe):
        storno = verein.storno(ausgabe)
        with pytest.raises(an.AnhangFehler, match="Stornobuchung"):
            an.anhaengen(session, storno.id, pdf_datei())
        # an die stornierte Originalbuchung aber schon
        an.anhaengen(session, ausgabe.id, pdf_datei())

    def test_unbekannte_buchung(self, session):
        with pytest.raises(bh.BuchhaltungsFehler, match="existiert nicht"):
            an.anhaengen(session, 999, pdf_datei())

    def test_entfernen(self, session, ausgabe):
        a = an.anhaengen(session, ausgabe.id, pdf_datei())
        an.entfernen(session, a.id)
        assert session.get(Buchung, ausgabe.id).anhaenge == []
        with pytest.raises(bh.BuchhaltungsFehler, match="existiert nicht mehr"):
            an.entfernen(session, a.id)

    def test_speichern_unter(self, session, ausgabe, tmp_path):
        a = an.anhaengen(session, ausgabe.id, pdf_datei())
        assert an.speichern_unter(session, a.id, tmp_path / "x.pdf").read_bytes() == PDF_DATEN

    def test_loeschen_der_buchung_nimmt_rechnungen_mit(self, session, ausgabe):
        an.anhaengen(session, ausgabe.id, pdf_datei())
        bh.buchungen_loeschen(session, [ausgabe.id])
        assert session.scalar(select(func.count()).select_from(Anhang)) == 0

    def test_korrektur_mit_neubuchung_nimmt_rechnungen_mit(self, session, ausgabe):
        an.anhaengen(session, ausgabe.id, pdf_datei())
        werte = bh.eingabe_aus_buchung(ausgabe) | {"betrag_cent": 3950}
        neu = bh.buchung_korrigieren(session, ausgabe.id, **werte)
        assert neu.id != ausgabe.id
        assert [a.dateiname for a in neu.anhaenge] == ["Rechnung.pdf"]
        assert ausgabe.anhaenge == []

    def test_textkorrektur_behaelt_rechnungen(self, session, ausgabe):
        an.anhaengen(session, ausgabe.id, pdf_datei())
        werte = bh.eingabe_aus_buchung(ausgabe) | {"text": "Getränke Metro"}
        neu = bh.buchung_korrigieren(session, ausgabe.id, **werte)
        assert neu.id == ausgabe.id and len(neu.anhaenge) == 1

    def test_kommt_in_sicherung_und_export_mit(self, tmp_path):
        pfad = tmp_path / "verein.db"
        engine = erstelle_engine(pfad)
        init_db(engine)
        with Session(engine) as s, s.begin():
            v = Verein(s)
            b = v.ausgabe(v.kasse("Kasse"), "5", "Kauf")
            an.anhaengen(s, b.id, pdf_datei())
        engine.dispose()
        kopie = tmp_path / "kopie.db"
        sicherung.kopiere_datenbank(pfad, kopie)
        engine2 = erstelle_engine(kopie)
        with Session(engine2) as s:
            assert s.scalars(select(Anhang)).one().inhalt == PDF_DATEN
        engine2.dispose()

    def test_bestehende_datenbank_bekommt_tabelle(self, tmp_path):
        """Alte verein.db ohne Tabelle `anhaenge`: wird beim Start ergänzt, Daten bleiben."""
        import sqlite3
        pfad = tmp_path / "alt.db"
        engine = erstelle_engine(pfad)
        init_db(engine)
        with Session(engine) as s, s.begin():
            v = Verein(s)
            v.ausgabe(v.kasse("Kasse"), "5", "Kauf")
        engine.dispose()
        with sqlite3.connect(pfad) as con:
            con.execute("DROP TABLE anhaenge")
        con.close()
        engine = erstelle_engine(pfad)
        init_db(engine)
        with Session(engine) as s:
            b = s.scalars(select(Buchung)).one()
            assert b.text == "Kauf" and b.anhaenge == []
        engine.dispose()


class TestAnsehen:
    def test_zum_ansehen_und_aufraeumen(self, session, ausgabe, tmp_path):
        a = an.anhaengen(session, ausgabe.id, pdf_datei("R:1.pdf"))
        ordner = tmp_path / "ansicht"
        pfad = an.zum_ansehen(session, a.id, ordner)
        assert pfad.read_bytes() == PDF_DATEN and pfad.name == f"{a.id}_R_1.pdf"
        assert an.zum_ansehen(session, a.id, ordner) == pfad  # zweites Mal: dieselbe Datei
        an.ansichten_aufraeumen(ordner)
        assert not ordner.exists()


# --- Oberfläche ------------------------------------------------------------

@pytest.fixture
def meldungen(monkeypatch):
    liste = []
    for name in ("warning", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, n=name: liste.append((n, a[2])))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.Yes)
    return liste


@pytest.fixture
def Sitzung(engine):
    with Session(engine) as s, s.begin():
        v = Verein(s)
        v.ausgabe(v.kasse("Getränkekasse"), "35,90", "Einkauf", datum=date(2026, 3, 4))
    return sessionmaker(engine, expire_on_commit=False)


def buchung_id(Sitzung) -> int:
    with Sitzung() as s:
        return s.scalars(select(Buchung.id)).one()


def rechnungen(Sitzung) -> list[str]:
    with Sitzung() as s:
        return [a.dateiname for a in s.scalars(select(Anhang).order_by(Anhang.id))]


@pytest.fixture
def dateien(tmp_path) -> dict[str, Path]:
    pfade = {"pdf": tmp_path / "Rechnung.pdf", "txt": tmp_path / "notiz.txt"}
    pfade["pdf"].write_bytes(PDF_DATEN)
    pfade["txt"].write_text("hallo")
    return pfade


class TestAnhaengeDialog:
    def test_anhaengen_oeffnen_entfernen(self, app, Sitzung, dateien, meldungen, tmp_path, monkeypatch):
        monkeypatch.setattr(an, "ansichtsordner", lambda: tmp_path / "ansicht")
        geoeffnet = []
        d = AnhaengeDialog(Sitzung, buchung_id(Sitzung), waehler=lambda _: [str(dateien["pdf"])],
                           oeffner=geoeffnet.append)
        assert d.tabelle.rowCount() == 0 and not d.oeffnen_knopf.isEnabled()
        assert "Einkauf" in d.kopf.text()

        d.hinzufuegen()
        assert d.geaendert and rechnungen(Sitzung) == ["Rechnung.pdf"]
        assert d.tabelle.item(0, 0).text() == "Rechnung.pdf"

        d.oeffnen()
        assert Path(geoeffnet[0].toLocalFile()).read_bytes() == PDF_DATEN

        d.entfernen()
        assert rechnungen(Sitzung) == [] and d.tabelle.rowCount() == 0

    def test_falsche_datei_wird_gemeldet(self, app, Sitzung, dateien, meldungen):
        d = AnhaengeDialog(Sitzung, buchung_id(Sitzung), waehler=lambda _: [str(dateien["txt"]), str(dateien["pdf"])])
        d.hinzufuegen()
        assert meldungen[-1][0] == "warning" and "notiz.txt" in meldungen[-1][1]
        assert rechnungen(Sitzung) == ["Rechnung.pdf"]  # die passende wird trotzdem angehängt

    def test_abbrechen_im_dateiwaehler(self, app, Sitzung):
        d = AnhaengeDialog(Sitzung, buchung_id(Sitzung), waehler=lambda _: [])
        d.hinzufuegen()
        assert not d.geaendert

    def test_stornobuchung_ohne_hinzufuegen(self, app, Sitzung):
        with Sitzung.begin() as s:
            storno = bh.stornieren(s, buchung_id_aus(s))
        d = AnhaengeDialog(Sitzung, storno.id)
        assert not d.hinzu_knopf.isEnabled()


def buchung_id_aus(s) -> int:
    return s.scalars(select(Buchung.id).where(Buchung.storno_von_id.is_(None))).first()


class TestBuchungDialog:
    def test_neue_buchung_mit_rechnung(self, app, Sitzung, dateien, meldungen):
        with Sitzung() as s:
            konten = bh.konten(s, nur_aktive=True)
        d = BuchungDialog(konten)
        assert d.rechnungen is not None
        d.rechnungen.waehler = lambda _: [str(dateien["pdf"])]
        d.rechnungen.hinzufuegen()
        assert [x.dateiname for x in d.dateien()] == ["Rechnung.pdf"]
        d.rechnungen.liste.item(0).setSelected(True)
        d.rechnungen.entfernen()
        assert d.dateien() == []

    def test_korrektur_ohne_dateiauswahl(self, app, Sitzung):
        with Sitzung() as s:
            konten = bh.konten(s, nur_aktive=True)
            vorlage = bh.eingabe_aus_buchung(s.get(Buchung, buchung_id(Sitzung)))
        d = BuchungDialog(konten, vorlage=vorlage)
        assert d.rechnungen is None and d.dateien() == []


class TestHauptfenster:
    @pytest.fixture
    def fenster(self, app, Sitzung, meldungen):
        w = Hauptfenster(Sitzung, "test")
        yield w
        w.close()

    def test_neue_buchung_speichert_rechnungen(self, fenster, Sitzung, dateien, monkeypatch):
        def ausfuellen(dialog):
            dialog.art.setCurrentIndex(dialog.art.findData(Art.KASSE_AUSGABE))
            dialog.betrag.setText("12,00")
            dialog.text.setText("Putzmittel")
            dialog.rechnungen.dateien_dazu([dateien["pdf"]])
            dialog._pruefen()
            return dialog.result()

        monkeypatch.setattr(BuchungDialog, "exec", ausfuellen)
        fenster.neue_buchung()
        with Sitzung() as s:
            neu = s.scalars(select(Buchung).where(Buchung.text == "Putzmittel")).one()
            assert [a.dateiname for a in neu.anhaenge] == ["Rechnung.pdf"]

    def test_bueroklammer_in_der_liste(self, fenster, Sitzung):
        with Sitzung.begin() as s:
            an.anhaengen(s, buchung_id(Sitzung), pdf_datei())
        fenster.aktualisieren()
        beleg = fenster.buchungen_tabelle.item(0, 2)
        assert "Rechnung.pdf" in beleg.toolTip()

    def test_rechnungen_knopf_braucht_genau_eine_buchung(self, fenster, meldungen, monkeypatch):
        geoeffnet = []
        monkeypatch.setattr(AnhaengeDialog, "exec", lambda d: geoeffnet.append(d.buchung_id) or QDialog.Accepted)
        fenster.buchungen_tabelle.clearSelection()
        fenster.rechnungen_auswahl()
        assert "auswählen" in meldungen[-1][1] and geoeffnet == []
        fenster.buchungen_tabelle.selectRow(0)
        fenster.rechnungen_auswahl()
        assert len(geoeffnet) == 1
