import pytest

from dikas.geld import cent_zu_text, text_zu_cent


@pytest.mark.parametrize(
    "cent, text",
    [(0, "0,00 €"), (5, "0,05 €"), (1250, "12,50 €"), (123456789, "1.234.567,89 €"), (-1999, "-19,99 €")],
)
def test_cent_zu_text(cent, text):
    assert cent_zu_text(cent) == text


@pytest.mark.parametrize(
    "text, cent",
    [("12,50", 1250), ("12.50", 1250), ("12", 1200), ("1.234,5 €", 123450), (" 0,01 ", 1)],
)
def test_text_zu_cent(text, cent):
    assert text_zu_cent(text) == cent


@pytest.mark.parametrize("text", ["", "abc", "1,234", "12,5,0"])
def test_text_zu_cent_ungueltig(text):
    with pytest.raises(ValueError):
        text_zu_cent(text)
