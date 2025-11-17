"""Hjelpefunksjoner for å normalisere periodeinformasjon fra SAF-T."""

from __future__ import annotations

import re
from typing import Optional, Tuple

from .dates import parse_saft_date
from .header import SaftHeader

PeriodParts = Tuple[Optional[int], Optional[int]]


def _extract_year_month(value: Optional[str]) -> PeriodParts:
    if value is None:
        return None, None

    text = value.strip()
    if not text:
        return None, None

    parsed = parse_saft_date(text)
    if parsed:
        return parsed.year, parsed.month

    normalized = text.replace(" ", "")
    patterns = (
        r"(?P<year>\d{4})[-/.](?P<month>\d{1,2})$",
        r"(?P<year>\d{4})(?P<month>\d{2})$",
        r"(?P<month>\d{1,2})[-/.](?P<year>\d{4})$",
        r"(?P<year>\d{4})[pP](?P<month>\d{1,2})$",
    )
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            year = match.groupdict().get("year")
            month = match.groupdict().get("month")
            month_int = int(month) if month else None
            if month_int is None or not 1 <= month_int <= 12:
                continue
            year_int = int(year) if year else None
            return year_int, month_int

    for pattern in (r"[pP]\s*(\d{1,2})$", r"(\d{1,2})$"):
        match = re.search(pattern, text)
        if match:
            month_int = int(match.group(1))
            if 1 <= month_int <= 12:
                return None, month_int

    return None, None


def _format_period(month: Optional[int]) -> Optional[str]:
    if month is None:
        return None
    if not 1 <= month <= 12:
        return None
    return f"P{int(month)}"


def _sanitize_year(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return text
    return None


def _combine_years(start_year: Optional[int], end_year: Optional[int]) -> Optional[str]:
    if start_year and end_year:
        if start_year == end_year:
            return str(start_year)
        return f"{start_year}–{end_year}"
    if end_year:
        return str(end_year)
    if start_year:
        return str(start_year)
    return None


def format_header_period(header: Optional[SaftHeader]) -> Optional[str]:
    """Bygg en menneskelig lesbar periode av SAF-T header-informasjon."""

    if header is None:
        return None

    start_year, start_month = _extract_year_month(header.period_start)
    end_year, end_month = _extract_year_month(header.period_end)

    year_text = _sanitize_year(header.fiscal_year)
    if year_text is None:
        year_text = _combine_years(start_year, end_year)

    start_label = _format_period(start_month)
    end_label = _format_period(end_month)

    if start_label and end_label:
        period_text = start_label if start_label == end_label else f"{start_label}–{end_label}"
    else:
        period_text = start_label or end_label

    if period_text is None:
        return year_text

    if year_text:
        return f"{year_text} {period_text}"
    return period_text


__all__ = ["format_header_period"]
