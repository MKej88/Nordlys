"""Generelle hjelpefunksjoner for konvertering og formatering."""
from __future__ import annotations

from typing import List, Optional

import xml.etree.ElementTree as ET


def to_float(value: Optional[str]) -> float:
    """Prøver å tolke en verdi som flyttall og faller tilbake til 0."""
    if value in (None, ""):
        return 0.0
    try:
        return float(str(value).replace(" ", "").replace("\xa0", "").replace(",", ""))
    except Exception:
        try:
            return float(value)  # type: ignore[arg-type]
        except Exception:
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


def _format_amount(value: float) -> str:
    formatted = f"{abs(value):,.0f}".replace(",", " ").replace(".", " ")
    sign = "-" if value < 0 else ""
    return f"{sign}{formatted} kr"


def format_currency(value: Optional[float]) -> str:
    """Formatterer beløp som hele kroner med norske skilletegn."""
    try:
        amount = round(float(value))
    except Exception:
        return "—"
    return _format_amount(float(amount))


def format_difference(a: Optional[float], b: Optional[float]) -> str:
    """Formatterer differansen mellom to beløp som hele kroner."""
    try:
        amount = round(float(a) - float(b))
    except Exception:
        return "—"
    return _format_amount(float(amount))


__all__ = [
    "to_float",
    "text_or_none",
    "findall_any_namespace",
    "format_currency",
    "format_difference",
]
