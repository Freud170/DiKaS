"""Eingabedialoge für Konten, Buchungen und den Beitragslauf."""

from datetime import date
from typing import Callable

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from dikas.buchhaltung import REGELN
from dikas.db.models import Buchungsart, Konto, KontoTyp, MitgliedStatus
from dikas.geld import cent_zu_text, text_zu_cent


def _knoepfe(dialog: QDialog, bei_ok: Callable[[], None]) -> QDialogButtonBox:
    knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    knoepfe.accepted.connect(bei_ok)
    knoepfe.rejected.connect(dialog.reject)
    return knoepfe


def _datum_feld() -> QDateEdit:
    feld = QDateEdit(QDate.currentDate())
    feld.setCalendarPopup(True)
    feld.setDisplayFormat("dd.MM.yyyy")
    return feld


def _status_auswahl() -> QComboBox:
    box = QComboBox()
    for status in MitgliedStatus:
        box.addItem(status.anzeige, status)
    return box


class KontoDialog(QDialog):
    """Neues Konto anlegen (konto=None) oder bestehendes bearbeiten."""

    def __init__(self, parent=None, konto: Konto | None = None):
        super().__init__(parent)
        self.setWindowTitle("Konto bearbeiten" if konto else "Neues Konto")

        self.name = QLineEdit(konto.name if konto else "")
        self.typ = QComboBox()
        if konto:
            self.typ.addItem(konto.typ.anzeige, konto.typ)
            self.typ.setEnabled(False)
        else:
            for typ in (KontoTyp.PRIVAT, KontoTyp.KASSE):
                self.typ.addItem(typ.anzeige, typ)
        self.status = _status_auswahl()
        if konto and konto.status:
            self.status.setCurrentIndex(self.status.findData(konto.status))
        else:
            self.status.setCurrentIndex(self.status.findData(MitgliedStatus.AKTIVER))
        self.bemerkung = QLineEdit(konto.bemerkung if konto else "")
        self.aktiv = QCheckBox("Konto ist aktiv")
        self.aktiv.setChecked(konto.aktiv if konto else True)

        self.form = QFormLayout(self)
        self.form.addRow("Name:", self.name)
        self.form.addRow("Typ:", self.typ)
        self.form.addRow("Status:", self.status)
        self.form.addRow("Bemerkung:", self.bemerkung)
        if konto:
            self.form.addRow("", self.aktiv)
        self.form.addRow(_knoepfe(self, self._pruefen))

        self.typ.currentIndexChanged.connect(self._typ_geaendert)
        self._typ_geaendert()
        self.resize(380, self.sizeHint().height())

    def _typ_geaendert(self):
        self.form.setRowVisible(self.status, self.typ.currentData() == KontoTyp.PRIVAT)

    def _pruefen(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Fehler", "Bitte einen Namen angeben.")
            return
        self.accept()

    def werte(self) -> dict:
        typ = self.typ.currentData()
        return {
            "name": self.name.text(),
            "typ": typ,
            "status": self.status.currentData() if typ == KontoTyp.PRIVAT else None,
            "bemerkung": self.bemerkung.text(),
            "aktiv": self.aktiv.isChecked(),
        }


class BuchungDialog(QDialog):
    def __init__(self, konten: list[Konto], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neue Buchung")
        self.konten = konten
        self.betrag_cent = 0

        self.art = QComboBox()
        for art in REGELN:
            self.art.addItem(art.anzeige, art)
        self.datum = _datum_feld()
        self.konto = QComboBox()
        self.gegen = QComboBox()
        self.hinweis = QLabel()
        self.hinweis.setStyleSheet("color: gray;")
        self.betrag = QLineEdit()
        self.betrag.setPlaceholderText("z. B. 12,50")
        self.text = QLineEdit()
        self.beleg = QLineEdit()

        self.form = QFormLayout(self)
        self.form.addRow("Buchungsart:", self.art)
        self.form.addRow("", self.hinweis)
        self.form.addRow("Datum:", self.datum)
        self.form.addRow("Konto:", self.konto)
        self.form.addRow("Gegenkonto:", self.gegen)
        self.form.addRow("Betrag (€):", self.betrag)
        self.form.addRow("Buchungstext:", self.text)
        self.form.addRow("Beleg-Nr.:", self.beleg)
        self.form.addRow(_knoepfe(self, self._pruefen))

        self.art.currentIndexChanged.connect(self._art_geaendert)
        self._art_geaendert()
        self.resize(440, self.sizeHint().height())

    def _fuelle(self, box: QComboBox, typen: tuple[KontoTyp, ...]):
        box.clear()
        for konto in self.konten:
            if konto.typ in typen:
                zusatz = konto.status.anzeige if konto.status else konto.typ.anzeige
                box.addItem(f"{konto.name} ({zusatz})", konto.id)

    def _art_geaendert(self):
        art: Buchungsart = self.art.currentData()
        regel = REGELN[art]
        self._fuelle(self.konto, regel.konto_typen)
        self.form.labelForField(self.konto).setText(f"{regel.konto_beschriftung}:")
        hat_gegen = regel.gegen_typen is not None
        self.form.setRowVisible(self.gegen, hat_gegen)
        if hat_gegen:
            self._fuelle(self.gegen, regel.gegen_typen)
            self.form.labelForField(self.gegen).setText(f"{regel.gegen_beschriftung}:")
        self.hinweis.setText(
            {
                Buchungsart.EINZAHLUNG: "Mitglied zahlt Geld ein: Privatkonto + / KW +",
                Buchungsart.AUSZAHLUNG: "Mitglied bekommt Geld: Privatkonto − / KW −",
                Buchungsart.KASSE_EINNAHME: "Kasse nimmt Geld ein: Kasse + / KW +",
                Buchungsart.KASSE_AUSGABE: "Kasse gibt Geld aus: Kasse − / KW −",
                Buchungsart.UMBUCHUNG: "Von − / Nach +, KW bleibt gleich",
                Buchungsart.BEITRAG: "Privatkonto − / Kasse +, KW bleibt gleich",
            }[art]
        )

    def _pruefen(self):
        try:
            self.betrag_cent = text_zu_cent(self.betrag.text())
        except ValueError:
            QMessageBox.warning(self, "Fehler", "Bitte einen gültigen Betrag eingeben.")
            return
        if self.betrag_cent <= 0:
            QMessageBox.warning(self, "Fehler", "Der Betrag muss größer als 0 sein.")
            return
        if self.konto.currentData() is None:
            QMessageBox.warning(self, "Fehler", "Für diese Buchungsart gibt es kein passendes Konto.")
            return
        if self.form.isRowVisible(self.gegen):
            if self.gegen.currentData() is None:
                QMessageBox.warning(self, "Fehler", "Für diese Buchungsart gibt es kein passendes Gegenkonto.")
                return
            if self.konto.currentData() == self.gegen.currentData():
                QMessageBox.warning(self, "Fehler", "Die beiden Konten müssen verschieden sein.")
                return
        if not self.text.text().strip():
            QMessageBox.warning(self, "Fehler", "Bitte einen Buchungstext angeben.")
            return
        self.accept()

    def werte(self) -> dict:
        return {
            "art": self.art.currentData(),
            "datum": self.datum.date().toPython(),
            "konto_id": self.konto.currentData(),
            "gegenkonto_id": self.gegen.currentData() if self.form.isRowVisible(self.gegen) else None,
            "betrag_cent": self.betrag_cent,
            "text": self.text.text(),
            "beleg": self.beleg.text(),
        }


class BeitragDialog(QDialog):
    """Beitragslauf: Betrag je Status eingeben, Vorschau ansehen, abbuchen."""

    def __init__(
        self,
        kassen: list[Konto],
        vorschau: Callable[[dict[MitgliedStatus, int]], list[tuple[Konto, int]]],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Beiträge abbuchen")
        self._vorschau = vorschau
        self.betraege: dict[MitgliedStatus, int] = {}

        self.felder: dict[MitgliedStatus, QLineEdit] = {}
        form = QFormLayout()
        for status in MitgliedStatus:
            feld = QLineEdit()
            feld.setPlaceholderText("0,00")
            feld.textChanged.connect(self._aktualisiere_vorschau)
            self.felder[status] = feld
            form.addRow(f"Beitrag {status.mehrzahl} (€):", feld)
        self.kasse = QComboBox()
        for kasse in kassen:
            self.kasse.addItem(kasse.name, kasse.id)
        form.addRow("Auf Kasse:", self.kasse)
        self.datum = _datum_feld()
        form.addRow("Datum:", self.datum)
        self.text = QLineEdit(f"Jahresbeitrag {date.today().year}")
        form.addRow("Buchungstext:", self.text)

        self.tabelle = QTableWidget(0, 3)
        self.tabelle.setHorizontalHeaderLabels(["Mitglied", "Status", "Beitrag"])
        self.tabelle.verticalHeader().setVisible(False)
        self.tabelle.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabelle.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.summe = QLabel()

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("<b>Vorschau</b>"))
        layout.addWidget(self.tabelle)
        layout.addWidget(self.summe)
        layout.addWidget(_knoepfe(self, self._pruefen))

        self._aktualisiere_vorschau()
        self.resize(480, 560)

    def _lese_betraege(self) -> dict[MitgliedStatus, int] | None:
        """Cent je Status; None, wenn ein Feld ungültig ist."""
        betraege = {}
        for status, feld in self.felder.items():
            text = feld.text().strip()
            try:
                betraege[status] = text_zu_cent(text) if text else 0
            except ValueError:
                return None
        return betraege

    def _aktualisiere_vorschau(self):
        betraege = self._lese_betraege()
        if betraege is None:
            self.tabelle.setRowCount(0)
            self.summe.setText("<span style='color:#c0392b'>Ungültiger Betrag</span>")
            return
        zeilen = self._vorschau(betraege)
        self.tabelle.setRowCount(len(zeilen))
        for i, (mitglied, cent) in enumerate(zeilen):
            betrag = QTableWidgetItem(cent_zu_text(cent))
            betrag.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tabelle.setItem(i, 0, QTableWidgetItem(mitglied.name))
            self.tabelle.setItem(i, 1, QTableWidgetItem(mitglied.status.anzeige))
            self.tabelle.setItem(i, 2, betrag)
        gesamt = sum(cent for _, cent in zeilen)
        self.summe.setText(f"{len(zeilen)} Mitglieder, Summe: <b>{cent_zu_text(gesamt)}</b>")

    def _pruefen(self):
        betraege = self._lese_betraege()
        if betraege is None:
            QMessageBox.warning(self, "Fehler", "Bitte gültige Beträge eingeben.")
            return
        zeilen = self._vorschau(betraege)
        if not zeilen:
            QMessageBox.warning(self, "Fehler", "Es wird für kein Mitglied ein Beitrag fällig.")
            return
        if self.kasse.currentData() is None:
            QMessageBox.warning(self, "Fehler", "Bitte zuerst eine Kasse anlegen.")
            return
        if not self.text.text().strip():
            QMessageBox.warning(self, "Fehler", "Bitte einen Buchungstext angeben.")
            return
        gesamt = sum(cent for _, cent in zeilen)
        antwort = QMessageBox.question(
            self,
            "Beiträge abbuchen",
            f"{len(zeilen)} Beitragsbuchungen über insgesamt {cent_zu_text(gesamt)} "
            f"auf „{self.kasse.currentText()}“ anlegen?",
        )
        if antwort != QMessageBox.Yes:
            return
        self.betraege = betraege
        self.accept()

    def werte(self) -> dict:
        return {
            "betraege": self.betraege,
            "kasse_id": self.kasse.currentData(),
            "text": self.text.text(),
            "datum": self.datum.date().toPython(),
        }
