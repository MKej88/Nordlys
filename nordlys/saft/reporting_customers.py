"""Rapporter som analyserer kunder og leverandører."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from .customer_buckets import DESCRIPTION_BUCKET_MAP
from .entry_helpers import get_amount, get_tx_customer_id, get_tx_supplier_id
from .name_lookup import (
    build_customer_name_map,
    build_parent_map,
    build_supplier_name_map,
)
from .reporting_utils import (
    _ensure_date,
    _is_cost_account,
    _is_revenue_account,
    _iter_transactions,
    _normalize_account_key,
    _require_pandas,
)
from .xml_helpers import _clean_text, _find, _findall, NamespaceMap

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd

__all__ = [
    "compute_customer_supplier_totals",
    "compute_sales_per_customer",
    "compute_purchases_per_supplier",
]

_DESCRIPTION_BUCKET_NAMES: set[str] = set(DESCRIPTION_BUCKET_MAP)


def _build_description_customer_map(
    root: ET.Element, ns: NamespaceMap
) -> Dict[str, str]:
    """Returnerer kunde-IDer for kjente bilagstekster."""

    mapping: Dict[str, str] = {}
    if not _DESCRIPTION_BUCKET_NAMES:
        return mapping

    for customer in _findall(root, ".//n1:MasterFiles//n1:Customer", ns):
        cid_element = _find(customer, "n1:CustomerID", ns)
        customer_id = _clean_text(cid_element.text if cid_element is not None else None)
        if not customer_id:
            continue
        name_element = _find(customer, "n1:Name", ns)
        if name_element is None:
            name_element = _find(customer, "n1:CompanyName", ns)
        name = _clean_text(name_element.text if name_element is not None else None)
        if not name:
            continue
        normalized = name.strip().lower()
        if normalized in _DESCRIPTION_BUCKET_NAMES and normalized not in mapping:
            mapping[normalized] = customer_id
    for bucket_name in _DESCRIPTION_BUCKET_NAMES:
        if bucket_name not in mapping:
            mapping[bucket_name] = DESCRIPTION_BUCKET_MAP[bucket_name]
    return mapping


def _extract_transaction_descriptions(
    transaction: ET.Element, ns: NamespaceMap
) -> Tuple[Optional[str], Optional[str]]:
    """Returnerer både VoucherDescription og Description fra bilaget."""

    voucher_element = _find(transaction, "n1:VoucherDescription", ns)
    voucher_description = _clean_text(
        voucher_element.text if voucher_element is not None else None
    )
    description_element = _find(transaction, "n1:Description", ns)
    description = _clean_text(
        description_element.text if description_element is not None else None
    )
    return voucher_description, description


def _lookup_description_customer(
    voucher_description: Optional[str],
    description: Optional[str],
    mapping: Dict[str, str],
) -> Optional[str]:
    """Returnerer kunde-ID for kjente VoucherDescription-verdier."""

    def _normalize(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        normalized_value = value.strip().lower()
        return normalized_value or None

    normalized_voucher = _normalize(voucher_description)
    if normalized_voucher:
        direct = mapping.get(normalized_voucher)
        if direct:
            return direct
        for keyword in _DESCRIPTION_BUCKET_NAMES:
            if keyword in normalized_voucher:
                fallback = mapping.get(keyword)
                if fallback:
                    return fallback

    normalized_description = _normalize(description)
    if normalized_description:
        return mapping.get(normalized_description)

    return None


def _extract_transaction_period(
    transaction: ET.Element, ns: NamespaceMap
) -> Tuple[Optional[int], Optional[int]]:
    """Henter periodeår og -nummer fra et bilag hvis mulig."""

    def _read_int(element: Optional[ET.Element]) -> Optional[int]:
        if element is None:
            return None
        text = _clean_text(element.text if element is not None else None)
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    period_element = _find(transaction, "n1:Period", ns)
    if period_element is not None:
        period_year = _read_int(_find(period_element, "n1:PeriodYear", ns))
        period_number = _read_int(_find(period_element, "n1:PeriodNumber", ns))
        if period_year is not None or period_number is not None:
            return period_year, period_number

    period_year = _read_int(_find(transaction, "n1:PeriodYear", ns))
    period_number = _read_int(_find(transaction, "n1:PeriodNumber", ns))
    return period_year, period_number


def _extract_line_customer_id(line: ET.Element, ns: NamespaceMap) -> Optional[str]:
    """Henter CustomerID fra en linje om den finnes."""

    for path in ("n1:CustomerID", "n1:Customer/n1:CustomerID"):
        element = _find(line, path, ns)
        identifier = _clean_text(element.text if element is not None else None)
        if identifier:
            return identifier
    return None


def _compute_customer_sales_map(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    start_date: Optional[date],
    end_date: Optional[date],
    year: Optional[int],
    last_period: Optional[int],
) -> Tuple[Dict[str, Decimal], Dict[str, int]]:
    """Returnerer netto salg per kunde basert på 1500- og 27xx-linjer."""

    totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts: Dict[str, int] = defaultdict(int)
    use_range = start_date is not None or end_date is not None
    description_customer_map = _build_description_customer_map(root, ns)

    for transaction in _iter_transactions(root, ns):
        lines_list = list(_findall(transaction, "n1:Line", ns))
        if not lines_list:
            continue

        date_element = _find(transaction, "n1:TransactionDate", ns)
        tx_date = _ensure_date(date_element.text if date_element is not None else None)
        voucher_description, transaction_description = (
            _extract_transaction_descriptions(transaction, ns)
        )

        if use_range:
            if tx_date is None:
                continue
            if start_date and tx_date < start_date:
                continue
            if end_date and tx_date > end_date:
                continue
        else:
            if year is None:
                continue
            period_year, period_number = _extract_transaction_period(transaction, ns)
            if period_year is None and tx_date is not None:
                period_year = tx_date.year
            if period_year is None or period_year != year:
                continue
            if last_period is not None:
                if period_number is None and tx_date is not None:
                    period_number = tx_date.month
                if period_number is None or period_number > last_period:
                    continue

        gross_per_customer: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        vat_total = Decimal("0")
        vat_found = False
        has_revenue_account = False
        vat_share_per_customer: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        revenue_total = Decimal("0")
        transaction_customer_id = get_tx_customer_id(transaction, ns, lines=lines_list)
        if not transaction_customer_id:
            transaction_customer_id = _lookup_description_customer(
                voucher_description, transaction_description, description_customer_map
            )
        fallback_customer_id: Optional[str] = transaction_customer_id
        line_summaries: List[Tuple[str, Optional[str], Decimal, Decimal]] = []

        for line in lines_list:
            account_element = _find(line, "n1:AccountID", ns)
            account_text = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account_text:
                continue

            normalized_digits = _normalize_account_key(account_text)
            normalized = normalized_digits or account_text

            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)
            line_summaries.append((normalized, normalized_digits, debit, credit))
            if _is_revenue_account(normalized):
                has_revenue_account = True
                revenue_total += credit - debit

            customer_id = _extract_line_customer_id(line, ns)
            is_receivable_account = bool(
                normalized_digits and normalized_digits.startswith("15")
            )
            should_include_line = is_receivable_account or customer_id is not None

            if should_include_line:
                if not customer_id:
                    if not is_receivable_account:
                        continue
                    if fallback_customer_id is None:
                        fallback_customer_id = transaction_customer_id
                        if fallback_customer_id is None:
                            fallback_customer_id = _lookup_description_customer(
                                voucher_description,
                                transaction_description,
                                description_customer_map,
                            )
                    if fallback_customer_id is None:
                        fallback_customer_id = get_tx_customer_id(
                            transaction, ns, lines=lines_list
                        )
                    customer_id = fallback_customer_id
                if not customer_id:
                    continue
                amount = debit - credit
                if amount == 0:
                    continue
                gross_per_customer[customer_id] += amount
                if debit > 0:
                    vat_share_per_customer[customer_id] += debit
            elif normalized.startswith("27"):
                vat_found = True
                vat_total += credit - debit

        if not vat_found and not has_revenue_account:
            continue

        gross_per_customer = {
            customer_id: amount
            for customer_id, amount in gross_per_customer.items()
            if amount != 0
        }
        if not gross_per_customer and transaction_customer_id:
            fallback_gross = Decimal("0")
            used_revenue_basis = False
            for normalized, normalized_digits, debit, credit in line_summaries:
                if normalized and _is_revenue_account(normalized):
                    fallback_gross += credit - debit
                    used_revenue_basis = True
                    continue
                if normalized_digits and normalized_digits.startswith("27"):
                    fallback_gross += credit - debit
                    used_revenue_basis = True
            if used_revenue_basis and fallback_gross != 0:
                gross_per_customer[transaction_customer_id] = fallback_gross
        if not gross_per_customer:
            continue

        expected_gross_total = revenue_total + vat_total
        gross_sum = sum(gross_per_customer.values(), Decimal("0"))
        if has_revenue_account and expected_gross_total != gross_sum:
            diff = expected_gross_total - gross_sum
            if diff != 0:
                target_customer: Optional[str] = transaction_customer_id
                if not target_customer:
                    if len(gross_per_customer) == 1:
                        target_customer = next(iter(gross_per_customer))
                    else:
                        target_customer = max(
                            gross_per_customer.items(), key=lambda item: abs(item[1])
                        )[0]
                if target_customer:
                    gross_per_customer[target_customer] = (
                        gross_per_customer.get(target_customer, Decimal("0")) + diff
                    )

        vat_share_per_customer = {
            customer_id: share
            for customer_id, share in vat_share_per_customer.items()
            if share > 0 and customer_id in gross_per_customer
        }

        vat_share_total = sum(vat_share_per_customer.values(), Decimal("0"))
        share_basis_per_customer: Dict[str, Decimal]
        share_total: Decimal
        if vat_share_total > 0:
            share_basis_per_customer = dict(vat_share_per_customer)
            share_total = vat_share_total
            for customer_id, gross_amount in gross_per_customer.items():
                if customer_id in share_basis_per_customer:
                    continue
                fallback_share = abs(gross_amount)
                if fallback_share == 0:
                    continue
                share_basis_per_customer[customer_id] = fallback_share
                share_total += fallback_share
        else:
            share_basis_per_customer = gross_per_customer
            share_total = sum(gross_per_customer.values(), Decimal("0"))

        if share_total == 0:
            continue

        for customer_id, gross_amount in gross_per_customer.items():
            share_basis = share_basis_per_customer.get(customer_id, Decimal("0"))
            if share_basis == 0:
                continue
            share = share_basis / share_total
            net_amount = gross_amount - (vat_total * share)
            if net_amount == 0:
                continue
            totals[customer_id] += net_amount
            counts[customer_id] += 1

    return totals, counts


def compute_customer_supplier_totals(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    year: Optional[int] = None,
    last_period: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None,
) -> Tuple["pd.DataFrame", "pd.DataFrame"]:
    """Beregner kundesalg og leverandørkjøp i ett pass gjennom transaksjonene."""

    pandas = _require_pandas()

    start_date = _ensure_date(date_from)
    end_date = _ensure_date(date_to)
    use_range = start_date is not None or end_date is not None
    if use_range:
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date
    elif year is None:
        raise ValueError("Angi enten year eller date_from/date_to.")

    customer_totals, customer_counts = _compute_customer_sales_map(
        root,
        ns,
        start_date=start_date,
        end_date=end_date,
        year=year,
        last_period=last_period if not use_range else None,
    )
    supplier_totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    supplier_counts: Dict[str, int] = defaultdict(int)

    for transaction in _iter_transactions(root, ns):
        lines_list = list(_findall(transaction, "n1:Line", ns))
        if not lines_list:
            continue

        date_element = _find(transaction, "n1:TransactionDate", ns)
        tx_date = _ensure_date(date_element.text if date_element is not None else None)
        if use_range:
            if tx_date is None:
                continue
            if start_date and tx_date < start_date:
                continue
            if end_date and tx_date > end_date:
                continue
        else:
            if year is None:
                continue
            period_year, period_number = _extract_transaction_period(transaction, ns)
            if period_year is None and tx_date is not None:
                period_year = tx_date.year
            if period_year is None or period_year != year:
                continue
            if last_period is not None:
                if period_number is None and tx_date is not None:
                    period_number = tx_date.month
                if period_number is None or period_number > last_period:
                    continue

        purchase_total = Decimal("0")
        has_purchase = False

        for line in lines_list:
            account_element = _find(line, "n1:AccountID", ns)
            account_text = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account_text:
                continue

            credit = get_amount(line, "CreditAmount", ns)
            debit = get_amount(line, "DebitAmount", ns)

            if _is_cost_account(account_text):
                has_purchase = True
                purchase_total += debit - credit

        if has_purchase:
            supplier_id = get_tx_supplier_id(transaction, ns, lines=lines_list)
            if supplier_id:
                supplier_totals[supplier_id] += purchase_total
                supplier_counts[supplier_id] += 1

    lookup_map = parent_map
    if (customer_totals or supplier_totals) and lookup_map is None:
        lookup_map = build_parent_map(root)

    pandas_module = pandas
    if not customer_totals:
        customer_df = pandas_module.DataFrame(
            columns=["Kundenr", "Kundenavn", "Omsetning eks mva"]
        )
    else:
        customer_names = build_customer_name_map(root, ns, parent_map=lookup_map)
        customer_rows = []
        for customer_id, amount in customer_totals.items():
            if amount == 0:
                continue
            rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            customer_rows.append(
                {
                    "Kundenr": customer_id,
                    "Kundenavn": customer_names.get(customer_id, ""),
                    "Omsetning eks mva": float(rounded),
                    "Transaksjoner": customer_counts.get(customer_id, 0),
                }
            )
        if not customer_rows:
            customer_df = pandas_module.DataFrame(
                columns=["Kundenr", "Kundenavn", "Omsetning eks mva"]
            )
        else:
            customer_df = pandas_module.DataFrame(customer_rows)
            customer_df["Omsetning eks mva"] = (
                customer_df["Omsetning eks mva"].astype(float).round(2)
            )
            customer_df = customer_df.sort_values(
                "Omsetning eks mva", ascending=False
            ).reset_index(drop=True)

    if not supplier_totals:
        supplier_df = pandas_module.DataFrame(
            columns=["Leverandørnr", "Leverandørnavn", "Innkjøp eks mva"]
        )
    else:
        supplier_names = build_supplier_name_map(root, ns, parent_map=lookup_map)
        supplier_rows = []
        for supplier_id, amount in supplier_totals.items():
            rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            supplier_rows.append(
                {
                    "Leverandørnr": supplier_id,
                    "Leverandørnavn": supplier_names.get(supplier_id, ""),
                    "Innkjøp eks mva": float(rounded),
                    "Transaksjoner": supplier_counts.get(supplier_id, 0),
                }
            )
        supplier_df = pandas_module.DataFrame(supplier_rows)
        if not supplier_df.empty:
            supplier_df["Innkjøp eks mva"] = (
                supplier_df["Innkjøp eks mva"].astype(float).round(2)
            )
            supplier_df = supplier_df.sort_values(
                "Innkjøp eks mva", ascending=False
            ).reset_index(drop=True)

    return customer_df, supplier_df


def compute_sales_per_customer(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    year: Optional[int] = None,
    last_period: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
) -> "pd.DataFrame":
    """Beregner netto omsetning per kunde basert på konto 1500 og mva-linjer."""

    pandas = _require_pandas()

    start_date = _ensure_date(date_from)
    end_date = _ensure_date(date_to)
    use_range = start_date is not None or end_date is not None
    if use_range:
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date
    elif year is None:
        raise ValueError("Angi enten year eller date_from/date_to.")

    totals, counts = _compute_customer_sales_map(
        root,
        ns,
        start_date=start_date,
        end_date=end_date,
        year=year,
        last_period=last_period if not use_range else None,
    )

    if not totals:
        return pandas.DataFrame(columns=["Kundenr", "Kundenavn", "Omsetning eks mva"])

    name_map = build_customer_name_map(root, ns)
    rows = []
    for customer_id, amount in totals.items():
        if amount == 0:
            continue
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rows.append(
            {
                "Kundenr": customer_id,
                "Kundenavn": name_map.get(customer_id, ""),
                "Omsetning eks mva": float(rounded),
                "Transaksjoner": counts.get(customer_id, 0),
            }
        )

    if not rows:
        return pandas.DataFrame(columns=["Kundenr", "Kundenavn", "Omsetning eks mva"])

    df = pandas.DataFrame(rows)
    df["Omsetning eks mva"] = df["Omsetning eks mva"].astype(float).round(2)
    return df.sort_values("Omsetning eks mva", ascending=False).reset_index(drop=True)


def compute_purchases_per_supplier(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    year: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
) -> "pd.DataFrame":
    """Beregner innkjøp eksklusiv mva per leverandør basert på kostnadskonti."""

    pandas = _require_pandas()

    start_date = _ensure_date(date_from)
    end_date = _ensure_date(date_to)
    use_range = start_date is not None or end_date is not None
    if use_range:
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date
    elif year is None:
        raise ValueError("Angi enten year eller date_from/date_to.")

    totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts: Dict[str, int] = defaultdict(int)

    transactions = _findall(
        root, ".//n1:GeneralLedgerEntries/n1:Journal/n1:Transaction", ns
    )
    for transaction in transactions:
        date_element = _find(transaction, "n1:TransactionDate", ns)
        tx_date = _ensure_date(date_element.text if date_element is not None else None)
        if tx_date is None:
            continue
        if use_range:
            if start_date and tx_date < start_date:
                continue
            if end_date and tx_date > end_date:
                continue
        elif year is not None and tx_date.year != year:
            continue

        supplier_id = get_tx_supplier_id(transaction, ns)
        if not supplier_id:
            continue

        lines = _findall(transaction, "n1:Line", ns)
        transaction_total = Decimal("0")
        has_cost = False
        for line in lines:
            account_element = _find(line, "n1:AccountID", ns)
            account = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account:
                continue
            if not _is_cost_account(account):
                continue
            has_cost = True
            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)
            transaction_total += debit - credit

        if has_cost:
            totals[supplier_id] += transaction_total
            counts[supplier_id] += 1

    if not totals:
        return pandas.DataFrame(
            columns=["Leverandørnr", "Leverandørnavn", "Innkjøp eks mva"]
        )

    name_map = build_supplier_name_map(root, ns)
    rows = []
    for supplier_id, amount in totals.items():
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rows.append(
            {
                "Leverandørnr": supplier_id,
                "Leverandørnavn": name_map.get(supplier_id, ""),
                "Innkjøp eks mva": float(rounded),
                "Transaksjoner": counts.get(supplier_id, 0),
            }
        )

    df = pandas.DataFrame(rows)
    df["Innkjøp eks mva"] = df["Innkjøp eks mva"].astype(float).round(2)
    return df.sort_values("Innkjøp eks mva", ascending=False).reset_index(drop=True)
