"""Offentlig API for SAF-T funksjoner i Nordlys."""

from __future__ import annotations

from .entry_stream import check_trial_balance, iter_saft_entries
from .header import SaftHeader, parse_saft_header
from .masterfiles import CustomerInfo, SupplierInfo, parse_customers, parse_suppliers
from .trial_balance_summary import ns4102_summary_from_tb, parse_saldobalanse
from .validation import (
    SAFT_RESOURCE_DIR,
    XMLSCHEMA_AVAILABLE,
    SaftValidationResult,
    ensure_saft_validated,
    validate_saft_against_xsd,
)

__all__ = [
    "SaftHeader",
    "SaftValidationResult",
    "CustomerInfo",
    "SupplierInfo",
    "parse_saft_header",
    "parse_saldobalanse",
    "ns4102_summary_from_tb",
    "parse_customers",
    "parse_suppliers",
    "validate_saft_against_xsd",
    "ensure_saft_validated",
    "iter_saft_entries",
    "check_trial_balance",
    "SAFT_RESOURCE_DIR",
    "XMLSCHEMA_AVAILABLE",
]
