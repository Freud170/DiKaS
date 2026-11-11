import pytest

from dikas.geld import cent_zu_text, text_zu_cent


@pytest.mark.parametrize(
    "cent, text",
    [
        (0, "0,00 €"),
        (1, "0,01 €"),
        (5, "0,05 €"),
        (10, "0,10 €"),
        (1250, "12,50 €"),
        (100000, "1.000,00 €"),
        (123456789, "1.234.567,89 €"),
        (-1, "-0,01 €"),
        (-1999, "-19,99 €"),
        (-100000, "-1.000,00 €"),
    ],
)
def test_cent_zu_text(cent, text):
    assert cent_zu_text(cent) == text


def test_cent_zu_text_ohne_waehrung():
    assert cent_zu_text(1250, waehrung=False) == "12,50"


@pytest.mark.parametrize(
    "text, cent",
    [
        ("12,50", 1250),
        ("12.50", 1250),
        ("12", 1200),
        ("12,5", 1250),
        ("0,01", 1),
        (",50", 50),
        ("1.234,5 €", 123450),
        ("1.234.567,89", 123456789),
        ("1234,56", 123456),
        (" 0,01 ", 1),
        ("12 €", 1200),
        ("12€", 1200),
        ("1 000,00", 100000),
        ("-5,00", -500),
        ("0", 0),
        # Tausenderpunkte ohne Komma: so zeigt DiKaS Beträge selbst an ("1.000,00 €")
        ("1.000", 100000),
        ("2.500 €", 250000),
        ("12.345", 1234500),
        ("1.234.567", 123456700),
        ("-1.000", -100000),
        # Kein Tausendermuster: Punkt bleibt Dezimalpunkt
        ("1.5", 150),
        ("0.50", 50),
        ("1234.56", 123456),
    ],
)
def test_text_zu_cent(text, cent):
    assert text_zu_cent(text) == cent


@pytest.mark.parametrize("text", [
    "", " ", "abc", "1,234", "12,5,0", "12,345", "€", "1e3,0", "zwölf",
    "1.2345", "12.5.0", "1.00.000",
    # Für Decimal wären das Zahlen – als Betrag sind sie Unsinn und dürfen nur ValueError auslösen
    "Infinity", "-inf", "NaN", "1e30", "1E5", "9" * 40, "10000000000",
])
def test_text_zu_cent_ungueltig(text):
    with pytest.raises(ValueError):
        text_zu_cent(text)


@pytest.mark.parametrize("cent", [0, 1, 99, 100, 1250, 123456789, -1999])
def test_hin_und_zurueck(cent):
    assert text_zu_cent(cent_zu_text(cent)) == cent
