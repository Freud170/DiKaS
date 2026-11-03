"""Erzeugt das Programmsymbol (dikas.ico / dikas.png) – nur nötig, wenn es sich ändern soll.

Aufruf: .venv\\Scripts\\python.exe packaging\\symbol_erzeugen.py
"""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

AKZENT = QColor("#1f5fae")
ORDNER = Path(__file__).resolve().parent


def zeichne(groesse: int) -> QImage:
    bild = QImage(groesse, groesse, QImage.Format_ARGB32)
    bild.fill(Qt.transparent)
    maler = QPainter(bild)
    maler.setRenderHint(QPainter.Antialiasing)
    rand = groesse * 0.04
    flaeche = QRectF(rand, rand, groesse - 2 * rand, groesse - 2 * rand)
    pfad = QPainterPath()
    pfad.addRoundedRect(flaeche, groesse * 0.22, groesse * 0.22)
    maler.fillPath(pfad, AKZENT)
    schrift = QFont("Segoe UI", 1, QFont.Bold)
    schrift.setPixelSize(int(groesse * 0.62))
    maler.setFont(schrift)
    maler.setPen(QColor("white"))
    maler.drawText(flaeche, Qt.AlignCenter, "€")
    maler.end()
    return bild


def main() -> None:
    QGuiApplication(sys.argv)
    gross = zeichne(256)
    gross.save(str(ORDNER / "dikas.png"))
    gross.save(str(ORDNER.parent / "dikas" / "ui" / "symbol.png"))  # Fenstersymbol im Programm
    if not gross.save(str(ORDNER / "dikas.ico")):
        raise SystemExit("ICO konnte nicht gespeichert werden")
    print("Symbol gespeichert:", ORDNER / "dikas.ico")


if __name__ == "__main__":
    main()
