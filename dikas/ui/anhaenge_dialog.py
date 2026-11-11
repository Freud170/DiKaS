"""Rechnungen (Bilder/PDFs) an Buchungen: Auswahl beim Buchen und Verwaltung bestehender Anhänge."""

from html import escape
from pathlib import Path
from collections.abc import Callable, Sequence

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import sessionmaker

from dikas import anhaenge
from dikas.buchhaltung import BuchhaltungsFehler
from dikas.db.models import Anhang, Buchung
from dikas.geld import cent_zu_text
from dikas.ui import stil
from dikas.ui.bausteine import zelle

# Liefert die gewählten Dateipfade (leer = abgebrochen); in Tests ersetzbar
DateiWaehler = Callable[[QWidget], list[str]]


def dateien_waehlen(parent: QWidget) -> list[str]:
    start = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
    pfade, _ = QFileDialog.getOpenFileNames(parent, "Rechnungen auswählen", start, anhaenge.DATEIFILTER)
    return pfade


def _symbol_fuer(mime_typ: str):
    return stil.symbol("DocumentNew" if mime_typ == anhaenge.PDF else "InsertImage")


def gezogene_dateien(ereignis) -> list[Path]:
    daten = ereignis.mimeData()
    if not daten.hasUrls():
        return []
    return [Path(u.toLocalFile()) for u in daten.urls() if u.isLocalFile()]


def vorbereiten_mit_meldung(parent: QWidget, pfade: Sequence[str | Path]) -> list[anhaenge.Datei]:
    """Bereitet die Dateien vor; nicht passende werden gesammelt gemeldet und ausgelassen."""
    fertig, fehler = [], []
    for pfad in pfade:
        try:
            fertig.append(anhaenge.datei_vorbereiten(pfad))
        except anhaenge.AnhangFehler as f:
            fehler.append(str(f))
    if fehler:
        QMessageBox.warning(parent, "Nicht angehängt", "\n\n".join(fehler))
    return fertig


class AnhangAuswahl(QWidget):
    """Dateiliste im Buchungsdialog: Rechnungen, die mit der neuen Buchung gespeichert werden.

    Dateien lassen sich auch aus dem Explorer auf den Dialog ziehen.
    """

    def __init__(self, parent=None, waehler: DateiWaehler = dateien_waehlen):
        super().__init__(parent)
        self.waehler = waehler
        self.dateien: list[anhaenge.Datei] = []
        self.liste = QListWidget()
        self.liste.setMaximumHeight(84)
        self.liste.setSelectionMode(QAbstractItemView.ExtendedSelection)
        hinzu = QPushButton(stil.symbol("ListAdd"), "Datei …")
        hinzu.setAutoDefault(False)
        hinzu.setToolTip("Rechnung als PDF oder Foto anhängen (oder Datei hierher ziehen)")
        hinzu.clicked.connect(self.hinzufuegen)
        self.weg = QPushButton(stil.symbol("ListRemove"), "")
        self.weg.setAutoDefault(False)
        self.weg.setToolTip("Markierte Datei wieder entfernen")
        self.weg.clicked.connect(self.entfernen)
        knoepfe = QVBoxLayout()
        knoepfe.addWidget(hinzu)
        knoepfe.addWidget(self.weg)
        knoepfe.addStretch()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.liste, 1)
        layout.addLayout(knoepfe)
        self._aktualisieren()

    def hinzufuegen(self):
        self.dateien_dazu(self.waehler(self))

    def dateien_dazu(self, pfade: Sequence[str | Path]):
        if pfade:
            self.dateien += vorbereiten_mit_meldung(self, pfade)
            self._aktualisieren()

    def entfernen(self):
        weg = {i.row() for i in self.liste.selectedIndexes()}
        self.dateien = [d for i, d in enumerate(self.dateien) if i not in weg]
        self._aktualisieren()

    def _aktualisieren(self):
        self.liste.clear()
        for d in self.dateien:
            QListWidgetItem(_symbol_fuer(d.mime_typ), f"{d.dateiname}  ({anhaenge.groesse_text(d.groesse)})", self.liste)
        if not self.dateien:
            leer = QListWidgetItem("Keine – Dateien hierher ziehen oder „Datei …“", self.liste)
            leer.setFlags(Qt.NoItemFlags)
        self.liste.setMaximumHeight(84 if len(self.dateien) < 3 else 120)
        self.weg.setEnabled(bool(self.dateien))


