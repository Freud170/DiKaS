"""Rechnungen und Belege als Dateien (Bilder, PDFs) an Buchungen hängen.

Die Dateien liegen in der Datenbank (Tabelle `anhaenge`), damit Export/Import zwischen PCs
und die automatischen Sicherungen sie ohne Weiteres mitnehmen. Damit Datenbank und
Sicherungen nicht unnötig wachsen, werden große Fotos beim Anhängen verkleinert
(Handyfotos haben 3–5 MB, für eine lesbare Rechnung reichen 2000 Pixel).
"""

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter
from sqlalchemy.orm import Session

from dikas.buchhaltung import BuchhaltungsFehler
from dikas.db.models import Anhang, Buchung

PDF = "application/pdf"
BILDTYPEN = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
ENDUNGEN = {".pdf": PDF, **BILDTYPEN}
DATEIFILTER = "Rechnungen (*.pdf *.jpg *.jpeg *.png *.gif *.bmp *.webp *.tif *.tiff);;Alle Dateien (*)"

MAX_EINGABE = 50 * 1024 * 1024  # größere Dateien werden abgelehnt
MAX_PDF = 20 * 1024 * 1024
MAX_PIXEL = 2000  # längste Seite nach dem Verkleinern
KLEIN_GENUG = 800 * 1024  # JPG/PNG bis zu dieser Größe (und MAX_PIXEL) bleiben unverändert
JPEG_QUALITAET = 80


class AnhangFehler(BuchhaltungsFehler):
    """Datei kann nicht angehängt werden (Typ, Größe, nicht lesbar)."""


@dataclass(frozen=True)
class Datei:
    """Eine zum Anhängen vorbereitete Datei (ggf. schon verkleinert)."""

    dateiname: str
    mime_typ: str
    inhalt: bytes

    @property
    def groesse(self) -> int:
        return len(self.inhalt)


def groesse_text(byte: int) -> str:
    if byte < 1024:
        return f"{byte} Byte"
    if byte < 1024 * 1024:
        return f"{byte / 1024:.0f} KB"
    return f"{byte / 1024 / 1024:.1f} MB".replace(".", ",")


