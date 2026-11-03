"""Hauptfenster: Kennzahlen oben, Kontenübersicht links, Buchungen des gewählten Kontos rechts."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import sessionmaker

from dikas import __version__, buchhaltung
from dikas.db.models import Buchung, Konto, KontoTyp, MitgliedStatus
from dikas.geld import cent_zu_text
from dikas.ui import stil
from dikas.ui.auswertung import AuswertungDialog
from dikas.ui.einstellungen_dialog import einstellungen_bearbeiten
from dikas.ui.sicherungen_dialog import SicherungenDialog
from dikas.ui.versand_dialog import VersandDialog
from dikas.ui.bausteine import GRAU, Kennzahl, Panel
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
    "Gelöschte": lambda k: k.geloescht,
}


class Hauptfenster(QMainWindow):
    def __init__(self, session_factory: sessionmaker, db_pfad: str):
        super().__init__()
        self.Session = session_factory
        self.db_pfad = db_pfad
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
        self.suche.textChanged.connect(self.aktualisieren)
        self.filter = QComboBox()
        self.filter.addItems(KONTEN_FILTER)
        self.filter.currentIndexChanged.connect(self.aktualisieren)
        self.konten_tabelle = self._neue_tabelle(
            ["Konto", "Bierspitz", "Typ", "Status", "Eintritt", "Saldo"], rechts=[5]
        )
        self.konten_tabelle.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.konten_tabelle.itemSelectionChanged.connect(self.lade_buchungen)
        self.konten_tabelle.itemDoubleClicked.connect(self.konto_bearbeiten)

        links = Panel("Konten")
        auswahl = QHBoxLayout()
        auswahl.addWidget(self.suche, 3)
        auswahl.addWidget(self.filter, 2)
        links.layout_.addLayout(auswahl)
        links.layout_.addWidget(self.konten_tabelle)
        self.konten_info = links.info

        # Buchungen
        self.buchungen_tabelle = self._neue_tabelle(
            ["Datum", "Art", "Beleg", "Text", "Soll", "Haben", "Betrag", "Status"], rechts=[6]
        )
        self.buchungen_tabelle.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        rechts = Panel("")
        self.buchungen_titel = rechts.titel
        self.buchungen_info = rechts.info
        # Aktionen für die ausgewählte Buchung in eigener Zeile über der Liste
        # (auch per Doppelklick/Rechtsklick)
        aktionen = QHBoxLayout()
        for text, icon, tipp, slot in (
            ("Korrigieren", "MailMessageNew", "Ausgewählte Buchung korrigieren (Doppelklick)",
             self.korrigiere_auswahl),
            ("Stornieren", "EditUndo", "Ausgewählte Buchung stornieren (Gegenbuchung)", self.storniere_auswahl),
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
        self.buchungen_tabelle.setContextMenuPolicy(Qt.CustomContextMenu)
        self.buchungen_tabelle.customContextMenuRequested.connect(self._buchungs_menue)
        rechts.layout_.addWidget(self.buchungen_tabelle)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(links)
        splitter.addWidget(rechts)
        splitter.setSizes([600, 720])  # links genug Platz für Name, Bierspitz, Status, Eintritt, Saldo

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
        menue.addAction(stil.symbol("DocumentProperties"), "Einstellungen …", self.einstellungen)
        menue.addAction(stil.symbol("DocumentRevert"), "Sicherungen …", self.sicherungen)
        self.extras_knopf = QToolButton()
        self.extras_knopf.setIcon(stil.symbol("DocumentProperties"))
        self.extras_knopf.setToolTip("Einstellungen und Sicherungen")
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
        gewaehlt = self._gewaehltes_konto_id()
        passt = KONTEN_FILTER[self.filter.currentText()]
        suchtext = self.suche.text().strip().lower()
        self.konten_tabelle.blockSignals(True)
        self.konten_tabelle.clearSelection()
        with self.Session() as session:
            alle = buchhaltung.konten(session)
            salden = buchhaltung.salden(session)
            abstimmung = buchhaltung.abstimmung(session)
        konten = sorted(
            (k for k in alle if passt(k) and suchtext in f"{k.name} {k.bierspitz} {k.email}".lower()),
            key=lambda k: (k.typ.reihenfolge, (k.nachname or k.name).lower(), k.vorname.lower()),
        )

        self.konten_tabelle.setRowCount(len(konten))
        for zeile, konto in enumerate(konten):
            werte = [
                _zelle(konto.name, daten=konto.id),
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
        self.konten_info.setText(f"{len(konten)} von {len(alle)}")

        self._aktualisiere_kennzahlen(alle, salden)
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
            if konto:
                self.buchungen_titel.setText(f"Buchungen – {konto.name}")
                saldo = buchhaltung.saldo(session, konto.id)
                self.buchungen_info.setText(
                    f"{len(liste)} Buchungen · Saldo <b>{cent_zu_text(saldo)}</b>"
                )
            else:
                self.buchungen_titel.setText("Alle Buchungen")
                self.buchungen_info.setText(f"{len(liste)} Buchungen")
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
        werte = dialog.werte()
        self._ausfuehren(lambda s: buchhaltung.buchen(s, **werte))

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
        if self.buchungen_tabelle.itemAt(position) is None:
            return
        menue = QMenu(self)
        menue.addAction(stil.symbol("MailMessageNew"), "Korrigieren …", self.korrigiere_auswahl)
        menue.addAction(stil.symbol("EditUndo"), "Stornieren", self.storniere_auswahl)
        menue.exec(self.buchungen_tabelle.viewport().mapToGlobal(position))

    def _gewaehlte_buchung_id(self) -> int | None:
        zeilen = self.buchungen_tabelle.selectionModel().selectedRows()
        if not zeilen:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst eine Buchung auswählen.")
            return None
        return self.buchungen_tabelle.item(zeilen[0].row(), 0).data(Qt.UserRole)

    def korrigiere_auswahl(self, *_):
        buchung_id = self._gewaehlte_buchung_id()
        if buchung_id is None:
            return
        with self.Session() as session:
            buchung = session.get(Buchung, buchung_id)
            if buchung.ist_storno or buchung.ist_storniert:
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
        dialog = BuchungDialog(konten, self, vorlage=vorlage)
        if dialog.exec() != BuchungDialog.Accepted:
            return
        werte = dialog.werte()
        if self._ausfuehren(lambda s: buchhaltung.buchung_korrigieren(s, buchung_id, **werte)):
            self.statusBar().showMessage("Buchung korrigiert.", 5000)

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
