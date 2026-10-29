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

„Beiträge abbuchen“: **Beitragsjahr** wählen, Betrag je Status (Füxe / Aktive / Alumni)
eintragen und die Zielkasse wählen. Nach Vorschau und Bestätigung wird für jedes fällige
Mitglied eine Beitragsbuchung angelegt. Bei einem Fehler wird gar nichts gebucht.

Fällig ist, wer **aktiv** ist und am **01.01. des Jahres schon eingetreten** war
(Eintrittsdatum im Privatkonto). Ausgelassen – und in der Vorschau aufgelistet – werden:

- wer für das Jahr **schon einen Beitrag** hat (Schutz vor Doppelabbuchung; ein Storno gibt das Jahr wieder frei)
- wer **erst später eingetreten** ist
- wer **kein Eintrittsdatum** hat (ältere Konten – im Konto nachtragen)

Das Buchungsdatum steht standardmäßig auf dem 01.01. des Beitragsjahres, damit nachgeholte
Beiträge in der Auswertung im richtigen Jahr erscheinen. Es zählt der **aktuelle** Status
des Mitglieds.

### Auswertung

Button „Auswertung“ (Strg+P): Zeitraum wählen (Schnellauswahl Dieses/Letztes Jahr,
Dieser/Letzter Monat oder frei), Start- und Enddatum zählen mit.

- **Kontobewegungen**: je Konto Anfangsbestand, Zugänge, Abgänge, Veränderung und
  Endbestand, mit Summen für Kassen und Privatkonten; filterbar nach Kontoart/Status
- **Nach Buchungsart**: Anzahl und Summe je Buchungsart
- **Buchungen**: alle Buchungen im Zeitraum, filterbar nach Konto
- **Als PDF speichern**: Bericht mit allen drei Teilen (A4)

Stornierte Buchungen und ihre Stornos zählen jeweils als Zu- und Abgang, heben sich
in der Veränderung aber auf.

### Regeln

- Salden werden nie gespeichert, sondern aus den Buchungen berechnet.
- Beträge werden in Cent (Ganzzahl) gespeichert.
- Buchungen werden nie gelöscht, sondern **storniert** (automatische Gegenbuchung).
- **Deaktivieren** (Konto bearbeiten): z. B. ausgetreten, aber noch sichtbar, keine neuen Buchungen.
- **Löschen** geht nur bei Privatkonten mit **Saldo 0**:
  - ohne Buchungen → Konto wird wirklich entfernt
  - mit Buchungen → Konto wird als gelöscht markiert und ausgeblendet; die Buchungen
    bleiben in der Historie. Über den Filter „Gelöschte“ + „Wiederherstellen“ zurückholbar.
  - Buchungen eines gelöschten Kontos können erst nach dem Wiederherstellen storniert werden.

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
Zum Sichern oder Weitergeben einfach diese Datei kopieren. Neue Spalten aus späteren
Versionen werden beim Start automatisch ergänzt (`NACHTRAEGLICHE_SPALTEN` in
`dikas/db/database.py`), vorhandene Daten bleiben dabei unverändert.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

| Datei | Inhalt |
|---|---|
| `test_buchhaltung.py` | Grundregeln: Konten, Buchungsarten, Storno, Beitragslauf |
| `test_szenarien.py` | Vereinsalltag: Beiträge, Raten, Überzahlung, Strichliste, Auslagen, Feste, Spenden, Korrekturen, Austritt, ein komplettes Vereinsjahr |
| `test_robustheit.py` | Transaktionen (alles oder nichts), Speichern/Neustart, DB-Regeln, Zufallsabläufe, große Mengen, Rundung |
| `test_loeschen.py` | Privatkonto löschen/archivieren/wiederherstellen inkl. Oberfläche |
| `test_beitragsjahr.py` | Eintrittsdatum, Stichtag 01.01., Doppelschutz, Nachholen alter Jahre, DB-Update |
| `test_auswertung.py` | Kontobewegungen im Zeitraum, Summen je Art, Zeitraum-Vorlagen, PDF, Dialog |
| `test_geld.py` | Betragseingabe und -anzeige |
| `test_ui.py` | Hauptfenster und Dialoge (ohne sichtbares Fenster) |

`tests/conftest.py` enthält die Hilfsklasse `Verein`, mit der sich Abläufe lesbar in Euro
schreiben lassen (`verein.einzahlung(tom, "12,50")`).

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
    stil.py         Farben, Stylesheet, Symbole, deutsche Qt-Texte
    bausteine.py    Gemeinsame Bausteine (Tabellenzellen, Kennzahl-Karten, Panels)
    hauptfenster.py Kennzahlen, Kontenübersicht (Suche/Filter) + Buchungsliste
    auswertung.py   Auswertung über einen Zeitraum + PDF-Export
    dialoge.py      Dialoge Konto, Buchung, Beitragslauf
tests/              pytest-Tests
```

## Geplant

- Weitere Buchungsfälle (Beispiele folgen)
- Export/Import der Daten zwischen PCs
- Weitergabe als `.exe` per PyInstaller
