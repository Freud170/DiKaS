"""Daten an einen anderen PC weitergeben: Export in eine Datei und Import aus einer Datei.

Damit beim Hin- und Herkopieren nichts verloren geht, merkt sich jede Datenbank
- wann sie zuletzt geändert wurde (`_letzte_aenderung`, setzt database.py automatisch) und
- welchen Stand sie beim letzten Export/Import hatte (`_letzter_austausch`).
Daraus ergeben sich die Warnungen beim Import (ältere Datei, ungesicherte Änderungen hier).
"""

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dikas import sicherung
from dikas.db.database import LETZTE_AENDERUNG, LETZTER_AUSTAUSCH, STAND_ID

ENDUNG = ".db"


@dataclass(frozen=True)
class Datenstand:
    letzte_aenderung: datetime | None
    letzter_austausch: datetime | None
    mitglieder: int
    buchungen: int
    stand_id: str | None = None  # gleiche ID = gleicher Inhalt

    @property
    def ungesicherte_aenderungen(self) -> bool:
        """Wurde seit dem letzten Export/Import etwas geändert?"""
        if self.letzte_aenderung is None:
            return False
        return self.letzter_austausch is None or self.letzte_aenderung > self.letzter_austausch

    def beschreibung(self) -> str:
        zeit = f"{self.letzte_aenderung:%d.%m.%Y um %H:%M}" if self.letzte_aenderung else "unbekannt"
        return f"zuletzt geändert {zeit} · {self.mitglieder} Mitglieder · {self.buchungen} Buchungen"


def _zeit(wert: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(wert) if wert else None
    except ValueError:
        return None


def datenstand(pfad: Path) -> Datenstand:
    """Stand einer Datenbankdatei (nur lesend)."""
    with sqlite3.connect(f"file:{Path(pfad).as_posix()}?mode=ro", uri=True) as con:
        tabellen = {z[0] for z in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        merker = {}
        if "einstellungen" in tabellen:
            merker = dict(con.execute(
                "SELECT schluessel, wert FROM einstellungen WHERE schluessel IN (?, ?, ?)",
                (LETZTE_AENDERUNG, LETZTER_AUSTAUSCH, STAND_ID),
            ).fetchall())
        mitglieder = con.execute("SELECT COUNT(*) FROM konten WHERE typ = 'PRIVAT'").fetchone()[0]
        buchungen = con.execute("SELECT COUNT(*) FROM buchungen").fetchone()[0]
    con.close()
    return Datenstand(_zeit(merker.get(LETZTE_AENDERUNG)), _zeit(merker.get(LETZTER_AUSTAUSCH)),
                      mitglieder, buchungen, merker.get(STAND_ID))


def _austausch_merken(pfad: Path) -> None:
    """Merkt sich den aktuellen Stand als „ausgetauscht“ (direkt per SQL, ändert nicht die letzte Änderung)."""
    with sqlite3.connect(pfad) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS einstellungen (schluessel VARCHAR(50) NOT NULL PRIMARY KEY, wert TEXT NOT NULL)"
        )
        zeile = con.execute("SELECT wert FROM einstellungen WHERE schluessel = ?", (LETZTE_AENDERUNG,)).fetchone()
        stand = zeile[0] if zeile else datetime.now().isoformat(timespec="seconds")
        if zeile is None:
            con.execute("INSERT INTO einstellungen VALUES (?, ?)", (LETZTE_AENDERUNG, stand))
        con.execute(
            "INSERT INTO einstellungen VALUES (?, ?) ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
            (LETZTER_AUSTAUSCH, stand),
        )
    con.close()


def export_dateiname(jetzt: datetime | None = None) -> str:
    return f"DiKaS_{(jetzt or datetime.now()):%Y-%m-%d_%H-%M}{ENDUNG}"


def exportieren(db_pfad: Path, ziel: Path) -> Path:
    """Schreibt den aktuellen Stand in `ziel` (z. B. auf einen USB-Stick)."""
    db_pfad, ziel = Path(db_pfad), Path(ziel)
    if ziel.resolve() == db_pfad.resolve():
        raise ValueError("Bitte einen anderen Speicherort als die laufende Datenbank wählen.")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    # Erst in eine Hilfsdatei schreiben: Scheitert der Export (Stick voll, schreibgeschützt,
    # abgezogen), bleibt eine frühere Exportdatei erhalten und der eigene Stand gilt weiter
    # als „noch nicht ausgetauscht“ – sonst fehlte später die Warnung beim Import.
    entwurf = ziel.with_name(ziel.name + ".teil")
    try:
        entwurf.unlink(missing_ok=True)
        sicherung.kopiere_datenbank(db_pfad, entwurf)
        _austausch_merken(entwurf)
        os.replace(entwurf, ziel)
    except BaseException:
        entwurf.unlink(missing_ok=True)
        raise
    _austausch_merken(db_pfad)
    return ziel


def import_warnungen(quelle: Path, db_pfad: Path) -> list[str]:
    """Hinweise, bevor `quelle` die eigenen Daten ersetzt (leer = unbedenklich)."""
    sicherung.pruefen(quelle)
    if not Path(db_pfad).exists():
        return []
    neu, hier = datenstand(quelle), datenstand(db_pfad)
    warnungen = []
    if hier.ungesicherte_aenderungen and hier.mitglieder + hier.buchungen > 0:
        warnungen.append(
            "Auf diesem PC wurde seit dem letzten Austausch weitergearbeitet. Diese Änderungen "
            "werden durch den Import ersetzt (sie bleiben aber als Sicherung erhalten)."
        )
    if neu.letzte_aenderung and hier.letzte_aenderung and neu.letzte_aenderung < hier.letzte_aenderung:
        warnungen.append("Die Datei ist ÄLTER als der Stand auf diesem PC.")
    elif neu.stand_id and neu.stand_id == hier.stand_id:
        warnungen.append("Die Datei hat denselben Stand wie dieser PC – ein Import ist nicht nötig.")
    return warnungen


def importieren(quelle: Path, db_pfad: Path) -> sicherung.Sicherung | None:
    """Ersetzt die eigenen Daten durch `quelle`. Vorher wird der eigene Stand gesichert (Rückgabe).

    Die Verbindungen zur Datenbank müssen vorher geschlossen werden (engine.dispose()),
    danach init_db() aufrufen, damit ältere Dateien auf den aktuellen Stand kommen.
    """
    quelle, db_pfad = Path(quelle), Path(db_pfad)
    if quelle.resolve() == db_pfad.resolve():
        raise ValueError("Das ist die laufende Datenbank selbst.")
    sicherung.pruefen(quelle)
    vorher = sicherung.sichern(db_pfad)
    db_pfad.parent.mkdir(parents=True, exist_ok=True)
    sicherung.kopiere_datenbank(quelle, db_pfad)
    _austausch_merken(db_pfad)
    return vorher
