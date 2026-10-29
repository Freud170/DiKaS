"""Programmstart."""

import sqlite3
import sys

from PySide6.QtWidgets import QApplication
from sqlalchemy.orm import sessionmaker

from dikas import sicherung
from dikas.db import erstelle_engine, init_db, standard_db_pfad
from dikas.ui import stil
from dikas.ui.hauptfenster import Hauptfenster


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("DiKaS")
    stil.anwenden(app)

    db_pfad = standard_db_pfad()
    # Vor allem anderen (auch vor DB-Updates) den aktuellen Stand lokal sichern
    try:
        neu = sicherung.sichern(db_pfad)
        meldung = f"Sicherung erstellt: {neu.zeitpunkt:%d.%m.%Y %H:%M}" if neu else ""
    except (OSError, sqlite3.Error) as fehler:
        meldung = f"Sicherung fehlgeschlagen: {fehler}"
    engine = erstelle_engine(db_pfad)
    init_db(engine)

    fenster = Hauptfenster(sessionmaker(engine, expire_on_commit=False), str(db_pfad))
    fenster.show()
    if meldung:
        fenster.statusBar().showMessage(meldung, 8000)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
