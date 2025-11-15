"""Konvertering fra tekstlige tall til flyttall."""

from __future__ import annotations

from typing import Optional


def to_float(value: Optional[str]) -> float:
    """Prøver å tolke en verdi som flyttall og faller tilbake til 0."""

    if value in (None, ""):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0

    cleaned = text.replace(" ", "").replace("\xa0", "")
    if not cleaned:
        return 0.0

    sign = ""
    if cleaned.startswith("(") or cleaned.endswith(")"):
        if not (cleaned.startswith("(") and cleaned.endswith(")")):
            return 0.0
        cleaned = cleaned[1:-1].strip()
        if not cleaned:
            return 0.0
        sign = "-"

    allowed_chars = set("0123456789.,+-")
    if any(char not in allowed_chars for char in cleaned):
        return 0.0

    if cleaned[0] in "+-":
        sign, cleaned = cleaned[0], cleaned[1:]
    elif cleaned[-1] in "+-":
        sign = cleaned[-1]
        cleaned = cleaned[:-1]

    cleaned = cleaned.strip()
    if not cleaned:
        return 0.0

    comma_pos = cleaned.rfind(",")
    dot_pos = cleaned.rfind(".")
    decimal_sep: Optional[str] = None

    if comma_pos != -1 and dot_pos != -1:
        decimal_sep = "," if comma_pos > dot_pos else "."
    elif comma_pos != -1 and len(cleaned) - comma_pos - 1 <= 2:
        decimal_sep = ","
    elif dot_pos != -1:
        decimal_sep = "."

    if decimal_sep:
        integer_part, fractional_part = cleaned.rsplit(decimal_sep, 1)
    else:
        integer_part, fractional_part = cleaned, ""

    integer_digits = integer_part.replace(",", "").replace(".", "")
    fractional_digits = fractional_part.replace(",", "").replace(".", "")

    normalized = sign + (integer_digits or "0")
    if fractional_digits:
        normalized = f"{normalized}.{fractional_digits}"

    try:
        return float(normalized)
    except ValueError:
        return 0.0


__all__ = ["to_float"]
