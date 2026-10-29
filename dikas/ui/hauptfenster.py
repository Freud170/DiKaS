"""Hauptfenster: Kontenübersicht links, Buchungen des gewählten Kontos rechts."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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
from dikas.db.models import Konto, KontoTyp, MitgliedStatus
from dikas.geld import cent_zu_text
from dikas.ui.dialoge import BeitragDialog, BuchungDialog, KontoDialog

ALLE_BUCHUNGEN = None  # Auswahl "kein Konto" -> alle Buchungen anzeigen
GRAU = QColor("#888888")
ROT = QColor("#c0392b")

# Filter für die Kontenliste: Beschriftung -> Prüffunktion
KONTEN_FILTER = {
    "Alle Konten": lambda k: True,
    "Privatkonten": lambda k: k.typ == KontoTyp.PRIVAT,
    **{
        status.mehrzahl: (lambda k, s=status: k.status == s)
        for status in MitgliedStatus
    },
    "Kassen": lambda k: k.typ == KontoTyp.KASSE,
}


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
        item.setForeground(ROT)
    return item


class Hauptfenster(QMainWindow):
    def __init__(self, session_factory: sessionmaker, db_pfad: str):
        super().__init__()
        self.Session = session_factory
        self.setWindowTitle(f"DiKaS {__version__} – {db_pfad}")
        self.resize(1250, 720)

        self._baue_werkzeugleiste()

        self.filter = QComboBox()
        self.filter.addItems(KONTEN_FILTER)
        self.filter.currentIndexChanged.connect(self.aktualisieren)
        self.konten_tabelle = self._neue_tabelle(["Konto", "Typ", "Status", "Saldo"])
        self.konten_tabelle.itemSelectionChanged.connect(self.lade_buchungen)
        self.konten_tabelle.itemDoubleClicked.connect(self.konto_bearbeiten)

        links = QWidget()
        layout = QVBoxLayout(links)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter)
        layout.addWidget(self.konten_tabelle)

        self.buchungen_titel = QLabel()
        self.buchungen_tabelle = self._neue_tabelle(
            ["Datum", "Art", "Beleg", "Text", "Soll", "Haben", "Betrag", "Status"]
        )
        self.buchungen_tabelle.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        rechts = QWidget()
        layout = QVBoxLayout(rechts)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.buchungen_titel)
        layout.addWidget(self.buchungen_tabelle)

        splitter = QSplitter()
        splitter.addWidget(links)
        splitter.addWidget(rechts)
        splitter.setSizes([450, 800])
        self.setCentralWidget(splitter)

        self.abstimmung = QLabel()
        self.statusBar().addPermanentWidget(self.abstimmung)

        self.aktualisieren()

    # --- Aufbau -----------------------------------------------------------

    def _baue_werkzeugleiste(self):
        leiste = QToolBar("Aktionen")
        leiste.setMovable(False)
        self.addToolBar(leiste)
        for text, kuerzel, slot in (
            ("Neues Konto", "Ctrl+K", self.neues_konto),
            ("Konto bearbeiten", None, self.konto_bearbeiten),
            ("Neue Buchung", "Ctrl+N", self.neue_buchung),
            ("Beiträge abbuchen", None, self.beitraege_abbuchen),
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
        passt = KONTEN_FILTER[self.filter.currentText()]
        self.konten_tabelle.blockSignals(True)
        self.konten_tabelle.clearSelection()
        with self.Session() as session:
            konten = [k for k in buchhaltung.konten(session) if passt(k)]
            salden = buchhaltung.salden(session)
            abstimmung = buchhaltung.abstimmung(session)
        self.konten_tabelle.setRowCount(len(konten))
        for zeile, konto in enumerate(konten):
            werte = [
                _zelle(konto.name, daten=konto.id),
                _zelle(konto.typ.anzeige),
                _zelle(konto.status.anzeige if konto.status else ""),
                _betrag_zelle(salden[konto.id]),
            ]
            for spalte, item in enumerate(werte):
                if not konto.aktiv:
                    item.setForeground(GRAU)
                self.konten_tabelle.setItem(zeile, spalte, item)
            if konto.id == gewaehlt:
                self.konten_tabelle.selectRow(zeile)
        self.konten_tabelle.blockSignals(False)

        if abstimmung.stimmt:
            self.abstimmung.setText(f"KW-Konto {cent_zu_text(abstimmung.kw_cent)} ✔ stimmt")
        else:
            self.abstimmung.setText(
                f"<span style='color:#c0392b'>KW {cent_zu_text(abstimmung.kw_cent)} ≠ "
                f"Privatkonten + Kassen {cent_zu_text(abstimmung.verteilt_cent)}</span>"
            )
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
            konto = session.get(Konto, konto_id) if konto_id is not ALLE_BUCHUNGEN else None
            self.buchungen_titel.setText(
                f"<b>Buchungen: {konto.name}</b>" if konto else "<b>Alle Buchungen</b>"
            )
            self.buchungen_tabelle.setRowCount(len(liste))
            for zeile, b in enumerate(liste):
                # Aus Sicht des gewählten Kontos: Wirkung auf dessen Saldo
                betrag = b.wirkung_auf(konto) if konto else b.betrag_cent
                status = "storniert" if b.ist_storniert else ""
                werte = [
                    _zelle(b.datum.strftime("%d.%m.%Y"), daten=b.id),
                    _zelle(b.art.anzeige),
                    _zelle(b.beleg),
                    _zelle(b.text),
                    _zelle(b.soll_konto.name),
                    _zelle(b.haben_konto.name),
                    _betrag_zelle(betrag),
                    _zelle(status),
                ]
                for spalte, item in enumerate(werte):
                    if b.ist_storniert or b.ist_storno:
                        item.setForeground(GRAU)
                    self.buchungen_tabelle.setItem(zeile, spalte, item)

    # --- Aktionen ---------------------------------------------------------

    def zeige_alle_buchungen(self):
        self.konten_tabelle.clearSelection()

    def neues_konto(self):
        dialog = KontoDialog(self)
        if dialog.exec() != KontoDialog.Accepted:
            return
        w = dialog.werte()
        self._ausfuehren(
            lambda s: buchhaltung.konto_anlegen(s, w["name"], w["typ"], w["status"], w["bemerkung"])
        )

    def konto_bearbeiten(self):
        konto_id = self._gewaehltes_konto_id()
        if konto_id is ALLE_BUCHUNGEN:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst ein Konto auswählen.")
            return
        with self.Session() as session:
            konto = session.get(Konto, konto_id)
        dialog = KontoDialog(self, konto)
        if dialog.exec() != KontoDialog.Accepted:
            return
        w = dialog.werte()
        self._ausfuehren(
            lambda s: buchhaltung.konto_bearbeiten(
                s, konto_id, w["name"], w["status"], w["bemerkung"], w["aktiv"]
            )
        )

    def neue_buchung(self):
        with self.Session() as session:
            konten = buchhaltung.konten(session, nur_aktive=True)
        dialog = BuchungDialog(konten, self)
        if dialog.exec() != BuchungDialog.Accepted:
            return
        werte = dialog.werte()
        self._ausfuehren(lambda s: buchhaltung.buchen(s, **werte))

    def beitraege_abbuchen(self):
        with self.Session() as session:
            kassen = [k for k in buchhaltung.konten(session, nur_aktive=True) if k.typ == KontoTyp.KASSE]
        if not kassen:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst eine Kasse für die Beiträge anlegen.")
            return

        def vorschau(betraege):
            with self.Session() as session:
                return buchhaltung.beitrag_vorschau(session, betraege)

        dialog = BeitragDialog(kassen, vorschau, self)
        if dialog.exec() != BeitragDialog.Accepted:
            return
        werte = dialog.werte()
        if self._ausfuehren(lambda s: buchhaltung.beitraege_abbuchen(s, **werte)):
            self.statusBar().showMessage("Beiträge wurden gebucht.", 5000)

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

    def _ausfuehren(self, aktion) -> bool:
        """Führt eine Änderung in einer Transaktion aus und zeigt Fehler an."""
        try:
            with self.Session.begin() as session:
                aktion(session)
        except buchhaltung.BuchhaltungsFehler as fehler:
            QMessageBox.warning(self, "Fehler", str(fehler))
            return False
        self.aktualisieren()
        return True
