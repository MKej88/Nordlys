from __future__ import annotations

import pytest

from nordlys.utils import to_float


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
        (1234, 1234.0),
        ("1 234,50-", -1234.5),
    ],
)
def test_to_float_handles_common_separators(value, expected):
    assert to_float(value) == pytest.approx(expected)


def test_to_float_invalid_returns_zero():
    assert to_float("not a number") == 0.0
