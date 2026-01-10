"""Felles hjelpefunksjoner for dato-parsing i SAF-T-koden."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

__all__ = ["parse_saft_date"]


def parse_saft_date(value: Optional[str]) -> Optional[date]:
    """Forsøk å tolke en dato fra SAF-T-felt med ulike formater."""

    if value is None:
        return None

    text = value.strip()
    if not text:
        return None

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass

    formats = (
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y.%m.%d",
        "%Y%m%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return None
