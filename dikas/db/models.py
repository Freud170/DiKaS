"""Datenmodell: doppelte Buchführung mit Soll und Haben.

Kontoarten:
- Geldorte (KW, Aktivkonten): wo das tatsächlich vorhandene Geld liegt (z. B. Bargeld,
  Bankkonto, vorübergehend bei einer Person). Soll = Plus, Haben = Minus.
- Privatkonten und Kassen (Passivkonten): wem das Geld „gehört“. Haben = Plus, Soll = Minus.

Dadurch gilt immer: Summe aller Geldorte (KW) = Summe aller Privatkonten und Kassen.
Kontostände werden nie gespeichert, sondern immer aus den Buchungen berechnet.
Beträge werden in Cent (int) gespeichert, um Rundungsfehler zu vermeiden.
"""

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class KontoTyp(enum.StrEnum):
    PRIVAT = "PRIVAT"  # Privatkonto eines Mitglieds
    KASSE = "KASSE"  # separat geführte Kasse
    KW = "KW"  # Geldort: Teil des tatsächlichen liquiden Bestands (mindestens einer)

    @property
    def anzeige(self) -> str:
        return {"PRIVAT": "Privatkonto", "KASSE": "Kasse", "KW": "Geldort"}[self.value]

    @property
    def reihenfolge(self) -> int:
        """Sortierung in Listen: Geldorte oben, dann Kassen, dann Mitglieder."""
        return {"KW": 0, "KASSE": 1, "PRIVAT": 2}[self.value]

    @property
    def ist_aktivkonto(self) -> bool:
        """Aktivkonten steigen im Soll, alle anderen im Haben."""
        return self is KontoTyp.KW


class MitgliedStatus(enum.StrEnum):
    FUX = "FUX"
    AKTIVER = "AKTIVER"
    ALUMNI = "ALUMNI"
    FOERDER = "FOERDER"  # Fördermitglied (FM)
    EHREN = "EHREN"  # Ehrenmitglied (EM)

    @property
    def anzeige(self) -> str:
        return {
            "FUX": "Fux", "AKTIVER": "Aktiver", "ALUMNI": "Alumni",
            "FOERDER": "Fördermitglied (FM)", "EHREN": "Ehrenmitglied (EM)",
        }[self.value]

    @property
    def mehrzahl(self) -> str:
        return {
            "FUX": "Füxe", "AKTIVER": "Aktive", "ALUMNI": "Alumni",
            "FOERDER": "Fördermitglieder", "EHREN": "Ehrenmitglieder",
        }[self.value]

    @property
    def naechster(self) -> "MitgliedStatus":
        """Üblicher nächster Status im Vereinsleben (Fux → Aktiver → Alumni), sonst unverändert."""
        return {"FUX": MitgliedStatus.AKTIVER, "AKTIVER": MitgliedStatus.ALUMNI}.get(self.value, self)


class Buchungsart(enum.StrEnum):
    EINZAHLUNG = "EINZAHLUNG"  # Mitglied zahlt Geld ein (KW +, Privat +)
    AUSZAHLUNG = "AUSZAHLUNG"  # Mitglied bekommt Geld ausgezahlt (KW -, Privat -)
    KASSE_EINNAHME = "KASSE_EINNAHME"  # Kasse nimmt Geld ein (KW +, Kasse +)
    KASSE_AUSGABE = "KASSE_AUSGABE"  # Kasse gibt Geld aus (KW -, Kasse -)
    UMBUCHUNG = "UMBUCHUNG"  # zwischen Privatkonten/Kassen, KW unverändert
    BEITRAG = "BEITRAG"  # Mitgliedsbeitrag: Privat -, Kasse +
    GELDTRANSFER = "GELDTRANSFER"  # Geld wechselt den Ort: Geldort -, Geldort +, KW gesamt gleich
    STORNO = "STORNO"  # Gegenbuchung zu einer anderen Buchung

    @property
    def anzeige(self) -> str:
        return {
            "EINZAHLUNG": "Einzahlung",
            "AUSZAHLUNG": "Auszahlung",
            "KASSE_EINNAHME": "Kassen-Einnahme",
            "KASSE_AUSGABE": "Kassen-Ausgabe",
            "UMBUCHUNG": "Umbuchung",
            "BEITRAG": "Beitrag",
            "GELDTRANSFER": "Geldtransfer",
            "STORNO": "Storno",
        }[self.value]


