"""Wiederverwendbare Oberflächen-Bausteine: Tabellenzellen, Kennzahl-Karten, Panels."""

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIntValidator
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidgetItem,
    QToolButton,
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


class Spaltenbreiten(QObject):
    """Spalten so breit wie ihr Inhalt; übriger Platz wird verteilt, damit die Tabelle auch im
    Vollbild die ganze Breite füllt. Reicht der Platz nicht, scrollt die Tabelle waagerecht –
    keine Spalte wird zusammengequetscht.

    `verteilen_auf`: Spalte, die den freien Platz bekommt (z. B. Buchungstext); sonst gleichmäßig.
    Nach dem Neubefüllen der Tabelle `anpassen()` aufrufen.
    """

    def __init__(self, tabelle, verteilen_auf: int | None = None):
        super().__init__(tabelle)
        self.tabelle = tabelle
        self.verteilen_auf = verteilen_auf
        tabelle.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        tabelle.viewport().installEventFilter(self)

    def eventFilter(self, objekt, ereignis):
        if ereignis.type() == QEvent.Resize:
            self.anpassen()
        return False

    def anpassen(self) -> None:
        t = self.tabelle
        kopf = t.horizontalHeader()
        sichtbar = [s for s in range(t.columnCount()) if not kopf.isSectionHidden(s)]
        if not sichtbar:
            return
        breiten = {s: max(t.sizeHintForColumn(s), kopf.sectionSizeHint(s)) for s in sichtbar}
        frei = t.viewport().width() - sum(breiten.values())
        if frei > 0:
            if self.verteilen_auf in breiten:
                breiten[self.verteilen_auf] += frei
            else:
                anteil, rest = divmod(frei, len(sichtbar))
                for i, s in enumerate(sichtbar):
                    breiten[s] += anteil + (1 if i < rest else 0)
        for s, breite in breiten.items():
            if kopf.sectionSize(s) != breite:
                kopf.resizeSection(s, breite)


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


class JahrAuswahl(QFrame):
    """Kompakter Jahresumschalter ‹ 2026 › (auch per Mausrad und Pfeiltasten),
    mit value()/setValue()/valueChanged wie eine QSpinBox."""

    valueChanged = Signal(int)

    def __init__(self, von: int, bis: int, wert: int):
        super().__init__()
        self.setObjectName("jahrAuswahl")
        self.setFocusPolicy(Qt.StrongFocus)
        self._von, self._bis = von, bis
        self.zurueck = QToolButton()
        self.zurueck.setText("‹")
        self.zurueck.setToolTip("Vorheriges Jahr")
        self.zurueck.clicked.connect(lambda: self.setValue(self._wert - 1))
        self.weiter = QToolButton()
        self.weiter.setText("›")
        self.weiter.setToolTip("Nächstes Jahr")
        self.weiter.clicked.connect(lambda: self.setValue(self._wert + 1))
        self.anzeige = QLabel()
        self.anzeige.setObjectName("jahrWert")
        self.anzeige.setAlignment(Qt.AlignCenter)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.zurueck)
        layout.addWidget(self.anzeige)
        layout.addWidget(self.weiter)
        layout.addStretch()
        self._wert = None
        self.setValue(wert)

    def value(self) -> int:
        return self._wert

    def setValue(self, jahr: int):
        jahr = max(self._von, min(self._bis, jahr))
        geaendert = jahr != self._wert
        self._wert = jahr
        self.anzeige.setText(str(jahr))
        self.zurueck.setEnabled(jahr > self._von)
        self.weiter.setEnabled(jahr < self._bis)
        if geaendert:
            self.valueChanged.emit(jahr)

    def wheelEvent(self, event):
        self.setValue(self._wert + (1 if event.angleDelta().y() > 0 else -1))

    def keyPressEvent(self, event):
        schritte = {Qt.Key_Up: 1, Qt.Key_Right: 1, Qt.Key_Down: -1, Qt.Key_Left: -1}
        if event.key() in schritte:
            self.setValue(self._wert + schritte[event.key()])
        else:
            super().keyPressEvent(event)


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
