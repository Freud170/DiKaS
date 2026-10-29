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
    ],
)
def test_text_zu_cent(text, cent):
    assert text_zu_cent(text) == cent


@pytest.mark.parametrize("text", ["", " ", "abc", "1,234", "12,5,0", "12,345", "€", "1e3,0", "zwölf"])
def test_text_zu_cent_ungueltig(text):
    with pytest.raises(ValueError):
        text_zu_cent(text)


@pytest.mark.parametrize("cent", [0, 1, 99, 100, 1250, 123456789, -1999])
def test_hin_und_zurueck(cent):
    assert text_zu_cent(cent_zu_text(cent)) == cent
