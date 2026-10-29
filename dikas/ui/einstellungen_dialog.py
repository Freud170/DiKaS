"""Einstellungen: Mailserver und Absender, Bankdaten, Textvorlagen für den Kontoauszug."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import sessionmaker

from dikas import einstellungen as es
from dikas.buchhaltung import EMAIL_MUSTER
from dikas.einstellungen import Einstellungen
from dikas.ui import stil
from dikas.ui.bausteine import ZahlFeld
from dikas.ui.dialoge import _knoepfe


def _seite(form: QFormLayout) -> QWidget:
    seite = QWidget()
    form.setContentsMargins(16, 16, 16, 16)
    seite.setLayout(form)
    return seite


def _hinweis(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("hinweis")
    label.setWordWrap(True)
    return label


class EinstellungenDialog(QDialog):
    def __init__(self, einstellungen: Einstellungen, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.resize(640, 640)
        e = einstellungen

        # --- E-Mail-Konto ---
        self.anbieter = QComboBox()
        self.anbieter.addItems([a.name for a in es.ANBIETER])
        self.server = QLineEdit(e.smtp_server)
        self.port = ZahlFeld(1, 65535, e.smtp_port)
        self.verschluesselung = QComboBox()
        self.verschluesselung.addItems(es.VERSCHLUESSELUNGEN)
        self.verschluesselung.setCurrentText(e.smtp_verschluesselung)
        self.benutzer = QLineEdit(e.smtp_benutzer)
        self.benutzer.setPlaceholderText("meist die E-Mail-Adresse")
        self.absender_name = QLineEdit(e.absender_name)
        self.absender_name.setPlaceholderText("z. B. Max Mustermann (Kassenwart)")
        self.absender_email = QLineEdit(e.absender_email)
        self.absender_email.setPlaceholderText("name@beispiel.de")
        self.anbieter_hinweis = _hinweis()

        form = stil.formular(QFormLayout())
        form.addRow("Anbieter:", self.anbieter)
        form.addRow("", self.anbieter_hinweis)
        form.addRow("Absendername:", self.absender_name)
        form.addRow("Absender-E-Mail:", self.absender_email)
        form.addRow("Benutzername:", self.benutzer)
        form.addRow("Mailserver (SMTP):", self.server)
        form.addRow("Port:", self.port)
        form.addRow("Verschlüsselung:", self.verschluesselung)
        form.addRow("", _hinweis(
            "Das Passwort wird nicht gespeichert, sondern bei jedem Versand abgefragt."
        ))
        konto_seite = _seite(form)

        # --- Bankdaten ---
        self.kontoinhaber = QLineEdit(e.kontoinhaber)
        self.iban = QLineEdit(e.iban)
        self.iban.setPlaceholderText("DE12 3456 7890 1234 5678 90")
        self.bic = QLineEdit(e.bic)
        self.bic.setPlaceholderText("optional")
        self.bank = QLineEdit(e.bank)
        self.bank.setPlaceholderText("optional")
        form = stil.formular(QFormLayout())
        form.addRow("Kontoinhaber:", self.kontoinhaber)
        form.addRow("IBAN:", self.iban)
        form.addRow("BIC:", self.bic)
        form.addRow("Bank:", self.bank)
        form.addRow("", _hinweis("Diese Bankdaten stehen in der Mail an Mitglieder mit negativem Kontostand."))
        bank_seite = _seite(form)

        # --- Texte ---
        self.betreff = QLineEdit(e.betreff)
        self.verwendungszweck = QLineEdit(e.verwendungszweck)
        self.texte = {
            "text_negativ": QPlainTextEdit(e.text_negativ),
            "text_positiv": QPlainTextEdit(e.text_positiv),
            "text_null": QPlainTextEdit(e.text_null),
        }
        text_reiter = QTabWidget()
        for feld, titel in (("text_negativ", "Saldo negativ"), ("text_positiv", "Saldo positiv"),
                            ("text_null", "Saldo 0")):
            text_reiter.addTab(self.texte[feld], titel)
        standard = QPushButton("Standardtexte wiederherstellen")
        standard.setAutoDefault(False)
        standard.clicked.connect(self._standardtexte)
        platzhalter = _hinweis("Platzhalter: " + ", ".join(f"{{{n}}}" for n in es.PLATZHALTER))
        platzhalter.setToolTip("\n".join(f"{{{n}}} – {b}" for n, b in es.PLATZHALTER.items()))

        texte_seite = QWidget()
        layout = QVBoxLayout(texte_seite)
        layout.setContentsMargins(16, 16, 16, 16)
        form = stil.formular(QFormLayout())
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Betreff:", self.betreff)
        form.addRow("Verwendungszweck:", self.verwendungszweck)
        layout.addLayout(form)
        layout.addWidget(text_reiter, 1)
        unten = QHBoxLayout()
        unten.addWidget(platzhalter, 1)
        unten.addWidget(standard)
        layout.addLayout(unten)

        reiter = QTabWidget()
        reiter.addTab(konto_seite, "E-Mail-Konto")
        reiter.addTab(bank_seite, "Bankdaten")
        reiter.addTab(texte_seite, "Texte")

        haupt = QVBoxLayout(self)
        haupt.setContentsMargins(20, 18, 20, 16)
        haupt.addWidget(reiter, 1)
        haupt.addWidget(_knoepfe(self, self._pruefen))

        # Anbieter erst nach dem Befüllen verbinden, damit gespeicherte Werte nicht überschrieben werden
        self.anbieter.setCurrentText(e.smtp_anbieter if es.anbieter(e.smtp_anbieter) else es.EIGENER_SERVER)
        self._zeige_hinweis()
        self.anbieter.currentTextChanged.connect(self._anbieter_gewaehlt)

    def _anbieter_gewaehlt(self, name: str):
        a = es.anbieter(name)
        if a and a.server:
            self.server.setText(a.server)
            self.port.setValue(a.port)
            self.verschluesselung.setCurrentText(a.verschluesselung)
        self._zeige_hinweis()

    def _zeige_hinweis(self):
        a = es.anbieter(self.anbieter.currentText())
        self.anbieter_hinweis.setText(a.hinweis if a else "")
        self.anbieter_hinweis.setVisible(bool(a and a.hinweis))

    def _standardtexte(self):
        standard = Einstellungen()
        self.betreff.setText(standard.betreff)
        self.verwendungszweck.setText(standard.verwendungszweck)
        for feld, editor in self.texte.items():
            editor.setPlainText(getattr(standard, feld))

    def werte(self) -> Einstellungen:
        absender = self.absender_email.text().strip()
        return Einstellungen(
            smtp_anbieter=self.anbieter.currentText(),
            smtp_server=self.server.text().strip(),
            smtp_port=self.port.value(),
            smtp_verschluesselung=self.verschluesselung.currentText(),
            smtp_benutzer=self.benutzer.text().strip() or absender,
            absender_name=self.absender_name.text().strip(),
            absender_email=absender,
            kontoinhaber=self.kontoinhaber.text().strip(),
            iban=self.iban.text().strip().upper(),
            bic=self.bic.text().strip().upper(),
            bank=self.bank.text().strip(),
            betreff=self.betreff.text().strip(),
            verwendungszweck=self.verwendungszweck.text().strip(),
            **{feld: editor.toPlainText().strip() for feld, editor in self.texte.items()},
        )

    def fehler(self) -> str | None:
        e = self.werte()
        if not 1 <= e.smtp_port <= 65535:
            return "Bitte einen Port zwischen 1 und 65535 angeben."
        if e.absender_email and not EMAIL_MUSTER.match(e.absender_email):
            return f"„{e.absender_email}“ ist keine gültige E-Mail-Adresse."
        iban = e.iban.replace(" ", "")
        if iban and not (15 <= len(iban) <= 34 and iban[:2].isalpha() and iban[2:4].isdigit()):
            return f"„{e.iban}“ sieht nicht wie eine IBAN aus."
        for name, vorlage in (("Betreff", e.betreff), ("Verwendungszweck", e.verwendungszweck),
                              ("Text Saldo negativ", e.text_negativ), ("Text Saldo positiv", e.text_positiv),
                              ("Text Saldo 0", e.text_null)):
            if not vorlage:
                return f"{name} darf nicht leer sein."
            if meldung := es.pruefe_vorlage(vorlage):
                return f"{name}: {meldung}"
        return None

    def _pruefen(self):
        if meldung := self.fehler():
            QMessageBox.warning(self, "Fehler", meldung)
            return
        self.accept()


def einstellungen_bearbeiten(Session: sessionmaker, parent=None) -> bool:
    """Öffnet den Dialog und speichert bei OK. Rückgabe: True, wenn gespeichert wurde."""
    with Session() as session:
        aktuell = es.laden(session)
    dialog = EinstellungenDialog(aktuell, parent)
    if dialog.exec() != QDialog.Accepted:
        return False
    with Session.begin() as session:
        es.speichern(session, dialog.werte())
    return True