class Konto(Base):
    __tablename__ = "konten"
    __table_args__ = (
        UniqueConstraint("typ", "name", name="uq_konto_typ_name"),
        CheckConstraint(
            "(typ = 'PRIVAT') = (status IS NOT NULL)", name="ck_status_nur_privat"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Anzeigename; bei Privatkonten immer "Vorname Nachname" (wird aus beiden gebildet)
    name: Mapped[str] = mapped_column(String(100))
    vorname: Mapped[str] = mapped_column(String(100), default="")
    nachname: Mapped[str] = mapped_column(String(100), default="")
    typ: Mapped[KontoTyp] = mapped_column(Enum(KontoTyp, native_enum=False, length=10))
    # Nur bei Privatkonten gesetzt: aktueller Status (= neuester Eintrag im Statusverlauf)
    status: Mapped[Optional[MitgliedStatus]] = mapped_column(
        Enum(MitgliedStatus, native_enum=False, length=10), default=None
    )
    # Nur bei Privatkonten; entscheidet, ab welchem Jahr Beiträge fällig sind
    eintrittsdatum: Mapped[Optional[date]] = mapped_column(default=None)
    # Nur bei Privatkonten: Spitzname im Verein und Adresse für den Kontoauszug
    bierspitz: Mapped[str] = mapped_column(String(100), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    aktiv: Mapped[bool] = mapped_column(default=True)
    # Archiviert: Saldo war 0, Konto hat aber Buchungen und bleibt deshalb erhalten
    geloescht: Mapped[bool] = mapped_column(default=False)
    bemerkung: Mapped[str] = mapped_column(String(500), default="")
    erstellt_am: Mapped[datetime] = mapped_column(default=datetime.now)

    # Wird mit dem Konto geladen, damit er auch nach Schließen der Session verfügbar ist
    statusverlauf: Mapped[list["Statuswechsel"]] = relationship(
        back_populates="konto",
        order_by="Statuswechsel.gueltig_ab",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Konto {self.id} {self.typ} {self.name!r}>"


class Statuswechsel(Base):
    """Ab wann ein Mitglied welchen Status hatte (Fux → Aktiver → Alumni)."""

    __tablename__ = "statuswechsel"
    __table_args__ = (UniqueConstraint("konto_id", "gueltig_ab", name="uq_statuswechsel_datum"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    konto_id: Mapped[int] = mapped_column(ForeignKey("konten.id"))
    status: Mapped[MitgliedStatus] = mapped_column(Enum(MitgliedStatus, native_enum=False, length=10))
    gueltig_ab: Mapped[date]
    erstellt_am: Mapped[datetime] = mapped_column(default=datetime.now)

    konto: Mapped[Konto] = relationship(back_populates="statusverlauf")

    def __repr__(self) -> str:
        return f"<Statuswechsel {self.konto_id} {self.status} ab {self.gueltig_ab}>"


class Buchung(Base):
    __tablename__ = "buchungen"
    __table_args__ = (
        CheckConstraint("betrag_cent > 0", name="ck_betrag_positiv"),
        CheckConstraint("soll_konto_id <> haben_konto_id", name="ck_konten_verschieden"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    datum: Mapped[date]
    art: Mapped[Buchungsart] = mapped_column(Enum(Buchungsart, native_enum=False, length=20))
    betrag_cent: Mapped[int]
    soll_konto_id: Mapped[int] = mapped_column(ForeignKey("konten.id"))
    haben_konto_id: Mapped[int] = mapped_column(ForeignKey("konten.id"))
    text: Mapped[str] = mapped_column(String(200))
    beleg: Mapped[str] = mapped_column(String(50), default="")
    erstellt_am: Mapped[datetime] = mapped_column(default=datetime.now)
    # Bei Beiträgen aus dem Beitragslauf: für welches Jahr (verhindert doppelte Abbuchung)
    beitragsjahr: Mapped[Optional[int]] = mapped_column(default=None)
    # Gesetzt, wenn diese Buchung die Stornobuchung einer anderen ist
    storno_von_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("buchungen.id"), unique=True, default=None
    )

    soll_konto: Mapped[Konto] = relationship(foreign_keys=[soll_konto_id])
    haben_konto: Mapped[Konto] = relationship(foreign_keys=[haben_konto_id])
    storno_von: Mapped[Optional["Buchung"]] = relationship(
        remote_side=[id], back_populates="storniert_durch"
    )
    storniert_durch: Mapped[Optional["Buchung"]] = relationship(back_populates="storno_von")

    @property
    def ist_storniert(self) -> bool:
        return self.storniert_durch is not None

    @property
    def ist_storno(self) -> bool:
        return self.storno_von_id is not None

    def wirkung_auf(self, konto: Konto) -> int:
        """Veränderung des Saldos von `konto` durch diese Buchung (in Cent)."""
        if konto.id == self.soll_konto_id:
            im_soll = True
        elif konto.id == self.haben_konto_id:
            im_soll = False
        else:
            return 0
        steigt = im_soll == konto.typ.ist_aktivkonto
        return self.betrag_cent if steigt else -self.betrag_cent

    def __repr__(self) -> str:
        return (
            f"<Buchung {self.id} {self.datum} {self.art} {self.betrag_cent}ct "
            f"S{self.soll_konto_id}/H{self.haben_konto_id}>"
        )


class Einstellung(Base):
    """Programmeinstellungen als Schlüssel/Wert (z. B. Mailserver, Bankdaten, Textvorlagen)."""

    __tablename__ = "einstellungen"

    schluessel: Mapped[str] = mapped_column(String(50), primary_key=True)
    wert: Mapped[str] = mapped_column(Text, default="")


class Mailversand(Base):
    """Protokoll: wem wann welcher Kontoauszug geschickt wurde (auch fehlgeschlagene Versuche)."""

    __tablename__ = "mailversand"

    id: Mapped[int] = mapped_column(primary_key=True)
    konto_id: Mapped[int] = mapped_column(ForeignKey("konten.id"))
    stichtag: Mapped[date]
    saldo_cent: Mapped[int]
    empfaenger: Mapped[str] = mapped_column(String(200))
    gesendet_am: Mapped[datetime] = mapped_column(default=datetime.now)
    erfolgreich: Mapped[bool]
    fehler: Mapped[str] = mapped_column(String(500), default="")

    konto: Mapped[Konto] = relationship()