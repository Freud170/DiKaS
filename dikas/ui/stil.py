"""Farben, Schrift und Stylesheet der Oberfläche."""

from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFormLayout,
    QHeaderView,
    QTableWidget,
)

# Farbtokens
HINTERGRUND = "#f3f5f8"
FLAECHE = "#ffffff"
RAND = "#e1e5eb"
TEXT = "#1f2933"
TEXT_LEISE = "#6b7684"
AKZENT = "#1f5fae"
AKZENT_HOVER = "#184d8e"
AKZENT_HELL = "#e7effa"
POSITIV = "#1e7b45"
NEGATIV = "#c0392b"
INAKTIV = "#9aa3ae"

HAKEN = (Path(__file__).parent / "haken.svg").as_posix()

STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    font-size: 10pt;
}}
QMainWindow, QDialog {{
    background: {HINTERGRUND};
}}

/* Kennzahl-Karten und Panels */
#karte, #panel {{
    background: {FLAECHE};
    border: 1px solid {RAND};
    border-radius: 8px;
}}
#karteTitel {{
    color: {TEXT_LEISE};
    font-size: 8.5pt;
    font-weight: 600;
}}
#karteWert {{
    font-size: 15pt;
    font-weight: 600;
}}
#panelTitel {{
    font-size: 12pt;
    font-weight: 600;
}}
#panelInfo {{
    color: {TEXT_LEISE};
}}

/* Werkzeugleiste */
QToolBar {{
    background: {FLAECHE};
    border: none;
    border-bottom: 1px solid {RAND};
    padding: 4px 12px;
    spacing: 2px;
}}
QToolBar::separator {{
    background: {RAND};
    width: 1px;
    margin: 6px 8px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 9px;
}}
QToolButton:hover {{
    background: {AKZENT_HELL};
}}
QToolButton:pressed {{
    background: #d5e3f6;
}}
QToolButton#primaer {{
    background: {AKZENT};
    color: white;
    font-weight: 600;
}}
QToolButton#primaer:hover {{
    background: {AKZENT_HOVER};
}}

/* Tabellen */
QTableWidget {{
    background: {FLAECHE};
    alternate-background-color: #f8fafc;
    border: none;
    gridline-color: transparent;
    selection-background-color: {AKZENT_HELL};
    selection-color: {TEXT};
    outline: 0;
}}
QTableWidget::item {{
    padding: 0 8px;
    border-bottom: 1px solid #eef1f4;
}}
QTableWidget::item:selected {{
    background: {AKZENT_HELL};
    color: {TEXT};
}}
QHeaderView::section {{
    background: {FLAECHE};
    color: {TEXT_LEISE};
    font-size: 8.5pt;
    font-weight: 600;
    border: none;
    border-bottom: 2px solid {RAND};
    padding: 7px 8px;
}}

/* Eingabefelder */
QLineEdit, QComboBox, QDateEdit {{
    background: {FLAECHE};
    border: 1px solid #cfd5dd;
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus {{
    border: 1px solid {AKZENT};
}}
QComboBox::drop-down, QDateEdit::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {FLAECHE};
    border: 1px solid {RAND};
    selection-background-color: {AKZENT_HELL};
    selection-color: {TEXT};
    outline: 0;
}}

/* Schaltflächen in Dialogen */
QPushButton {{
    background: {FLAECHE};
    border: 1px solid #cfd5dd;
    border-radius: 6px;
    padding: 6px 16px;
    min-width: 70px;
}}
QPushButton:hover {{
    background: #f0f3f7;
}}
QPushButton:default {{
    background: {AKZENT};
    border-color: {AKZENT};
    color: white;
    font-weight: 600;
}}
QPushButton:default:hover {{
    background: {AKZENT_HOVER};
}}

/* Reiter */
QTabWidget::pane {{
    background: {FLAECHE};
    border: 1px solid {RAND};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_LEISE};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 16px;
    margin-right: 4px;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {TEXT};
}}
QTabBar::tab:selected {{
    color: {AKZENT};
    border-bottom: 2px solid {AKZENT};
}}

/* Kontrollkästchen */
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #b7c0cb;
    border-radius: 4px;
    background: {FLAECHE};
}}
QCheckBox::indicator:hover {{
    border-color: {AKZENT};
}}
QCheckBox::indicator:checked {{
    background: {AKZENT};
    border-color: {AKZENT};
    image: url({HAKEN});
}}

/* Sonstiges */
QSplitter::handle {{
    background: transparent;
    width: 12px;
}}
QStatusBar {{
    background: {FLAECHE};
    border-top: 1px solid {RAND};
    color: {TEXT_LEISE};
}}
QStatusBar::item {{
    border: none;
}}
#abstimmungOk, #abstimmungFehler {{
    border-radius: 10px;
    padding: 2px 10px;
    margin: 2px 6px;
    font-weight: 600;
}}
#abstimmungOk {{
    background: #e3f4ea;
    color: {POSITIV};
}}
#abstimmungFehler {{
    background: #fbe7e4;
    color: {NEGATIV};
}}
#hinweis {{
    color: {TEXT_LEISE};
    font-size: 9pt;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #c9d0d8;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
}}
"""


def anwenden(app: QApplication) -> None:
    """Einheitliches Aussehen auf jedem Windows-PC (unabhängig vom System-Theme)."""
    # Qt-eigene Texte (Abbrechen, Ja/Nein, Kalender …) auf Deutsch
    uebersetzer = QTranslator(app)
    pfad = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    if uebersetzer.load(QLocale(QLocale.German), "qtbase", "_", pfad):
        app.installTranslator(uebersetzer)
    QLocale.setDefault(QLocale(QLocale.German, QLocale.Germany))

    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor(HINTERGRUND))
    palette.setColor(QPalette.Base, QColor(FLAECHE))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(AKZENT))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)


def tabelle(spalten: list[str], rechts: list[int] = ()) -> QTableWidget:
    """Einheitlich gestaltete Tabelle; Spalten in `rechts` sind rechtsbündig (Beträge)."""
    t = QTableWidget(0, len(spalten))
    t.setHorizontalHeaderLabels(spalten)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setWordWrap(False)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(34)
    kopf = t.horizontalHeader()
    kopf.setSectionResizeMode(QHeaderView.ResizeToContents)
    kopf.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    kopf.setHighlightSections(False)
    for spalte in rechts:
        t.horizontalHeaderItem(spalte).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return t


def formular(form: QFormLayout) -> QFormLayout:
    """Einheitliche Abstände für Eingabeformulare in Dialogen."""
    form.setContentsMargins(22, 20, 22, 16)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return form


def symbol(name: str) -> QIcon:
    """Windows-Symbol (Segoe Fluent Icons) per Name aus QIcon.ThemeIcon, sonst leer."""
    eintrag = getattr(QIcon.ThemeIcon, name, None)
    return QIcon.fromTheme(eintrag) if eintrag is not None else QIcon()
