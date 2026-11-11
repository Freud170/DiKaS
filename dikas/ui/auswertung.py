"""Auswertung: Kontobewegungen in einem Zeitraum, Summen je Buchungsart, Buchungsliste, PDF-Export."""

from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from PySide6.QtCore import QDate, QStandardPaths
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import sessionmaker

from dikas import buchhaltung
from dikas.buchhaltung import ArtSumme, KontoBewegung, sortierschluessel
from dikas.db.models import Buchung, KontoTyp, MitgliedStatus
from dikas.geld import cent_zu_text
from dikas.pdf import html_zu_pdf
from dikas.ui import stil
from dikas.ui.bausteine import GRAU, Kennzahl, betrag_zelle, fett_machen, zelle

GRUPPEN = [
    (KontoTyp.KW, "Geldorte"),
    (KontoTyp.KASSE, "Kassen"),
    (KontoTyp.PRIVAT, "Privatkonten"),
]

KONTOART_FILTER = {
    "Alle Konten": lambda k: True,
    "Geldorte": lambda k: k.typ == KontoTyp.KW,
    "Kassen": lambda k: k.typ == KontoTyp.KASSE,
    "Privatkonten": lambda k: k.typ == KontoTyp.PRIVAT,
    **{s.mehrzahl: (lambda k, s=s: k.status == s) for s in MitgliedStatus},
}


def zeitraum_vorlage(name: str, heute: date) -> tuple[date, date] | None:
    """Start- und Enddatum für eine Schnellauswahl."""
    if name == "Dieses Jahr":
        return date(heute.year, 1, 1), date(heute.year, 12, 31)
    if name == "Letztes Jahr":
        return date(heute.year - 1, 1, 1), date(heute.year - 1, 12, 31)
    if name == "Dieser Monat":
        erster = heute.replace(day=1)
        naechster = (erster + timedelta(days=32)).replace(day=1)
        return erster, naechster - timedelta(days=1)
    if name == "Letzter Monat":
        ende = heute.replace(day=1) - timedelta(days=1)
        return ende.replace(day=1), ende
    return None


ZEITRAEUME = ["Dieses Jahr", "Letztes Jahr", "Dieser Monat", "Letzter Monat", "Benutzerdefiniert"]


def _konto_name(konto) -> str:
    return f"{konto.name} (gelöscht)" if konto.geloescht else konto.name


def gruppiere(bewegungen: list[KontoBewegung]) -> list[tuple[str, list[KontoBewegung], bool]]:
    """Bewegungen nach Kontoart gruppiert und sortiert; leere Gruppen fallen weg.

    Das dritte Element sagt, ob eine Summenzeile sinnvoll ist (nicht bei nur einem Geldort).
    """
    ergebnis = []
    for typ, titel in GRUPPEN:
        zeilen = sorted(
            (b for b in bewegungen if b.konto.typ == typ), key=lambda b: sortierschluessel(b.konto)
        )
        if zeilen:
            ergebnis.append((titel, zeilen, typ != KontoTyp.KW or len(zeilen) > 1))
    return ergebnis


def summe(zeilen: list[KontoBewegung]) -> tuple[int, int, int, int, int]:
    """(anfang, zugang, abgang, veraenderung, ende) über mehrere Konten."""
    return (
        sum(b.anfang for b in zeilen),
        sum(b.zugang for b in zeilen),
        sum(b.abgang for b in zeilen),
        sum(b.veraenderung for b in zeilen),
        sum(b.ende for b in zeilen),
    )


