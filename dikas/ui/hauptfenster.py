"""Hauptfenster: Kennzahlen oben, Kontenübersicht links, Buchungen des gewählten Kontos rechts."""

import sqlite3
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, QSettings, QSize, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import sessionmaker

from dikas import __version__, anhaenge, buchhaltung, datenaustausch, sicherung
from dikas.db import init_db
from dikas.db.models import Buchung, Buchungsart, Konto, KontoTyp, MitgliedStatus
from dikas.geld import cent_zu_text
from dikas.ui import stil
from dikas.ui.anhaenge_dialog import AnhaengeDialog
from dikas.ui.auswertung import AuswertungDialog
from dikas.ui.einstellungen_dialog import einstellungen_bearbeiten
from dikas.ui.sicherungen_dialog import SicherungenDialog
from dikas.ui.versand_dialog import VersandDialog
from dikas.ui.bausteine import GRAU, Kennzahl, Panel, Spaltenbreiten
from dikas.ui.bausteine import betrag_zelle as _betrag_zelle
from dikas.ui.bausteine import zelle as _zelle
from dikas.ui.dialoge import BeitragDialog, BuchungDialog, KontoDialog

ALLE_BUCHUNGEN = None  # Auswahl "kein Konto" -> alle Buchungen anzeigen

# Filter für die Kontenliste: Beschriftung -> Prüffunktion.
# Gelöschte Konten erscheinen nur unter "Gelöschte".
KONTEN_FILTER = {
    "Alle Konten": lambda k: not k.geloescht,
    "Privatkonten": lambda k: not k.geloescht and k.typ == KontoTyp.PRIVAT,
    **{
        status.mehrzahl: (lambda k, s=status: not k.geloescht and k.status == s)
        for status in MitgliedStatus
    },
    "Kassen": lambda k: not k.geloescht and k.typ == KontoTyp.KASSE,
    "Geldorte": lambda k: not k.geloescht and k.typ == KontoTyp.KW,
    "Gelöschte": lambda k: k.geloescht,
}

# Spalten der Kontenliste
NACHNAME, VORNAME, BIERSPITZ, TYP, STATUS, EINTRITT, SALDO = range(7)
KONTEN_SPALTEN = ["Nachname", "Vorname", "Bierspitz", "Typ", "Status", "Eintritt", "Saldo"]
# Am ersten Feld jeder Zeile: voller Kontoname (z. B. "Tom Becker"), unabhängig von der Spaltenaufteilung
NAME_ROLLE = Qt.UserRole + 1

# Sortierung der Kontenliste: Beschriftung -> (Spalte, absteigend); None = nach Typ, dann Nachname.
# Ein Klick auf die Spaltenüberschrift wählt den passenden Eintrag (zweiter Klick: umgekehrt).
KONTEN_SORTIERUNG = {
    "Sortierung: Standard": None,
    "Nachname A–Z": (NACHNAME, False),
    "Nachname Z–A": (NACHNAME, True),
    "Vorname A–Z": (VORNAME, False),
    "Vorname Z–A": (VORNAME, True),
    "Bierspitz A–Z": (BIERSPITZ, False),
    "Bierspitz Z–A": (BIERSPITZ, True),
    "Status (Fux zuerst)": (STATUS, False),
    "Status (Fux zuletzt)": (STATUS, True),
    "Eintritt: älteste zuerst": (EINTRITT, False),
    "Eintritt: neueste zuerst": (EINTRITT, True),
    "Saldo: niedrigster zuerst": (SALDO, False),
    "Saldo: höchster zuerst": (SALDO, True),
}


def _hat_namensteile(konto: Konto) -> bool:
    return konto.typ == KontoTyp.PRIVAT and bool(konto.vorname or konto.nachname)


def _sortierwert(spalte: int, konto: Konto, saldo: int):
    """Wert, nach dem eine Spalte sortiert; None = leer (steht immer unten)."""
    if spalte == VORNAME:
        return buchhaltung.sortierform(konto.vorname) if _hat_namensteile(konto) and konto.vorname else None
    if spalte == NACHNAME:
        return buchhaltung.sortierschluessel(konto) if _hat_namensteile(konto) and konto.nachname else None
    if spalte == BIERSPITZ:
        return buchhaltung.sortierform(konto.bierspitz) or None
    if spalte == STATUS:
        return list(MitgliedStatus).index(konto.status) if konto.status else None
    if spalte == EINTRITT:
        return konto.eintrittsdatum
    return saldo


def sortiere_konten(konten: list[Konto], salden: dict[int, int], sortierung) -> list[Konto]:
    """Grundordnung: Geldorte, Kassen, Mitglieder (je nach Nachname); dann die gewählte Spalte."""
    basis = sorted(konten, key=lambda k: (k.typ.reihenfolge, buchhaltung.sortierschluessel(k)))
    if sortierung is None:
        return basis
    spalte, absteigend = sortierung
    werte = {k.id: _sortierwert(spalte, k, salden.get(k.id, 0)) for k in basis}
    mit_wert = [k for k in basis if werte[k.id] is not None]
    # sort() ist stabil (auch rückwärts): Gleichstände bleiben in der Grundordnung
    mit_wert.sort(key=lambda k: werte[k.id], reverse=absteigend)
    return mit_wert + [k for k in basis if werte[k.id] is None]


