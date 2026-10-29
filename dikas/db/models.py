"""Datenmodell: doppelte Buchführung.

Jede Buchung bewegt einen Betrag von einem Konto auf ein anderes.
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


class Konto(Base):
    __tablename__ = "konten"
    __table_args__ = (UniqueConstraint("typ", "name", name="uq_konto_typ_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    typ: Mapped[KontoTyp] = mapped_column(Enum(KontoTyp, native_enum=False, length=10))
    aktiv: Mapped[bool] = mapped_column(default=True)
    bemerkung: Mapped[str] = mapped_column(String(500), default="")
    erstellt_am: Mapped[datetime] = mapped_column(default=datetime.now)

    def __repr__(self) -> str:
        return f"<Konto {self.id} {self.typ} {self.name!r}>"


class Buchung(Base):
    __tablename__ = "buchungen"
    __table_args__ = (
        CheckConstraint("betrag_cent > 0", name="ck_betrag_positiv"),
        CheckConstraint("von_konto_id <> nach_konto_id", name="ck_konten_verschieden"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    datum: Mapped[date]
    betrag_cent: Mapped[int]
    von_konto_id: Mapped[int] = mapped_column(ForeignKey("konten.id"))
    nach_konto_id: Mapped[int] = mapped_column(ForeignKey("konten.id"))
    text: Mapped[str] = mapped_column(String(200))
    beleg: Mapped[str] = mapped_column(String(50), default="")
    erstellt_am: Mapped[datetime] = mapped_column(default=datetime.now)
    # Gesetzt, wenn diese Buchung die Stornobuchung einer anderen ist
    storno_von_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("buchungen.id"), unique=True, default=None
    )

    von_konto: Mapped[Konto] = relationship(foreign_keys=[von_konto_id])
    nach_konto: Mapped[Konto] = relationship(foreign_keys=[nach_konto_id])
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

    def __repr__(self) -> str:
        return f"<Buchung {self.id} {self.datum} {self.betrag_cent}ct {self.von_konto_id}->{self.nach_konto_id}>"
