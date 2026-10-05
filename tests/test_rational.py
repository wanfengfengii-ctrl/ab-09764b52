import pytest

from app.rational import RationalParseError, format_rational, parse_rational


@pytest.mark.parametrize(
    "text,num,den",
    [
        ("0", 0, 1),
        ("7", 7, 1),
        ("-3", -3, 1),
        ("2/3", 2, 3),
        ("-4/5", -4, 5),
        ("4/-6", -2, 3),  # normalized sign and reduced
        ("  6/9 ", 2, 3),
        ("0/5", 0, 1),
    ],
)
def test_parse_valid(text, num, den):
    value = parse_rational(text)
    assert (value.numerator, value.denominator) == (num, den)


@pytest.mark.parametrize("text", ["1.5", "1/2/3", "1e3", "", "abc", "1/0", "-2/0", "0.0"])
def test_parse_invalid(text):
    with pytest.raises(RationalParseError):
        parse_rational(text)


def test_format():
    assert format_rational(parse_rational("6/4")) == "3/2"
    assert format_rational(parse_rational("8/4")) == "2"
