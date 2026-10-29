# DiKaS – Rechnungssystem für den Verein

Lokales Desktop-Programm (Windows) für Privatkonten, Kassen und das KW-Konto.
Läuft komplett offline, die Daten liegen in einer einzigen SQLite-Datei.

## Konzept

- **Privatkonten**: eins pro Mitglied, mit Status **Fux**, **Aktiver** oder **Alumni**
- **Kassen**: beliebig viele, getrennt geführt
- **KW-Konto**: genau eins, bildet den tatsächlichen liquiden Bestand ab (wird automatisch angelegt)

### Doppelte Buchführung (Soll/Haben)

- Das **KW-Konto** ist das Geld, das tatsächlich da ist (Aktivkonto: Soll = Plus).
- **Privatkonten und Kassen** zeigen, wem dieses Geld zusteht (Passivkonten: Haben = Plus).
- Kontrollregel (unten rechts in der Statusleiste): **KW = Summe aller Privatkonten + Kassen**.

Gebucht wird über **Buchungsarten**, Soll und Haben setzt das Programm selbst:

| Buchungsart | Wirkung |
|---|---|
| Einzahlung | Mitglied zahlt ein: Privatkonto +, KW + |
| Auszahlung | Mitglied bekommt Geld: Privatkonto −, KW − |
| Kassen-Einnahme | Kasse +, KW + |
| Kassen-Ausgabe | Kasse −, KW − |
| Umbuchung | zwischen Privatkonten/Kassen: Von −, Nach +, KW unverändert |
| Beitrag | Privatkonto −, Kasse +, KW unverändert |
| Storno | Gegenbuchung zu einer bestehenden Buchung |

Ein Privatkonto im Minus heißt: Das Mitglied schuldet dem Verein noch etwas.

### Beitragslauf

„Beiträge abbuchen“: Betrag je Status (Füxe / Aktive / Alumni) eintragen und die
Zielkasse wählen. Nach Vorschau und Bestätigung wird für jedes aktive Mitglied eine
Beitragsbuchung angelegt. Bei einem Fehler wird gar nichts gebucht.

### Regeln

- Salden werden nie gespeichert, sondern aus den Buchungen berechnet.
- Beträge werden in Cent (Ganzzahl) gespeichert.
- Buchungen werden nie gelöscht, sondern **storniert** (automatische Gegenbuchung).
- Konten werden nicht gelöscht, sondern deaktiviert.

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
  buchhaltung.py    Fachlogik: Konten, Buchungsarten, Storno, Beitragslauf, Salden
  geld.py           Cent <-> "12,50 €"
  db/
    models.py       Tabellen (Konto, Buchung)
    database.py     SQLite-Verbindung, DB-Pfad, Initialisierung
  ui/
    hauptfenster.py Kontenübersicht + Buchungsliste
    dialoge.py      Dialoge Konto, Buchung, Beitragslauf
tests/              pytest-Tests
```

## Geplant

- Weitere Buchungsfälle (Beispiele folgen)
- DB-Migrationen (Alembic), sobald echte Daten vorhanden sind
- Export/Import der Daten zwischen PCs
- Weitergabe als `.exe` per PyInstaller
