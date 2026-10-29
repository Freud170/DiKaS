"""Hauptfenster: Kontenübersicht links, Buchungen des gewählten Kontos rechts."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import sessionmaker

from dikas import __version__, buchhaltung
from dikas.geld import cent_zu_text
from dikas.ui.dialoge import BuchungDialog, KontoDialog

ALLE_BUCHUNGEN = None  # Auswahl "kein Konto" -> alle Buchungen anzeigen


def _zelle(text: str, rechts: bool = False, daten=None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    if rechts:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if daten is not None:
        item.setData(Qt.UserRole, daten)
    return item


def _betrag_zelle(cent: int) -> QTableWidgetItem:
    item = _zelle(cent_zu_text(cent), rechts=True)
    if cent < 0:
        item.setForeground(QColor("#c0392b"))
    return item


class Hauptfenster(QMainWindow):
    def __init__(self, session_factory: sessionmaker, db_pfad: str):
        super().__init__()
        self.Session = session_factory
        self.setWindowTitle(f"DiKaS {__version__} – {db_pfad}")
        self.resize(1200, 700)

        self._baue_werkzeugleiste()

        self.konten_tabelle = self._neue_tabelle(["Konto", "Typ", "Saldo"])
        self.konten_tabelle.itemSelectionChanged.connect(self.lade_buchungen)

        self.buchungen_titel = QLabel()
        self.buchungen_tabelle = self._neue_tabelle(
            ["Datum", "Beleg", "Text", "Von", "Nach", "Betrag", "Status"]
        )
        self.buchungen_tabelle.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        rechts = QWidget()
        layout = QVBoxLayout(rechts)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.buchungen_titel)
        layout.addWidget(self.buchungen_tabelle)

        splitter = QSplitter()
        splitter.addWidget(self.konten_tabelle)
        splitter.addWidget(rechts)
        splitter.setSizes([400, 800])
        self.setCentralWidget(splitter)

        self.aktualisieren()

    # --- Aufbau -----------------------------------------------------------

    def _baue_werkzeugleiste(self):
        leiste = QToolBar("Aktionen")
        leiste.setMovable(False)
        self.addToolBar(leiste)
        for text, kuerzel, slot in (
            ("Neues Konto", "Ctrl+K", self.neues_konto),
            ("Neue Buchung", "Ctrl+N", self.neue_buchung),
            ("Stornieren", None, self.storniere_auswahl),
            ("Alle Buchungen", None, self.zeige_alle_buchungen),
            ("Aktualisieren", "F5", self.aktualisieren),
        ):
            aktion = QAction(text, self)
            if kuerzel:
                aktion.setShortcut(kuerzel)
            aktion.triggered.connect(slot)
            leiste.addAction(aktion)

    @staticmethod
    def _neue_tabelle(spalten: list[str]) -> QTableWidget:
        tabelle = QTableWidget(0, len(spalten))
        tabelle.setHorizontalHeaderLabels(spalten)
        tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        tabelle.setSelectionMode(QAbstractItemView.SingleSelection)
        tabelle.verticalHeader().setVisible(False)
        tabelle.setWordWrap(False)
        tabelle.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        return tabelle

    # --- Daten laden ------------------------------------------------------

    def aktualisieren(self):
        gewaehlt = self._gewaehltes_konto_id()
        self.konten_tabelle.blockSignals(True)
        with self.Session() as session:
            konten = buchhaltung.konten(session)
            salden = buchhaltung.salden(session)
        self.konten_tabelle.setRowCount(len(konten))
        for zeile, konto in enumerate(konten):
            self.konten_tabelle.setItem(zeile, 0, _zelle(konto.name, daten=konto.id))
            self.konten_tabelle.setItem(zeile, 1, _zelle(konto.typ.anzeige))
            self.konten_tabelle.setItem(zeile, 2, _betrag_zelle(salden[konto.id]))
            if konto.id == gewaehlt:
                self.konten_tabelle.selectRow(zeile)
        self.konten_tabelle.blockSignals(False)
        self.lade_buchungen()

    def _gewaehltes_konto_id(self) -> int | None:
        zeilen = self.konten_tabelle.selectionModel().selectedRows()
        if not zeilen:
            return ALLE_BUCHUNGEN
        return self.konten_tabelle.item(zeilen[0].row(), 0).data(Qt.UserRole)

    def lade_buchungen(self):
        konto_id = self._gewaehltes_konto_id()
        with self.Session() as session:
            liste = buchhaltung.buchungen(session, konto_id)
            if konto_id is ALLE_BUCHUNGEN:
                self.buchungen_titel.setText("<b>Alle Buchungen</b>")
            else:
                zeile = self.konten_tabelle.selectionModel().selectedRows()[0].row()
                name = self.konten_tabelle.item(zeile, 0).text()
                self.buchungen_titel.setText(f"<b>Buchungen: {name}</b>")
            self.buchungen_tabelle.setRowCount(len(liste))
            for zeile, b in enumerate(liste):
                # Aus Sicht des gewählten Kontos: Abgang negativ
                betrag = b.betrag_cent
                if konto_id is not ALLE_BUCHUNGEN and b.von_konto_id == konto_id:
                    betrag = -betrag
                status = "storniert" if b.ist_storniert else ("Storno" if b.ist_storno else "")
                werte = [
                    _zelle(b.datum.strftime("%d.%m.%Y"), daten=b.id),
                    _zelle(b.beleg),
                    _zelle(b.text),
                    _zelle(b.von_konto.name),
                    _zelle(b.nach_konto.name),
                    _betrag_zelle(betrag),
                    _zelle(status),
                ]
                for spalte, item in enumerate(werte):
                    if b.ist_storniert or b.ist_storno:
                        item.setForeground(QColor("#888888"))
                    self.buchungen_tabelle.setItem(zeile, spalte, item)

    # --- Aktionen ---------------------------------------------------------

    def zeige_alle_buchungen(self):
        self.konten_tabelle.clearSelection()

    def neues_konto(self):
        dialog = KontoDialog(self)
        if dialog.exec() != KontoDialog.Accepted:
            return
        name, typ, bemerkung = dialog.werte()
        self._ausfuehren(lambda s: buchhaltung.konto_anlegen(s, name, typ, bemerkung))

    def neue_buchung(self):
        with self.Session() as session:
            konten = buchhaltung.konten(session, nur_aktive=True)
        if len(konten) < 2:
            QMessageBox.information(self, "Hinweis", "Es werden mindestens zwei Konten benötigt.")
            return
        dialog = BuchungDialog(konten, self)
        if dialog.exec() != BuchungDialog.Accepted:
            return
        werte = dialog.werte()
        self._ausfuehren(lambda s: buchhaltung.buchen(s, **werte))

    def storniere_auswahl(self):
        zeilen = self.buchungen_tabelle.selectionModel().selectedRows()
        if not zeilen:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst eine Buchung auswählen.")
            return
        buchung_id = self.buchungen_tabelle.item(zeilen[0].row(), 0).data(Qt.UserRole)
        antwort = QMessageBox.question(
            self, "Stornieren", "Diese Buchung wirklich stornieren?\n(Es wird eine Gegenbuchung erzeugt.)"
        )
        if antwort == QMessageBox.Yes:
            self._ausfuehren(lambda s: buchhaltung.stornieren(s, buchung_id))

    def _ausfuehren(self, aktion):
        """Führt eine Änderung in einer Transaktion aus und zeigt Fehler an."""
        try:
            with self.Session.begin() as session:
                aktion(session)
        except buchhaltung.BuchhaltungsFehler as fehler:
            QMessageBox.warning(self, "Fehler", str(fehler))
            return
        self.aktualisieren()
