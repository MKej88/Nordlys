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

    cleaned = "".join(ch for ch in text if not ch.isspace())
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

    sign_positions = [idx for idx, ch in enumerate(cleaned) if ch in "+-"]
    if len(sign_positions) > 1:
        return 0.0
    if sign_positions and sign_positions[0] not in {0, len(cleaned) - 1}:
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
    comma_count = cleaned.count(",")
    dot_count = cleaned.count(".")
    decimal_sep: Optional[str] = None

    if comma_count and dot_count:
        decimal_sep = "," if comma_pos > dot_pos else "."
    elif comma_count == 1 and dot_count == 0 and len(cleaned) - comma_pos - 1 <= 2:
        decimal_sep = ","
    elif dot_count == 1 and comma_count == 0:
        decimal_sep = "."

    def _valid_thousands(text: str, separator: str) -> bool:
        parts = text.split(separator)
        if len(parts) == 1:
            return True
        if any(part == "" for part in parts):
            return False
        if len(parts[0]) not in {1, 2, 3}:
            return False
        return all(len(part) == 3 for part in parts[1:])

    if decimal_sep:
        integer_part, fractional_part = cleaned.rsplit(decimal_sep, 1)
        thousand_sep = "," if decimal_sep == "." else "."
        if thousand_sep in integer_part and not _valid_thousands(
            integer_part, thousand_sep
        ):
            return 0.0
    else:
        integer_part, fractional_part = cleaned, ""
        separators = {sep for sep in ",." if sep in integer_part}
        if len(separators) > 1:
            return 0.0
        if separators:
            separator = separators.pop()
            if not _valid_thousands(integer_part, separator):
                return 0.0

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
