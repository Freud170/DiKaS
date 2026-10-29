"""Datenmodell: doppelte Buchführung mit Soll und Haben.

Kontoarten:
- KW-Konto (Aktivkonto): das tatsächlich vorhandene Geld. Soll = Plus, Haben = Minus.
- Privatkonten und Kassen (Passivkonten): wem das Geld „gehört“. Haben = Plus, Soll = Minus.

Dadurch gilt immer: Saldo KW = Summe aller Privatkonten und Kassen.
Kontostände werden nie gespeichert, sondern immer aus den Buchungen berechnet.
Beträge werden in Cent (int) gespeichert, um Rundungsfehler zu vermeiden.
"""

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class KontoTyp(enum.StrEnum):
    PRIVAT = "PRIVAT"  # Privatkonto eines Mitglieds
    KASSE = "KASSE"  # separat geführte Kasse
    KW = "KW"  # tatsächlicher liquider Bestand (genau eins)

    @property
    def anzeige(self) -> str:
        return {"PRIVAT": "Privatkonto", "KASSE": "Kasse", "KW": "KW-Konto"}[self.value]

    @property
    def reihenfolge(self) -> int:
        """Sortierung in Listen: KW oben, dann Kassen, dann Mitglieder."""
        return {"KW": 0, "KASSE": 1, "PRIVAT": 2}[self.value]

    @property
    def ist_aktivkonto(self) -> bool:
        """Aktivkonten steigen im Soll, alle anderen im Haben."""
        return self is KontoTyp.KW


class MitgliedStatus(enum.StrEnum):
    FUX = "FUX"
    AKTIVER = "AKTIVER"
    ALUMNI = "ALUMNI"

    @property
    def anzeige(self) -> str:
        return {"FUX": "Fux", "AKTIVER": "Aktiver", "ALUMNI": "Alumni"}[self.value]

    @property
    def mehrzahl(self) -> str:
        return {"FUX": "Füxe", "AKTIVER": "Aktive", "ALUMNI": "Alumni"}[self.value]


class Buchungsart(enum.StrEnum):
    EINZAHLUNG = "EINZAHLUNG"  # Mitglied zahlt Geld ein (KW +, Privat +)
    AUSZAHLUNG = "AUSZAHLUNG"  # Mitglied bekommt Geld ausgezahlt (KW -, Privat -)
    KASSE_EINNAHME = "KASSE_EINNAHME"  # Kasse nimmt Geld ein (KW +, Kasse +)
    KASSE_AUSGABE = "KASSE_AUSGABE"  # Kasse gibt Geld aus (KW -, Kasse -)
    UMBUCHUNG = "UMBUCHUNG"  # zwischen Privatkonten/Kassen, KW unverändert
    BEITRAG = "BEITRAG"  # Mitgliedsbeitrag: Privat -, Kasse +
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
    name: Mapped[str] = mapped_column(String(100))
    typ: Mapped[KontoTyp] = mapped_column(Enum(KontoTyp, native_enum=False, length=10))
    # Nur bei Privatkonten gesetzt
    status: Mapped[Optional[MitgliedStatus]] = mapped_column(
        Enum(MitgliedStatus, native_enum=False, length=10), default=None
    )
    aktiv: Mapped[bool] = mapped_column(default=True)
    # Archiviert: Saldo war 0, Konto hat aber Buchungen und bleibt deshalb erhalten
    geloescht: Mapped[bool] = mapped_column(default=False)
    bemerkung: Mapped[str] = mapped_column(String(500), default="")
    erstellt_am: Mapped[datetime] = mapped_column(default=datetime.now)

    def __repr__(self) -> str:
        return f"<Konto {self.id} {self.typ} {self.name!r}>"


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
