"""Generelle hjelpefunksjoner for konvertering og formatering."""
from __future__ import annotations

from typing import List, Optional

import xml.etree.ElementTree as ET


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

    allowed_chars = set("0123456789.,+-")
    if any(char not in allowed_chars for char in cleaned):
        return 0.0

    sign = ""
    if cleaned[0] in "+-":
        sign, cleaned = cleaned[0], cleaned[1:]

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


def text_or_none(element: Optional[ET.Element]) -> Optional[str]:
    """Returnerer tekstinnholdet hvis elementet finnes og har tekst."""
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def findall_any_namespace(inv: ET.Element, localname: str) -> List[ET.Element]:
    """Returnerer alle under-elementer med gitt lokale navn uansett namespace."""
    matches: List[ET.Element] = []
    for elem in inv.iter():
        if elem.tag.split('}')[-1].lower() == localname.lower():
            matches.append(elem)
    return matches


def format_currency(value: Optional[float]) -> str:
    """Formatterer beløp til heltall med tusenskilletegn."""
    try:
        return f"{round(float(value)):,.0f}"
    except Exception:
        return "—"


def format_difference(a: Optional[float], b: Optional[float]) -> str:
    """Formatterer differansen mellom to beløp."""
    try:
        return f"{round(float(a) - float(b)):,.0f}"
    except Exception:
        return "—"


__all__ = [
    "to_float",
    "text_or_none",
    "findall_any_namespace",
    "format_currency",
    "format_difference",
]
