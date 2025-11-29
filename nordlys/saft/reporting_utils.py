"""Grunnleggende hjelpere for rapportering på SAF-T-data."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Optional, TYPE_CHECKING

from ..helpers.lazy_imports import lazy_pandas
from .xml_helpers import _find, _findall, NamespaceMap

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd

__all__ = [
    "_require_pandas",
    "_ensure_date",
    "_iter_transactions",
    "_format_decimal",
    "_normalize_account_key",
    "_is_cost_account",
    "_is_revenue_account",
]

_pd: Optional["pd"] = None


def _require_pandas() -> "pd":
    """Laster pandas først når det faktisk trengs."""

    global _pd
    if _pd is None:
        module = lazy_pandas()
        if module is None:  # pragma: no cover - avhenger av installert pandas
            raise RuntimeError(
                "Pandas må være installert for å bruke analysefunksjonene for SAF-T."
            )
        _pd = module
    return _pd


def _ensure_date(value: Optional[object]) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None


def _iter_transactions(root: ET.Element, ns: NamespaceMap) -> Iterable[ET.Element]:
    entries = _find(root, "n1:GeneralLedgerEntries", ns)
    if entries is None:
        return
    for journal in _findall(entries, "n1:Journal", ns):
        for transaction in _findall(journal, "n1:Transaction", ns):
            yield transaction


def _format_decimal(value: Decimal) -> float:
    """Konverterer Decimal til float med to desimaler."""

    from decimal import ROUND_HALF_UP

    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _normalize_account_key(account: str) -> Optional[str]:
    """Fjerner ikke-numeriske tegn fra kontonummer for enklere oppslag."""

    digits = "".join(ch for ch in account if ch.isdigit())
    return digits or None


def _is_cost_account(account: str) -> bool:
    """Returnerer True dersom kontoen tilhører kostnadsklassene 4xxx–8xxx."""

    if not account:
        return False
    normalized = account.strip()
    digits = "".join(ch for ch in normalized if ch.isdigit())
    normalized = digits or normalized
    if not normalized:
        return False
    first_char = normalized[0]
    return first_char in {"4", "5", "6", "7", "8"}


def _is_revenue_account(account: str) -> bool:
    """Returnerer True dersom kontoen tilhører kontoklasse 3xxx."""

    if not account:
        return False
    normalized = account.strip()
    digits = "".join(ch for ch in normalized if ch.isdigit())
    normalized = digits or normalized
    if not normalized:
        return False
    return normalized[0] == "3"