def _sicherer_name(name: str) -> str:
    """Nur der Dateiname, ohne Zeichen, die Windows in Dateinamen nicht erlaubt."""
    # Nicht Path(name).name: unter Windows würde aus "a:b.pdf" das Laufwerk "a:" abgeschnitten
    name = re.split(r"[/\\]", name)[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    return (name or "Rechnung")[-150:]


def _bildleser(daten: bytes) -> tuple[QImageReader, QBuffer]:
    """Bildleser über die Bytes im Speicher (der Puffer muss so lange leben wie der Leser)."""
    puffer = QBuffer()
    puffer.setData(QByteArray(daten))
    puffer.open(QIODevice.OpenModeFlag.ReadOnly)
    return QImageReader(puffer), puffer


def _bild_verkleinern(daten: bytes, name: str) -> Datei:
    reader, _puffer = _bildleser(daten)
    reader.setAutoTransform(True)  # Handyfotos: Drehung laut EXIF übernehmen
    bild = reader.read()
    if bild.isNull():
        raise AnhangFehler(f"„{name}“ lässt sich nicht als Bild lesen ({reader.errorString()}).")
    if max(bild.width(), bild.height()) > MAX_PIXEL:
        bild = bild.scaled(
            MAX_PIXEL, MAX_PIXEL, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    if bild.hasAlphaChannel():
        # JPEG kennt keine Transparenz: auf weißen Hintergrund legen statt schwarz
        flach = QImage(bild.size(), QImage.Format.Format_RGB32)
        flach.fill(Qt.GlobalColor.white)
        maler = QPainter(flach)
        maler.drawImage(0, 0, bild)
        maler.end()
        bild = flach
    ausgabe = QByteArray()
    ziel = QBuffer(ausgabe)
    ziel.open(QIODevice.OpenModeFlag.WriteOnly)
    if not bild.save(ziel, "JPG", JPEG_QUALITAET):  # ty: ignore[no-matching-overload]
        raise AnhangFehler(f"„{name}“ konnte nicht verkleinert werden.")
    ziel.close()
    return Datei(f"{Path(name).stem}.jpg", "image/jpeg", bytes(ausgabe.data()))


def _bildgroesse(daten: bytes) -> tuple[int, int] | None:
    reader, _puffer = _bildleser(daten)
    groesse = reader.size()
    return (groesse.width(), groesse.height()) if groesse.isValid() else None


def vorbereiten(name: str, daten: bytes) -> Datei:
    """Prüft eine Datei und verkleinert Fotos bei Bedarf. Wirft AnhangFehler mit verständlicher Meldung."""
    name = _sicherer_name(name)
    endung = Path(name).suffix.lower()
    if endung in (".heic", ".heif"):
        raise AnhangFehler(
            f"„{name}“ ist ein HEIC-Foto (iPhone), das kann DiKaS nicht lesen. Bitte als JPG "
            "speichern – oder am iPhone unter Einstellungen → Kamera → Formate „Maximale "
            "Kompatibilität“ wählen."
        )
    if endung not in ENDUNGEN:
        raise AnhangFehler(f"„{name}“: Nur PDFs und Bilder (JPG, PNG …) können angehängt werden.")
    if not daten:
        raise AnhangFehler(f"„{name}“ ist leer.")
    if len(daten) > MAX_EINGABE:
        raise AnhangFehler(f"„{name}“ ist zu groß ({groesse_text(len(daten))}, höchstens 50 MB).")

    if endung == ".pdf":
        if not daten.lstrip()[:5].startswith(b"%PDF"):
            raise AnhangFehler(f"„{name}“ ist keine gültige PDF-Datei.")
        if len(daten) > MAX_PDF:
            raise AnhangFehler(
                f"„{name}“ ist zu groß ({groesse_text(len(daten))}, höchstens 20 MB). "
                "Gescannte PDFs lassen sich meist mit geringerer Auflösung neu speichern."
            )
        return Datei(name, PDF, daten)

    mime = BILDTYPEN[endung]
    if mime in ("image/jpeg", "image/png") and len(daten) <= KLEIN_GENUG:
        groesse = _bildgroesse(daten)
        if groesse is None:
            raise AnhangFehler(f"„{name}“ lässt sich nicht als Bild lesen.")
        if max(groesse) <= MAX_PIXEL:
            return Datei(name, mime, daten)  # klein genug, Original behalten
    return _bild_verkleinern(daten, name)


def datei_vorbereiten(pfad: str | Path) -> Datei:
    pfad = Path(pfad)
    try:
        if pfad.stat().st_size > MAX_EINGABE:
            raise AnhangFehler(f"„{pfad.name}“ ist zu groß (höchstens 50 MB).")
        daten = pfad.read_bytes()
    except OSError as fehler:
        raise AnhangFehler(f"„{pfad.name}“ kann nicht gelesen werden: {fehler.strerror or fehler}") from None
    return vorbereiten(pfad.name, daten)


def anhaengen(session: Session, buchung_id: int, datei: Datei) -> Anhang:
    buchung = session.get(Buchung, buchung_id)
    if buchung is None:
        raise BuchhaltungsFehler(f"Buchung {buchung_id} existiert nicht.")
    if buchung.ist_storno:
        raise AnhangFehler("An eine Stornobuchung kann nichts angehängt werden – bitte an die Originalbuchung.")
    anhang = Anhang(dateiname=datei.dateiname, mime_typ=datei.mime_typ, groesse=datei.groesse, inhalt=datei.inhalt)
    buchung.anhaenge.append(anhang)
    session.flush()
    return anhang


def _anhang(session: Session, anhang_id: int) -> Anhang:
    anhang = session.get(Anhang, anhang_id)
    if anhang is None:
        raise BuchhaltungsFehler("Die Datei existiert nicht mehr. Bitte die Liste neu laden.")
    return anhang


def entfernen(session: Session, anhang_id: int) -> None:
    anhang = _anhang(session, anhang_id)
    anhang.buchung.anhaenge.remove(anhang)  # delete-orphan: wird gelöscht, Liste stimmt sofort
    session.flush()


def speichern_unter(session: Session, anhang_id: int, ziel: str | Path) -> Path:
    ziel = Path(ziel)
    ziel.write_bytes(_anhang(session, anhang_id).inhalt)
    return ziel


# --- Ansehen --------------------------------------------------------------
# Zum Öffnen mit dem Standardprogramm (PDF-Reader, Fotos) muss die Datei auf die Platte.
# Sie kommt in einen eigenen Temp-Ordner, der beim Programmstart geleert wird.

def ansichtsordner() -> Path:
    return Path(tempfile.gettempdir()) / "DiKaS" / "ansicht"


def zum_ansehen(session: Session, anhang_id: int, ordner: Path | None = None) -> Path:
    """Schreibt den Anhang in den Ansichtsordner und gibt den Pfad zurück."""
    anhang = _anhang(session, anhang_id)
    ordner = ordner or ansichtsordner()
    ordner.mkdir(parents=True, exist_ok=True)
    pfad = ordner / f"{anhang.id}_{_sicherer_name(anhang.dateiname)}"
    if not pfad.exists() or pfad.stat().st_size != anhang.groesse:
        teil = pfad.with_name(pfad.name + ".teil")
        teil.write_bytes(anhang.inhalt)
        os.replace(teil, pfad)
    return pfad


def ansichten_aufraeumen(ordner: Path | None = None) -> None:
    """Angesehene Rechnungen vom letzten Mal löschen (geöffnete Dateien bleiben einfach liegen)."""
    shutil.rmtree(ordner or ansichtsordner(), ignore_errors=True)
