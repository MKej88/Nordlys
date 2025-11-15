"""Analysefunksjoner for kunder og leverandører i SAF-T."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, MutableMapping, Optional, Tuple, TYPE_CHECKING
import xml.etree.ElementTree as ET

from ..helpers.lazy_imports import lazy_import, lazy_pandas

if TYPE_CHECKING:
    import pandas as pd
    from .. import saft
    from .. import saft_customers
else:
    pd = lazy_pandas()
    saft = lazy_import("nordlys.saft")
    saft_customers = lazy_import("nordlys.saft_customers")


@dataclass
class CustomerSupplierAnalysis:
    """Resultatdata fra kunde- og leverandør-analysen."""

    analysis_year: Optional[int]
    customer_sales: Optional["pd.DataFrame"]
    supplier_purchases: Optional["pd.DataFrame"]
    cost_vouchers: List["saft_customers.CostVoucher"]


def determine_analysis_year(
    header: Optional["saft.SaftHeader"],
    root: ET.Element,
    ns: MutableMapping[str, object],
) -> Tuple[Optional[int], Optional[Dict[ET.Element, Optional[ET.Element]]]]:
    """Finn analyseår og parent-map basert på SAF-T-data."""

    period_start = _parse_date(header.period_start) if header else None
    period_end = _parse_date(header.period_end) if header else None
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None

    if period_start or period_end:
        parent_map = saft_customers.build_parent_map(root)
        if period_end:
            return period_end.year, parent_map
        if period_start:
            return period_start.year, parent_map
        return None, parent_map

    if header and header.fiscal_year:
        try:
            return int(header.fiscal_year), None
        except (TypeError, ValueError):
            pass

    if header and header.period_end:
        parsed_end = _parse_date(header.period_end)
        if parsed_end:
            return parsed_end.year, None

    ns_et = {
        key: value
        for key, value in ns.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    for tx in root.findall(
        ".//n1:GeneralLedgerEntries/n1:Journal/n1:Transaction", ns_et or None
    ):
        date_element = tx.find("n1:TransactionDate", ns_et or None)
        if date_element is not None and date_element.text:
            parsed = _parse_date(date_element.text)
            if parsed:
                return parsed.year, None
    return None, None


def build_customer_supplier_analysis(
    header: Optional["saft.SaftHeader"],
    root: ET.Element,
    ns: MutableMapping[str, object],
) -> CustomerSupplierAnalysis:
    """Analyser kunder og leverandører, og returner et samlet resultat."""

    analysis_year, parent_map = determine_analysis_year(header, root, ns)
    customer_sales: Optional["pd.DataFrame"] = None
    supplier_purchases: Optional["pd.DataFrame"] = None
    cost_vouchers: List["saft_customers.CostVoucher"] = []

    period_start = _parse_date(header.period_start) if header else None
    period_end = _parse_date(header.period_end) if header else None

    if period_start or period_end:
        if parent_map is None:
            parent_map = saft_customers.build_parent_map(root)
        customer_sales, supplier_purchases = (
            saft_customers.compute_customer_supplier_totals(
                root,
                ns,
                date_from=period_start,
                date_to=period_end,
                parent_map=parent_map,
            )
        )
        cost_vouchers = saft_customers.extract_cost_vouchers(
            root,
            ns,
            date_from=period_start,
            date_to=period_end,
            parent_map=parent_map,
        )
    elif analysis_year is not None:
        if parent_map is None:
            parent_map = saft_customers.build_parent_map(root)
        customer_sales, supplier_purchases = (
            saft_customers.compute_customer_supplier_totals(
                root,
                ns,
                year=analysis_year,
                parent_map=parent_map,
            )
        )
        cost_vouchers = saft_customers.extract_cost_vouchers(
            root,
            ns,
            year=analysis_year,
            parent_map=parent_map,
        )

    return CustomerSupplierAnalysis(
        analysis_year=analysis_year,
        customer_sales=customer_sales,
        supplier_purchases=supplier_purchases,
        cost_vouchers=cost_vouchers,
    )


def _parse_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            from datetime import datetime

            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None
