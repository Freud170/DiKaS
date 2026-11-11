"""Kontoauszüge per E-Mail versenden: Auswahl, Vorschau, Testmail, Versand mit Fortschritt."""

from datetime import date
from typing import Callable

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)
from sqlalchemy.orm import sessionmaker

from dikas import einstellungen as es
from dikas import kontoauszug as ka
from dikas.db.models import Konto
from dikas.ui import stil
from dikas.ui.bausteine import GRAU, Panel, betrag_zelle, zelle
from dikas.ui.einstellungen_dialog import einstellungen_bearbeiten

SPALTE_SENDEN, SPALTE_NAME, SPALTE_SALDO = 0, 1, 4


def passwort_abfragen(parent, einstellungen: es.Einstellungen) -> str | None:
    text, ok = QInputDialog.getText(
        parent,
        "Passwort",
        f"Passwort für {einstellungen.smtp_benutzer} ({einstellungen.smtp_server}):",
        QLineEdit.Password,
    )
    return text if ok else None


class VersandDialog(QDialog):
    def __init__(
        self,
        session_factory: sessionmaker,
        parent=None,
        heute: date | None = None,
        verbinder: ka.Verbinder = ka.verbinden,
        passwort_quelle: Callable[[QDialog, es.Einstellungen], str | None] = passwort_abfragen,
    ):
        super().__init__(parent)
        self.Session = session_factory
        self.verbinder = verbinder
        self.passwort_quelle = passwort_quelle
        self._passwort: str | None = None
        self.setWindowTitle("Kontoauszüge per E-Mail")
        self.resize(1200, 720)

        self.stichtag = QDateEdit()
        self.stichtag.setCalendarPopup(True)
        self.stichtag.setDisplayFormat("dd.MM.yyyy")
        h = heute or date.today()
        self.stichtag.setDate(QDate(h.year, h.month, h.day))
        self.stichtag.dateChanged.connect(self.laden)

        einstellungen_knopf = QPushButton(stil.symbol("DocumentProperties"), "Einstellungen …")
        einstellungen_knopf.setAutoDefault(False)
        einstellungen_knopf.clicked.connect(self._einstellungen)
        alle = QPushButton("Alle mit E-Mail")
        alle.setAutoDefault(False)
        alle.clicked.connect(lambda: self._auswahl_setzen(True))
        keine = QPushButton("Keine")
        keine.setAutoDefault(False)
        keine.clicked.connect(lambda: self._auswahl_setzen(False))

        oben = QHBoxLayout()
        oben.addWidget(QLabel("Kontostand zum:"))
        oben.addWidget(self.stichtag)
        oben.addSpacing(16)
        oben.addWidget(alle)
        oben.addWidget(keine)
        oben.addStretch()
        oben.addWidget(einstellungen_knopf)

        self.tabelle = stil.tabelle(
            ["Senden", "Mitglied", "Bierspitz", "E-Mail", "Saldo", "Mail", "Zuletzt versendet"], rechts=[4]
        )
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabelle.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabelle.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tabelle.itemSelectionChanged.connect(self._zeige_vorschau)
        self.tabelle.itemChanged.connect(self._zaehle)

        links = Panel("Empfänger")
        self.info = links.info
        links.layout_.addWidget(self.tabelle)
        self.hinweis = QLabel()
        self.hinweis.setObjectName("hinweis")
        self.hinweis.setWordWrap(True)
        links.layout_.addWidget(self.hinweis)

        rechts = Panel("Vorschau")
        self.vorschau = QPlainTextEdit()
        self.vorschau.setReadOnly(True)
        rechts.layout_.addWidget(self.vorschau)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(links)
        splitter.addWidget(rechts)
        splitter.setSizes([760, 440])

        self.test_knopf = QPushButton("Testmail an mich")
        self.test_knopf.setAutoDefault(False)
        self.test_knopf.clicked.connect(self.testmail)
        self.senden_knopf = QPushButton(stil.symbol("MailSend"), "Ausgewählte senden")
        self.senden_knopf.setDefault(True)
        self.senden_knopf.clicked.connect(self.senden)
        schliessen = QPushButton("Schließen")
        schliessen.setAutoDefault(False)
        schliessen.clicked.connect(self.reject)
        unten = QHBoxLayout()
        unten.addStretch()
        unten.addWidget(self.test_knopf)
        unten.addWidget(self.senden_knopf)
        unten.addWidget(schliessen)

        haupt = QVBoxLayout(self)
        haupt.setContentsMargins(20, 18, 20, 16)
        haupt.setSpacing(14)
        haupt.addLayout(oben)
        haupt.addWidget(splitter, 1)
        haupt.addLayout(unten)

        self.zeilen: list[tuple[Konto, int]] = []
        self.laden()

    # --- Daten ------------------------------------------------------------

    @property
    def stichtag_wert(self) -> date:
        return self.stichtag.date().toPython()

    def laden(self):
        with self.Session() as session:
            self.einstellungen = es.laden(session)
            self.zeilen = ka.empfaenger_liste(session, self.stichtag_wert)
            schon = ka.bereits_versendet(session, self.stichtag_wert)
            zuletzt = ka.letzter_versand(session)

        t = self.tabelle
        t.blockSignals(True)
        t.setRowCount(len(self.zeilen))
        for zeile, (konto, saldo) in enumerate(self.zeilen):
            senden = zelle("")
            senden.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            # Vorauswahl: mit E-Mail, aktiv oder mit offenem Saldo, noch nicht für diesen Stichtag versendet
            vorauswahl = bool(konto.email) and (konto.aktiv or saldo != 0) and konto.id not in schon
            senden.setCheckState(Qt.Checked if vorauswahl else Qt.Unchecked)
            if not konto.email:
                senden.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            letzte = zuletzt.get(konto.id)
            werte = [
                senden,
                zelle(konto.name, daten=konto.id),
                zelle(konto.bierspitz),
                zelle(konto.email or "– keine E-Mail –"),
                betrag_zelle(saldo, fett=True),
                zelle("offen" if saldo < 0 else "Guthaben" if saldo > 0 else "ausgeglichen"),
                zelle(f"{letzte.gesendet_am:%d.%m.%Y} (Stand {letzte.stichtag:%d.%m.%Y})" if letzte else ""),
            ]
            for spalte, item in enumerate(werte):
                if not konto.email or not konto.aktiv:
                    item.setForeground(GRAU)
                t.setItem(zeile, spalte, item)
        t.blockSignals(False)

        ohne_email = [k.name for k, _ in self.zeilen if not k.email]
        bereits = [k.name for k, _ in self.zeilen if k.id in schon]
        teile = []
        if ohne_email:
            teile.append(f"<b>Ohne E-Mail-Adresse:</b> {', '.join(ohne_email)}")
        if bereits:
            teile.append(f"<b>Für diesen Stichtag schon versendet (abgewählt):</b> {', '.join(bereits)}")
        if fehlend := self.einstellungen.fehlende_angaben():
            teile.append(f"<b>In den Einstellungen fehlt noch:</b> {', '.join(fehlend)}")
        self.hinweis.setText("<br>".join(teile))
        self.hinweis.setVisible(bool(teile))
        self._zaehle()
        if self.zeilen:
            t.selectRow(0)
        self._zeige_vorschau()

    def ausgewaehlte(self) -> list[tuple[Konto, int]]:
        return [
            self.zeilen[z] for z in range(self.tabelle.rowCount())
            if self.tabelle.item(z, SPALTE_SENDEN).checkState() == Qt.Checked
        ]

    def _auswahl_setzen(self, an: bool):
        self.tabelle.blockSignals(True)
        for z, (konto, _) in enumerate(self.zeilen):
            if konto.email:
                self.tabelle.item(z, SPALTE_SENDEN).setCheckState(Qt.Checked if an else Qt.Unchecked)
        self.tabelle.blockSignals(False)
        self._zaehle()

    def _zaehle(self, *_):
        anzahl = len(self.ausgewaehlte())
        self.info.setText(f"{anzahl} von {len(self.zeilen)} ausgewählt")
        self.senden_knopf.setText(f"{anzahl} Mails senden" if anzahl != 1 else "1 Mail senden")
        self.senden_knopf.setEnabled(anzahl > 0)

    def _auszug(self, konto: Konto, saldo: int) -> ka.Kontoauszug:
        return ka.erstelle_auszug(konto, saldo, self.stichtag_wert, self.einstellungen)

    def _gewaehlte_zeile(self) -> tuple[Konto, int] | None:
        zeilen = self.tabelle.selectionModel().selectedRows()
        return self.zeilen[zeilen[0].row()] if zeilen else None

    def _zeige_vorschau(self):
        auswahl = self._gewaehlte_zeile()
        if auswahl is None:
            self.vorschau.clear()
            return
        a = self._auszug(*auswahl)
        kopf = f"An: {a.empfaenger or '– keine E-Mail-Adresse –'}\nBetreff: {a.betreff}\n{'─' * 40}\n\n"
        self.vorschau.setPlainText(kopf + a.text)

    # --- Aktionen ---------------------------------------------------------

    def _einstellungen(self):
        if einstellungen_bearbeiten(self.Session, self):
            self.laden()

    def _bereit(self) -> bool:
        if fehlend := self.einstellungen.fehlende_angaben():
            QMessageBox.warning(
                self, "Einstellungen unvollständig",
                "Bitte zuerst in den Einstellungen ergänzen:\n• " + "\n• ".join(fehlend),
            )
            return False
        return True

    def _passwort_holen(self) -> str | None:
        if not self.einstellungen.smtp_benutzer:
            return ""  # Server ohne Anmeldung
        if self._passwort is None:
            self._passwort = self.passwort_quelle(self, self.einstellungen)
        return self._passwort

    def testmail(self):
        auswahl = self._gewaehlte_zeile()
        if auswahl is None:
            QMessageBox.information(self, "Hinweis", "Bitte ein Mitglied für die Testmail auswählen.")
            return
        if not self._bereit() or (passwort := self._passwort_holen()) is None:
            return
        try:
            ka.testmail_senden(self._auszug(*auswahl), self.einstellungen, passwort, self.verbinder)
        except ka.VersandFehler as fehler:
            self._passwort = None
            QMessageBox.warning(self, "Testmail fehlgeschlagen", str(fehler))
            return
        QMessageBox.information(
            self, "Testmail", f"Die Testmail für „{auswahl[0].name}“ wurde an "
            f"{self.einstellungen.absender_email} geschickt."
        )

    def senden(self):
        auswahl = self.ausgewaehlte()
        if not auswahl or not self._bereit():
            return
        antwort = QMessageBox.question(
            self, "Kontoauszüge senden",
            f"{len(auswahl)} Kontoauszüge (Stand {self.stichtag_wert:%d.%m.%Y}) jetzt per E-Mail senden?",
        )
        if antwort != QMessageBox.Yes or (passwort := self._passwort_holen()) is None:
            return

        fortschritt = QProgressDialog("Mails werden gesendet …", "Abbrechen", 0, len(auswahl), self)
        fortschritt.setWindowTitle("Versand")
        fortschritt.setWindowModality(Qt.WindowModal)
        fortschritt.setMinimumDuration(0)

        def weiter(i: int, auszug: ka.Kontoauszug) -> bool:
            fortschritt.setValue(i)
            fortschritt.setLabelText(f"Sende an {auszug.konto.name} ({auszug.empfaenger}) …")
            return not fortschritt.wasCanceled()

        auszuege = [self._auszug(k, s) for k, s in auswahl]
        try:
            # Keine umschließende Transaktion: versenden() speichert das Protokoll nach jeder Mail
            with self.Session() as session:
                ergebnisse = ka.versenden(session, auszuege, self.einstellungen, passwort, self.verbinder, weiter)
        except ka.VersandFehler as fehler:
            self._passwort = None
            fortschritt.close()
            QMessageBox.warning(self, "Versand fehlgeschlagen", str(fehler))
            return
        fortschritt.setValue(len(auswahl))
        fortschritt.close()

        ok = [e for e in ergebnisse if e.erfolgreich]
        fehler = [e for e in ergebnisse if not e.erfolgreich]
        text = f"{len(ok)} von {len(auszuege)} Mails wurden gesendet."
        if len(ergebnisse) < len(auszuege):
            text += f"\n{len(auszuege) - len(ergebnisse)} wurden wegen Abbruch nicht gesendet."
        if fehler:
            text += "\n\nFehlgeschlagen:\n" + "\n".join(f"• {e.auszug.konto.name}: {e.fehler}" for e in fehler)
        (QMessageBox.warning if fehler else QMessageBox.information)(self, "Versand abgeschlossen", text)
        self.laden()
