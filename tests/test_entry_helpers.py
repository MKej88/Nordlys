from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from nordlys.saft.entry_helpers import _normalize_decimal_text, _parse_decimal_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1 234,56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
    ],
)
def test_normalize_decimal_text_handles_common_formats(
    raw: str,
    expected: str,
) -> None:
    assert _normalize_decimal_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1 234,56", Decimal("1234.56")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
    ],
)
def test_parse_decimal_text_parses_common_formats(
    raw: str,
    expected: Decimal,
) -> None:
    value = _parse_decimal_text(
        raw,
        field="DebitAmount",
        line=None,
        xml_path=Path("test.xml"),
    )
    assert value == expected
