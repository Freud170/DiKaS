"""Fachlogik: Konten anlegen, buchen, stornieren, Salden berechnen.

Vorzeichen: Eine Buchung erhöht den Saldo des Zielkontos (nach) und
verringert den Saldo des Quellkontos (von).
"""

from datetime import date

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from dikas.db.models import Buchung, Konto, KontoTyp


class BuchhaltungsFehler(ValueError):
    pass


# --- Konten ---------------------------------------------------------------

def kw_konto(session: Session) -> Konto:
    return session.scalars(select(Konto).where(Konto.typ == KontoTyp.KW)).one()


def konten(session: Session, nur_aktive: bool = False) -> list[Konto]:
    abfrage = select(Konto).order_by(Konto.typ, Konto.name)
    if nur_aktive:
        abfrage = abfrage.where(Konto.aktiv)
    return list(session.scalars(abfrage))


def konto_anlegen(session: Session, name: str, typ: KontoTyp, bemerkung: str = "") -> Konto:
    name = name.strip()
    if not name:
        raise BuchhaltungsFehler("Der Kontoname darf nicht leer sein.")
    if typ == KontoTyp.KW:
        raise BuchhaltungsFehler("Es gibt genau ein KW-Konto, es wird automatisch angelegt.")
    vorhanden = session.scalar(select(Konto).where(Konto.typ == typ, Konto.name == name))
    if vorhanden is not None:
        raise BuchhaltungsFehler(f"Es gibt bereits ein {typ.anzeige} mit dem Namen „{name}“.")
    konto = Konto(name=name, typ=typ, bemerkung=bemerkung.strip())
    session.add(konto)
    session.flush()
    return konto


# --- Buchungen ------------------------------------------------------------

def buchen(
    session: Session,
    von_konto_id: int,
    nach_konto_id: int,
    betrag_cent: int,
    text: str,
    datum: date | None = None,
    beleg: str = "",
) -> Buchung:
    if betrag_cent <= 0:
        raise BuchhaltungsFehler("Der Betrag muss größer als 0 sein.")
    if von_konto_id == nach_konto_id:
        raise BuchhaltungsFehler("Quell- und Zielkonto müssen verschieden sein.")
    text = text.strip()
    if not text:
        raise BuchhaltungsFehler("Bitte einen Buchungstext angeben.")
    for konto_id in (von_konto_id, nach_konto_id):
        konto = session.get(Konto, konto_id)
        if konto is None:
            raise BuchhaltungsFehler(f"Konto {konto_id} existiert nicht.")
        if not konto.aktiv:
            raise BuchhaltungsFehler(f"Konto „{konto.name}“ ist deaktiviert.")

    buchung = Buchung(
        datum=datum or date.today(),
        betrag_cent=betrag_cent,
        von_konto_id=von_konto_id,
        nach_konto_id=nach_konto_id,
        text=text,
        beleg=beleg.strip(),
    )
    session.add(buchung)
    session.flush()
    return buchung


def stornieren(session: Session, buchung_id: int, datum: date | None = None) -> Buchung:
    """Storniert eine Buchung durch eine Gegenbuchung. Nichts wird gelöscht."""
    original = session.get(Buchung, buchung_id)
    if original is None:
        raise BuchhaltungsFehler(f"Buchung {buchung_id} existiert nicht.")
    if original.ist_storno:
        raise BuchhaltungsFehler("Eine Stornobuchung kann nicht storniert werden.")
    if original.ist_storniert:
        raise BuchhaltungsFehler("Diese Buchung wurde bereits storniert.")

    storno = Buchung(
        datum=datum or date.today(),
        betrag_cent=original.betrag_cent,
        von_konto_id=original.nach_konto_id,
        nach_konto_id=original.von_konto_id,
        text=f"Storno: {original.text}",
        beleg=original.beleg,
        storno_von=original,
    )
    session.add(storno)
    session.flush()
    return storno


def buchungen(session: Session, konto_id: int | None = None) -> list[Buchung]:
    """Alle Buchungen (neueste zuerst), optional nur die eines Kontos."""
    abfrage = (
        select(Buchung)
        .options(
            joinedload(Buchung.von_konto),
            joinedload(Buchung.nach_konto),
            joinedload(Buchung.storniert_durch),
        )
        .order_by(Buchung.datum.desc(), Buchung.id.desc())
    )
    if konto_id is not None:
        abfrage = abfrage.where(
            or_(Buchung.von_konto_id == konto_id, Buchung.nach_konto_id == konto_id)
        )
    return list(session.scalars(abfrage).unique())


# --- Salden ---------------------------------------------------------------

def salden(session: Session) -> dict[int, int]:
    """Saldo in Cent für jedes Konto (auch Konten ohne Buchungen)."""
    ergebnis = {konto_id: 0 for konto_id in session.scalars(select(Konto.id))}
    zugang = select(Buchung.nach_konto_id, func.sum(Buchung.betrag_cent)).group_by(
        Buchung.nach_konto_id
    )
    abgang = select(Buchung.von_konto_id, func.sum(Buchung.betrag_cent)).group_by(
        Buchung.von_konto_id
    )
    for konto_id, summe in session.execute(zugang):
        ergebnis[konto_id] += summe
    for konto_id, summe in session.execute(abgang):
        ergebnis[konto_id] -= summe
    return ergebnis


def saldo(session: Session, konto_id: int) -> int:
    betrag = case(
        (Buchung.nach_konto_id == konto_id, Buchung.betrag_cent),
        else_=-Buchung.betrag_cent,
    )
    summe = session.scalar(
        select(func.coalesce(func.sum(betrag), 0)).where(
            or_(Buchung.von_konto_id == konto_id, Buchung.nach_konto_id == konto_id)
        )
    )
    return int(summe)