def als_html(
    von: date,
    bis: date,
    bewegungen: list[KontoBewegung],
    arten: list[ArtSumme],
    buchungen: list[Buchung],
    buchungen_titel: str = "Buchungen im Zeitraum",
) -> str:
    """Bericht als HTML (für den PDF-Export)."""
    def euro(cent: int) -> str:
        farbe = f" style='color:{stil.NEGATIV}'" if cent < 0 else ""
        return f"<td align='right' nowrap{farbe}>{cent_zu_text(cent)}</td>"

    def tabelle(spalten: list[tuple[str, str]], breite: str = "100%") -> str:
        kopf = "".join(f"<th align='{ausrichtung}' nowrap>{name}</th>" for name, ausrichtung in spalten)
        return (
            f"<table width='{breite}' cellspacing='0' cellpadding='4' border='0'>"
            f"<tr bgcolor='{stil.AKZENT_HELL}' style='color:{stil.TEXT_LEISE}'>{kopf}</tr>"
        )

    def zeile(inhalt: str, nummer: int) -> str:
        hintergrund = " bgcolor='#f7f9fb'" if nummer % 2 else ""
        return f"<tr{hintergrund}>{inhalt}</tr>"

    teile = [
        "<html><body style='font-family:Segoe UI; font-size:9pt'>",
        f"<h2 style='margin:0'>Auswertung {von:%d.%m.%Y} – {bis:%d.%m.%Y}</h2>",
        f"<p style='color:{stil.TEXT_LEISE}'>Erstellt am {datetime.now():%d.%m.%Y %H:%M}</p>",
        "<h3>Kontobewegungen</h3>",
        tabelle([("Konto", "left"), ("Status", "left"), ("Anfang", "right"), ("Zugänge", "right"),
                 ("Abgänge", "right"), ("Veränderung", "right"), ("Ende", "right")]),
    ]
    nummer = 0
    for titel, zeilen, mit_summe in gruppiere(bewegungen):
        for b in zeilen:
            status = b.konto.status.anzeige if b.konto.status else ""
            teile.append(zeile(
                f"<td>{escape(_konto_name(b.konto))}</td><td>{status}</td>"
                f"{euro(b.anfang)}{euro(b.zugang)}{euro(-b.abgang)}{euro(b.veraenderung)}{euro(b.ende)}",
                nummer,
            ))
            nummer += 1
        if mit_summe:
            a, z, ab, v, e = summe(zeilen)
            teile.append(
                f"<tr bgcolor='{stil.HINTERGRUND}' style='font-weight:bold'><td colspan='2'>Summe {titel}</td>"
                f"{euro(a)}{euro(z)}{euro(-ab)}{euro(v)}{euro(e)}</tr>"
            )
    teile.append("</table>")

    teile += [
        "<h3>Summen nach Buchungsart</h3>",
        tabelle([("Buchungsart", "left"), ("Anzahl", "right"), ("Summe", "right")], breite="50%"),
    ]
    for i, a in enumerate(arten):
        teile.append(zeile(f"<td>{a.art.anzeige}</td><td align='right'>{a.anzahl}</td>{euro(a.summe)}", i))
    teile.append("</table>")

    teile += [
        f"<h3>{escape(buchungen_titel)}</h3>",
        tabelle([("Datum", "left"), ("Art", "left"), ("Beleg", "left"), ("Text", "left"),
                 ("Soll", "left"), ("Haben", "left"), ("Betrag", "right")]),
    ]
    for i, b in enumerate(sorted(buchungen, key=lambda b: (b.datum, b.id))):
        teile.append(zeile(
            f"<td nowrap>{b.datum:%d.%m.%Y}</td><td nowrap>{b.art.anzeige}</td><td>{escape(b.beleg)}</td>"
            f"<td>{escape(b.text)}</td><td>{escape(b.soll_konto.name)}</td>"
            f"<td>{escape(b.haben_konto.name)}</td>{euro(b.betrag_cent)}",
            i,
        ))
    teile.append("</table></body></html>")
    return "".join(teile)


def speichere_pdf(html: str, pfad: str | Path, titel: str) -> None:
    Path(pfad).write_bytes(html_zu_pdf(html, titel))


