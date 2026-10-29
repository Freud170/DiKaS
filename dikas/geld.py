"""Umrechnung zwischen Cent-Beträgen (int) und deutscher Textdarstellung."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def cent_zu_text(cent: int, waehrung: bool = True) -> str:
    """1234567 -> '12.345,67 €'"""
    vorzeichen = "-" if cent < 0 else ""
    euro, rest = divmod(abs(cent), 100)
    text = f"{vorzeichen}{euro:,}".replace(",", ".") + f",{rest:02d}"
    return f"{text} €" if waehrung else text


def text_zu_cent(text: str) -> int:
    """'12,50' / '12.50' / '1.234,5 €' -> Cent. Wirft ValueError bei ungültiger Eingabe."""
    t = text.strip().replace("€", "").replace(" ", "")
    if "," in t:
        # Deutsches Format: Punkte sind Tausendertrenner
        t = t.replace(".", "").replace(",", ".")
    try:
        betrag = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"Ungültiger Betrag: {text!r}") from None
    if betrag != betrag.quantize(Decimal("0.01")):
        raise ValueError(f"Mehr als zwei Nachkommastellen: {text!r}")
    return int((betrag * 100).to_integral_value(ROUND_HALF_UP))
