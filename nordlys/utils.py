"""Generelle hjelpefunksjoner for konvertering og formatering."""
from __future__ import annotations

from typing import List, Optional

import xml.etree.ElementTree as ET


def to_float(value: Optional[str]) -> float:
    """Prøver å tolke en verdi som flyttall og faller tilbake til 0."""
    if value in (None, ""):
        return 0.0
    try:
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        if not text:
            return 0.0

        cleaned = text.replace(" ", "").replace("\xa0", "")
        if not cleaned:
            return 0.0

        comma_pos = cleaned.rfind(",")
        dot_pos = cleaned.rfind(".")

        if comma_pos != -1 and dot_pos != -1:
            # Begge separatorer finnes – anta at den sist forekommende er desimaltegn.
            if comma_pos > dot_pos:
                normalized = cleaned.replace(".", "").replace(",", ".")
            else:
                normalized = cleaned.replace(",", "")
        elif comma_pos != -1:
            left, right = cleaned.rsplit(",", 1)
            if right and len(right) <= 2:
                normalized = f"{left.replace('.', '').replace(',', '')}.{right}"
            else:
                normalized = cleaned.replace(",", "")
        elif dot_pos != -1:
            left, right = cleaned.rsplit(".", 1)
            if right and len(right) <= 2:
                normalized = f"{left.replace(',', '')}.{right}"
            else:
                normalized = cleaned.replace(".", "")
        else:
            normalized = cleaned

        return float(normalized)
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
