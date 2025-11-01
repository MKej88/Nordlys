"""Formateringshjelpere for Nordlys sitt brukergrensesnitt."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

__all__ = ["format_orgnr", "format_period", "format_account_count"]


def format_orgnr(value: Optional[str]) -> str:
    if not value:
        return "–"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 9:
        return f"{digits[:3]} {digits[3:6]} {digits[6:]}"
    stripped = value.strip()
    return stripped or "–"


def _format_period_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    if text.isdigit():
        if len(text) <= 2:
            return text.zfill(2)
        if len(text) == 4:
            return text
    return text


def format_period(fiscal_year: Optional[str], start: Optional[str], end: Optional[str]) -> str:
    year_txt = (fiscal_year or "").strip()
    start_txt = _format_period_value(start)
    end_txt = _format_period_value(end)

    range_txt: Optional[str]
    if start_txt and end_txt:
        if start_txt == end_txt:
            range_txt = start_txt
        else:
            range_txt = f"{start_txt} – {end_txt}"
    else:
        range_txt = start_txt or end_txt

    parts: List[str] = []
    if year_txt:
        parts.append(year_txt)
    if range_txt:
        label = "Periode" if " – " not in range_txt and (start_txt == end_txt or end_txt is None) else "Perioder"
        parts.append(f"{label} {range_txt}")

    if not parts:
        return "–"
    if len(parts) == 1:
        return parts[0]
    return " · ".join(parts)


def format_account_count(value: int) -> str:
    return f"{value:,}".replace(",", " ").replace(".", " ")
