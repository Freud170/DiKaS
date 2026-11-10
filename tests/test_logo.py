"""Vereinslogo umwandeln (PNG + ICO); ohne Logo startet DiKaS trotzdem."""

import struct

import pytest
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from dikas import logo
from dikas.ui import stil


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bild(tmp_path):
    """Querformat 300×200, damit der Zuschnitt aufs mittige Quadrat greift."""
    pfad = tmp_path / "wappen.png"
    b = QImage(300, 200, QImage.Format_ARGB32)
    b.fill(QColor("red"))
    b.save(str(pfad))
    return pfad


@pytest.mark.parametrize("rund", [False, True])
def test_logo_erstellen(app, tmp_path, bild, rund):
    png, ico = logo.logo_erstellen(bild, rund, ziel=tmp_path)
    fenster = QImage(str(png))
    assert (fenster.width(), fenster.height()) == (256, 256)
    # Ecke ist nur beim runden Zuschnitt transparent
    assert (fenster.pixelColor(0, 0).alpha() == 0) == rund
    reserviert, typ, anzahl = struct.unpack("<HHH", ico.read_bytes()[:6])
    assert (reserviert, typ, anzahl) == (0, 1, len(logo.ICO_GROESSEN))


def test_kein_bild(app, tmp_path):
    kaputt = tmp_path / "kein_bild.png"
    kaputt.write_text("hallo")
    with pytest.raises(ValueError, match="nicht als Bild"):
        logo.logo_erstellen(kaputt, ziel=tmp_path)


def test_start_ohne_logo(app, monkeypatch, tmp_path):
    monkeypatch.setattr(stil, "LOGO", tmp_path / "fehlt.png")
    stil.anwenden(QGuiApplication.instance())  # darf nicht abstürzen
