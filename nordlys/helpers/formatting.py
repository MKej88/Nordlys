"""Formattering av valuta og differanser."""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional


def _round_half_up(value: Optional[float]) -> Optional[int]:
    """Runder til nærmeste heltall med kommersiell avrunding (0.5 -> 1)."""

    if value is None:
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(numeric):
        return None

    try:
        decimal_value = Decimal(str(numeric))
        quantized = decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None

    return int(quantized)


def _format_thousands(value: int) -> str:
    """Formaterer heltall med mellomrom som tusenskille."""

    return f"{value:,}".replace(",", " ")


def format_currency(value: Optional[float]) -> str:
    """Formatterer beløp til heltall med mellomrom som tusenskilletegn."""

    rounded = _round_half_up(value)
    if rounded is None:
        return "—"
    return _format_thousands(rounded)


def format_difference(a: Optional[float], b: Optional[float]) -> str:
    """Formatterer differansen mellom to beløp."""

    if a is None or b is None:
        return "—"

    try:
        value_a = float(a)
        value_b = float(b)
    except (TypeError, ValueError):
        return "—"

    difference = value_a - value_b

    rounded = _round_half_up(difference)
    if rounded is None:
        return "—"
    return _format_thousands(rounded)


__all__ = ["format_currency", "format_difference"]
