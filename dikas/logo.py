"""Vereinslogo einbauen: Bild in Fenstersymbol (PNG) und Verknüpfungssymbol (ICO) umwandeln.

Aufruf:  python -m dikas.logo pfad\\zum\\bild.png [--rund]

Das Bild wird auf ein mittiges Quadrat zugeschnitten (mit --rund kreisförmig, außen
transparent) und als dikas/ui/logo.png und dikas/ui/logo.ico gespeichert. Ohne diese
Dateien startet DiKaS ganz normal, nur ohne eigenes Symbol.
"""

import argparse
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPainterPath

ZIEL = Path(__file__).parent / "ui"
ICO_GROESSEN = [16, 24, 32, 48, 64, 128, 256]


def zuschneiden(bild: QImage, rund: bool, seite: int = 512) -> QImage:
    """Mittiges Quadrat des Bildes, auf `seite` Pixel skaliert, optional kreisförmig."""
    kante = min(bild.width(), bild.height())
    quelle = QRectF((bild.width() - kante) / 2, (bild.height() - kante) / 2, kante, kante)
    ergebnis = QImage(seite, seite, QImage.Format_ARGB32)
    ergebnis.fill(Qt.transparent)
    maler = QPainter(ergebnis)
    maler.setRenderHint(QPainter.Antialiasing)
    maler.setRenderHint(QPainter.SmoothPixmapTransform)
    if rund:
        pfad = QPainterPath()
        pfad.addEllipse(QRectF(0, 0, seite, seite))
        maler.setClipPath(pfad)
    maler.drawImage(QRectF(0, 0, seite, seite), bild, quelle)
    maler.end()
    return ergebnis


def _png_daten(bild: QImage, groesse: int) -> bytes:
    daten = QByteArray()
    puffer = QBuffer(daten)
    puffer.open(QIODevice.WriteOnly)
    bild.scaled(groesse, groesse, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(puffer, "PNG")
    return bytes(daten)


def ico_speichern(bild: QImage, pfad: Path) -> None:
    """ICO mit mehreren Größen (Qt selbst schreibt nur eine), Einträge als PNG."""
    pngs = [_png_daten(bild, g) for g in ICO_GROESSEN]
    versatz = 6 + 16 * len(pngs)
    eintraege = b""
    for groesse, png in zip(ICO_GROESSEN, pngs):
        # Größe 256 wird im ICO-Format als 0 geschrieben
        eintraege += struct.pack("<BBBBHHII", groesse % 256, groesse % 256, 0, 0, 1, 32, len(png), versatz)
        versatz += len(png)
    pfad.write_bytes(struct.pack("<HHH", 0, 1, len(pngs)) + eintraege + b"".join(pngs))


def logo_erstellen(quelle: Path, rund: bool = False, ziel: Path = ZIEL) -> tuple[Path, Path]:
    bild = QImage(str(quelle))
    if bild.isNull():
        raise ValueError(f"„{quelle}“ konnte nicht als Bild gelesen werden.")
    quadrat = zuschneiden(bild, rund)
    png, ico = ziel / "logo.png", ziel / "logo.ico"
    quadrat.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(png))
    ico_speichern(quadrat, ico)
    return png, ico


def main() -> None:
    parser = argparse.ArgumentParser(description="Vereinslogo für DiKaS einbauen.")
    parser.add_argument("bild", type=Path, help="Logo als PNG oder JPG, am besten quadratisch")
    parser.add_argument("--rund", action="store_true", help="kreisförmig zuschneiden")
    argumente = parser.parse_args()
    _app = QGuiApplication.instance() or QGuiApplication([])
    try:
        png, ico = logo_erstellen(argumente.bild, argumente.rund)
    except ValueError as fehler:
        sys.exit(str(fehler))
    print(f"Gespeichert: {png}\n             {ico}")


if __name__ == "__main__":
    main()
