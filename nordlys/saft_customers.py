"""Samlemodul som eksponerer SAF-T analysefunksjoner for kunder og leverandører."""

from __future__ import annotations

from .saft.analytics import (
    build_account_name_map,
    build_customer_name_map,
    build_parent_map,
    build_supplier_name_map,
    compute_customer_supplier_totals,
    compute_purchases_per_supplier,
    compute_sales_per_customer,
    extract_cost_vouchers,
)
from .saft.export import save_outputs
from .saft.models import CostVoucher, VoucherLine
from .saft.parsing import (
    get_amount,
    get_tx_customer_id,
    get_tx_supplier_id,
    parse_saft,
)

__all__ = [
    "parse_saft",
    "get_amount",
    "get_tx_customer_id",
    "get_tx_supplier_id",
    "build_customer_name_map",
    "build_supplier_name_map",
    "build_account_name_map",
    "build_parent_map",
    "compute_customer_supplier_totals",
    "compute_sales_per_customer",
    "compute_purchases_per_supplier",
    "CostVoucher",
    "VoucherLine",
    "extract_cost_vouchers",
    "save_outputs",
]
