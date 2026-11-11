"""Automatische Sicherung der Datenbank bei jedem Programmstart.

Sicherungen liegen im Ordner `sicherung` neben der Datenbank, mit Datum und Uhrzeit im
Dateinamen. Es bleiben die letzten `BEHALTEN` unterschiedlichen Stände erhalten; ist die
Datenbank seit der letzten Sicherung unverändert, wird keine neue angelegt.
"""

import hashlib
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BEHALTEN = 10
ORDNER = "sicherung"
PRAEFIX = "verein_"
ZEITFORMAT = "%Y-%m-%d_%H-%M-%S"


@dataclass(frozen=True)
class Sicherung:
    pfad: Path
    zeitpunkt: datetime

    @property
    def groesse(self) -> int:
        return self.pfad.stat().st_size


def sicherungs_ordner(db_pfad: Path) -> Path:
    return Path(db_pfad).parent / ORDNER


def _zeitpunkt(pfad: Path) -> datetime | None:
    """Zeitpunkt aus dem Dateinamen (verein_2026-10-29_21-30-05[_2].db), sonst None."""
    name = pfad.stem.removeprefix(PRAEFIX)
    try:
        return datetime.strptime(name[: len("2026-10-29_21-30-05")], ZEITFORMAT)
    except ValueError:
        return None


def sicherungen(db_pfad: Path) -> list[Sicherung]:
    """Alle vorhandenen Sicherungen, neueste zuerst."""
    ordner = sicherungs_ordner(db_pfad)
    if not ordner.is_dir():
        return []
    gefunden = [
        Sicherung(p, zeit) for p in ordner.glob(f"{PRAEFIX}*.db") if (zeit := _zeitpunkt(p)) is not None
    ]
    return sorted(gefunden, key=lambda s: (s.zeitpunkt, s.pfad.name), reverse=True)


def _pruefsumme(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def kopiere_datenbank(quelle: Path, ziel: Path) -> None:
    """Konsistente Kopie über die SQLite-Backup-Funktion (auch wenn die DB gerade offen ist)."""
    # sqlite3.connect würde eine fehlende Quelle stillschweigend als leere Datei anlegen –
    # und das Ziel dann mit einer leeren Datenbank überschreiben
    if not Path(quelle).is_file():
        raise FileNotFoundError(f"{Path(quelle).name} nicht gefunden.")
    with sqlite3.connect(quelle) as von, sqlite3.connect(ziel) as nach:
        von.backup(nach)
    von.close()
    nach.close()


def sichern(
    db_pfad: Path, jetzt: datetime | None = None, behalten: int | None = BEHALTEN
) -> Sicherung | None:
    """Sichert die Datenbank. Rückgabe None, wenn es keine DB gibt oder sich nichts geändert hat.

    Mit `behalten=None` werden keine älteren Sicherungen gelöscht.
    """
    db_pfad = Path(db_pfad)
    if not db_pfad.exists():
        return None
    ordner = sicherungs_ordner(db_pfad)
    ordner.mkdir(parents=True, exist_ok=True)

    zeit = (jetzt or datetime.now()).replace(microsecond=0)
    ziel = ordner / f"{PRAEFIX}{zeit.strftime(ZEITFORMAT)}.db"
    nummer = 2
    while ziel.exists():  # mehrere Sicherungen in derselben Sekunde
        ziel = ordner / f"{PRAEFIX}{zeit.strftime(ZEITFORMAT)}_{nummer}.db"
        nummer += 1

    vorherige = sicherungen(db_pfad)
    kopiere_datenbank(db_pfad, ziel)
    if vorherige and _pruefsumme(vorherige[0].pfad) == _pruefsumme(ziel):
        ziel.unlink()  # unverändert seit der letzten Sicherung
        return None

    if behalten is not None:
        aufraeumen(db_pfad, behalten)
    return Sicherung(ziel, zeit)


def aufraeumen(db_pfad: Path, behalten: int = BEHALTEN, schuetzen: Collection[Path] = ()) -> list[Path]:
    """Löscht die ältesten Sicherungen, bis höchstens `behalten` übrig sind. Rückgabe: gelöschte Dateien.

    Dateien in `schuetzen` bleiben auf jeden Fall erhalten; dafür muss dann die nächstältere weichen.
    """
    geschuetzt = {Path(p) for p in schuetzen}
    alle = sicherungen(db_pfad)  # neueste zuerst
    zu_viele = max(len(alle) - behalten, 0)
    loeschbar = [s.pfad for s in reversed(alle) if s.pfad not in geschuetzt]  # älteste zuerst
    zu_alt = loeschbar[:zu_viele]
    for pfad in zu_alt:
        pfad.unlink(missing_ok=True)
    return zu_alt


def wiederherstellen(sicherung: Sicherung, db_pfad: Path, jetzt: datetime | None = None) -> Sicherung | None:
    """Ersetzt die Datenbank durch die Sicherung.

    Vorher wird der aktuelle Stand gesichert (Rückgabe), damit nichts verloren geht.
    Die Verbindungen zur Datenbank müssen vorher geschlossen werden (engine.dispose()).
    """
    if not sicherung.pfad.exists():
        raise FileNotFoundError(f"Sicherung {sicherung.pfad.name} nicht gefunden.")
    pruefen(sicherung.pfad)
    # Erst nach dem Zurückspielen aufräumen und die gewählte Sicherung dabei nie löschen:
    # Sonst könnte sie als älteste verschwinden, bevor sie kopiert ist
    vorher = sichern(db_pfad, jetzt, behalten=None)
    kopiere_datenbank(sicherung.pfad, Path(db_pfad))
    aufraeumen(db_pfad, BEHALTEN + 1, schuetzen=[sicherung.pfad])
    return vorher


def pruefen(pfad: Path) -> None:
    """Wirft ValueError, wenn die Datei keine intakte Vereinsdatenbank ist."""
    try:
        with sqlite3.connect(f"file:{Path(pfad).as_posix()}?mode=ro", uri=True) as con:
            ergebnis = con.execute("PRAGMA quick_check").fetchone()[0]
            tabellen = {z[0] for z in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
    except sqlite3.DatabaseError as fehler:
        raise ValueError(f"{Path(pfad).name} ist keine gültige Datenbank ({fehler}).") from None
    if ergebnis != "ok":
        raise ValueError(f"{Path(pfad).name} ist beschädigt ({ergebnis}).")
    if not {"konten", "buchungen"} <= tabellen:
        raise ValueError(f"{Path(pfad).name} ist keine Vereinsdatenbank.")
