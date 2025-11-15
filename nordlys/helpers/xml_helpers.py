"""Hjelpefunksjoner for å lese XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional


def text_or_none(element: Optional[ET.Element]) -> Optional[str]:
    """Returnerer tekstinnholdet hvis elementet finnes og har tekst."""

    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def findall_any_namespace(inv: ET.Element, localname: str) -> List[ET.Element]:
    """Returnerer alle under-elementer med gitt lokale navn uansett namespace."""

    matches: List[ET.Element] = []
    for elem in inv.iter():
        if elem.tag.split("}")[-1].lower() == localname.lower():
            matches.append(elem)
    return matches


__all__ = ["findall_any_namespace", "text_or_none"]
