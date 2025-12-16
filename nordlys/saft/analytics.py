"""Fasade for analysemulighetene i SAF-T modulen."""

from __future__ import annotations

from .name_lookup import (
    build_customer_name_map,
    build_parent_map,
    build_supplier_name_map,
)
from .reporting import (
    SalesReceivableCorrelation,
    build_account_name_map,
    compute_customer_supplier_totals,
    compute_purchases_per_supplier,
    compute_sales_per_customer,
    analyze_sales_receivable_correlation,
    extract_credit_notes,
    extract_cost_vouchers,
)

__all__ = [
    "build_parent_map",
    "build_customer_name_map",
    "build_supplier_name_map",
    "compute_customer_supplier_totals",
    "compute_sales_per_customer",
    "compute_purchases_per_supplier",
    "build_account_name_map",
    "SalesReceivableCorrelation",
    "analyze_sales_receivable_correlation",
    "extract_cost_vouchers",
    "extract_credit_notes",
]
