"""Tester for desimal-parsing i SAF-T-hjelperne."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from nordlys.saft.entry_helpers import _normalize_decimal_text, _parse_decimal_text


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1.234.567", "1234567"),
    ],
)
def test_normalize_decimal_text_stripper_tusenskilletegn(
    raw: str, expected: str
) -> None:
    """Vanlige tusenskilletegn skal fjernes før desimalberegning."""

    assert _normalize_decimal_text(raw) == expected


def test_parse_decimal_text_håndterer_formatterte_tall() -> None:
    """Parsingen skal tåle formaterte tall uten å kaste."""

    value = _parse_decimal_text(
        "9.876,54", field="Amount", line=10, xml_path=Path("fil.xml")
    )
    assert value == Decimal("9876.54")
