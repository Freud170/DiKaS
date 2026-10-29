"""Verbindung zur SQLite-Datenbank."""

import sys
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session

from dikas.db.models import Base, Konto, KontoTyp

DB_DATEINAME = "verein.db"


def programm_verzeichnis() -> Path:
    """Ordner der .exe (gebündelt) bzw. Projektordner (Entwicklung)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def standard_db_pfad() -> Path:
    """Die DB liegt portabel im Ordner 'daten' neben dem Programm."""
    return programm_verzeichnis() / "daten" / DB_DATEINAME


def erstelle_engine(pfad: Path | str | None = None) -> Engine:
    """Engine für die angegebene DB-Datei. ':memory:' für Tests."""
    if pfad is None:
        pfad = standard_db_pfad()
    if str(pfad) == ":memory:":
        url = "sqlite://"
    else:
        pfad = Path(pfad)
        pfad.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{pfad}"
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    """Legt fehlende Tabellen an und stellt sicher, dass es das KW-Konto gibt."""
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        kw = session.scalar(select(Konto).where(Konto.typ == KontoTyp.KW))
        if kw is None:
            session.add(Konto(name="KW", typ=KontoTyp.KW, bemerkung="Liquider Bestand"))