class AuswertungDialog(QDialog):
    def __init__(self, session_factory: sessionmaker, parent=None, heute: date | None = None):
        super().__init__(parent)
        self.Session = session_factory
        self.heute = heute or date.today()
        self.setWindowTitle("Auswertung")
        self.resize(1150, 760)

        # Zeitraum und Filter
        self.vorlage = QComboBox()
        self.vorlage.addItems(ZEITRAEUME)
        self.von = self._datum_feld()
        self.bis = self._datum_feld()
        self.kontoart = QComboBox()
        self.kontoart.addItems(KONTOART_FILTER)
        self.ohne_bewegung = QCheckBox("Konten ohne Bewegung anzeigen")
        pdf = QPushButton(stil.symbol("DocumentSave"), "Als PDF speichern")
        pdf.setAutoDefault(False)
        pdf.clicked.connect(self.pdf_speichern)

        leiste = QHBoxLayout()
        leiste.setSpacing(8)
        for widget in (QLabel("Zeitraum:"), self.vorlage, QLabel("von"), self.von, QLabel("bis"), self.bis):
            leiste.addWidget(widget)
        leiste.addSpacing(16)
        leiste.addWidget(QLabel("Konten:"))
        leiste.addWidget(self.kontoart)
        leiste.addWidget(self.ohne_bewegung)
        leiste.addStretch()
        leiste.addWidget(pdf)

        # Kennzahlen
        self.karte_anfang = Kennzahl("KW am Anfang")
        self.karte_einnahmen = Kennzahl("Einnahmen (KW)")
        self.karte_ausgaben = Kennzahl("Ausgaben (KW)")
        self.karte_ende = Kennzahl("KW am Ende")
        karten = QHBoxLayout()
        karten.setSpacing(12)
        for karte in (self.karte_anfang, self.karte_einnahmen, self.karte_ausgaben, self.karte_ende):
            karten.addWidget(karte)

        # Tabellen
        self.konten_tabelle = stil.tabelle(
            ["Konto", "Status", "Anfangsbestand", "Zugänge", "Abgänge", "Veränderung", "Endbestand"],
            rechts=[2, 3, 4, 5, 6],
        )
        self.konten_tabelle.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.arten_tabelle = stil.tabelle(["Buchungsart", "Anzahl", "Summe"], rechts=[1, 2])
        self.arten_tabelle.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.buchungen_konto = QComboBox()
        self.buchungen_konto.setMinimumWidth(260)
        self.buchungen_tabelle = stil.tabelle(
            ["Datum", "Art", "Beleg", "Text", "Soll", "Haben", "Betrag"], rechts=[6]
        )
        self.buchungen_tabelle.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        buchungen_seite = QWidget()
        layout = QVBoxLayout(buchungen_seite)
        filterzeile = QHBoxLayout()
        filterzeile.addWidget(QLabel("Konto:"))
        filterzeile.addWidget(self.buchungen_konto)
        filterzeile.addStretch()
        layout.addLayout(filterzeile)
        layout.addWidget(self.buchungen_tabelle)

        self.reiter = QTabWidget()
        self.reiter.addTab(self.konten_tabelle, "Kontobewegungen")
        self.reiter.addTab(self.arten_tabelle, "Nach Buchungsart")
        self.reiter.addTab(buchungen_seite, "Buchungen")

        self.fehler = QLabel()
        self.fehler.setStyleSheet(f"color: {stil.NEGATIV}; font-weight: 600;")

        haupt = QVBoxLayout(self)
        haupt.setContentsMargins(20, 18, 20, 16)
        haupt.setSpacing(14)
        haupt.addLayout(leiste)
        haupt.addWidget(self.fehler)
        haupt.addLayout(karten)
        haupt.addWidget(self.reiter, 1)

        # Daten
        self.bewegungen: list[KontoBewegung] = []
        self.arten: list[ArtSumme] = []
        self.buchungen: list[Buchung] = []

        self._setze_vorlage()
        self.vorlage.currentIndexChanged.connect(self._setze_vorlage)
        self.von.dateChanged.connect(self._datum_geaendert)
        self.bis.dateChanged.connect(self._datum_geaendert)
        self.kontoart.currentIndexChanged.connect(self._zeige_konten)
        self.ohne_bewegung.toggled.connect(self._zeige_konten)
        self.buchungen_konto.currentIndexChanged.connect(self._zeige_buchungen)
        self.laden()

    @staticmethod
    def _datum_feld() -> QDateEdit:
        feld = QDateEdit()
        feld.setCalendarPopup(True)
        feld.setDisplayFormat("dd.MM.yyyy")
        return feld

    @property
    def zeitraum(self) -> tuple[date, date]:
        return self.von.date().toPython(), self.bis.date().toPython()

    # --- Zeitraum ---------------------------------------------------------

    def _setze_vorlage(self):
        bereich = zeitraum_vorlage(self.vorlage.currentText(), self.heute)
        if bereich is None:
            return
        for feld, wert in zip((self.von, self.bis), bereich):
            feld.blockSignals(True)
            feld.setDate(QDate(wert.year, wert.month, wert.day))
            feld.blockSignals(False)
        self.laden()

    def _datum_geaendert(self):
        passend = next(
            (n for n in ZEITRAEUME if zeitraum_vorlage(n, self.heute) == self.zeitraum),
            "Benutzerdefiniert",
        )
        self.vorlage.blockSignals(True)
        self.vorlage.setCurrentText(passend)
        self.vorlage.blockSignals(False)
        self.laden()

    # --- Daten ------------------------------------------------------------

    def laden(self):
        von, bis = self.zeitraum
        try:
            with self.Session() as session:
                self.bewegungen = buchhaltung.kontobewegungen(session, von, bis)
                self.arten = buchhaltung.summen_nach_art(session, von, bis)
                self.buchungen = buchhaltung.buchungen(session, von=von, bis=bis)
        except buchhaltung.BuchhaltungsFehler as fehler:
            self.fehler.setText(str(fehler))
            self.fehler.show()
            self.bewegungen, self.arten, self.buchungen = [], [], []
        else:
            self.fehler.hide()
        self._zeige_kennzahlen()
        self._zeige_konten()
        self._zeige_arten()
        self._fuelle_kontoauswahl()

    def sichtbare_bewegungen(self) -> list[KontoBewegung]:
        passt = KONTOART_FILTER[self.kontoart.currentText()]
        alle = self.ohne_bewegung.isChecked()
        return [b for b in self.bewegungen if passt(b.konto) and (alle or b.hat_werte)]

    def gefilterte_buchungen(self) -> list[Buchung]:
        konto_id = self.buchungen_konto.currentData()
        if konto_id is None:
            return self.buchungen
        return [b for b in self.buchungen if konto_id in (b.soll_konto_id, b.haben_konto_id)]

    def _zeige_kennzahlen(self):
        kw = [b for b in self.bewegungen if b.konto.typ == KontoTyp.KW]
        # Geld, das nur zwischen Geldorten wandert (Geldtransfer und dessen Storno),
        # ist weder Einnahme noch Ausgabe
        intern = sum(
            b.betrag_cent for b in self.buchungen
            if b.soll_konto.typ == KontoTyp.KW and b.haben_konto.typ == KontoTyp.KW
        )
        anfang, zugang, abgang, _, ende = summe(kw)
        werte = (anfang, zugang - intern, abgang - intern, ende)
        for karte, wert in zip(
            (self.karte_anfang, self.karte_einnahmen, self.karte_ausgaben, self.karte_ende), werte
        ):
            karte.setze(wert, stil.NEGATIV if wert < 0 else None)

    def _zeige_konten(self):
        t = self.konten_tabelle
        t.setRowCount(0)
        for titel, zeilen, mit_summe in gruppiere(self.sichtbare_bewegungen()):
            for b in zeilen:
                status = b.konto.status.anzeige if b.konto.status else ""
                self._zeile(t, [
                    zelle(_konto_name(b.konto)), zelle(status),
                    betrag_zelle(b.anfang), betrag_zelle(b.zugang), betrag_zelle(-b.abgang),
                    betrag_zelle(b.veraenderung), betrag_zelle(b.ende, fett=True),
                ], grau=b.konto.geloescht or not b.konto.aktiv)
            if not mit_summe:
                continue
            a, z, ab, v, e = summe(zeilen)
            self._zeile(t, [
                zelle(f"Summe {titel}"), zelle(""),
                betrag_zelle(a), betrag_zelle(z), betrag_zelle(-ab), betrag_zelle(v), betrag_zelle(e),
            ], summe=True)

    def _zeige_arten(self):
        t = self.arten_tabelle
        t.setRowCount(0)
        for a in self.arten:
            self._zeile(t, [zelle(a.art.anzeige), zelle(str(a.anzahl), rechts=True), betrag_zelle(a.summe)])
        if self.arten:
            self._zeile(t, [
                zelle("Gesamt"), zelle(str(sum(a.anzahl for a in self.arten)), rechts=True), zelle(""),
            ], summe=True)

    def _fuelle_kontoauswahl(self):
        gewaehlt = self.buchungen_konto.currentData()
        self.buchungen_konto.blockSignals(True)
        self.buchungen_konto.clear()
        self.buchungen_konto.addItem("Alle Konten", None)
        for _, zeilen, _ in gruppiere([b for b in self.bewegungen if b.zugang or b.abgang]):
            for b in zeilen:
                self.buchungen_konto.addItem(_konto_name(b.konto), b.konto.id)
        index = self.buchungen_konto.findData(gewaehlt)
        self.buchungen_konto.setCurrentIndex(max(index, 0))
        self.buchungen_konto.blockSignals(False)
        self._zeige_buchungen()

    def _zeige_buchungen(self):
        t = self.buchungen_tabelle
        t.setRowCount(0)
        for b in self.gefilterte_buchungen():
            self._zeile(t, [
                zelle(b.datum.strftime("%d.%m.%Y")), zelle(b.art.anzeige), zelle(b.beleg), zelle(b.text),
                zelle(b.soll_konto.name), zelle(b.haben_konto.name), betrag_zelle(b.betrag_cent),
            ], grau=b.ist_storno or b.ist_storniert)
        self.reiter.setTabText(2, f"Buchungen ({t.rowCount()})")

    @staticmethod
    def _zeile(tabelle: QTableWidget, items, grau: bool = False, summe: bool = False):
        zeile = tabelle.rowCount()
        tabelle.insertRow(zeile)
        for spalte, item in enumerate(items):
            if grau:
                item.setForeground(GRAU)
            if summe:
                fett_machen(item)
                item.setBackground(QBrush(QColor(stil.AKZENT_HELL)))
            tabelle.setItem(zeile, spalte, item)

    # --- PDF --------------------------------------------------------------

    def pdf_speichern(self):
        if self.fehler.isVisible():
            QMessageBox.warning(self, "Fehler", self.fehler.text())
            return
        von, bis = self.zeitraum
        ordner = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        vorschlag = str(Path(ordner) / f"Auswertung_{von:%Y-%m-%d}_bis_{bis:%Y-%m-%d}.pdf")
        pfad, _ = QFileDialog.getSaveFileName(self, "Auswertung speichern", vorschlag, "PDF (*.pdf)")
        if not pfad:
            return
        titel = "Buchungen im Zeitraum"
        if self.buchungen_konto.currentData() is not None:
            titel += f" – {self.buchungen_konto.currentText()}"
        html = als_html(von, bis, self.sichtbare_bewegungen(), self.arten, self.gefilterte_buchungen(), titel)
        try:
            speichere_pdf(html, pfad, f"Auswertung {von:%d.%m.%Y} – {bis:%d.%m.%Y}")
        except OSError as fehler:
            QMessageBox.warning(self, "Fehler", f"PDF konnte nicht gespeichert werden:\n{fehler}")
            return
        QMessageBox.information(self, "Gespeichert", f"Die Auswertung wurde gespeichert:\n{pfad}")
