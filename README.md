# DiKaS – Rechnungssystem für den Verein

Lokales Desktop-Programm (Windows) für Privatkonten, Kassen und das KW-Konto.
Läuft komplett offline, die Daten liegen in einer einzigen SQLite-Datei.

## Installation (für Nutzer)

1. `DiKaS-Setup-<Version>.exe` per Doppelklick starten – keine Administratorrechte, kein
   Python und kein Internet nötig. Zeigt Windows „Der Computer wurde durch Windows
   geschützt“: **Weitere Informationen → Trotzdem ausführen** (das Programm ist nicht
   kostenpflichtig signiert).
2. DiKaS über Startmenü oder Desktop-Verknüpfung starten.
3. **Updates** – zwei Wege, die Daten bleiben jeweils erhalten:
   - In DiKaS: Schraubenschlüssel → **„Update installieren …“** → neue
     `DiKaS-Setup-<Version>.exe` wählen. DiKaS schließt sich, aktualisiert sich ohne
     weitere Fragen und startet neu.
   - Oder die neue Setup-Datei per Doppelklick starten: Sie erkennt die installierte
     Version, fragt einmal nach, deinstalliert die alte und installiert die neue.

Die Daten liegen bei der installierten Version unter `%LOCALAPPDATA%\DiKaS\daten\`
(Schraubenschlüssel → „Datenordner öffnen“) – getrennt vom Programm, nicht in OneDrive,
und sie bleiben auch bei einer Deinstallation erhalten.

## Daten an einen anderen PC weitergeben

Alle Daten (Mitglieder, Buchungen, Einstellungen – aber keine Passwörter) stecken in
**einer** Datei. Weitergabe über den Schraubenschlüssel:

1. Bisheriger PC: **„Daten exportieren …“** → z. B. auf USB-Stick
   (`DiKaS_2026-11-03_19-30.db`).
2. Anderer PC: **„Daten importieren …“** → Datei wählen. Der eigene Stand wird vorher
   gesichert. DiKaS **warnt**, wenn die Datei älter ist als der eigene Stand oder auf diesem
   PC seit dem letzten Austausch weitergearbeitet wurde.

**Regel:** Es arbeitet immer nur ein PC mit den Daten („Staffelstab“) – getrennt
gebuchte Stände lassen sich nicht zusammenführen. Die Datei enthält personenbezogene
Daten: nicht per Mail verschicken, am besten verschlüsselten USB-Stick nutzen.

## Installer bauen (Entwicklung)

Voraussetzungen: `.venv` eingerichtet (inkl. `pip install -e ".[dev]"`, enthält PyInstaller)
und [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

```powershell
.\packaging\bauen.ps1            # Tests, DiKaS.exe (PyInstaller), Installer (Inno Setup)
.\packaging\bauen.ps1 -OhneTests # schneller, ohne Testlauf
```

Ergebnis: `build\installer\DiKaS-Setup-<Version>.exe` (ca. 40 MB). Die Version steht in
`dikas/__init__.py`. Der Ordner `build\` wird von Git ignoriert.

## Konzept

- **Privatkonten**: eins pro Mitglied, mit **Vor- und Nachname** (Pflicht; angezeigt als
  „Vorname Nachname“, sortiert nach Nachname – Namenszusätze wie „von“, „van“, „de“, „zu“
  werden dabei übersprungen, „von Hahn“ steht also unter H; Umlaute wie im Telefonbuch), Status **Fux**, **Aktiver**, **Alumni**,
  **Fördermitglied (FM)** oder **Ehrenmitglied (EM)**,
  Eintrittsdatum, **Bierspitz** (Spitzname, optional) und **E-Mail-Adresse** (optional, kann
  nachgetragen werden; wird beim Kontoauszug-Versand gebraucht). Die Suche findet Name,
  Bierspitz und E-Mail.
- **Kontenliste**: Spalten Nachname, Vorname, Bierspitz, Typ, Status, Eintritt, Saldo. Sortierbar
  über die Auswahl neben dem Filter (z. B. „Nachname A–Z“, „Saldo: höchster zuerst“) oder per
  Klick auf die Spaltenüberschrift (zweiter Klick dreht um). Leere Werte stehen immer unten.
  Spalten lassen sich an der Überschrift **verschieben** (ziehen) und per **Rechtsklick** ein-
  und ausblenden („Standardansicht“ stellt alles zurück). Das merkt sich DiKaS pro PC in
  `%APPDATA%\DiKaS\DiKaS.ini` – nicht in der Vereinsdatenbank, also auch nicht im Export.
- Spaltenbreiten passen sich der Fenstergröße an (auch im Vollbild); ist das Fenster zu schmal,
  lässt sich die Liste waagerecht scrollen.
- **Buchungssuche** (über der Buchungsliste): findet Text, Beleg und Kontonamen; eine Zahl wie
  `25` oder `12,50` findet außerdem alle Buchungen über genau diesen Betrag. Gilt für das gewählte
  Konto bzw. alle Buchungen.
- **Kassen**: beliebig viele, getrennt geführt
- **Geldorte (KW)**: wo das tatsächlich vorhandene Geld liegt, z. B. „Bargeld“, „Bankkonto“
  oder vorübergehend „Bei Max Mustermann“. Der erste („KW“) wird automatisch angelegt, weitere
  über „Neues Konto“ → Typ *Geldort*. **KW gesamt** = Summe aller Geldorte.

### Doppelte Buchführung (Soll/Haben)

- Die **Geldorte** zeigen, wo das Geld liegt, das tatsächlich da ist (Aktivkonten: Soll = Plus).
- **Privatkonten und Kassen** zeigen, wem dieses Geld zusteht (Passivkonten: Haben = Plus).
- Kontrollregel (unten rechts in der Statusleiste): **KW (alle Geldorte) = Summe aller Privatkonten + Kassen**.

Gebucht wird über **Buchungsarten**, Soll und Haben setzt das Programm selbst:

| Buchungsart | Wirkung |
|---|---|
| Einzahlung | Mitglied zahlt ein: Privatkonto +, Geldort + |
| Auszahlung | Mitglied bekommt Geld: Privatkonto −, Geldort − |
| Kassen-Einnahme | Kasse +, Geldort + |
| Kassen-Ausgabe | Kasse −, Geldort − |
| Umbuchung | zwischen Privatkonten/Kassen: Von −, Nach +, KW unverändert |
| Beitrag | Privatkonto −, Kasse +, KW unverändert |
| Geldtransfer | zwischen Geldorten (z. B. Bargeld zur Bank): Von −, Nach +, KW gesamt unverändert |
| Storno | Gegenbuchung zu einer bestehenden Buchung |

Gibt es mehrere Geldorte, fragt die Buchung zusätzlich nach dem **Geldort**. Vorausgewählt ist
der Standard-Geldort, also der älteste aktive. Bei nur einem Geldort bleibt das Feld ausgeblendet.

**Beispiel:** Solange das Vereinskonto fehlt, verwahrt Max 300 € → Geldort „Bei Max“ anlegen
und *Geldtransfer* KW → Bei Max über 300 €. Wenn das Bankkonto da ist: Geldort „Bankkonto“
anlegen, *Geldtransfer* Bei Max → Bankkonto, danach „Bei Max“ deaktivieren.

Ein Privatkonto im Minus heißt: Das Mitglied schuldet dem Verein noch etwas.

### Beitragslauf

„Beiträge abbuchen“: **Beitragsjahr** wählen (‹ 2026 ›, auch per Mausrad/Pfeiltasten), Betrag je Status (Füxe / Aktive / Alumni /
Fördermitglieder / Ehrenmitglieder, 0 = beitragsfrei) eintragen und die Zielkasse wählen.
In der Vorschau wird per **Häkchen** festgelegt, wer belastet wird. Bei einem Fehler wird
gar nichts gebucht.

- **Angehakt** sind alle, die **aktiv** sind und am **01.01. des Jahres schon eingetreten**
  waren. Einzelne lassen sich abwählen.
- **Nicht angehakt, aber wählbar** sind Mitglieder, die **erst nach dem 01.01. eingetreten**
  sind (z. B. am 02.01.) oder **kein Eintrittsdatum** haben.
- **Gesperrt** ist, wer für das Jahr **schon einen Beitrag** hat (Schutz vor
  Doppelabbuchung; ein Storno gibt das Jahr wieder frei) oder für wessen Status **kein
  Beitrag** eingetragen ist (z. B. Ehrenmitglieder mit 0 €) – jeweils mit Hinweis.
- **Maßgeblicher Status**: Wer am 01.01. schon Mitglied war, zahlt nach dem Status am 01.01.
  Wer im Laufe des Jahres eingetreten ist, zahlt nach dem Status, den er in dem Jahr erreicht
  hat (Stand 31.12. bzw. heute, wenn das Jahr noch läuft).

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
  Endbestand, mit Summen für Geldorte (ab zwei), Kassen und Privatkonten; filterbar nach
  Kontoart/Status. Die Kennzahlen „Einnahmen/Ausgaben (KW)“ zählen Geldtransfers nicht mit.
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
ist beim nächsten Öffnen abgewählt. Fehlgeschlagene Mails bleiben ausgewählt. Das Protokoll
wird nach jeder einzelnen Mail gespeichert: Bricht ein Lauf mittendrin ab, bekommt beim
nächsten Mal niemand seinen Kontoauszug doppelt.

**Umsätze als PDF** (Häkchen oben, standardmäßig an): Jede Mail bekommt ein PDF
`Kontoauszug_JJJJ_Nachname_Vorname.pdf` mit den Buchungen auf dem **eigenen** Privatkonto vom
01.01. bis zum Stichtag: Kontostand am Anfang, jede Buchung mit Art, Text, Gegenkonto, Betrag und
laufendem Kontostand, Kontostand am Ende. Die Konten anderer Mitglieder stehen nicht darin
(nur als Gegenkonto bei einer Umbuchung). „PDF ansehen“ öffnet das PDF des markierten
Mitglieds, die Testmail enthält es ebenfalls.

**Einstellungen** (Schraubenschlüssel oben rechts):

- *E-Mail-Konto*: Anbieter-Vorlagen für Gmail, GMX, web.de, T-Online, iCloud, IONOS, Strato
  oder eigener Server (SMTP-Server, Port, STARTTLS/SSL). Das **Passwort wird nicht
  gespeichert**, sondern beim Versand abgefragt. Gmail braucht ein **App-Passwort**
  (Google-Konto → Sicherheit → Bestätigung in zwei Schritten → App-Passwörter).
  Bei Strato ist der Benutzername die vollständige Postfach-Adresse, und die Absender-E-Mail
  sollte dieselbe Adresse sein.
- *Bankdaten*: Kontoinhaber, IBAN, BIC, Bank
- *Texte*: Betreff, Verwendungszweck und die drei Mailtexte mit Platzhaltern wie
  `{anrede}` (Bierspitz, sonst Vorname), `{vorname}`, `{nachname}`, `{saldo}`, `{betrag}`,
  `{stichtag}`, `{iban}` …

**Mail kommt nicht an?** „Gesendet“ heißt: Der Mailserver hat die Mail angenommen. Was danach
passiert, sieht DiKaS nicht. Der Reihe nach prüfen: Spam-Ordner des Empfängers, Postfach der
Absenderadresse (abgelehnte Mails kommen dort als „Mail delivery failed“ zurück) und ob
Absender-E-Mail und Benutzername zum selben Postfach gehören.

### Rechnungen an Buchungen

Rechnungen und Belege als **PDF oder Foto** (JPG, PNG, GIF, BMP, WebP, TIFF) lassen sich an
Buchungen hängen:

- **Beim Buchen:** Im Dialog „Neue Buchung“ unter „Rechnungen“ auf „Datei …“ klicken oder
  Dateien aus dem Explorer auf den Dialog ziehen.
- **Nachträglich:** Buchung markieren → Knopf **„Rechnungen“** über der Buchungsliste (oder
  Rechtsklick → „Rechnungen …“). Dort lassen sich Dateien anhängen (auch per Ziehen),
  **öffnen** (Doppelklick, mit dem Standardprogramm), speichern und entfernen.
- Buchungen mit Rechnung zeigen eine **Büroklammer** in der Spalte „Beleg“; der Tooltip nennt
  die Dateinamen.

Die Dateien liegen **in der Datenbank** (Tabelle `anhaenge`). Deshalb gehen sie bei
Export/Import und in den Sicherungen automatisch mit. Damit die Datenbank nicht zu groß
wird, werden Fotos über 2000 Pixel oder 800 KB beim Anhängen verkleinert (JPG, Qualität 80;
ein Handyfoto hat danach meist 300–500 KB). PDFs bleiben unverändert (höchstens 20 MB).
iPhone-Fotos im HEIC-Format gehen nicht, bitte als JPG speichern.

Bei einer **Korrektur** mit Neubuchung wandern die Rechnungen zur neuen Buchung. Beim
**Löschen** einer Buchung werden ihre Rechnungen mitgelöscht (die Sicherung davor enthält sie
noch). An Stornobuchungen kann nichts angehängt werden. Zum Ansehen wird die Datei in den
Temp-Ordner (`%TEMP%\DiKaS\ansicht`) entpackt, der beim nächsten Start geleert wird.

### Regeln

- Salden werden nie gespeichert, sondern aus den Buchungen berechnet.
- Beträge werden in Cent (Ganzzahl) gespeichert. Eingabe als `12,50`, `12.50` oder mit
  Tausenderpunkt wie in der Anzeige: `1.000` sind eintausend Euro, `1.000,50` ebenso gültig.
- Buchhalterisch sauber ist **Stornieren** (automatische Gegenbuchung).
- **Löschen** (Knopf an der Buchungsliste, Entf-Taste oder Rechtsklick; mehrere per
  Strg/Umschalt markierbar) entfernt Buchungen endgültig – für eine übersichtliche Liste.
  Storno-Paare werden immer gemeinsam gelöscht. Vor dem ersten Löschen einer Sitzung wird
  automatisch gesichert (nur einmal, damit ältere Sicherungen nicht verdrängt werden). Sind
  gültige Jahresbeiträge dabei, warnt DiKaS: Das Mitglied ist danach wieder fällig.
- **Mehrfachauswahl:** Stornieren wirkt auf alle markierten Buchungen (bereits stornierte
  werden übersprungen); Korrigieren geht immer nur für eine Buchung (Doppelklick).
- **Korrigieren** (Doppelklick auf eine Buchung, Knopf über der Buchungsliste oder
  Rechtsklick): Dialog mit allen Werten vorbefüllt. Reine Text-/Beleg-Änderungen werden direkt
  übernommen; ändern sich Betrag, Konten, Art oder Datum, wird die alte Buchung (mit ihrem
  Datum) storniert und eine neue angelegt. Ein Beitragsjahr bleibt dabei erhalten.
  Bei Buchungen deaktivierter Konten lassen sich nur Text und Beleg korrigieren.
- **Deaktivieren** (Konto bearbeiten): z. B. ausgetreten, aber noch sichtbar, keine neuen Buchungen.
  Ein Geldort lässt sich nur bei Saldo 0 deaktivieren, und mindestens einer bleibt aktiv.
- **Löschen** geht nur bei Privatkonten mit **Saldo 0**:
  - ohne Buchungen → Konto wird wirklich entfernt (samt Einträgen im Versandprotokoll)
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

Oder per Desktop-Verknüpfung (startet ohne Konsolenfenster):

```powershell
$verknuepfung = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\DiKaS.lnk")
$verknuepfung.TargetPath = "$PWD\.venv\Scripts\dikas.exe"
$verknuepfung.WorkingDirectory = "$PWD"
$verknuepfung.IconLocation = "$PWD\dikas\ui\logo.ico,0"   # nur mit eigenem Logo, siehe unten
$verknuepfung.Save()
```

### Eigenes Vereinslogo

Das Logo ist nicht im Repo (`.gitignore`), jeder Verein baut sein eigenes ein. Ohne Logo
startet DiKaS ganz normal, nur mit Standardsymbol.

```powershell
.\.venv\Scripts\python.exe -m dikas.logo C:\Pfad\zum\wappen.png --rund
```

- Erzeugt `dikas\ui\logo.png` (Fenster und Taskleiste) und `dikas\ui\logo.ico`
  (Desktop-Verknüpfung, mehrere Größen von 16 bis 256 px).
- Das Bild wird auf ein **mittiges Quadrat** zugeschnitten. Am besten also ein quadratisches
  Bild verwenden, auf dem das Wappen den Platz ausfüllt (PNG mit transparentem Hintergrund
  ist ideal; ab 256 × 256 px).
- `--rund` schneidet kreisförmig aus und macht die Ecken transparent, z. B. für Wappen auf
  rundem Hintergrund. Ohne `--rund` bleibt das Quadrat vollständig erhalten.
- Danach DiKaS neu starten. Für die Desktop-Verknüpfung: Rechtsklick → Eigenschaften →
  „Anderes Symbol …“ → `dikas\ui\logo.ico` wählen (oder die Verknüpfung oben neu anlegen).
  Windows speichert Symbole zwischen; zeigt die Verknüpfung noch das alte Bild, hilft eine
  Ab- und Anmeldung.
- `packaging\bauen.ps1` nimmt das eigene Logo automatisch für `DiKaS.exe` und das
  Programmfenster, sonst das Standardsymbol aus `packaging\dikas.ico`.

In der Entwicklung liegt die Datenbank unter `daten\verein.db` im Projekt, bei der
installierten Version unter `%LOCALAPPDATA%\DiKaS\daten\verein.db`. Weitergeben über
„Daten exportieren/importieren“ (siehe oben).

**Automatische Sicherung:** Bei jedem Programmstart wird der aktuelle Stand nach
`…\daten\sicherung\verein_JJJJ-MM-TT_HH-MM-SS.db` gesichert – nur wenn sich seit der letzten
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
| `test_buchungen_loeschen.py` | Buchungen löschen (Storno-Paare, Mehrfachauswahl, Schutz), Update-Menüpunkt |
| `test_korrektur.py` | Buchungen korrigieren, Beitragsstatus bei Eintritt im Laufe des Jahres |
| `test_beitrag_auswahl.py` | Status FM/EM, manuelle Auswahl im Beitragslauf, Doppelschutz |
| `test_namen.py` | Vor-/Nachname: Pflicht, Aufteilen alter Namen, Sortierung, Anrede, Dialog |
| `test_kontakt.py` | Bierspitz und E-Mail: Prüfung, Dialog, Suche, DB-Update |
| `test_kontoauszug.py` | Einstellungen, Mailtexte, Versand (inkl. Test-SMTP-Server im Test), Umsatz-PDF als Anhang, Fehlerfälle, Dialoge |
| `test_anhaenge.py` | Rechnungen an Buchungen: Dateiprüfung, Fotos verkleinern, Korrektur/Löschen, Sicherung, Dialoge |
| `test_datenaustausch.py` | Export/Import zwischen zwei PCs, Warnungen (älter, getrennt bearbeitet), Datenordner |
| `test_sicherung.py` | Sicherung bei Start, nur bei Änderung, letzte 10, Wiederherstellen, Git-Ignorierung |
| `test_auswertung.py` | Kontobewegungen im Zeitraum, Summen je Art, Zeitraum-Vorlagen, PDF, Dialog |
| `test_geldorte.py` | Mehrere Geldorte, Geldtransfer, Deaktivieren, Buchungsdialog, Auswertung |
| `test_geld.py` | Betragseingabe und -anzeige |
| `test_listen.py` | Kontenliste (Spalten, Sortierung, Verschieben/Ausblenden), Spaltenbreiten, Buchungssuche |
| `test_logo.py` | Vereinslogo umwandeln (Zuschnitt, rund, ICO), Start ohne Logo |
| `test_ui.py` | Hauptfenster und Dialoge (ohne sichtbares Fenster) |

`tests/conftest.py` enthält die Hilfsklasse `Verein`, mit der sich Abläufe lesbar in Euro
schreiben lassen (`verein.einzahlung(tom, "12,50")`).

## Code prüfen

Vor einem Commit alle Prüfungen in einem Lauf (Rückgabewert 0 = alles in Ordnung):

```powershell
.\werkzeuge\pruefen.ps1            # ruff, ty, Tests mit Abdeckung
.\werkzeuge\pruefen.ps1 -OhneTests # nur ruff und ty (wenige Sekunden)
.\werkzeuge\pruefen.ps1 -Audit     # zusätzlich pip-audit (braucht Internet)
```

| Werkzeug | Prüft | Einstellung in `pyproject.toml` |
|---|---|---|
| [ruff](https://docs.astral.sh/ruff/) | unbenutzte Importe/Variablen, typische Fehlerquellen, Sicherheitsregeln | `[tool.ruff]` |
| [ty](https://docs.astral.sh/ty/) | Typen: Fehler in der Fachlogik brechen ab, in `dikas/ui` sind es nur Warnungen (Qt-Typangaben sind lückenhaft) | `[tool.ty]` |
| pytest-cov | Tests und Testabdeckung, mindestens 90 % (Wert in `pruefen.ps1`) | `[tool.coverage]` |
| pip-audit | bekannte Sicherheitslücken in den installierten Paketen | – |

Die Regeln sind bewusst auf echte Fehler statt Stilfragen ausgewählt; der Code wird nicht
automatisch umformatiert. Auf GitHub laufen dieselben Prüfungen bei jedem Push
(`.github/workflows/pruefen.yml`).

## Projektstruktur

```
dikas/
  app.py            Programmstart
  buchhaltung.py    Fachlogik: Konten, Buchungsarten, Storno, Beitragslauf, Salden
  einstellungen.py  Einstellungen (Mailserver, Bankdaten, Textvorlagen), Anbieter-Vorlagen
  kontoauszug.py    Kontoauszug-Mails erzeugen (mit Umsatz-PDF), per SMTP senden, Versand protokollieren
  anhaenge.py       Rechnungen (PDF/Fotos) an Buchungen: prüfen, verkleinern, speichern, ansehen
  pdf.py            HTML als PDF (A4) über Qt, im Speicher
  sicherung.py      Automatische lokale Sicherung, letzte 10 Stände, Wiederherstellen
  datenaustausch.py Export/Import für die Weitergabe an andere PCs, Warnungen
  geld.py           Cent <-> "12,50 €"
  logo.py           Eigenes Vereinslogo einbauen (PNG + ICO erzeugen)
  db/
    models.py       Tabellen (Konto, Statuswechsel, Buchung, Anhang, Einstellung, Mailversand)
    database.py     SQLite-Verbindung, DB-Pfad, Initialisierung
  ui/
    stil.py         Farben, Stylesheet, Symbole, deutsche Qt-Texte
    bausteine.py    Gemeinsame Bausteine (Tabellenzellen, Kennzahl-Karten, Panels)
    hauptfenster.py Kennzahlen, Kontenübersicht (Suche/Filter/Sortierung) + Buchungsliste (Suche)
    auswertung.py   Auswertung über einen Zeitraum + PDF-Export
    einstellungen_dialog.py  Einstellungen bearbeiten
    versand_dialog.py        Kontoauszüge per E-Mail versenden
    anhaenge_dialog.py       Rechnungen einer Buchung, Dateiauswahl im Buchungsdialog
    sicherungen_dialog.py    Sicherungen ansehen und wiederherstellen
    dialoge.py      Dialoge Konto, Buchung, Beitragslauf
tests/              pytest-Tests
packaging/
  bauen.ps1         Baut DiKaS.exe und den Installer
  dikas.iss         Inno-Setup-Skript (Installation ohne Adminrechte)
  start_dikas.py    Startpunkt für die .exe
  symbol_erzeugen.py, dikas.ico, dikas.png   Programmsymbol
werkzeuge/
  pruefen.ps1       Code prüfen: ruff, ty, Tests mit Abdeckung, optional pip-audit
.github/workflows/
  pruefen.yml       Dieselben Prüfungen bei jedem Push auf GitHub
```

## Geplant

- Weitere Buchungsfälle (Beispiele folgen)
- Optional: verschlüsselte Exportdatei (Passwort)
