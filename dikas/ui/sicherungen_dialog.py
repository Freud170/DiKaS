"""Übersicht der automatischen Sicherungen mit Wiederherstellen."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from sqlalchemy import Engine

from dikas import sicherung
from dikas.db import init_db
from dikas.ui import stil
from dikas.ui.bausteine import Panel, zelle


def _groesse(bytes_: int) -> str:
    return f"{bytes_ / 1024:,.0f} KB".replace(",", ".") if bytes_ >= 1024 else f"{bytes_} Bytes"


class SicherungenDialog(QDialog):
    def __init__(self, engine: Engine, db_pfad: Path, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.db_pfad = Path(db_pfad)
        self.wiederhergestellt = False
        self.setWindowTitle("Sicherungen")
        self.resize(640, 520)

        panel = Panel("Sicherungen")
        self.info = panel.info
        self.tabelle = stil.tabelle(["Datum", "Uhrzeit", "Größe", "Datei"], rechts=[2])
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabelle.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabelle.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tabelle.itemDoubleClicked.connect(self.wiederherstellen)
        panel.layout_.addWidget(self.tabelle)
        hinweis = QLabel(
            f"Bei jedem Programmstart wird der aktuelle Stand gesichert, sofern sich seit der letzten "
            f"Sicherung etwas geändert hat. Es bleiben die letzten {sicherung.BEHALTEN} Stände erhalten. "
            "Die Sicherungen liegen nur lokal auf diesem PC."
        )
        hinweis.setObjectName("hinweis")
        hinweis.setWordWrap(True)
        panel.layout_.addWidget(hinweis)

        ordner = QPushButton(stil.symbol("FolderOpen"), "Ordner öffnen")
        ordner.setAutoDefault(False)
        ordner.clicked.connect(self.ordner_oeffnen)
        jetzt = QPushButton("Jetzt sichern")
        jetzt.setAutoDefault(False)
        jetzt.clicked.connect(self.jetzt_sichern)
        self.wiederherstellen_knopf = QPushButton(stil.symbol("DocumentRevert"), "Wiederherstellen")
        self.wiederherstellen_knopf.setAutoDefault(False)
        self.wiederherstellen_knopf.clicked.connect(self.wiederherstellen)
        schliessen = QPushButton("Schließen")
        schliessen.clicked.connect(self.accept)
        knoepfe = QHBoxLayout()
        knoepfe.addWidget(ordner)
        knoepfe.addWidget(jetzt)
        knoepfe.addStretch()
        knoepfe.addWidget(self.wiederherstellen_knopf)
        knoepfe.addWidget(schliessen)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(panel, 1)
        layout.addLayout(knoepfe)
        self.laden()

    def laden(self):
        self.liste = sicherung.sicherungen(self.db_pfad)
        self.tabelle.setRowCount(len(self.liste))
        for zeile, s in enumerate(self.liste):
            for spalte, item in enumerate([
                zelle(s.zeitpunkt.strftime("%d.%m.%Y")),
                zelle(s.zeitpunkt.strftime("%H:%M:%S")),
                zelle(_groesse(s.groesse), rechts=True),
                zelle(s.pfad.name),
            ]):
                self.tabelle.setItem(zeile, spalte, item)
        self.info.setText(f"{len(self.liste)} von {sicherung.BEHALTEN}")
        self.wiederherstellen_knopf.setEnabled(bool(self.liste))
        if self.liste:
            self.tabelle.selectRow(0)

    def _gewaehlt(self) -> sicherung.Sicherung | None:
        zeilen = self.tabelle.selectionModel().selectedRows()
        return self.liste[zeilen[0].row()] if zeilen else None

    def ordner_oeffnen(self):
        ordner = sicherung.sicherungs_ordner(self.db_pfad)
        ordner.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ordner)))

    def jetzt_sichern(self):
        try:
            neu = sicherung.sichern(self.db_pfad)
        except OSError as fehler:
            QMessageBox.warning(self, "Fehler", f"Sicherung fehlgeschlagen:\n{fehler}")
            return
        if neu is None:
            QMessageBox.information(self, "Sicherung", "Seit der letzten Sicherung hat sich nichts geändert.")
        self.laden()

    def wiederherstellen(self, *_):
        s = self._gewaehlt()
        if s is None:
            return
        antwort = QMessageBox.question(
            self,
            "Wiederherstellen",
            f"Stand vom {s.zeitpunkt:%d.%m.%Y um %H:%M} wiederherstellen?\n\n"
            "Alle Änderungen seitdem werden zurückgesetzt. Der aktuelle Stand wird vorher "
            "gesichert und kann bei Bedarf wieder zurückgeholt werden.",
        )
        if antwort != QMessageBox.Yes:
            return
        self.engine.dispose()  # alle offenen Verbindungen schließen, bevor die Datei ersetzt wird
        try:
            sicherung.wiederherstellen(s, self.db_pfad)
        except (OSError, ValueError) as fehler:
            QMessageBox.warning(self, "Fehler", f"Wiederherstellen fehlgeschlagen:\n{fehler}")
            return
        finally:
            init_db(self.engine)  # ältere Sicherungen auf den aktuellen Datenbank-Stand bringen
        self.wiederhergestellt = True
        QMessageBox.information(self, "Wiederhergestellt", f"Der Stand vom {s.zeitpunkt:%d.%m.%Y %H:%M} ist wiederhergestellt.")
        self.laden()
