"""Wiederverwendbare Oberflächen-Bausteine: Tabellenzellen, Kennzahl-Karten, Panels."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidgetItem,
    QVBoxLayout,
)

from dikas.geld import cent_zu_text
from dikas.ui import stil

GRAU = QColor(stil.INAKTIV)
ROT = QColor(stil.NEGATIV)


def zelle(text: str, rechts: bool = False, daten=None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    if rechts:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if daten is not None:
        item.setData(Qt.UserRole, daten)
    return item


def betrag_zelle(cent: int, fett: bool = False) -> QTableWidgetItem:
    item = zelle(cent_zu_text(cent), rechts=True)
    if cent < 0:
        item.setForeground(ROT)
    if fett:
        fett_machen(item)
    return item


def fett_machen(item: QTableWidgetItem) -> None:
    schrift = QFont(item.font())
    schrift.setWeight(QFont.DemiBold)
    item.setFont(schrift)


# Statt QSpinBox: Die Zahlenfelder von Qt verschlucken mit unserem Stylesheet ihren Text.

class ZahlFeld(QLineEdit):
    """Eingabefeld nur für ganze Zahlen (z. B. Port), mit value()/setValue() wie eine QSpinBox."""

    def __init__(self, minimum: int, maximum: int, wert: int = 0):
        super().__init__()
        self.setValidator(QIntValidator(minimum, maximum, self))
        self.setValue(wert)

    def value(self) -> int:
        return int(self.text()) if self.text().strip() else 0

    def setValue(self, wert: int):
        self.setText(str(wert))


class JahrAuswahl(QComboBox):
    """Auswahlliste von Jahren (neuestes oben), mit value()/setValue()/valueChanged."""

    valueChanged = Signal(int)

    def __init__(self, von: int, bis: int, wert: int):
        super().__init__()
        for jahr in range(bis, von - 1, -1):
            self.addItem(str(jahr), jahr)
        self.setValue(wert)
        self.currentIndexChanged.connect(lambda _: self.valueChanged.emit(self.value()))

    def value(self) -> int:
        return self.currentData()

    def setValue(self, jahr: int):
        self.setCurrentIndex(self.findData(jahr))


class Kennzahl(QFrame):
    """Kleine Karte mit Überschrift und großem Wert."""

    def __init__(self, titel: str):
        super().__init__()
        self.setObjectName("karte")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        ueberschrift = QLabel(titel.upper())
        ueberschrift.setObjectName("karteTitel")
        self.wert = QLabel()
        self.wert.setObjectName("karteWert")
        layout.addWidget(ueberschrift)
        layout.addWidget(self.wert)

    def setze(self, cent: int, farbe: str | None = None):
        self.wert.setText(cent_zu_text(cent))
        self.wert.setStyleSheet(f"color: {farbe};" if farbe else "")


class Panel(QFrame):
    """Weiße Fläche mit Titelzeile für eine Tabelle."""

    def __init__(self, titel: str):
        super().__init__()
        self.setObjectName("panel")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(14, 12, 14, 6)
        self.layout_.setSpacing(8)
        self.kopf = QHBoxLayout()
        self.titel = QLabel(titel)
        self.titel.setObjectName("panelTitel")
        self.info = QLabel()
        self.info.setObjectName("panelInfo")
        self.kopf.addWidget(self.titel)
        self.kopf.addStretch()
        self.kopf.addWidget(self.info)
        self.layout_.addLayout(self.kopf)
