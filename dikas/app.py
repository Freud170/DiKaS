"""Programmstart."""

import sys

from PySide6.QtWidgets import QApplication
from sqlalchemy.orm import sessionmaker

from dikas.db import erstelle_engine, init_db, standard_db_pfad
from dikas.ui import stil
from dikas.ui.hauptfenster import Hauptfenster


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("DiKaS")
    stil.anwenden(app)

    db_pfad = standard_db_pfad()
    engine = erstelle_engine(db_pfad)
    init_db(engine)

    fenster = Hauptfenster(sessionmaker(engine, expire_on_commit=False), str(db_pfad))
    fenster.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
