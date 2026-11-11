"""Umrechnung zwischen Cent-Beträgen (int) und deutscher Textdarstellung."""

import re
from decimal import Decimal

# Deutsche Tausenderpunkte ohne Komma: '1.000', '12.345', '1.234.567' (so zeigt DiKaS Beträge selbst an)
_TAUSENDERPUNKTE = re.compile(r"[-+]?[1-9]\d{0,2}(\.\d{3})+")
# Nur reine Dezimalzahlen – 'Infinity', 'NaN' oder '1e30' wären für Decimal sonst auch Zahlen
_ZAHL = re.compile(r"[-+]?(\d+(\.\d*)?|\.\d+)")
# Obergrenze für Eingaben (unter 10 Milliarden Euro): schützt vor Tippfehlern mit zu vielen Stellen
GRENZE_EURO = Decimal(10**10)


def cent_zu_text(cent: int, waehrung: bool = True) -> str:
    """1234567 -> '12.345,67 €'"""
    vorzeichen = "-" if cent < 0 else ""
    euro, rest = divmod(abs(cent), 100)
    text = f"{vorzeichen}{euro:,}".replace(",", ".") + f",{rest:02d}"
    return f"{text} €" if waehrung else text


def text_zu_cent(text: str) -> int:
    """'12,50' / '12.50' / '1.234,5 €' / '1.000' -> Cent. Wirft ValueError bei ungültiger Eingabe.

    Punkte sind Tausendertrenner, wenn ein Komma vorkommt oder die Zahl wie '1.000' aufgebaut
    ist (Dreiergruppen). Sonst gilt der Punkt als Dezimalpunkt: '12.50' sind 12,50 €.
    """
    t = text.strip().replace("€", "").replace(" ", "")
    if "," in t or _TAUSENDERPUNKTE.fullmatch(t):
        t = t.replace(".", "").replace(",", ".")
    if not _ZAHL.fullmatch(t):
        raise ValueError(f"Ungültiger Betrag: {text!r}")
    betrag = Decimal(t)
    if abs(betrag) >= GRENZE_EURO:
        raise ValueError(f"Betrag zu groß: {text!r}")
    cent = betrag * 100
    if cent != cent.to_integral_value():
        raise ValueError(f"Mehr als zwei Nachkommastellen: {text!r}")
    return int(cent)
