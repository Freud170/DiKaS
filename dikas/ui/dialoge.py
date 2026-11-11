"""Eingabedialoge für Konten, Buchungen und den Beitragslauf."""

from datetime import date
from typing import Callable

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dikas.buchhaltung import EMAIL_MUSTER, REGELN, BeitragVorschau
from dikas.db.models import Buchungsart, Konto, KontoTyp, MitgliedStatus
from dikas.geld import cent_zu_text, text_zu_cent
from dikas.ui import stil
from dikas.ui.bausteine import JahrAuswahl


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


class StatusverlaufEditor(QWidget):
    """Liste der Statuswechsel (Status + gültig ab) mit Hinzufügen/Entfernen."""

    def __init__(self, verlauf: list[tuple[MitgliedStatus, date]], parent=None):
        super().__init__(parent)
        self.tabelle = stil.tabelle(["Status", "gültig ab"])
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabelle.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabelle.verticalHeader().setDefaultSectionSize(40)
        self.tabelle.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabelle.setMinimumHeight(150)

        hinzufuegen = QPushButton("Statuswechsel hinzufügen")
        hinzufuegen.setAutoDefault(False)
        hinzufuegen.clicked.connect(self.neuer_wechsel)
        self.entfernen = QPushButton("Entfernen")
        self.entfernen.setAutoDefault(False)
        self.entfernen.clicked.connect(self.ausgewaehlten_entfernen)

        knoepfe = QHBoxLayout()
        knoepfe.addWidget(hinzufuegen)
        knoepfe.addWidget(self.entfernen)
        knoepfe.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabelle)
        layout.addLayout(knoepfe)

        for status, ab in sorted(verlauf, key=lambda e: e[1]):
            self._zeile(status, ab)
        self._knoepfe_aktualisieren()

    def _zeile(self, status: MitgliedStatus, ab: date):
        zeile = self.tabelle.rowCount()
        self.tabelle.insertRow(zeile)
        auswahl = _status_auswahl()
        auswahl.setCurrentIndex(auswahl.findData(status))
        datum = _datum_feld()
        datum.setMaximumDate(QDate.currentDate())
        datum.setDate(_qdate(ab))
        self.tabelle.setCellWidget(zeile, 0, auswahl)
        self.tabelle.setCellWidget(zeile, 1, datum)

    def neuer_wechsel(self):
        """Neue Zeile mit dem nächsten Status (Fux → Aktiver → Alumni) ab heute."""
        letzter = self.werte()[-1][0] if self.tabelle.rowCount() else MitgliedStatus.FUX
        self._zeile(MitgliedStatus(letzter).naechster, date.today())
        self.tabelle.selectRow(self.tabelle.rowCount() - 1)
        self._knoepfe_aktualisieren()

    def ausgewaehlten_entfernen(self):
        if self.tabelle.rowCount() <= 1:
            return
        zeilen = self.tabelle.selectionModel().selectedRows()
        self.tabelle.removeRow(zeilen[0].row() if zeilen else self.tabelle.rowCount() - 1)
        self._knoepfe_aktualisieren()

    def _knoepfe_aktualisieren(self):
        self.entfernen.setEnabled(self.tabelle.rowCount() > 1)

    def werte(self) -> list[tuple[MitgliedStatus, date]]:
        return [
            (self.tabelle.cellWidget(z, 0).currentData(), self.tabelle.cellWidget(z, 1).date().toPython())
            for z in range(self.tabelle.rowCount())
        ]

    def fehler(self) -> str | None:
        daten = [ab for _, ab in self.werte()]
        if not daten:
            return "Der Statusverlauf braucht mindestens einen Eintrag."
        if len(set(daten)) != len(daten):
            return "Zwei Statuswechsel haben dasselbe Datum."
        return None

    def aktueller_status(self) -> MitgliedStatus:
        return max(self.werte(), key=lambda e: e[1])[0]


