"""Analysefunksjoner for kunder og leverandører i SAF-T."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, MutableMapping, Optional, Tuple, TYPE_CHECKING
import xml.etree.ElementTree as ET

from ..helpers.lazy_imports import lazy_import, lazy_pandas
from .dates import parse_saft_date

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
    credit_notes: Optional["pd.DataFrame"] = None
    sales_ar_correlation: Optional["saft_customers.SalesReceivableCorrelation"] = None
    receivable_analysis: Optional["saft_customers.ReceivablePostingAnalysis"] = None
    analysis_start_date: Optional[date] = None
    analysis_end_date: Optional[date] = None


def determine_analysis_year(
    header: Optional["saft.SaftHeader"],
    root: ET.Element,
    ns: MutableMapping[str, object],
    transaction_span: Optional[Tuple[Optional[date], Optional[date]]] = None,
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

    if transaction_span:
        observed_start, observed_end = transaction_span
        if observed_end:
            return observed_end.year, None
        if observed_start:
            return observed_start.year, None
    return None, None


def build_customer_supplier_analysis(
    header: Optional["saft.SaftHeader"],
    root: ET.Element,
    ns: MutableMapping[str, object],
) -> CustomerSupplierAnalysis:
    """Analyser kunder og leverandører, og returner et samlet resultat."""

    observed_start, observed_end = _detect_transaction_span(root, ns)
    analysis_year, parent_map = determine_analysis_year(
        header, root, ns, transaction_span=(observed_start, observed_end)
    )
    customer_sales: Optional["pd.DataFrame"] = None
    supplier_purchases: Optional["pd.DataFrame"] = None
    cost_vouchers: List["saft_customers.CostVoucher"] = []
    credit_notes: Optional["pd.DataFrame"] = None

    period_start = _parse_date(header.period_start) if header else None
    period_end = _parse_date(header.period_end) if header else None
    has_transaction_dates = observed_start is not None or observed_end is not None
    effective_start = period_start
    if observed_start is not None:
        if effective_start is None or observed_start < effective_start:
            effective_start = observed_start
    effective_end = period_end
    if observed_end is not None:
        if effective_end is None or observed_end > effective_end:
            effective_end = observed_end

    if period_start or period_end:
        if parent_map is None:
            parent_map = saft_customers.build_parent_map(root)
        if has_transaction_dates:
            customer_sales, supplier_purchases = (
                saft_customers.compute_customer_supplier_totals(
                    root,
                    ns,
                    date_from=effective_start,
                    date_to=effective_end,
                    parent_map=parent_map,
                )
            )
            cost_vouchers = saft_customers.extract_cost_vouchers(
                root,
                ns,
                date_from=effective_start,
                date_to=effective_end,
                parent_map=parent_map,
            )
        elif analysis_year is not None:
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
        credit_notes = saft_customers.extract_credit_notes(
            root, ns, months=(1, 2), year=analysis_year
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
        credit_notes = saft_customers.extract_credit_notes(
            root, ns, months=(1, 2), year=analysis_year
        )

    if has_transaction_dates:
        sales_ar_correlation = saft_customers.analyze_sales_receivable_correlation(
            root,
            ns,
            date_from=effective_start,
            date_to=effective_end,
            year=analysis_year,
        )
    else:
        sales_ar_correlation = saft_customers.analyze_sales_receivable_correlation(
            root, ns, year=analysis_year
        )

    return CustomerSupplierAnalysis(
        analysis_year=analysis_year,
        customer_sales=customer_sales,
        supplier_purchases=supplier_purchases,
        cost_vouchers=cost_vouchers,
        credit_notes=credit_notes,
        sales_ar_correlation=sales_ar_correlation,
        analysis_start_date=effective_start,
        analysis_end_date=effective_end,
    )


def _parse_date(value: Optional[str]) -> Optional[date]:
    return parse_saft_date(value)


def _detect_transaction_span(
    root: ET.Element, ns: MutableMapping[str, object]
) -> Tuple[Optional[date], Optional[date]]:
    """Finn første og siste transaksjonsdato i SAF-T-filen."""

    ns_et = {
        key: value
        for key, value in ns.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    transactions = root.findall(
        ".//n1:GeneralLedgerEntries/n1:Journal/n1:Transaction",
        ns_et or None,
    )
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    for transaction in transactions:
        element = transaction.find("n1:TransactionDate", ns_et or None)
        if element is None or not element.text:
            continue
        parsed = _parse_date(element.text)
        if parsed is None:
            continue
        if first_date is None or parsed < first_date:
            first_date = parsed
        if last_date is None or parsed > last_date:
            last_date = parsed
    return first_date, last_date
