"""Eingabedialoge für Konten und Buchungen."""

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
)

from dikas.db.models import Konto, KontoTyp
from dikas.geld import text_zu_cent


class KontoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neues Konto")

        self.name = QLineEdit()
        self.typ = QComboBox()
        for typ in (KontoTyp.PRIVAT, KontoTyp.KASSE):
            self.typ.addItem(typ.anzeige, typ)
        self.bemerkung = QLineEdit()

        form = QFormLayout(self)
        form.addRow("Name:", self.name)
        form.addRow("Typ:", self.typ)
        form.addRow("Bemerkung:", self.bemerkung)

        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        knoepfe.accepted.connect(self._pruefen)
        knoepfe.rejected.connect(self.reject)
        form.addRow(knoepfe)

    def _pruefen(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Fehler", "Bitte einen Namen angeben.")
            return
        self.accept()

    def werte(self) -> tuple[str, KontoTyp, str]:
        return self.name.text(), self.typ.currentData(), self.bemerkung.text()


class BuchungDialog(QDialog):
    def __init__(self, konten: list[Konto], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neue Buchung")
        self.betrag_cent = 0

        self.datum = QDateEdit(QDate.currentDate())
        self.datum.setCalendarPopup(True)
        self.datum.setDisplayFormat("dd.MM.yyyy")
        self.von = self._konto_auswahl(konten)
        self.nach = self._konto_auswahl(konten)
        self.betrag = QLineEdit()
        self.betrag.setPlaceholderText("z. B. 12,50")
        self.text = QLineEdit()
        self.beleg = QLineEdit()

        form = QFormLayout(self)
        form.addRow("Datum:", self.datum)
        form.addRow("Von Konto:", self.von)
        form.addRow("Nach Konto:", self.nach)
        form.addRow("Betrag (€):", self.betrag)
        form.addRow("Buchungstext:", self.text)
        form.addRow("Beleg-Nr.:", self.beleg)

        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        knoepfe.accepted.connect(self._pruefen)
        knoepfe.rejected.connect(self.reject)
        form.addRow(knoepfe)
        self.resize(420, self.sizeHint().height())

    @staticmethod
    def _konto_auswahl(konten: list[Konto]) -> QComboBox:
        box = QComboBox()
        for konto in konten:
            box.addItem(f"{konto.name} ({konto.typ.anzeige})", konto.id)
        return box

    def _pruefen(self):
        try:
            self.betrag_cent = text_zu_cent(self.betrag.text())
        except ValueError:
            QMessageBox.warning(self, "Fehler", "Bitte einen gültigen Betrag eingeben.")
            return
        if self.betrag_cent <= 0:
            QMessageBox.warning(self, "Fehler", "Der Betrag muss größer als 0 sein.")
            return
        if self.von.currentData() == self.nach.currentData():
            QMessageBox.warning(self, "Fehler", "Von- und Nach-Konto müssen verschieden sein.")
            return
        if not self.text.text().strip():
            QMessageBox.warning(self, "Fehler", "Bitte einen Buchungstext angeben.")
            return
        self.accept()

    def werte(self) -> dict:
        return {
            "datum": self.datum.date().toPython(),
            "von_konto_id": self.von.currentData(),
            "nach_konto_id": self.nach.currentData(),
            "betrag_cent": self.betrag_cent,
            "text": self.text.text(),
            "beleg": self.beleg.text(),
        }
