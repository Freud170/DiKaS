"""Verbindung zur SQLite-Datenbank."""

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session

from dikas.db.models import Base, Einstellung, Konto, KontoTyp

DB_DATEINAME = "verein.db"

# Interne Merker in der Tabelle `einstellungen` (Präfix "_": keine Benutzereinstellung)
LETZTE_AENDERUNG = "_letzte_aenderung"  # Zeitpunkt der letzten Datenänderung
LETZTER_AUSTAUSCH = "_letzter_austausch"  # Stand (= letzte Änderung) beim letzten Export/Import
STAND_ID = "_stand_id"  # ändert sich bei jeder Datenänderung: gleiche ID = gleicher Inhalt


def programm_verzeichnis() -> Path:
    """Ordner der .exe (gebündelt) bzw. Projektordner (Entwicklung)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def daten_verzeichnis() -> Path:
    """Wo die Vereinsdaten liegen.

    Installierte Version (.exe): %LOCALAPPDATA%\\DiKaS\\daten – beschreibbar ohne Adminrechte,
    bleibt bei Updates/Deinstallation erhalten und wird nicht von OneDrive synchronisiert.
    Entwicklung: Ordner `daten` im Projekt.
    """
    if getattr(sys, "frozen", False):
        basis = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return basis / "DiKaS" / "daten"
    return programm_verzeichnis() / "daten"


def standard_db_pfad() -> Path:
    return daten_verzeichnis() / DB_DATEINAME


@event.listens_for(Session, "before_flush")
def _aenderung_merken(session: Session, _kontext, _instanzen) -> None:
    """Bei jeder Datenänderung den Zeitpunkt festhalten (für Warnungen beim Import)."""
    geaendert = [
        obj for obj in (*session.new, *session.dirty, *session.deleted)
        if not (isinstance(obj, Einstellung) and obj.schluessel.startswith("_"))
    ]
    if not geaendert:
        return
    with session.no_autoflush:
        for schluessel, wert in (
            (LETZTE_AENDERUNG, datetime.now().isoformat(timespec="seconds")),
            (STAND_ID, uuid.uuid4().hex),
        ):
            eintrag = session.get(Einstellung, schluessel)
            if eintrag is None:
                session.add(Einstellung(schluessel=schluessel, wert=wert))
            else:
                eintrag.wert = wert


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


# Spalten, die nach dem ersten Einsatz dazugekommen sind: werden in bestehenden
# Datenbanken beim Start ergänzt (vorhandene Daten bleiben unverändert).
NACHTRAEGLICHE_SPALTEN = {
    "konten": {
        "eintrittsdatum": "DATE",
        "vorname": "VARCHAR(100) NOT NULL DEFAULT ''",
        "nachname": "VARCHAR(100) NOT NULL DEFAULT ''",
        "bierspitz": "VARCHAR(100) NOT NULL DEFAULT ''",
        "email": "VARCHAR(200) NOT NULL DEFAULT ''",
    },
    "buchungen": {"beitragsjahr": "INTEGER", "rechnung_noetig": "BOOLEAN"},
}


def _ergaenze_spalten(engine: Engine) -> None:
    with engine.begin() as conn:
        for tabelle, spalten in NACHTRAEGLICHE_SPALTEN.items():
            vorhanden = {zeile[1] for zeile in conn.exec_driver_sql(f"PRAGMA table_info({tabelle})")}
            for name, typ in spalten.items():
                if name not in vorhanden:
                    conn.exec_driver_sql(f"ALTER TABLE {tabelle} ADD COLUMN {name} {typ}")


def teile_namen(name: str) -> tuple[str, str]:
    """'Max von Müller' -> ('Max von', 'Müller'): letztes Wort = Nachname, Rest = Vorname."""
    teile = name.split()
    if not teile:
        return "", ""
    return " ".join(teile[:-1]), teile[-1]


def _namen_aufteilen(session: Session) -> None:
    """Mitglieder aus der Zeit vor Vor-/Nachname: Namen einmalig aufteilen."""
    alte = session.scalars(
        select(Konto).where(Konto.typ == KontoTyp.PRIVAT, Konto.vorname == "", Konto.nachname == "")
    )
    for konto in alte:
        konto.vorname, konto.nachname = teile_namen(konto.name)


def init_db(engine: Engine) -> None:
    """Legt fehlende Tabellen/Spalten an und stellt sicher, dass es das KW-Konto gibt."""
    Base.metadata.create_all(engine)
    _ergaenze_spalten(engine)
    with Session(engine) as session, session.begin():
        kw = session.scalar(select(Konto).where(Konto.typ == KontoTyp.KW))
        if kw is None:
            session.add(Konto(name="KW", typ=KontoTyp.KW, bemerkung="Liquider Bestand"))
        _namen_aufteilen(session)
