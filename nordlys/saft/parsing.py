"""Tilgjengeliggjør sentrale funksjoner for SAF-T parsing."""

from __future__ import annotations

from .entry_stream import (
    SaftEntry,
    check_trial_balance,
    get_amount,
    get_tx_customer_id,
    get_tx_supplier_id,
    iter_saft_entries,
)
from .xml_helpers import (
    _clean_text,
    _find,
    _findall,
    _local_name,
    NamespaceMap,
    parse_saft,
)

__all__ = [
    "NamespaceMap",
    "SaftEntry",
    "parse_saft",
    "get_amount",
    "get_tx_customer_id",
    "get_tx_supplier_id",
    "iter_saft_entries",
    "check_trial_balance",
    "_clean_text",
    "_find",
    "_findall",
    "_local_name",
]