class KontoDialog(QDialog):
    """Neues Konto anlegen (konto=None) oder bestehendes bearbeiten."""

    def __init__(self, parent=None, konto: Konto | None = None):
        super().__init__(parent)
        self.setWindowTitle("Konto bearbeiten" if konto else "Neues Konto")

        self.name = QLineEdit(konto.name if konto else "")
        self.vorname = QLineEdit(konto.vorname if konto else "")
        self.nachname = QLineEdit(konto.nachname if konto else "")
        self.typ = QComboBox()
        if konto:
            self.typ.addItem(konto.typ.anzeige, konto.typ)
            self.typ.setEnabled(False)
        else:
            for typ in (KontoTyp.PRIVAT, KontoTyp.KASSE, KontoTyp.KW):
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
        self.bierspitz = QLineEdit(konto.bierspitz if konto else "")
        self.bierspitz.setPlaceholderText("optional")
        self.email = QLineEdit(konto.email if konto else "")
        self.email.setPlaceholderText("optional, z. B. name@beispiel.de")
        self.bemerkung = QLineEdit(konto.bemerkung if konto else "")
        self.aktiv = QCheckBox("Konto ist aktiv")
        self.aktiv.setChecked(konto.aktiv if konto else True)

        # Beim Bearbeiten eines Mitglieds: Statusverlauf statt einzelnem Status
        self.verlauf: StatusverlaufEditor | None = None
        if konto and konto.typ == KontoTyp.PRIVAT:
            eintraege = [(w.status, w.gueltig_ab) for w in konto.statusverlauf]
            if not eintraege:  # älteres Konto ohne Verlauf
                eintraege = [(konto.status, konto.eintrittsdatum or date.today())]
            self.verlauf = StatusverlaufEditor(eintraege)

        self.form = stil.formular(QFormLayout(self))
        self.form.addRow("Typ:", self.typ)
        self.form.addRow("Name:", self.name)
        self.form.addRow("Vorname:", self.vorname)
        self.form.addRow("Nachname:", self.nachname)
        self.form.addRow("Bierspitz:", self.bierspitz)
        self.form.addRow("E-Mail:", self.email)
        self.form.addRow("Status:", self.status)
        self.form.addRow("Eintrittsdatum:", self.eintritt)
        if self.verlauf:
            self.form.addRow("Statusverlauf:", self.verlauf)
        self.form.addRow("Bemerkung:", self.bemerkung)
        if konto:
            self.form.addRow("", self.aktiv)
        self.form.addRow(_knoepfe(self, self._pruefen))

        self.typ.currentIndexChanged.connect(self._typ_geaendert)
        self._typ_geaendert()
        self.resize(460 if self.verlauf else 380, self.sizeHint().height())

    def _typ_geaendert(self):
        privat = self.typ.currentData() == KontoTyp.PRIVAT
        self.form.setRowVisible(self.status, privat and self.verlauf is None)
        self.form.setRowVisible(self.name, not privat)
        for feld in (self.vorname, self.nachname, self.eintritt, self.bierspitz, self.email):
            self.form.setRowVisible(feld, privat)

    def _pruefen(self):
        privat = self.typ.currentData() == KontoTyp.PRIVAT
        if privat:
            for feld, bezeichnung in ((self.vorname, "Vornamen"), (self.nachname, "Nachnamen")):
                if not feld.text().strip():
                    QMessageBox.warning(self, "Fehler", f"Bitte einen {bezeichnung} angeben.")
                    return
        elif not self.name.text().strip():
            QMessageBox.warning(self, "Fehler", "Bitte einen Namen angeben.")
            return
        if privat:
            # E-Mail ist optional (kann nachgetragen werden), muss aber gültig sein, wenn angegeben
            email = self.email.text().strip()
            if email and not EMAIL_MUSTER.match(email):
                QMessageBox.warning(self, "Fehler", f"„{email}“ ist keine gültige E-Mail-Adresse.")
                return
            if self.eintritt.date() == UNBEKANNT:
                QMessageBox.warning(self, "Fehler", "Bitte ein Eintrittsdatum angeben.")
                return
        if self.verlauf and (fehler := self.verlauf.fehler()):
            QMessageBox.warning(self, "Fehler", fehler)
            return
        self.accept()

    def werte(self) -> dict:
        typ = self.typ.currentData()
        privat = typ == KontoTyp.PRIVAT
        eintritt = self.eintritt.date()
        if self.verlauf:
            status = self.verlauf.aktueller_status()
        else:
            status = self.status.currentData() if privat else None
        vorname, nachname = self.vorname.text().strip(), self.nachname.text().strip()
        return {
            "name": f"{vorname} {nachname}".strip() if privat else self.name.text(),
            "vorname": vorname if privat else None,
            "nachname": nachname if privat else None,
            "typ": typ,
            "status": status,
            "eintrittsdatum": eintritt.toPython() if privat and eintritt != UNBEKANNT else None,
            "statusverlauf": self.verlauf.werte() if self.verlauf else None,
            "bierspitz": self.bierspitz.text() if privat else "",
            "email": self.email.text() if privat else "",
            "bemerkung": self.bemerkung.text(),
            "aktiv": self.aktiv.isChecked(),
        }