class AnhaengeDialog(QDialog):
    """Rechnungen einer bestehenden Buchung ansehen, ergänzen, speichern und entfernen.

    Jede Änderung wird sofort gespeichert; `geaendert` sagt dem Hauptfenster, ob es neu laden muss.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        buchung_id: int,
        parent=None,
        waehler: DateiWaehler = dateien_waehlen,
        oeffner: Callable[[QUrl], object] = QDesktopServices.openUrl,
    ):
        super().__init__(parent)
        self.Session = session_factory
        self.buchung_id = buchung_id
        self.waehler = waehler
        self.oeffner = oeffner
        self.geaendert = False
        self.setWindowTitle("Rechnungen zur Buchung")
        self.setAcceptDrops(True)
        self.resize(640, 380)

        self.kopf = QLabel()
        self.kopf.setWordWrap(True)
        self.tabelle = stil.tabelle(["Datei", "Größe", "Angehängt am"], rechts=[1])
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabelle.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tabelle.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabelle.itemDoubleClicked.connect(self.oeffnen)
        self.tabelle.itemSelectionChanged.connect(self._knoepfe_aktualisieren)
        hinweis = QLabel("Dateien lassen sich auch aus dem Explorer hierher ziehen. Große Fotos werden "
                         "beim Anhängen verkleinert.")
        hinweis.setObjectName("hinweis")
        hinweis.setWordWrap(True)

        self.hinzu_knopf = QPushButton(stil.symbol("ListAdd"), "Datei anhängen …")
        self.hinzu_knopf.clicked.connect(self.hinzufuegen)
        self.oeffnen_knopf = QPushButton(stil.symbol("DocumentOpen"), "Öffnen")
        self.oeffnen_knopf.clicked.connect(self.oeffnen)
        self.speichern_knopf = QPushButton(stil.symbol("DocumentSaveAs"), "Speichern unter …")
        self.speichern_knopf.clicked.connect(self.speichern_unter)
        self.entfernen_knopf = QPushButton(stil.symbol("EditDelete"), "Entfernen")
        self.entfernen_knopf.clicked.connect(self.entfernen)
        schliessen = QPushButton("Schließen")
        schliessen.clicked.connect(self.accept)
        for knopf in (self.hinzu_knopf, self.oeffnen_knopf, self.speichern_knopf, self.entfernen_knopf, schliessen):
            knopf.setAutoDefault(False)
        unten = QHBoxLayout()
        unten.addWidget(self.hinzu_knopf)
        unten.addWidget(self.oeffnen_knopf)
        unten.addWidget(self.speichern_knopf)
        unten.addWidget(self.entfernen_knopf)
        unten.addStretch()
        unten.addWidget(schliessen)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(self.kopf)
        layout.addWidget(self.tabelle, 1)
        layout.addWidget(hinweis)
        layout.addLayout(unten)
        self.laden()

    # --- Daten ------------------------------------------------------------

    def laden(self):
        with self.Session() as session:
            buchung = session.get(Buchung, self.buchung_id)
            if buchung is None:
                self.kopf.setText("Diese Buchung gibt es nicht mehr.")
                self.eintraege: list[Anhang] = []
                self.hinzu_knopf.setEnabled(False)
            else:
                self.kopf.setText(
                    f"<b>{buchung.datum:%d.%m.%Y} · {buchung.art.anzeige} · "
                    f"{cent_zu_text(buchung.betrag_cent)}</b><br>{escape(buchung.text)}"
                )
                self.eintraege = list(buchung.anhaenge)
                self.hinzu_knopf.setEnabled(not buchung.ist_storno)
        self.tabelle.setRowCount(len(self.eintraege))
        for zeile, a in enumerate(self.eintraege):
            name = zelle(a.dateiname, daten=a.id)
            name.setIcon(_symbol_fuer(a.mime_typ))
            self.tabelle.setItem(zeile, 0, name)
            self.tabelle.setItem(zeile, 1, zelle(anhaenge.groesse_text(a.groesse), rechts=True))
            self.tabelle.setItem(zeile, 2, zelle(f"{a.erstellt_am:%d.%m.%Y %H:%M}"))
        if self.eintraege:
            self.tabelle.selectRow(0)
        self._knoepfe_aktualisieren()

    def _gewaehlte_ids(self) -> list[int]:
        zeilen = sorted(i.row() for i in self.tabelle.selectionModel().selectedRows())
        return [self.tabelle.item(z, 0).data(Qt.UserRole) for z in zeilen]

    def _knoepfe_aktualisieren(self):
        anzahl = len(self._gewaehlte_ids())
        self.oeffnen_knopf.setEnabled(anzahl > 0)
        self.speichern_knopf.setEnabled(anzahl == 1)
        self.entfernen_knopf.setEnabled(anzahl > 0)

    # --- Aktionen ---------------------------------------------------------

    def hinzufuegen(self):
        self.dateien_anhaengen(self.waehler(self))

    def dateien_anhaengen(self, pfade: Sequence[str | Path]):
        dateien = vorbereiten_mit_meldung(self, pfade) if pfade else []
        if not dateien:
            return
        try:
            with self.Session.begin() as session:
                for d in dateien:
                    anhaenge.anhaengen(session, self.buchung_id, d)
        except BuchhaltungsFehler as fehler:
            QMessageBox.warning(self, "Fehler", str(fehler))
            return
        self.geaendert = True
        self.laden()

    def oeffnen(self, *_):
        try:
            with self.Session() as session:
                pfade = [anhaenge.zum_ansehen(session, i) for i in self._gewaehlte_ids()]
        except (BuchhaltungsFehler, OSError) as fehler:
            QMessageBox.warning(self, "Fehler", f"Die Datei konnte nicht geöffnet werden:\n{fehler}")
            return
        for pfad in pfade:
            self.oeffner(QUrl.fromLocalFile(str(pfad)))

    def speichern_unter(self):
        ids = self._gewaehlte_ids()
        if len(ids) != 1:
            return
        name = next(a.dateiname for a in self.eintraege if a.id == ids[0])
        start = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)) / name
        ziel, _ = QFileDialog.getSaveFileName(self, "Rechnung speichern", str(start))
        if not ziel:
            return
        try:
            with self.Session() as session:
                anhaenge.speichern_unter(session, ids[0], ziel)
        except (BuchhaltungsFehler, OSError) as fehler:
            QMessageBox.warning(self, "Fehler", f"Speichern fehlgeschlagen:\n{fehler}")

    def entfernen(self):
        ids = self._gewaehlte_ids()
        if not ids:
            return
        namen = "\n".join(f"• {a.dateiname}" for a in self.eintraege if a.id in ids)
        antwort = QMessageBox.question(
            self, "Rechnung entfernen",
            f"Diese Datei(en) von der Buchung entfernen?\n\n{namen}\n\n"
            "Die Buchung selbst bleibt unverändert. Ältere Stände stecken noch in den Sicherungen.",
        )
        if antwort != QMessageBox.Yes:
            return
        try:
            with self.Session.begin() as session:
                for i in ids:
                    anhaenge.entfernen(session, i)
        except BuchhaltungsFehler as fehler:
            QMessageBox.warning(self, "Fehler", str(fehler))
        self.geaendert = True
        self.laden()

    # --- Ziehen und Ablegen -----------------------------------------------

    def dragEnterEvent(self, ereignis):
        if gezogene_dateien(ereignis) and self.hinzu_knopf.isEnabled():
            ereignis.acceptProposedAction()

    def dropEvent(self, ereignis):
        self.dateien_anhaengen(gezogene_dateien(ereignis))
