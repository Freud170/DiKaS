"""HTML als PDF (A4) über Qt – ohne zusätzliche Bibliothek. Braucht eine laufende QApplication."""

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument


def html_zu_pdf(html: str, titel: str) -> bytes:
    daten = QByteArray()
    puffer = QBuffer(daten)
    puffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(puffer)
    writer.setTitle(titel)
    writer.setCreator("DiKaS")
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    dokument = QTextDocument()
    dokument.setDefaultFont(QFont("Segoe UI", 9))
    dokument.setHtml(html)
    dokument.print_(writer)  # schreibt das PDF vollständig in den Puffer
    del writer
    puffer.close()
    return bytes(daten.data())
