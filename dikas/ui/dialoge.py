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
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
)

from dikas.buchhaltung import REGELN, BeitragVorschau
from dikas.db.models import Buchungsart, Konto, KontoTyp, MitgliedStatus
from dikas.geld import cent_zu_text, text_zu_cent
from dikas.ui import stil


def _knoepfe(dialog: QDialog, bei_ok: Callable[[], None]) -> QDialogButtonBox:
    knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    knoepfe.accepted.connect(bei_ok)
    knoepfe.rejected.connect(dialog.reject)
    return knoepfe


UNBEKANNT = QDate(1900, 1, 1)


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


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
        # Kleinstes Datum steht für "unbekannt" (ältere Konten ohne Eintrittsdatum)
        self.eintritt = _datum_feld()
        self.eintritt.setMinimumDate(UNBEKANNT)
        self.eintritt.setSpecialValueText("unbekannt")
        if konto:
            self.eintritt.setDate(_qdate(konto.eintrittsdatum) if konto.eintrittsdatum else UNBEKANNT)
        self.bemerkung = QLineEdit(konto.bemerkung if konto else "")
        self.aktiv = QCheckBox("Konto ist aktiv")
        self.aktiv.setChecked(konto.aktiv if konto else True)

        self.form = stil.formular(QFormLayout(self))
        self.form.addRow("Name:", self.name)
        self.form.addRow("Typ:", self.typ)
        self.form.addRow("Status:", self.status)
        self.form.addRow("Eintrittsdatum:", self.eintritt)
        self.form.addRow("Bemerkung:", self.bemerkung)
        if konto:
            self.form.addRow("", self.aktiv)
        self.form.addRow(_knoepfe(self, self._pruefen))

        self.typ.currentIndexChanged.connect(self._typ_geaendert)
        self._typ_geaendert()
        self.resize(380, self.sizeHint().height())

    def _typ_geaendert(self):
        privat = self.typ.currentData() == KontoTyp.PRIVAT
        self.form.setRowVisible(self.status, privat)
        self.form.setRowVisible(self.eintritt, privat)

    def _pruefen(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Fehler", "Bitte einen Namen angeben.")
            return
        if self.typ.currentData() == KontoTyp.PRIVAT and self.eintritt.date() == UNBEKANNT:
            QMessageBox.warning(self, "Fehler", "Bitte ein Eintrittsdatum angeben.")
            return
        self.accept()

    def werte(self) -> dict:
        typ = self.typ.currentData()
        privat = typ == KontoTyp.PRIVAT
        eintritt = self.eintritt.date()
        return {
            "name": self.name.text(),
            "typ": typ,
            "status": self.status.currentData() if privat else None,
            "eintrittsdatum": eintritt.toPython() if privat and eintritt != UNBEKANNT else None,
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
        self.hinweis.setObjectName("hinweis")
        self.betrag = QLineEdit()
        self.betrag.setPlaceholderText("z. B. 12,50")
        self.text = QLineEdit()
        self.beleg = QLineEdit()

        self.form = stil.formular(QFormLayout(self))
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
    """Beitragslauf: Jahr und Betrag je Status eingeben, Vorschau ansehen, abbuchen."""

    def __init__(
        self,
        kassen: list[Konto],
        vorschau: Callable[[dict[MitgliedStatus, int], int], BeitragVorschau],
        parent=None,
        heute: date | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Beiträge abbuchen")
        self._vorschau = vorschau
        self.betraege: dict[MitgliedStatus, int] = {}
        heute = heute or date.today()

        form = stil.formular(QFormLayout())
        form.setContentsMargins(0, 0, 0, 0)
        self.jahr = QSpinBox()
        self.jahr.setRange(1950, heute.year + 1)
        self.jahr.setValue(heute.year)
        form.addRow("Beitragsjahr:", self.jahr)
        self.felder: dict[MitgliedStatus, QLineEdit] = {}
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
        form.addRow("Buchungsdatum:", self.datum)
        self.text = QLineEdit()
        form.addRow("Buchungstext:", self.text)

        self.tabelle = stil.tabelle(["Mitglied", "Status", "Eintritt", "Beitrag"], rechts=[3])
        self.tabelle.setSelectionMode(QAbstractItemView.NoSelection)
        self.tabelle.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.summe = QLabel()
        self.ausgelassen = QLabel()
        self.ausgelassen.setObjectName("hinweis")
        self.ausgelassen.setWordWrap(True)

        self.vorschau_titel = QLabel()
        self.vorschau_titel.setObjectName("panelTitel")
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 10, 12, 10)
        panel_layout.addWidget(self.vorschau_titel)
        panel_layout.addWidget(self.tabelle)
        panel_layout.addWidget(self.summe)
        panel_layout.addWidget(self.ausgelassen)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(14)
        layout.addLayout(form)
        layout.addWidget(panel, 1)
        layout.addWidget(_knoepfe(self, self._pruefen))

        self._letzter_standardtext = ""
        self.jahr.valueChanged.connect(self._jahr_geaendert)
        self._jahr_geaendert()
        self.resize(560, 760)

    def _jahr_geaendert(self):
        """Datum auf den 01.01. setzen; Text nur anpassen, wenn er nicht von Hand geändert wurde."""
        jahr = self.jahr.value()
        self.datum.setDate(QDate(jahr, 1, 1))
        standard = f"Jahresbeitrag {jahr}"
        if self.text.text() in ("", self._letzter_standardtext):
            self.text.setText(standard)
        self._letzter_standardtext = standard
        self._aktualisiere_vorschau()

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
        jahr = self.jahr.value()
        self.vorschau_titel.setText(f"Vorschau – fällig für {jahr}")
        betraege = self._lese_betraege()
        if betraege is None:
            self.tabelle.setRowCount(0)
            self.summe.setText(f"<span style='color:{stil.NEGATIV}'>Ungültiger Betrag</span>")
            self.ausgelassen.clear()
            return
        v = self._vorschau(betraege, jahr)
        self.tabelle.setRowCount(len(v.faellig))
        for i, (mitglied, cent) in enumerate(v.faellig):
            betrag = QTableWidgetItem(cent_zu_text(cent))
            betrag.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tabelle.setItem(i, 0, QTableWidgetItem(mitglied.name))
            self.tabelle.setItem(i, 1, QTableWidgetItem(mitglied.status.anzeige))
            self.tabelle.setItem(i, 2, QTableWidgetItem(mitglied.eintrittsdatum.strftime("%d.%m.%Y")))
            self.tabelle.setItem(i, 3, betrag)
        anzahl = f"{len(v.faellig)} Mitglied" + ("" if len(v.faellig) == 1 else "er")
        self.summe.setText(f"{anzahl}, Summe: <b>{cent_zu_text(v.summe)}</b>")

        gruende = [
            (f"Bereits für {jahr} abgebucht", v.bereits_abgebucht),
            (f"Erst nach dem 01.01.{jahr} eingetreten", v.spaeter_eingetreten),
            ("Ohne Eintrittsdatum (bitte im Konto nachtragen)", v.ohne_eintrittsdatum),
        ]
        self.ausgelassen.setText("<br>".join(
            f"<b>{grund}:</b> {', '.join(m.name for m in liste)}" for grund, liste in gruende if liste
        ))

    def _pruefen(self):
        betraege = self._lese_betraege()
        if betraege is None:
            QMessageBox.warning(self, "Fehler", "Bitte gültige Beträge eingeben.")
            return
        jahr = self.jahr.value()
        v = self._vorschau(betraege, jahr)
        if not v.faellig:
            QMessageBox.warning(self, "Fehler", f"Es wird für kein Mitglied ein Beitrag {jahr} fällig.")
            return
        if self.kasse.currentData() is None:
            QMessageBox.warning(self, "Fehler", "Bitte zuerst eine Kasse anlegen.")
            return
        if not self.text.text().strip():
            QMessageBox.warning(self, "Fehler", "Bitte einen Buchungstext angeben.")
            return
        antwort = QMessageBox.question(
            self,
            "Beiträge abbuchen",
            f"Beitrag {jahr}: {len(v.faellig)} Buchungen über insgesamt {cent_zu_text(v.summe)} "
            f"auf „{self.kasse.currentText()}“ anlegen?",
        )
        if antwort != QMessageBox.Yes:
            return
        self.betraege = betraege
        self.accept()

    def werte(self) -> dict:
        return {
            "betraege": self.betraege,
            "jahr": self.jahr.value(),
            "kasse_id": self.kasse.currentData(),
            "text": self.text.text(),
            "datum": self.datum.date().toPython(),
        }
