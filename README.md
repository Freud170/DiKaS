# DiKaS – Rechnungssystem für den Verein

Lokales Desktop-Programm (Windows) für Privatkonten, Kassen und das KW-Konto.
Läuft komplett offline, die Daten liegen in einer einzigen SQLite-Datei.

## Konzept

- **Privatkonten**: eins pro Mitglied, mit **Vor- und Nachname** (Pflicht; angezeigt als
  „Vorname Nachname“, sortiert nach Nachname), Status **Fux**, **Aktiver**, **Alumni**,
  **Fördermitglied (FM)** oder **Ehrenmitglied (EM)**,
  Eintrittsdatum, **Bierspitz** (Spitzname, optional) und **E-Mail-Adresse** (optional, kann
  nachgetragen werden; wird beim Kontoauszug-Versand gebraucht). Die Suche findet Name,
  Bierspitz und E-Mail.
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

„Beiträge abbuchen“: **Beitragsjahr** wählen, Betrag je Status (Füxe / Aktive / Alumni /
Fördermitglieder / Ehrenmitglieder, 0 = beitragsfrei) eintragen und die Zielkasse wählen.
In der Vorschau wird per **Häkchen** festgelegt, wer belastet wird. Bei einem Fehler wird
gar nichts gebucht.

- **Angehakt** sind alle, die **aktiv** sind und am **01.01. des Jahres schon eingetreten**
  waren. Einzelne lassen sich abwählen.
- **Nicht angehakt, aber wählbar** sind Mitglieder, die **erst nach dem 01.01. eingetreten**
  sind (z. B. am 02.01.) oder **kein Eintrittsdatum** haben.
- **Gesperrt** ist, wer für das Jahr **schon einen Beitrag** hat (Schutz vor
  Doppelabbuchung; ein Storno gibt das Jahr wieder frei).

Das Buchungsdatum steht standardmäßig auf dem 01.01. des Beitragsjahres, damit nachgeholte
Beiträge in der Auswertung im richtigen Jahr erscheinen.

### Statusverlauf

Jedes Privatkonto hat einen **Statusverlauf** (z. B. Fux ab 15.10.2023, Aktiver ab
01.11.2024, Alumni ab …). Beim Anlegen entsteht der erste Eintrag ab Eintrittsdatum; unter
„Bearbeiten“ lassen sich Statuswechsel mit Datum hinzufügen, korrigieren oder entfernen
(keine Daten in der Zukunft, höchstens ein Wechsel pro Tag). In der Kontenliste steht der
aktuelle Status (neuester Eintrag).

Der **Beitragslauf** nimmt den Status, der am **01.01. des Beitragsjahres** galt – auch beim
Nachholen alter Jahre. Ein Wechsel genau am 01.01. zählt schon für dieses Jahr.
Ältere Konten ohne Verlauf verwenden den aktuellen Status; der Verlauf beginnt beim ersten
Statuswechsel.

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

### Kontoauszüge per E-Mail

Button „Kontoauszüge“ (Strg+M): Stichtag wählen → jedes Mitglied bekommt seinen Kontostand
zu diesem Tag per Mail.

- **Saldo negativ**: offener Betrag + Bankdaten + Verwendungszweck zum Überweisen
- **Saldo positiv**: Guthaben + „melde dich, wenn du es zurück willst“
- **Saldo 0**: „Gut gewirtschaftet! 🍻“

Ablauf: Empfänger prüfen (Vorauswahl: mit E-Mail, aktiv oder mit offenem Saldo, für diesen
Stichtag noch nicht versendet) → Vorschau ansehen → **Testmail an mich** → senden. Jeder
Versand wird protokolliert („Zuletzt versendet“); wer für den Stichtag schon eine Mail hat,
ist beim nächsten Öffnen abgewählt. Fehlgeschlagene Mails bleiben ausgewählt.

**Einstellungen** (Schraubenschlüssel oben rechts):

- *E-Mail-Konto*: Anbieter-Vorlagen für Gmail, GMX, web.de, T-Online, iCloud, IONOS, Strato
  oder eigener Server (SMTP-Server, Port, STARTTLS/SSL). Das **Passwort wird nicht
  gespeichert**, sondern beim Versand abgefragt. Gmail braucht ein **App-Passwort**
  (Google-Konto → Sicherheit → Bestätigung in zwei Schritten → App-Passwörter).
- *Bankdaten*: Kontoinhaber, IBAN, BIC, Bank
- *Texte*: Betreff, Verwendungszweck und die drei Mailtexte mit Platzhaltern wie
  `{anrede}` (Bierspitz, sonst Vorname), `{vorname}`, `{nachname}`, `{saldo}`, `{betrag}`,
  `{stichtag}`, `{iban}` …

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
Zum Weitergeben einfach diese Datei kopieren.

**Automatische Sicherung:** Bei jedem Programmstart wird der aktuelle Stand nach
`daten\sicherung\verein_JJJJ-MM-TT_HH-MM-SS.db` gesichert – nur wenn sich seit der letzten
Sicherung etwas geändert hat. Es bleiben die **letzten 10 Stände** erhalten. Über
Schraubenschlüssel → „Sicherungen …“ lassen sie sich ansehen und wiederherstellen (der
aktuelle Stand wird vorher noch einmal gesichert). Sicherungen bleiben **nur lokal** und
werden von Git ignoriert. Neue Spalten aus späteren
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
| `test_statusverlauf.py` | Statuswechsel mit Datum, Status am Stichtag, Beitrag nach damaligem Status, Editor |
| `test_beitrag_auswahl.py` | Status FM/EM, manuelle Auswahl im Beitragslauf, Doppelschutz |
| `test_namen.py` | Vor-/Nachname: Pflicht, Aufteilen alter Namen, Sortierung, Anrede, Dialog |
| `test_kontakt.py` | Bierspitz und E-Mail: Prüfung, Dialog, Suche, DB-Update |
| `test_kontoauszug.py` | Einstellungen, Mailtexte, Versand (inkl. Test-SMTP-Server im Test), Fehlerfälle, Dialoge |
| `test_sicherung.py` | Sicherung bei Start, nur bei Änderung, letzte 10, Wiederherstellen, Git-Ignorierung |
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
  einstellungen.py  Einstellungen (Mailserver, Bankdaten, Textvorlagen), Anbieter-Vorlagen
  kontoauszug.py    Kontoauszug-Mails erzeugen, per SMTP senden, Versand protokollieren
  sicherung.py      Automatische lokale Sicherung, letzte 10 Stände, Wiederherstellen
  geld.py           Cent <-> "12,50 €"
  db/
    models.py       Tabellen (Konto, Statuswechsel, Buchung, Einstellung, Mailversand)
    database.py     SQLite-Verbindung, DB-Pfad, Initialisierung
  ui/
    stil.py         Farben, Stylesheet, Symbole, deutsche Qt-Texte
    bausteine.py    Gemeinsame Bausteine (Tabellenzellen, Kennzahl-Karten, Panels)
    hauptfenster.py Kennzahlen, Kontenübersicht (Suche/Filter) + Buchungsliste
    auswertung.py   Auswertung über einen Zeitraum + PDF-Export
    einstellungen_dialog.py  Einstellungen bearbeiten
    versand_dialog.py        Kontoauszüge per E-Mail versenden
    sicherungen_dialog.py    Sicherungen ansehen und wiederherstellen
    dialoge.py      Dialoge Konto, Buchung, Beitragslauf
tests/              pytest-Tests
```

## Geplant

- Weitere Buchungsfälle (Beispiele folgen)
- Export/Import der Daten zwischen PCs
- Weitergabe als `.exe` per PyInstaller