class BuchungDialog(QDialog):
    """Neue Buchung – oder mit `vorlage` (siehe buchhaltung.eingabe_aus_buchung) eine Korrektur."""

    def __init__(self, konten: list[Konto], parent=None, vorlage: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Buchung korrigieren" if vorlage else "Neue Buchung")
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
        if vorlage:
            erklaerung = QLabel(
                "Ändern sich Betrag, Konten, Art oder Datum, wird die alte Buchung storniert und "
                "eine neue angelegt – so bleibt nachvollziehbar, was korrigiert wurde. "
                "Reine Text-/Beleg-Änderungen werden direkt übernommen."
            )
            erklaerung.setObjectName("hinweis")
            erklaerung.setWordWrap(True)
            self.form.addRow(erklaerung)
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
        if vorlage:
            self._vorbelegen(vorlage)
        self.resize(460, self.sizeHint().height())

    def _vorbelegen(self, v: dict):
        self.art.setCurrentIndex(self.art.findData(v["art"]))
        self.konto.setCurrentIndex(self.konto.findData(v["konto_id"]))
        if v["gegenkonto_id"] is not None:
            self.gegen.setCurrentIndex(self.gegen.findData(v["gegenkonto_id"]))
        self.datum.setDate(_qdate(v["datum"]))
        self.betrag.setText(cent_zu_text(v["betrag_cent"], waehrung=False))
        self.text.setText(v["text"])
        self.beleg.setText(v["beleg"])

    def _fuelle(self, box: QComboBox, typen: tuple[KontoTyp, ...]):
        box.clear()
        for konto in self.konten:
            if konto.typ in typen:
                zusatz = konto.status.anzeige if konto.status else konto.typ.anzeige
                # Nur bei Korrekturen dabei: Konten der Buchung, die inzwischen stillgelegt sind
                if konto.geloescht:
                    zusatz += ", gelöscht"
                elif not konto.aktiv:
                    zusatz += ", deaktiviert"
                box.addItem(f"{konto.name} ({zusatz})", konto.id)
        # Vorauswahl bei Geldorten: der Standard-Geldort (ältester aktiver), wie in `buchhaltung.kw_konto`
        geldorte = [k.id for k in self.konten if k.typ == KontoTyp.KW and k.typ in typen and k.aktiv]
        if geldorte:
            box.setCurrentIndex(box.findData(min(geldorte)))

    def _art_geaendert(self):
        art: Buchungsart = self.art.currentData()
        regel = REGELN[art]
        self._fuelle(self.konto, regel.konto_typen)
        self.form.labelForField(self.konto).setText(f"{regel.konto_beschriftung}:")
        self._fuelle(self.gegen, regel.gegen_typen)
        self.form.labelForField(self.gegen).setText(f"{regel.gegen_beschriftung}:")
        # Gibt es nur einen Geldort, muss niemand etwas auswählen
        nur_ein_geldort = regel.standard_geldort and self.gegen.count() <= 1
        self.form.setRowVisible(self.gegen, not nur_ein_geldort)
        self.hinweis.setText(
            {
                Buchungsart.EINZAHLUNG: "Mitglied zahlt Geld ein: Privatkonto + / Geldort +",
                Buchungsart.AUSZAHLUNG: "Mitglied bekommt Geld: Privatkonto − / Geldort −",
                Buchungsart.KASSE_EINNAHME: "Kasse nimmt Geld ein: Kasse + / Geldort +",
                Buchungsart.KASSE_AUSGABE: "Kasse gibt Geld aus: Kasse − / Geldort −",
                Buchungsart.UMBUCHUNG: "Von − / Nach +, KW bleibt gleich",
                Buchungsart.BEITRAG: "Privatkonto − / Kasse +, KW bleibt gleich",
                Buchungsart.GELDTRANSFER: "Geld wechselt den Ort: Von − / Nach +, KW gesamt bleibt gleich",
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
        self.jahr = JahrAuswahl(1950, heute.year + 1, heute.year)
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

        # Vorschau mit Häkchen: fällige sind angehakt, später Eingetretene / ohne Eintrittsdatum
        # können dazugenommen werden, bereits Abgebuchte sind gesperrt.
        self.tabelle = stil.tabelle(["", "Mitglied", "Status", "Eintritt", "Beitrag", "Hinweis"], rechts=[4])
        self.tabelle.setSelectionMode(QAbstractItemView.NoSelection)
        # Namen immer ganz zeigen; der (lange) Hinweis bekommt den Rest und wird notfalls gekürzt
        self.tabelle.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.tabelle.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabelle.setTextElideMode(Qt.ElideRight)
        self.tabelle.itemChanged.connect(self._haken_geaendert)
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
        self._von_hand: dict[int, bool] = {}  # Häkchen, die von Hand gesetzt/entfernt wurden
        self._zeilen: list[tuple[Konto, int]] = []  # (Mitglied, Betrag) je Tabellenzeile
        self.jahr.valueChanged.connect(self._jahr_geaendert)
        self._jahr_geaendert()
        self.resize(680, 820)

    def _jahr_geaendert(self):
        """Datum auf den 01.01. setzen; Text nur anpassen, wenn er nicht von Hand geändert wurde."""
        jahr = self.jahr.value()
        self.datum.setDate(QDate(jahr, 1, 1))
        standard = f"Jahresbeitrag {jahr}"
        if self.text.text() in ("", self._letzter_standardtext):
            self.text.setText(standard)
        self._letzter_standardtext = standard
        self._von_hand.clear()  # Auswahl gilt nur für das jeweilige Jahr
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
        self.vorschau_titel.setText(f"Vorschau – Beitrag {jahr}")
        betraege = self._lese_betraege()
        t = self.tabelle
        t.blockSignals(True)
        t.setRowCount(0)
        self._zeilen = []
        if betraege is None:
            t.blockSignals(False)
            self.summe.setText(f"<span style='color:{stil.NEGATIV}'>Ungültiger Betrag</span>")
            self.ausgelassen.clear()
            return
        v = self._vorschau(betraege, jahr)
        eintraege = (
            [(m, True, "") for m, _ in v.faellig]
            + [(m, False, f"Eintritt nach 01.01.{jahr}") for m in v.spaeter_eingetreten]
            + [(m, False, "ohne Eintrittsdatum") for m in v.ohne_eintrittsdatum]
            + [(m, None, f"bereits für {jahr} abgebucht") for m in v.bereits_abgebucht]
            + [(m, None, f"kein Beitrag für „{v.status_je_konto[m.id].anzeige}“ eingetragen")
               for m in v.ohne_beitrag]
        )
        for mitglied, vorauswahl, hinweis in eintraege:
            zeile = t.rowCount()
            t.insertRow(zeile)
            haken = QTableWidgetItem()
            if vorauswahl is None:  # gesperrt
                haken.setFlags(Qt.ItemIsEnabled)
            else:
                haken.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                an = self._von_hand.get(mitglied.id, vorauswahl)
                haken.setCheckState(Qt.Checked if an else Qt.Unchecked)
            cent = v.betrag_je_konto.get(mitglied.id, 0)
            betrag = QTableWidgetItem(cent_zu_text(cent) if cent else "–")
            betrag.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            eintritt = mitglied.eintrittsdatum.strftime("%d.%m.%Y") if mitglied.eintrittsdatum else "–"
            items = [
                haken,
                QTableWidgetItem(mitglied.name),
                QTableWidgetItem(v.status_je_konto[mitglied.id].anzeige),
                QTableWidgetItem(eintritt),
                betrag,
                QTableWidgetItem(hinweis),
            ]
            for spalte, item in enumerate(items):
                if vorauswahl is not True and spalte:
                    item.setForeground(QColor(stil.INAKTIV))
                t.setItem(zeile, spalte, item)
            self._zeilen.append((mitglied, cent))
        t.blockSignals(False)
        self._zeige_summe()

        gruende = [
            (f"Bereits für {jahr} abgebucht", v.bereits_abgebucht),
            (f"Erst nach dem 01.01.{jahr} eingetreten (bei Bedarf anhaken)", v.spaeter_eingetreten),
            ("Ohne Eintrittsdatum (bei Bedarf anhaken oder im Konto nachtragen)", v.ohne_eintrittsdatum),
        ]
        self.ausgelassen.setText("<br>".join(
            f"<b>{grund}:</b> {', '.join(m.name for m in liste)}" for grund, liste in gruende if liste
        ))

    def _haken_geaendert(self, item: QTableWidgetItem):
        if item.column() != 0:
            return
        mitglied, _ = self._zeilen[item.row()]
        self._von_hand[mitglied.id] = item.checkState() == Qt.Checked
        self._zeige_summe()

    def ausgewaehlte(self) -> list[tuple[Konto, int]]:
        return [
            self._zeilen[z] for z in range(self.tabelle.rowCount())
            if self.tabelle.item(z, 0).checkState() == Qt.Checked
            and self.tabelle.item(z, 0).flags() & Qt.ItemIsUserCheckable
        ]

    def _zeige_summe(self):
        auswahl = self.ausgewaehlte()
        anzahl = f"{len(auswahl)} Mitglied" + ("" if len(auswahl) == 1 else "er")
        self.summe.setText(f"{anzahl} ausgewählt, Summe: <b>{cent_zu_text(sum(b for _, b in auswahl))}</b>")

    def _pruefen(self):
        betraege = self._lese_betraege()
        if betraege is None:
            QMessageBox.warning(self, "Fehler", "Bitte gültige Beträge eingeben.")
            return
        jahr = self.jahr.value()
        if not any(self.tabelle.item(z, 0).flags() & Qt.ItemIsUserCheckable for z in range(self.tabelle.rowCount())):
            QMessageBox.warning(self, "Fehler", f"Es wird für kein Mitglied ein Beitrag {jahr} fällig.")
            return
        auswahl = self.ausgewaehlte()
        if not auswahl:
            QMessageBox.warning(self, "Fehler", "Bitte mindestens ein Mitglied anhaken.")
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
            f"Beitrag {jahr}: {len(auswahl)} Buchungen über insgesamt "
            f"{cent_zu_text(sum(b for _, b in auswahl))} auf „{self.kasse.currentText()}“ anlegen?",
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
            "konto_ids": [m.id for m, _ in self.ausgewaehlte()],
        }
