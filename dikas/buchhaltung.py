"""Fachlogik: Konten anlegen, buchen, stornieren, Beiträge abbuchen, Salden berechnen.

Gebucht wird immer über eine Buchungsart. Die Regeln in `REGELN` legen fest,
welche Konten erlaubt sind und welches Konto im Soll bzw. Haben steht.
Wirkung auf den Saldo siehe `dikas.db.models`.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from dikas.db.models import Buchung, Buchungsart, Konto, KontoTyp, MitgliedStatus
from dikas.geld import cent_zu_text


class BuchhaltungsFehler(ValueError):
    pass


@dataclass(frozen=True)
class ArtRegel:
    konto_typen: tuple[KontoTyp, ...]
    # None = Gegenkonto ist automatisch das KW-Konto
    gegen_typen: tuple[KontoTyp, ...] | None
    konto_im_soll: bool
    konto_beschriftung: str
    gegen_beschriftung: str = ""


REGELN: dict[Buchungsart, ArtRegel] = {
    Buchungsart.EINZAHLUNG: ArtRegel((KontoTyp.PRIVAT,), None, False, "Mitglied"),
    Buchungsart.AUSZAHLUNG: ArtRegel((KontoTyp.PRIVAT,), None, True, "Mitglied"),
    Buchungsart.KASSE_EINNAHME: ArtRegel((KontoTyp.KASSE,), None, False, "Kasse"),
    Buchungsart.KASSE_AUSGABE: ArtRegel((KontoTyp.KASSE,), None, True, "Kasse"),
    Buchungsart.UMBUCHUNG: ArtRegel(
        (KontoTyp.PRIVAT, KontoTyp.KASSE), (KontoTyp.PRIVAT, KontoTyp.KASSE), True, "Von", "Nach"
    ),
    Buchungsart.BEITRAG: ArtRegel((KontoTyp.PRIVAT,), (KontoTyp.KASSE,), True, "Mitglied", "Kasse"),
}


# --- Konten ---------------------------------------------------------------

def kw_konto(session: Session) -> Konto:
    return session.scalars(select(Konto).where(Konto.typ == KontoTyp.KW)).one()


def konten(session: Session, nur_aktive: bool = False) -> list[Konto]:
    abfrage = select(Konto).order_by(Konto.typ, Konto.name)
    if nur_aktive:
        abfrage = abfrage.where(Konto.aktiv)
    return list(session.scalars(abfrage))


def _pruefe_name(session: Session, name: str, typ: KontoTyp, ausser_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise BuchhaltungsFehler("Der Kontoname darf nicht leer sein.")
    abfrage = select(Konto).where(Konto.typ == typ, Konto.name == name)
    if ausser_id is not None:
        abfrage = abfrage.where(Konto.id != ausser_id)
    vorhanden = session.scalar(abfrage)
    if vorhanden is not None:
        hinweis = " (gelöscht – ggf. wiederherstellen)" if vorhanden.geloescht else ""
        raise BuchhaltungsFehler(
            f"Es gibt bereits ein {typ.anzeige} mit dem Namen „{name}“{hinweis}."
        )
    return name


def _pruefe_status(typ: KontoTyp, status: MitgliedStatus | None) -> None:
    if typ == KontoTyp.PRIVAT and status is None:
        raise BuchhaltungsFehler("Für ein Privatkonto muss ein Status angegeben werden.")
    if typ != KontoTyp.PRIVAT and status is not None:
        raise BuchhaltungsFehler("Nur Privatkonten haben einen Status.")


def konto_anlegen(
    session: Session,
    name: str,
    typ: KontoTyp,
    status: MitgliedStatus | None = None,
    bemerkung: str = "",
) -> Konto:
    if typ == KontoTyp.KW:
        raise BuchhaltungsFehler("Es gibt genau ein KW-Konto, es wird automatisch angelegt.")
    name = _pruefe_name(session, name, typ)
    _pruefe_status(typ, status)
    konto = Konto(name=name, typ=typ, status=status, bemerkung=bemerkung.strip())
    session.add(konto)
    session.flush()
    return konto


def konto_bearbeiten(
    session: Session,
    konto_id: int,
    name: str,
    status: MitgliedStatus | None,
    bemerkung: str,
    aktiv: bool,
) -> Konto:
    konto = _konto(session, konto_id)
    if konto.geloescht:
        raise BuchhaltungsFehler(f"Konto „{konto.name}“ ist gelöscht. Bitte zuerst wiederherstellen.")
    if konto.typ == KontoTyp.KW and not aktiv:
        raise BuchhaltungsFehler("Das KW-Konto kann nicht deaktiviert werden.")
    konto.name = _pruefe_name(session, name, konto.typ, ausser_id=konto.id)
    _pruefe_status(konto.typ, status)
    konto.status = status
    konto.bemerkung = bemerkung.strip()
    konto.aktiv = aktiv
    session.flush()
    return konto


def _konto(session: Session, konto_id: int) -> Konto:
    konto = session.get(Konto, konto_id)
    if konto is None:
        raise BuchhaltungsFehler(f"Konto {konto_id} existiert nicht.")
    return konto


def hat_buchungen(session: Session, konto_id: int) -> bool:
    return session.scalar(
        select(Buchung.id)
        .where(or_(Buchung.soll_konto_id == konto_id, Buchung.haben_konto_id == konto_id))
        .limit(1)
    ) is not None


def konto_loeschen(session: Session, konto_id: int) -> bool:
    """Löscht ein Privatkonto mit Saldo 0.

    Ohne Buchungen wird es wirklich entfernt (Rückgabe True). Mit Buchungen wird es
    nur als gelöscht markiert (Rückgabe False), damit die Historie stimmig bleibt.
    """
    konto = _konto(session, konto_id)
    if konto.typ != KontoTyp.PRIVAT:
        raise BuchhaltungsFehler("Nur Privatkonten können gelöscht werden.")
    if konto.geloescht:
        raise BuchhaltungsFehler(f"Konto „{konto.name}“ ist bereits gelöscht.")
    stand = saldo(session, konto.id)
    if stand != 0:
        raise BuchhaltungsFehler(
            f"Konto „{konto.name}“ kann nur bei Saldo 0 gelöscht werden "
            f"(aktuell {cent_zu_text(stand)})."
        )
    if not hat_buchungen(session, konto.id):
        session.delete(konto)
        session.flush()
        return True
    konto.geloescht = True
    konto.aktiv = False
    session.flush()
    return False


def konto_wiederherstellen(session: Session, konto_id: int) -> Konto:
    konto = _konto(session, konto_id)
    if not konto.geloescht:
        raise BuchhaltungsFehler(f"Konto „{konto.name}“ ist nicht gelöscht.")
    konto.geloescht = False
    konto.aktiv = True
    session.flush()
    return konto


# --- Buchungen ------------------------------------------------------------

def _aktives_konto(session: Session, konto_id: int, erlaubt: tuple[KontoTyp, ...], rolle: str) -> Konto:
    konto = _konto(session, konto_id)
    if konto.geloescht:
        raise BuchhaltungsFehler(f"Konto „{konto.name}“ ist gelöscht.")
    if konto.typ not in erlaubt:
        erlaubt_text = " oder ".join(t.anzeige for t in erlaubt)
        raise BuchhaltungsFehler(f"{rolle}: „{konto.name}“ ist kein {erlaubt_text}.")
    if not konto.aktiv:
        raise BuchhaltungsFehler(f"Konto „{konto.name}“ ist deaktiviert.")
    return konto


def buchen(
    session: Session,
    art: Buchungsart,
    konto_id: int,
    betrag_cent: int,
    text: str,
    datum: date | None = None,
    beleg: str = "",
    gegenkonto_id: int | None = None,
) -> Buchung:
    """Bucht nach den Regeln der Buchungsart.

    `gegenkonto_id` wird nur bei Umbuchung und Beitrag gebraucht,
    sonst ist das Gegenkonto automatisch das KW-Konto.
    """
    regel = REGELN.get(art)
    if regel is None:
        raise BuchhaltungsFehler(f"„{art.anzeige}“ kann nicht direkt gebucht werden.")
    if betrag_cent <= 0:
        raise BuchhaltungsFehler("Der Betrag muss größer als 0 sein.")
    text = text.strip()
    if not text:
        raise BuchhaltungsFehler("Bitte einen Buchungstext angeben.")

    konto = _aktives_konto(session, konto_id, regel.konto_typen, regel.konto_beschriftung)
    if regel.gegen_typen is None:
        gegen = kw_konto(session)
    else:
        if gegenkonto_id is None:
            raise BuchhaltungsFehler(f"Bitte „{regel.gegen_beschriftung}“ angeben.")
        gegen = _aktives_konto(session, gegenkonto_id, regel.gegen_typen, regel.gegen_beschriftung)
    if konto.id == gegen.id:
        raise BuchhaltungsFehler("Die beiden Konten müssen verschieden sein.")

    soll, haben = (konto, gegen) if regel.konto_im_soll else (gegen, konto)
    buchung = Buchung(
        datum=datum or date.today(),
        art=art,
        betrag_cent=betrag_cent,
        soll_konto_id=soll.id,
        haben_konto_id=haben.id,
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
    # Sonst stünde ein gelöschtes (unsichtbares) Konto plötzlich nicht mehr auf 0
    for konto in (original.soll_konto, original.haben_konto):
        if konto.geloescht:
            raise BuchhaltungsFehler(
                f"Konto „{konto.name}“ ist gelöscht. Bitte zuerst wiederherstellen."
            )

    storno = Buchung(
        datum=datum or date.today(),
        art=Buchungsart.STORNO,
        betrag_cent=original.betrag_cent,
        soll_konto_id=original.haben_konto_id,
        haben_konto_id=original.soll_konto_id,
        text=f"Storno: {original.text}",
        beleg=original.beleg,
        storno_von=original,
    )
    session.add(storno)
    session.flush()
    return storno


def buchungen(
    session: Session,
    konto_id: int | None = None,
    von: date | None = None,
    bis: date | None = None,
) -> list[Buchung]:
    """Alle Buchungen (neueste zuerst), optional nur die eines Kontos und/oder eines Zeitraums."""
    abfrage = (
        select(Buchung)
        .options(
            joinedload(Buchung.soll_konto),
            joinedload(Buchung.haben_konto),
            joinedload(Buchung.storniert_durch),
        )
        .order_by(Buchung.datum.desc(), Buchung.id.desc())
    )
    if konto_id is not None:
        abfrage = abfrage.where(
            or_(Buchung.soll_konto_id == konto_id, Buchung.haben_konto_id == konto_id)
        )
    if von is not None:
        abfrage = abfrage.where(Buchung.datum >= von)
    if bis is not None:
        abfrage = abfrage.where(Buchung.datum <= bis)
    return list(session.scalars(abfrage).unique())


# --- Beiträge -------------------------------------------------------------

def beitrag_vorschau(
    session: Session, betraege: dict[MitgliedStatus, int]
) -> list[tuple[Konto, int]]:
    """Alle aktiven Mitglieder, die nach `betraege` (Cent je Status) etwas zahlen."""
    mitglieder = session.scalars(
        select(Konto)
        .where(Konto.typ == KontoTyp.PRIVAT, Konto.aktiv, ~Konto.geloescht)
        .order_by(Konto.status, Konto.name)
    )
    return [(m, betraege.get(m.status, 0)) for m in mitglieder if betraege.get(m.status, 0) > 0]


def beitraege_abbuchen(
    session: Session,
    betraege: dict[MitgliedStatus, int],
    kasse_id: int,
    text: str,
    datum: date | None = None,
) -> list[Buchung]:
    """Bucht den Beitrag je Status von allen aktiven Mitgliedern auf die Kasse.

    Läuft in der Transaktion des Aufrufers: Bei einem Fehler wird nichts gebucht.
    """
    if any(b < 0 for b in betraege.values()):
        raise BuchhaltungsFehler("Beiträge dürfen nicht negativ sein.")
    vorschau = beitrag_vorschau(session, betraege)
    if not vorschau:
        raise BuchhaltungsFehler("Es gibt keine Mitglieder, für die ein Beitrag fällig ist.")
    return [
        buchen(session, Buchungsart.BEITRAG, m.id, betrag, text, datum, gegenkonto_id=kasse_id)
        for m, betrag in vorschau
    ]


# --- Salden ---------------------------------------------------------------

def salden(session: Session) -> dict[int, int]:
    """Saldo in Cent für jedes Konto (auch Konten ohne Buchungen)."""
    typen = dict(session.execute(select(Konto.id, Konto.typ)).all())
    soll = dict(
        session.execute(
            select(Buchung.soll_konto_id, func.sum(Buchung.betrag_cent)).group_by(Buchung.soll_konto_id)
        ).all()
    )
    haben = dict(
        session.execute(
            select(Buchung.haben_konto_id, func.sum(Buchung.betrag_cent)).group_by(Buchung.haben_konto_id)
        ).all()
    )
    ergebnis = {}
    for konto_id, typ in typen.items():
        differenz = soll.get(konto_id, 0) - haben.get(konto_id, 0)
        ergebnis[konto_id] = differenz if typ.ist_aktivkonto else -differenz
    return ergebnis


def saldo(session: Session, konto_id: int) -> int:
    return salden(session)[konto_id]


# --- Auswertung -----------------------------------------------------------

@dataclass(frozen=True)
class KontoBewegung:
    """Entwicklung eines Kontos im Zeitraum (alle Werte in Cent)."""

    konto: Konto
    anfang: int  # Saldo vor dem Startdatum
    zugang: int  # Summe aller Buchungen, die den Saldo erhöhen
    abgang: int  # Summe aller Buchungen, die den Saldo senken (positiv)

    @property
    def veraenderung(self) -> int:
        return self.zugang - self.abgang

    @property
    def ende(self) -> int:
        return self.anfang + self.veraenderung

    @property
    def hat_werte(self) -> bool:
        return bool(self.anfang or self.zugang or self.abgang)


def _pruefe_zeitraum(von: date, bis: date) -> None:
    if von > bis:
        raise BuchhaltungsFehler("Das Startdatum liegt nach dem Enddatum.")


def kontobewegungen(session: Session, von: date, bis: date) -> list[KontoBewegung]:
    """Anfangsbestand, Zu- und Abgänge sowie Endbestand jedes Kontos im Zeitraum (inkl. Enddatum)."""
    _pruefe_zeitraum(von, bis)

    def summen(spalte, bedingung) -> dict[int, int]:
        return dict(
            session.execute(
                select(spalte, func.sum(Buchung.betrag_cent)).where(bedingung).group_by(spalte)
            ).all()
        )

    vorher = Buchung.datum < von
    im_zeitraum = Buchung.datum.between(von, bis)
    soll_vor, haben_vor = summen(Buchung.soll_konto_id, vorher), summen(Buchung.haben_konto_id, vorher)
    soll_im, haben_im = summen(Buchung.soll_konto_id, im_zeitraum), summen(Buchung.haben_konto_id, im_zeitraum)

    ergebnis = []
    for konto in konten(session):
        # Aktivkonto (KW) steigt im Soll, alle anderen im Haben
        if konto.typ.ist_aktivkonto:
            plus_vor, minus_vor, plus_im, minus_im = soll_vor, haben_vor, soll_im, haben_im
        else:
            plus_vor, minus_vor, plus_im, minus_im = haben_vor, soll_vor, haben_im, soll_im
        ergebnis.append(KontoBewegung(
            konto=konto,
            anfang=plus_vor.get(konto.id, 0) - minus_vor.get(konto.id, 0),
            zugang=plus_im.get(konto.id, 0),
            abgang=minus_im.get(konto.id, 0),
        ))
    return ergebnis


@dataclass(frozen=True)
class ArtSumme:
    art: Buchungsart
    anzahl: int
    summe: int


def summen_nach_art(session: Session, von: date, bis: date) -> list[ArtSumme]:
    """Anzahl und Gesamtbetrag der Buchungen je Buchungsart im Zeitraum."""
    _pruefe_zeitraum(von, bis)
    zeilen = session.execute(
        select(Buchung.art, func.count(), func.sum(Buchung.betrag_cent))
        .where(Buchung.datum.between(von, bis))
        .group_by(Buchung.art)
    ).all()
    reihenfolge = list(Buchungsart)
    return sorted(
        (ArtSumme(art, anzahl, summe) for art, anzahl, summe in zeilen),
        key=lambda a: reihenfolge.index(a.art),
    )


@dataclass(frozen=True)
class Abstimmung:
    kw_cent: int
    verteilt_cent: int  # Summe aller Privatkonten und Kassen

    @property
    def stimmt(self) -> bool:
        return self.kw_cent == self.verteilt_cent


def abstimmung(session: Session) -> Abstimmung:
    """Kontrolle: KW-Konto muss der Summe aller Privatkonten und Kassen entsprechen."""
    werte = salden(session)
    kw_id = kw_konto(session).id
    return Abstimmung(werte[kw_id], sum(v for k, v in werte.items() if k != kw_id))