class Hauptfenster(QMainWindow):
    def __init__(self, session_factory: sessionmaker, db_pfad: str):
        super().__init__()
        self.Session = session_factory
        self.db_pfad = db_pfad
        self._vor_loeschen_gesichert = False  # siehe _sichern_vor_loeschen
        # Zuletzt geladener Stand (siehe aktualisieren): Suche/Filter arbeiten darauf, ohne neu zu lesen
        self._konten: list[Konto] = []
        self._salden: dict[int, int] = {}
        self._buchungen: tuple[int | None, list[Buchung]] | None = None  # (Konto-ID, Buchungen)
        self.setWindowTitle(f"DiKaS {__version__} – {db_pfad}")
        self.resize(1320, 780)

        self._baue_werkzeugleiste()

        # Kennzahlen
        self.karte_kw = Kennzahl("KW-Bestand")
        self.karte_kassen = Kennzahl("Kassen gesamt")
        self.karte_guthaben = Kennzahl("Guthaben Mitglieder")
        self.karte_offen = Kennzahl("Offen bei Mitgliedern")
        kennzahlen = QHBoxLayout()
        kennzahlen.setSpacing(12)
        for karte in (self.karte_kw, self.karte_kassen, self.karte_guthaben, self.karte_offen):
            kennzahlen.addWidget(karte)

        # Konten
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Name, Bierspitz oder E-Mail suchen …")
        self.suche.setClearButtonEnabled(True)
        self.suche.addAction(stil.symbol("EditFind"), QLineEdit.LeadingPosition)
        self.suche.textChanged.connect(self._zeige_konten)
        self.filter = QComboBox()
        self.filter.addItems(KONTEN_FILTER)
        self.filter.currentIndexChanged.connect(self._zeige_konten)
        self.sortierung = QComboBox()
        self.sortierung.addItems(KONTEN_SORTIERUNG)
        self.sortierung.setToolTip("Reihenfolge der Konten (auch per Klick auf die Spaltenüberschrift)")
        self.sortierung.currentIndexChanged.connect(self._zeige_konten)
        self.konten_tabelle = self._neue_tabelle(KONTEN_SPALTEN, rechts=[SALDO])
        self.konten_breiten = Spaltenbreiten(self.konten_tabelle)
        kopf = self.konten_tabelle.horizontalHeader()
        kopf.setSectionsClickable(True)
        kopf.sectionClicked.connect(self._sortiere_nach_spalte)
        # Spalten verschieben (ziehen) und per Rechtsklick ein-/ausblenden; wird pro PC gemerkt
        kopf.setSectionsMovable(True)
        kopf.setContextMenuPolicy(Qt.CustomContextMenu)
        kopf.customContextMenuRequested.connect(
            lambda pos: self.spalten_menue().exec(kopf.mapToGlobal(pos))
        )
        self._lade_spalten()
        kopf.sectionMoved.connect(self._speichere_spalten)
        self.konten_tabelle.itemSelectionChanged.connect(self.lade_buchungen)
        self.konten_tabelle.itemDoubleClicked.connect(self.konto_bearbeiten)

        links = Panel("Konten")
        auswahl = QHBoxLayout()
        self.suche.setMinimumWidth(170)
        # Auswahllisten nicht so breit wie ihr längster Eintrag, sonst bleibt fürs Suchfeld nichts übrig
        for liste in (self.filter, self.sortierung):
            liste.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            liste.setMinimumContentsLength(12)
        auswahl.addWidget(self.suche, 3)
        auswahl.addWidget(self.filter, 2)
        auswahl.addWidget(self.sortierung, 2)
        links.layout_.addLayout(auswahl)
        links.layout_.addWidget(self.konten_tabelle)
        self.konten_info = links.info

        # Buchungen
        self.buchungen_tabelle = self._neue_tabelle(
            ["Datum", "Art", "Beleg", "Text", "Soll", "Haben", "Betrag", "Status"], rechts=[6]
        )
        self.buchungen_breiten = Spaltenbreiten(self.buchungen_tabelle, verteilen_auf=3)  # Text
        self._klammer = stil.symbol("MailAttachment")  # Buchung hat Rechnungen

        rechts = Panel("")
        self.buchungen_titel = rechts.titel
        self.buchungen_info = rechts.info
        # Aktionen für die ausgewählte Buchung in eigener Zeile über der Liste
        # (auch per Doppelklick/Rechtsklick)
        # Suche in eigener Zeile, damit die Kontenliste links genug Breite behält
        self.buchungssuche = QLineEdit()
        self.buchungssuche.setPlaceholderText("Text, Beleg oder Betrag suchen …")
        self.buchungssuche.setToolTip(
            "Sucht in Text, Beleg und Kontonamen. Eine Zahl wie 25 oder 12,50 findet\n"
            "außerdem alle Buchungen über genau diesen Betrag."
        )
        self.buchungssuche.setClearButtonEnabled(True)
        self.buchungssuche.addAction(stil.symbol("EditFind"), QLineEdit.LeadingPosition)
        self.buchungssuche.textChanged.connect(self.lade_buchungen)
        rechts.layout_.addWidget(self.buchungssuche)
        aktionen = QHBoxLayout()
        for text, icon, tipp, slot in (
            ("Korrigieren", "MailMessageNew", "Ausgewählte Buchung korrigieren (Doppelklick)",
             self.korrigiere_auswahl),
            ("Stornieren", "EditUndo", "Ausgewählte Buchung stornieren (Gegenbuchung)", self.storniere_auswahl),
            ("Rechnungen", "MailAttachment", "Rechnungen (PDFs, Fotos) der Buchung ansehen und anhängen",
             self.rechnungen_auswahl),
            ("Löschen", "EditDelete", "Ausgewählte Buchungen endgültig löschen (Entf)", self.loesche_auswahl),
            ("Alle anzeigen", None, "Auswahl aufheben und alle Buchungen anzeigen", self.zeige_alle_buchungen),
        ):
            knopf = QToolButton()
            knopf.setText(text)
            knopf.setToolTip(tipp)
            if icon:
                knopf.setIcon(stil.symbol(icon))
                knopf.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            knopf.clicked.connect(slot)
            if text == "Alle anzeigen":
                aktionen.addStretch()
            aktionen.addWidget(knopf)
        rechts.layout_.addLayout(aktionen)
        self.buchungen_tabelle.itemDoubleClicked.connect(self.korrigiere_auswahl)
        # Mehrere Buchungen markierbar (Strg/Umschalt) – zum gemeinsamen Löschen
        self.buchungen_tabelle.setSelectionMode(QAbstractItemView.ExtendedSelection)
        entf = QShortcut(QKeySequence.Delete, self.buchungen_tabelle, self.loesche_auswahl)
        entf.setContext(Qt.WidgetShortcut)
        self.buchungen_tabelle.setContextMenuPolicy(Qt.CustomContextMenu)
        self.buchungen_tabelle.customContextMenuRequested.connect(self._buchungs_menue)
        rechts.layout_.addWidget(self.buchungen_tabelle)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(links)
        splitter.addWidget(rechts)
        splitter.setSizes([740, 580])  # links genug Platz für Nachname, Vorname, Bierspitz, Status, Eintritt, Saldo
        # Bei jeder Fenstergröße neu aufteilen (Vollbild: Buchungen bekommen mehr) –
        # bis der Trenner von Hand gezogen wird, dann gilt die eigene Aufteilung
        self.splitter = splitter
        self._aufteilung_manuell = False
        splitter.splitterMoved.connect(lambda *_: setattr(self, "_aufteilung_manuell", True))
        splitter.installEventFilter(self)

        inhalt = QWidget()
        layout = QVBoxLayout(inhalt)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(14)
        layout.addLayout(kennzahlen)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(inhalt)

        self.abstimmung = QLabel()
        self.statusBar().addPermanentWidget(self.abstimmung)

        self.aktualisieren()

    # --- Aufbau -----------------------------------------------------------

    def _baue_werkzeugleiste(self):
        leiste = QToolBar("Aktionen")
        leiste.setMovable(False)
        leiste.setFloatable(False)
        leiste.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        leiste.setContextMenuPolicy(Qt.PreventContextMenu)
        leiste.setIconSize(QSize(18, 18))
        self.addToolBar(leiste)

        gruppen = (
            (
                ("Neue Buchung", "ListAdd", "Ctrl+N", self.neue_buchung, True),
                ("Beiträge abbuchen", "DocumentNew", "Ctrl+B", self.beitraege_abbuchen, False),
            ),
            (
                ("Neues Konto", "ContactNew", "Ctrl+K", self.neues_konto, False),
                ("Bearbeiten", "MailMessageNew", "Ctrl+E", self.konto_bearbeiten, False),
                ("Löschen", "EditDelete", None, self.konto_loeschen, False),
                ("Wiederherstellen", "DocumentRevert", None, self.konto_wiederherstellen, False),
            ),
            (
                ("Auswertung", "DocumentPrintPreview", "Ctrl+P", self.auswertung, False),
                ("Kontoauszüge", "MailSend", "Ctrl+M", self.kontoauszuege, False),
            ),
        )
        for i, gruppe in enumerate(gruppen):
            if i:
                leiste.addSeparator()
            for text, icon, kuerzel, slot, primaer in gruppe:
                self._aktion(leiste, text, icon, kuerzel, slot, primaer)

        abstand = QWidget()
        abstand.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        leiste.addWidget(abstand)
        # Rechts nur ein Symbol mit Menü, damit die Leiste nicht überläuft
        menue = QMenu(self)
        menue.addAction(stil.symbol("DocumentSaveAs"), "Daten exportieren (für anderen PC) …", self.daten_exportieren)
        menue.addAction(stil.symbol("DocumentOpen"), "Daten importieren (von anderem PC) …", self.daten_importieren)
        menue.addSeparator()
        menue.addAction(stil.symbol("DocumentRevert"), "Sicherungen …", self.sicherungen)
        menue.addAction(stil.symbol("FolderOpen"), "Datenordner öffnen", self.datenordner_oeffnen)
        menue.addSeparator()
        menue.addAction(stil.symbol("DocumentProperties"), "Einstellungen …", self.einstellungen)
        menue.addAction(stil.symbol("SyncSynchronizing"), "Update installieren …", self.update_installieren)
        self.extras_knopf = QToolButton()
        self.extras_knopf.setIcon(stil.symbol("DocumentProperties"))
        self.extras_knopf.setToolTip("Daten, Sicherungen und Einstellungen")
        self.extras_knopf.setMenu(menue)
        self.extras_knopf.setPopupMode(QToolButton.InstantPopup)
        leiste.addWidget(self.extras_knopf)
        # Aktualisieren nur per Taste: nach jeder Änderung wird ohnehin neu geladen
        neu_laden = QAction("Aktualisieren", self)
        neu_laden.setShortcut("F5")
        neu_laden.triggered.connect(self.aktualisieren)
        self.addAction(neu_laden)

    def _aktion(self, leiste, text, icon, kuerzel, slot, primaer, nur_symbol=False):
        aktion = QAction(stil.symbol(icon), text, self)
        if kuerzel:
            aktion.setShortcut(kuerzel)
            aktion.setToolTip(f"{text} ({QKeySequence(kuerzel).toString(QKeySequence.NativeText)})")
        aktion.triggered.connect(slot)
        leiste.addAction(aktion)
        knopf = leiste.widgetForAction(aktion)
        if primaer:
            knopf.setObjectName("primaer")
        if nur_symbol:
            knopf.setToolButtonStyle(Qt.ToolButtonIconOnly)

    @staticmethod
    def _neue_tabelle(spalten: list[str], rechts: list[int] = ()) -> QTableWidget:
        tabelle = stil.tabelle(spalten, rechts)
        tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        tabelle.setSelectionMode(QAbstractItemView.SingleSelection)
        return tabelle

    # --- Daten laden ------------------------------------------------------

    def aktualisieren(self):
        """Alles neu aus der Datenbank laden und anzeigen (nach jeder Änderung und per F5)."""
        with self.Session() as session:
            self._konten = buchhaltung.konten(session)
            self._salden = buchhaltung.salden(session)
            abstimmung = buchhaltung.abstimmung(session, self._salden)
        self._buchungen = None  # Buchungsliste beim nächsten Anzeigen neu laden

        self._aktualisiere_kennzahlen(self._konten, self._salden)
        if abstimmung.stimmt:
            self.abstimmung.setObjectName("abstimmungOk")
            self.abstimmung.setText("✔ Kasse stimmt: KW = Privatkonten + Kassen")
        else:
            self.abstimmung.setObjectName("abstimmungFehler")
            self.abstimmung.setText(
                f"✖ KW {cent_zu_text(abstimmung.kw_cent)} ≠ "
                f"Privatkonten + Kassen {cent_zu_text(abstimmung.verteilt_cent)}"
            )
        # Objektname geändert -> Stil neu anwenden
        self.abstimmung.style().unpolish(self.abstimmung)
        self.abstimmung.style().polish(self.abstimmung)
        self._zeige_konten()

    def _zeige_konten(self, *_):
        """Kontenliste aus den geladenen Daten neu aufbauen.

        Suche, Filter und Sortierung ändern nichts an den Daten – dafür muss die Datenbank
        nicht bei jedem Tastendruck neu gelesen werden.
        """
        gewaehlt = self._gewaehltes_konto_id()
        passt = KONTEN_FILTER[self.filter.currentText()]
        suchtext = self.suche.text().strip().lower()
        self.konten_tabelle.blockSignals(True)
        self.konten_tabelle.clearSelection()
        alle, salden = self._konten, self._salden
        sortierung = KONTEN_SORTIERUNG[self.sortierung.currentText()]
        konten = sortiere_konten(
            [k for k in alle if passt(k) and suchtext in f"{k.name} {k.bierspitz} {k.email}".lower()],
            salden,
            sortierung,
        )

        kopf = self.konten_tabelle.horizontalHeader()
        kopf.setSortIndicatorShown(sortierung is not None)
        if sortierung is not None:
            kopf.setSortIndicator(sortierung[0], Qt.DescendingOrder if sortierung[1] else Qt.AscendingOrder)

        self.konten_tabelle.setRowCount(len(konten))
        for zeile, konto in enumerate(konten):
            if _hat_namensteile(konto):
                namen = [_zelle(konto.nachname), _zelle(konto.vorname)]
            else:
                # Kassen, Geldorte: Name in der ersten Spalte
                namen = [_zelle(konto.name), _zelle("")]
            namen[0].setData(Qt.UserRole, konto.id)
            namen[0].setData(NAME_ROLLE, konto.name)
            werte = [
                *namen,
                _zelle(konto.bierspitz),
                _zelle(konto.typ.anzeige),
                _zelle(konto.status.anzeige if konto.status else ""),
                _zelle(konto.eintrittsdatum.strftime("%d.%m.%Y") if konto.eintrittsdatum else ""),
                _betrag_zelle(salden[konto.id], fett=True),
            ]
            for spalte, item in enumerate(werte):
                if not konto.aktiv or konto.geloescht:
                    item.setForeground(GRAU)
                self.konten_tabelle.setItem(zeile, spalte, item)
            if konto.id == gewaehlt:
                self.konten_tabelle.selectRow(zeile)
        self.konten_tabelle.blockSignals(False)
        self.konten_breiten.anpassen()
        self.konten_info.setText(f"{len(konten)} von {len(alle)}")
        self.lade_buchungen()

    def _aktualisiere_kennzahlen(self, konten: list[Konto], salden: dict[int, int]):
        privat = [salden[k.id] for k in konten if k.typ == KontoTyp.PRIVAT]
        kassen = sum(salden[k.id] for k in konten if k.typ == KontoTyp.KASSE)
        kw = sum(salden[k.id] for k in konten if k.typ == KontoTyp.KW)
        guthaben = sum(s for s in privat if s > 0)
        offen = -sum(s for s in privat if s < 0)
        self.karte_kw.setze(kw, stil.NEGATIV if kw < 0 else None)
        self.karte_kassen.setze(kassen, stil.NEGATIV if kassen < 0 else None)
        self.karte_guthaben.setze(guthaben)
        self.karte_offen.setze(offen, stil.NEGATIV if offen else None)

    KONTEN_MINDESTBREITE = 740

    def eventFilter(self, objekt, ereignis):
        if objekt is getattr(self, "splitter", None) and ereignis.type() == QEvent.Resize:
            self._splitter_aufteilen()
        return super().eventFilter(objekt, ereignis)

    def _splitter_aufteilen(self):
        """Konten 45 % der Breite (mind. 740 px für alle Spalten), Rest für die Buchungen."""
        if self._aufteilung_manuell:
            return
        gesamt = self.splitter.width() - self.splitter.handleWidth()
        links = min(max(self.KONTEN_MINDESTBREITE, int(gesamt * 0.45)), gesamt - 400)
        if links > 0:
            self.splitter.setSizes([links, gesamt - links])

    # --- Spalten der Kontenliste (Reihenfolge, Sichtbarkeit) --------------

    @staticmethod
    def _einstellungen() -> QSettings:
        """Ansichtseinstellungen dieses PCs (%APPDATA%\\DiKaS\\DiKaS.ini), nicht in der Vereinsdatenbank."""
        return QSettings(QSettings.IniFormat, QSettings.UserScope, "DiKaS", "DiKaS")

    def _lade_spalten(self):
        kopf = self.konten_tabelle.horizontalHeader()
        e = self._einstellungen()
        try:
            reihenfolge = [int(s) for s in str(e.value("konten/reihenfolge", "")).split(",") if s]
            versteckt = {int(s) for s in str(e.value("konten/ausgeblendet", "")).split(",") if s}
        except ValueError:
            return
        if sorted(reihenfolge) == list(range(len(KONTEN_SPALTEN))):
            for ziel, spalte in enumerate(reihenfolge):
                kopf.moveSection(kopf.visualIndex(spalte), ziel)
        for spalte in versteckt - {NACHNAME}:
            if 0 <= spalte < len(KONTEN_SPALTEN):
                kopf.setSectionHidden(spalte, True)

    def _speichere_spalten(self, *_):
        kopf = self.konten_tabelle.horizontalHeader()
        anzahl = len(KONTEN_SPALTEN)
        e = self._einstellungen()
        e.setValue("konten/reihenfolge", ",".join(str(kopf.logicalIndex(v)) for v in range(anzahl)))
        e.setValue("konten/ausgeblendet", ",".join(str(s) for s in range(anzahl) if kopf.isSectionHidden(s)))

    def spalten_menue(self) -> QMenu:
        """Rechtsklick auf die Spaltenüberschrift: Spalten ein-/ausblenden, Standard wiederherstellen."""
        kopf = self.konten_tabelle.horizontalHeader()
        menue = QMenu(self)
        for spalte, titel in enumerate(KONTEN_SPALTEN):
            aktion = menue.addAction(titel)
            aktion.setCheckable(True)
            aktion.setChecked(not kopf.isSectionHidden(spalte))
            aktion.setEnabled(spalte != NACHNAME)  # Nachname/Kontoname bleibt immer sichtbar
            aktion.toggled.connect(lambda an, s=spalte: self.spalte_zeigen(s, an))
        menue.addSeparator()
        menue.addAction("Standardansicht", self.spalten_zuruecksetzen)
        return menue

    def spalte_zeigen(self, spalte: int, sichtbar: bool):
        if spalte == NACHNAME:
            return
        self.konten_tabelle.horizontalHeader().setSectionHidden(spalte, not sichtbar)
        self._speichere_spalten()
        self.konten_breiten.anpassen()

    def spalten_zuruecksetzen(self):
        kopf = self.konten_tabelle.horizontalHeader()
        for spalte in range(len(KONTEN_SPALTEN)):
            kopf.setSectionHidden(spalte, False)
            kopf.moveSection(kopf.visualIndex(spalte), spalte)
        self._speichere_spalten()
        self.konten_breiten.anpassen()

    def _sortiere_nach_spalte(self, spalte: int):
        """Klick auf eine Spaltenüberschrift: aufsteigend sortieren, beim zweiten Klick absteigend."""
        aktuell = KONTEN_SORTIERUNG[self.sortierung.currentText()]
        gewuenscht = (spalte, aktuell == (spalte, False))
        for text, sortierung in KONTEN_SORTIERUNG.items():
            if sortierung == gewuenscht:
                self.sortierung.setCurrentText(text)
                return
        # Spalte ohne eigene Sortierung (Typ): Standard
        self.sortierung.setCurrentIndex(0)

    def _gewaehltes_konto_id(self) -> int | None:
        zeilen = self.konten_tabelle.selectionModel().selectedRows()
        if not zeilen:
            return ALLE_BUCHUNGEN
        return self.konten_tabelle.item(zeilen[0].row(), 0).data(Qt.UserRole)

    def lade_buchungen(self, *_):
        """Buchungen des gewählten Kontos anzeigen, gefiltert nach dem Suchtext.

        Aus der Datenbank wird nur gelesen, wenn ein anderes Konto gewählt wurde oder sich die
        Daten geändert haben (`aktualisieren`). Beim Tippen in der Suche wird die geladene
        Liste gefiltert.
        """
        konto_id = self._gewaehltes_konto_id()
        if self._buchungen is None or self._buchungen[0] != konto_id:
            with self.Session() as session:
                # Die Buchungen bringen ihre Konten und ihr Storno mit (joinedload) und
                # bleiben deshalb auch nach dem Schließen der Session vollständig lesbar
                self._buchungen = (konto_id, buchhaltung.buchungen(session, konto_id))
        alle = self._buchungen[1]
        konto = next((k for k in self._konten if k.id == konto_id), None)
        suchtext = self.buchungssuche.text()
        liste = [b for b in alle if buchhaltung.buchung_passt(b, suchtext)]
        anzahl = f"{len(liste)} von {len(alle)} Buchungen" if suchtext.strip() else f"{len(alle)} Buchungen"
        if konto:
            self.buchungen_titel.setText(f"Buchungen – {konto.name}")
            saldo = self._salden.get(konto.id, 0)
            self.buchungen_info.setText(f"{anzahl} · Saldo <b>{cent_zu_text(saldo)}</b>")
        else:
            self.buchungen_titel.setText("Alle Buchungen")
            self.buchungen_info.setText(anzahl)
        self.buchungen_tabelle.setRowCount(len(liste))
        for zeile, b in enumerate(liste):
            # Aus Sicht des gewählten Kontos: Wirkung auf dessen Saldo
            betrag = b.wirkung_auf(konto) if konto else b.betrag_cent
            status = "storniert" if b.ist_storniert else ""
            beleg = _zelle(b.beleg)
            if b.anhaenge:
                beleg.setIcon(self._klammer)
                beleg.setToolTip("Rechnungen: " + ", ".join(a.dateiname for a in b.anhaenge))
            werte = [
                _zelle(b.datum.strftime("%d.%m.%Y"), daten=b.id),
                _zelle(b.art.anzeige),
                beleg,
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
        self.buchungen_breiten.anpassen()

    # --- Aktionen ---------------------------------------------------------

    def zeige_alle_buchungen(self):
        self.konten_tabelle.clearSelection()

    def auswertung(self):
        AuswertungDialog(self.Session, self).exec()

    def kontoauszuege(self):
        VersandDialog(self.Session, self).exec()

    def einstellungen(self):
        if einstellungen_bearbeiten(self.Session, self):
            self.statusBar().showMessage("Einstellungen gespeichert.", 5000)

    def sicherungen(self):
        dialog = SicherungenDialog(self.Session.kw["bind"], Path(self.db_pfad), self)
        dialog.exec()
        if dialog.wiederhergestellt:
            self.aktualisieren()

    # --- Update ---------------------------------------------------------------

    # Stiller Installer-Aufruf: ersetzt die alte Version und startet DiKaS danach neu
    UPDATE_PARAMETER = ["/SILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/NORESTART", "/SP-"]  # noqa: RUF012

    def update_installieren(self):
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self, "Update",
                "Updates lassen sich nur in der installierten Version einspielen.\n"
                "In der Entwicklungsumgebung einfach den Code aktualisieren.",
            )
            return
        start = Path(QStandardPaths.writableLocation(QStandardPaths.DownloadLocation))
        setup, _ = QFileDialog.getOpenFileName(
            self, "Update installieren", str(start), "DiKaS-Installer (DiKaS-Setup*.exe)"
        )
        if not setup:
            return
        antwort = QMessageBox.question(
            self, "Update installieren",
            f"DiKaS wird jetzt geschlossen und mit\n{Path(setup).name}\naktualisiert.\n\n"
            "Deine Daten bleiben erhalten. DiKaS startet danach automatisch neu.",
        )
        if antwort != QMessageBox.Yes:
            return
        # PySide6 liefert (erfolgreich, pid) zurück – nur bei echtem Start DiKaS beenden
        ergebnis = QProcess.startDetached(setup, self.UPDATE_PARAMETER)
        gestartet = ergebnis[0] if isinstance(ergebnis, tuple) else bool(ergebnis)
        if not gestartet:
            QMessageBox.warning(
                self, "Update",
                "Der Installer konnte nicht gestartet werden (evtl. vom Virenscanner blockiert).\n"
                "DiKaS bleibt geöffnet – bitte die Setup-Datei per Doppelklick starten.",
            )
            return
        QApplication.quit()

    # --- Datenaustausch zwischen PCs ----------------------------------------

    def datenordner_oeffnen(self):
        ordner = Path(self.db_pfad).parent
        ordner.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ordner)))

    @staticmethod
    def _dokumente() -> Path:
        return Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))

    def daten_exportieren(self):
        vorschlag = str(self._dokumente() / datenaustausch.export_dateiname())
        ziel, _ = QFileDialog.getSaveFileName(
            self, "Daten exportieren", vorschlag, "DiKaS-Daten (*.db)"
        )
        if not ziel:
            return
        try:
            datenaustausch.exportieren(Path(self.db_pfad), Path(ziel))
        except (OSError, ValueError, sqlite3.Error) as fehler:
            QMessageBox.warning(self, "Export fehlgeschlagen", str(fehler))
            return
        QMessageBox.information(
            self, "Daten exportiert",
            f"Die Daten wurden gespeichert:\n{ziel}\n\n"
            "Auf dem anderen PC: Schraubenschlüssel → „Daten importieren …“.\n"
            "Bitte danach nur noch dort weiterarbeiten, bis die Daten zurückkommen.",
        )

    def daten_importieren(self):
        quelle, _ = QFileDialog.getOpenFileName(
            self, "Daten importieren", str(self._dokumente()), "DiKaS-Daten (*.db)"
        )
        if not quelle:
            return
        db_pfad = Path(self.db_pfad)
        try:
            warnungen = datenaustausch.import_warnungen(Path(quelle), db_pfad)
            neu = datenaustausch.datenstand(Path(quelle))
            hier = datenaustausch.datenstand(db_pfad) if db_pfad.exists() else None
        except (OSError, ValueError, sqlite3.Error) as fehler:
            QMessageBox.warning(self, "Import nicht möglich", str(fehler))
            return
        text = f"Datei: {neu.beschreibung()}\n"
        if hier:
            text += f"Dieser PC: {hier.beschreibung()}\n"
        if warnungen:
            text += "\n⚠ " + "\n⚠ ".join(warnungen) + "\n"
        text += "\nDie Daten dieses PCs werden durch die Datei ersetzt (vorher wird gesichert). Fortfahren?"
        antwort = QMessageBox.question(self, "Daten importieren", text)
        if antwort != QMessageBox.Yes:
            return
        engine = self.Session.kw["bind"]
        engine.dispose()  # Datei erst ersetzen, wenn keine Verbindung mehr offen ist
        try:
            datenaustausch.importieren(Path(quelle), db_pfad)
        except (OSError, ValueError, sqlite3.Error) as fehler:
            QMessageBox.warning(self, "Import fehlgeschlagen", str(fehler))
            return
        finally:
            init_db(engine)  # ältere Dateien auf den aktuellen Stand bringen
        self.aktualisieren()
        self.statusBar().showMessage("Daten importiert.", 8000)

    def neues_konto(self):
        dialog = KontoDialog(self)
        if dialog.exec() != KontoDialog.Accepted:
            return
        w = dialog.werte()
        self._ausfuehren(
            lambda s: buchhaltung.konto_anlegen(
                s, w["name"], w["typ"], w["status"], w["bemerkung"], w["eintrittsdatum"],
                bierspitz=w["bierspitz"], email=w["email"], vorname=w["vorname"], nachname=w["nachname"],
            )
        )

    def konto_bearbeiten(self):
        konto = self._gewaehltes_konto()
        if konto is None:
            return
        konto_id = konto.id
        dialog = KontoDialog(self, konto)
        if dialog.exec() != KontoDialog.Accepted:
            return
        w = dialog.werte()
        self._ausfuehren(
            lambda s: buchhaltung.konto_bearbeiten(
                s, konto_id, w["name"], w["status"], w["bemerkung"], w["aktiv"], w["eintrittsdatum"],
                statusverlauf=w["statusverlauf"], bierspitz=w["bierspitz"], email=w["email"],
                vorname=w["vorname"], nachname=w["nachname"],
            )
        )

    def _gewaehltes_konto(self) -> Konto | None:
        konto_id = self._gewaehltes_konto_id()
        if konto_id is ALLE_BUCHUNGEN:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst ein Konto auswählen.")
            return None
        with self.Session() as session:
            return session.get(Konto, konto_id)

    def konto_loeschen(self):
        konto = self._gewaehltes_konto()
        if konto is None:
            return
        antwort = QMessageBox.question(
            self,
            "Konto löschen",
            f"Konto „{konto.name}“ löschen?\n\n"
            "Hat das Konto Buchungen, bleibt es im Hintergrund erhalten und kann "
            "über den Filter „Gelöschte“ wiederhergestellt werden.",
        )
        if antwort != QMessageBox.Yes:
            return
        ergebnis = {}
        if self._ausfuehren(lambda s: ergebnis.update(entfernt=buchhaltung.konto_loeschen(s, konto.id))):
            art = "entfernt" if ergebnis["entfernt"] else "gelöscht (Buchungen bleiben erhalten)"
            self.statusBar().showMessage(f"Konto „{konto.name}“ {art}.", 5000)

    def konto_wiederherstellen(self):
        konto = self._gewaehltes_konto()
        if konto is None:
            return
        if self._ausfuehren(lambda s: buchhaltung.konto_wiederherstellen(s, konto.id)):
            self.statusBar().showMessage(f"Konto „{konto.name}“ wiederhergestellt.", 5000)

    def neue_buchung(self):
        with self.Session() as session:
            konten = buchhaltung.konten(session, nur_aktive=True)
        dialog = BuchungDialog(konten, self)
        if dialog.exec() != BuchungDialog.Accepted:
            return
        werte, dateien = dialog.werte(), dialog.dateien()

        def buchen_mit_rechnungen(session):
            buchung = buchhaltung.buchen(session, **werte)
            for datei in dateien:
                anhaenge.anhaengen(session, buchung.id, datei)

        self._ausfuehren(buchen_mit_rechnungen)

    def rechnungen_auswahl(self):
        ids = self._gewaehlte_buchung_ids()
        if not ids:
            return
        if len(ids) > 1:
            QMessageBox.information(self, "Hinweis", "Bitte genau eine Buchung auswählen.")
            return
        dialog = AnhaengeDialog(self.Session, ids[0], self)
        dialog.exec()
        if dialog.geaendert:
            self.aktualisieren()

    def beitraege_abbuchen(self):
        with self.Session() as session:
            kassen = [k for k in buchhaltung.konten(session, nur_aktive=True) if k.typ == KontoTyp.KASSE]
        if not kassen:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst eine Kasse für die Beiträge anlegen.")
            return

        def vorschau(betraege, jahr):
            with self.Session() as session:
                return buchhaltung.beitrag_vorschau(session, betraege, jahr)

        dialog = BeitragDialog(kassen, vorschau, self)
        if dialog.exec() != BeitragDialog.Accepted:
            return
        werte = dialog.werte()
        if self._ausfuehren(lambda s: buchhaltung.beitraege_abbuchen(s, **werte)):
            self.statusBar().showMessage("Beiträge wurden gebucht.", 5000)

    def _buchungs_menue(self, position):
        item = self.buchungen_tabelle.itemAt(position)
        if item is None:
            return
        self._auswahl_fuer_rechtsklick(item.row())
        menue = QMenu(self)
        menue.addAction(stil.symbol("MailMessageNew"), "Korrigieren …", self.korrigiere_auswahl)
        menue.addAction(stil.symbol("EditUndo"), "Stornieren", self.storniere_auswahl)
        menue.addAction(stil.symbol("MailAttachment"), "Rechnungen …", self.rechnungen_auswahl)
        menue.addSeparator()
        menue.addAction(stil.symbol("EditDelete"), "Löschen …", self.loesche_auswahl)
        menue.exec(self.buchungen_tabelle.viewport().mapToGlobal(position))

    def _auswahl_fuer_rechtsklick(self, zeile: int):
        """Rechtsklick auf eine nicht markierte Zeile: nur diese auswählen (wie im Explorer).
        Rechtsklick in eine bestehende Mehrfachauswahl lässt die Auswahl stehen."""
        markiert = {z.row() for z in self.buchungen_tabelle.selectionModel().selectedRows()}
        if zeile not in markiert:
            self.buchungen_tabelle.selectRow(zeile)

    def _gewaehlte_buchung_ids(self) -> list[int]:
        """IDs aller markierten Buchungen in Tabellenreihenfolge; Hinweis, wenn keine markiert ist."""
        zeilen = sorted(z.row() for z in self.buchungen_tabelle.selectionModel().selectedRows())
        if not zeilen:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst eine Buchung auswählen.")
        return [self.buchungen_tabelle.item(z, 0).data(Qt.UserRole) for z in zeilen]

    def _sichern_vor_loeschen(self) -> bool:
        """Höchstens eine Sicherung pro Sitzung, damit Löschaktionen ältere Stände nicht verdrängen."""
        if self._vor_loeschen_gesichert or not Path(self.db_pfad).exists():
            return True
        try:
            sicherung.sichern(Path(self.db_pfad))
        except (OSError, sqlite3.Error) as fehler:
            QMessageBox.warning(self, "Fehler", f"Sicherung vor dem Löschen fehlgeschlagen – nichts gelöscht.\n{fehler}")
            return False
        self._vor_loeschen_gesichert = True
        return True

    def loesche_auswahl(self):
        ids = self._gewaehlte_buchung_ids()
        if not ids:
            return
        try:
            with self.Session() as session:
                loeschen = buchhaltung.zu_loeschende_buchungen(session, ids)
                beitraege = [
                    f"{b.soll_konto.name} {b.beitragsjahr}" for b in loeschen
                    if b.art == Buchungsart.BEITRAG and b.beitragsjahr and not b.ist_storniert
                ]
                liste = "\n".join(
                    f"• {b.datum:%d.%m.%Y}  {b.art.anzeige}  {cent_zu_text(b.betrag_cent)}  {b.text}"
                    for b in loeschen[:12]
                )
        except buchhaltung.BuchhaltungsFehler as fehler:
            QMessageBox.warning(self, "Fehler", f"{fehler}\nDie Liste wird neu geladen.")
            self.aktualisieren()
            return
        if len(loeschen) > 12:
            liste += f"\n… und {len(loeschen) - 12} weitere"
        hinweise = []
        mitgenommen = len(loeschen) - len(set(ids))
        if mitgenommen:
            hinweise.append(
                f"{mitgenommen} weitere Buchung(en) werden mitgelöscht: Original und Storno "
                "gehören zusammen, sonst würde die falsche Buchung wieder gelten."
            )
        if beitraege:
            hinweise.append(
                "Achtung, darunter sind gültige Jahresbeiträge (" + ", ".join(beitraege) + "). "
                "Diese Mitglieder sind danach im Beitragslauf für das Jahr wieder fällig."
            )
        zusatz = "".join(f"\n\n⚠ {h}" for h in hinweise)
        antwort = QMessageBox.question(
            self,
            "Buchungen löschen",
            f"{len(loeschen)} Buchung(en) endgültig löschen?\n\n{liste}{zusatz}\n\n"
            "Die Kontostände ändern sich entsprechend. Vorher wird automatisch gesichert "
            "(zurückholen über Schraubenschlüssel → Sicherungen).",
        )
        if antwort != QMessageBox.Yes or not self._sichern_vor_loeschen():
            return
        if self._ausfuehren(lambda s: buchhaltung.buchungen_loeschen(s, ids)):
            self.statusBar().showMessage(f"{len(loeschen)} Buchung(en) gelöscht.", 5000)

    def korrigiere_auswahl(self, item=None):
        # Doppelklick: genau die angeklickte Zeile; sonst darf nur eine markiert sein
        if isinstance(item, QTableWidgetItem):
            ids = [self.buchungen_tabelle.item(item.row(), 0).data(Qt.UserRole)]
        else:
            ids = self._gewaehlte_buchung_ids()
            if len(ids) > 1:
                QMessageBox.information(
                    self, "Hinweis", "Bitte genau eine Buchung zum Korrigieren auswählen."
                )
                return
        if not ids:
            return
        buchung_id = ids[0]
        with self.Session() as session:
            buchung = session.get(Buchung, buchung_id)
            if buchung is None or buchung.ist_storno or buchung.ist_storniert:
                QMessageBox.information(
                    self, "Hinweis",
                    "Stornierte Buchungen und Stornobuchungen können nicht korrigiert werden.",
                )
                return
            try:
                vorlage = buchhaltung.eingabe_aus_buchung(buchung)
            except buchhaltung.BuchhaltungsFehler as fehler:
                QMessageBox.information(self, "Hinweis", str(fehler))
                return
            konten = buchhaltung.konten(session, nur_aktive=True)
            # Die Konten der Buchung auch anbieten, wenn sie inzwischen deaktiviert sind – sonst
            # ließe sich nicht einmal ein Tippfehler im Text korrigieren. Ändert sich mehr als
            # Text/Beleg, lehnt `buchung_korrigieren` das für stillgelegte Konten mit Meldung ab.
            vorhanden = {k.id for k in konten}
            konten += [k for k in (buchung.soll_konto, buchung.haben_konto) if k.id not in vorhanden]
        dialog = BuchungDialog(konten, self, vorlage=vorlage)
        if dialog.exec() != BuchungDialog.Accepted:
            return
        werte = dialog.werte()
        if self._ausfuehren(lambda s: buchhaltung.buchung_korrigieren(s, buchung_id, **werte)):
            self.statusBar().showMessage("Buchung korrigiert.", 5000)

    def storniere_auswahl(self):
        """Storniert alle markierten Buchungen (bereits stornierte und Stornos werden übersprungen)."""
        ids = self._gewaehlte_buchung_ids()
        if not ids:
            return
        with self.Session() as session:
            buchungen = [session.get(Buchung, i) for i in ids]
            stornierbar = [b.id for b in buchungen if b and not b.ist_storno and not b.ist_storniert]
        uebersprungen = len(ids) - len(stornierbar)
        if not stornierbar:
            QMessageBox.information(
                self, "Hinweis",
                "Die ausgewählte Buchung wurde bereits storniert oder ist selbst ein Storno.",
            )
            return
        frage = (
            "Diese Buchung wirklich stornieren?" if len(stornierbar) == 1
            else f"{len(stornierbar)} Buchungen wirklich stornieren?"
        )
        if uebersprungen:
            frage += f"\n({uebersprungen} bereits stornierte bzw. Storno-Buchung(en) werden übersprungen.)"
        antwort = QMessageBox.question(self, "Stornieren", frage + "\n\n(Es werden Gegenbuchungen erzeugt.)")
        if antwort == QMessageBox.Yes:
            self._ausfuehren(lambda s: [buchhaltung.stornieren(s, i) for i in stornierbar])

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
