from __future__ import annotations

import pytest

from nordlys.helpers.formatting import format_currency, format_difference
from nordlys.helpers.number_parsing import to_float


@pytest.mark.parametrize(
    "value, expected",
    [
        ("123,45", 123.45),
        ("1 234,50", 1234.5),
        ("1.234,50", 1234.5),
        ("1,234.50", 1234.5),
        ("\xa0123,00", 123.0),
        ("1.234", 1.234),
        ("123.4567", 123.4567),
        ("1.234.567", 1234567.0),
        (1234, 1234.0),
        ("1 234,50-", -1234.5),
    ],
)
def test_to_float_handles_common_separators(value, expected):
    assert to_float(value) == pytest.approx(expected)


def test_to_float_handles_parentheses_as_negative():
    assert to_float("(1 234,50)") == pytest.approx(-1234.5)


def test_to_float_invalid_returns_zero():
    assert to_float("not a number") == 0.0


def test_format_currency_invalid() -> None:
    assert format_currency(None) == "—"
    assert format_currency("hei") == "—"
    assert format_currency(float("nan")) == "—"


def test_format_currency_rounding() -> None:
    assert format_currency(2.5) == "3"
    assert format_currency(-2.5) == "-3"
    assert format_currency(1234.5) == "1,235"


def test_format_difference_valid() -> None:
    assert format_difference(5, 3) == "2"
    assert format_difference(1000.4, 500.4) == "500"


def test_format_difference_invalid() -> None:
    assert format_difference(None, 3) == "—"
    assert format_difference(5, None) == "—"
    assert format_difference("hei", 1) == "—"


def test_format_difference_rounding() -> None:
    assert format_difference(5.5, 0) == "6"
    assert format_difference(-5.5, 0) == "-6"
