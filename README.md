# DiKaS – Rechnungssystem für den Verein

Lokales Desktop-Programm (Windows) für Privatkonten, Kassen und das KW-Konto.
Läuft komplett offline, die Daten liegen in einer einzigen SQLite-Datei.

## Konzept

- **Privatkonten**: eins pro Mitglied
- **Kassen**: beliebig viele, getrennt geführt
- **KW-Konto**: genau eins, bildet den tatsächlichen liquiden Bestand ab (wird automatisch angelegt)

Gebucht wird nach dem Prinzip der **doppelten Buchführung**: Jede Buchung geht
*von* einem Konto *nach* einem anderen. Der Saldo des Zielkontos steigt, der des
Quellkontos sinkt. Die Summe aller Salden ist damit immer 0.

- Salden werden nie gespeichert, sondern aus den Buchungen berechnet.
- Beträge werden in Cent (Ganzzahl) gespeichert.
- Buchungen werden nie gelöscht, sondern **storniert** (automatische Gegenbuchung).

## Technik

| Bereich | Wahl |
|---|---|
| Sprache | Python 3.15 |
| Datenbank | SQLite über SQLAlchemy 2.1 |
| Oberfläche | PySide6 (Qt 6) |
| Tests | pytest |

## Einrichten (Entwicklung)

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Starten

```powershell
.\.venv\Scripts\python.exe -m dikas
```

Die Datenbank wird beim ersten Start unter `daten\verein.db` angelegt.
Zum Sichern oder Weitergeben einfach diese Datei kopieren.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Projektstruktur

```
dikas/
  app.py            Programmstart
  buchhaltung.py    Fachlogik: Konten, Buchungen, Storno, Salden
  geld.py           Cent <-> "12,50 €"
  db/
    models.py       Tabellen (Konto, Buchung)
    database.py     SQLite-Verbindung, DB-Pfad, Initialisierung
  ui/
    hauptfenster.py Kontenübersicht + Buchungsliste
    dialoge.py      Dialoge "Neues Konto" / "Neue Buchung"
tests/              pytest-Tests
```

## Geplant

- Konkrete Buchungsarten (Beispiele folgen)
- Export/Import der Daten zwischen PCs
- Weitergabe als `.exe` per PyInstaller
