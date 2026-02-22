"""Rapporter som analyserer kunder og leverandører."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

from .customer_buckets import DESCRIPTION_BUCKET_MAP
from .entry_helpers import get_amount, get_tx_customer_id, get_tx_supplier_id
from .name_lookup import (
    build_customer_name_map,
    build_parent_map,
    build_supplier_name_map,
)
from .reporting_utils import (
    _ensure_date,
    _format_decimal,
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
    "extract_credit_notes",
    "SalesReceivableCorrelation",
    "analyze_sales_receivable_correlation",
    "ReceivablePostingAnalysis",
    "analyze_receivable_postings",
    "BankPostingAnalysis",
    "analyze_bank_postings",
    "build_aged_receivables",
]

_DESCRIPTION_BUCKET_NAMES: set[str] = set(DESCRIPTION_BUCKET_MAP)


@dataclass
class TransactionScope:
    """Innsamlingsdata for ett bilag."""

    date: Optional[date]
    voucher_description: Optional[str]
    transaction_description: Optional[str]
    period_year: Optional[int]
    period_number: Optional[int]


@dataclass
class TransactionLineAggregation:
    """Aggregerte verdier for linjer i ett bilag."""

    gross_per_customer: Dict[str, Decimal]
    vat_share_per_customer: Dict[str, Decimal]
    vat_total: Decimal
    vat_found: bool
    has_revenue_account: bool
    revenue_total: Decimal
    purchase_total: Decimal
    has_purchase: bool
    transaction_customer_id: Optional[str]
    line_summaries: List[Tuple[str, Optional[str], Decimal, Decimal]]


@dataclass
class SalesReceivableCorrelation:
    """Oppsummerer sammenhengen mellom salg og kundefordringer."""

    with_receivable_total: float
    without_receivable_total: float
    missing_sales: "pd.DataFrame"


@dataclass
class ReceivablePostingAnalysis:
    """Oppsummerer bevegelser på kundefordringer (1500)."""

    opening_balance: Optional[float]
    sales_counter_total: float
    bank_counter_total: float
    other_counter_total: float
    closing_balance: Optional[float]
    unclassified_rows: "pd.DataFrame"

    @property
    def control_total(self) -> Optional[float]:
        if self.opening_balance is None or self.closing_balance is None:
            return None
        total = (
            self.opening_balance
            + self.sales_counter_total
            + self.bank_counter_total
            + self.other_counter_total
            - self.closing_balance
        )
        return round(total, 2)


@dataclass
class BankPostingAnalysis:
    """Oppsummerer bevegelser på bankkonti med og uten motpost kundefordringer."""

    opening_balance: Optional[float]
    with_receivable_total: float
    without_receivable_total: float
    closing_balance: Optional[float]
    mismatched_rows: "pd.DataFrame"

    @property
    def control_total(self) -> Optional[float]:
        if self.opening_balance is None or self.closing_balance is None:
            return None
        total = (
            self.opening_balance
            + self.with_receivable_total
            + self.without_receivable_total
            - self.closing_balance
        )
        return round(total, 2)


@dataclass
class _OpenReceivableItem:
    """Representerer en åpen kundefordringspost før aldersfordeling."""

    tx_date: date
    amount: Decimal


def _settle_customer_receivables(
    postings: List[Tuple[date, Decimal]],
) -> List[_OpenReceivableItem]:
    """Matcher innbetalinger mot fakturaer med enkel FIFO-logikk."""

    open_items: List[_OpenReceivableItem] = []
    for tx_date, amount in sorted(postings, key=lambda row: row[0]):
        if amount > 0:
            open_items.append(_OpenReceivableItem(tx_date=tx_date, amount=amount))
            continue

        remaining_credit = abs(amount)
        for item in open_items:
            if remaining_credit <= 0:
                break
            if item.amount <= 0:
                continue
            consumed = min(item.amount, remaining_credit)
            item.amount -= consumed
            remaining_credit -= consumed

    return [item for item in open_items if item.amount > 0]


def _bucket_for_age(age_days: int) -> str:
    """Returnerer navnet på aldersintervall for en åpen post."""

    if age_days <= 30:
        return "0-30"
    if age_days <= 60:
        return "31-60"
    if age_days <= 90:
        return "61-90"
    if age_days <= 120:
        return "91-120"
    return "121+"


def build_aged_receivables(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    as_of_date: Optional[date] = None,
) -> "pd.DataFrame":
    """Bygger aldersfordelt reskontro fra SAF-T transaksjoner.

    Metoden ser på linjer på kontoklasse 15 med CustomerID og matcher
    innbetalinger mot fakturalinjer med enkel FIFO per kunde.
    """

    pd = _require_pandas()
    description_customer_map = _build_description_customer_map(root, ns)
    customer_name_map = build_customer_name_map(root, ns)
    postings_by_customer: Dict[str, List[Tuple[date, Decimal]]] = defaultdict(list)
    detected_max_date: Optional[date] = None

    for transaction in _iter_transactions(root, ns):
        scope = _build_transaction_scope(transaction, ns)
        if scope.date is None:
            continue
        tx_date = scope.date
        if detected_max_date is None or tx_date > detected_max_date:
            detected_max_date = tx_date

        lines = _findall(transaction, "n1:Line", ns)
        transaction_customer_id = _resolve_transaction_customer(
            transaction,
            ns,
            lines,
            scope,
            description_customer_map,
        )

        for line in lines:
            account_element = _find(line, "n1:AccountID", ns)
            account_text = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account_text:
                continue
            normalized_digits = _normalize_account_key(account_text)
            normalized = normalized_digits or account_text
            if not normalized.startswith("15"):
                continue

            customer_id = _extract_line_customer_id(line, ns) or transaction_customer_id
            if not customer_id:
                continue

            amount = get_amount(line, "DebitAmount", ns) - get_amount(
                line, "CreditAmount", ns
            )
            if amount == 0:
                continue
            postings_by_customer[customer_id].append((tx_date, amount))

    effective_as_of = as_of_date or detected_max_date
    if effective_as_of is None:
        return pd.DataFrame(
            columns=[
                "Kundenr",
                "Kundenavn",
                "0-30",
                "31-60",
                "61-90",
                "91-120",
                "121+",
                "Sum",
            ]
        )

    rows: List[Dict[str, float | str]] = []
    for customer_id, postings in postings_by_customer.items():
        open_items = _settle_customer_receivables(postings)
        if not open_items:
            continue

        bucket_totals: Dict[str, Decimal] = {
            "0-30": Decimal("0"),
            "31-60": Decimal("0"),
            "61-90": Decimal("0"),
            "91-120": Decimal("0"),
            "121+": Decimal("0"),
        }
        for item in open_items:
            age_days = max((effective_as_of - item.tx_date).days, 0)
            bucket = _bucket_for_age(age_days)
            bucket_totals[bucket] += item.amount

        total = sum(bucket_totals.values(), Decimal("0"))
        if total <= 0:
            continue

        rows.append(
            {
                "Kundenr": customer_id,
                "Kundenavn": customer_name_map.get(customer_id, customer_id),
                "0-30": _format_decimal(bucket_totals["0-30"]),
                "31-60": _format_decimal(bucket_totals["31-60"]),
                "61-90": _format_decimal(bucket_totals["61-90"]),
                "91-120": _format_decimal(bucket_totals["91-120"]),
                "121+": _format_decimal(bucket_totals["121+"]),
                "Sum": _format_decimal(total),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "Kundenr",
                "Kundenavn",
                "0-30",
                "31-60",
                "61-90",
                "91-120",
                "121+",
                "Sum",
            ]
        )

    dataframe = pd.DataFrame(rows)
    dataframe = dataframe.sort_values(by="Sum", ascending=False, ignore_index=True)
    return dataframe


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


def _build_transaction_scope(
    transaction: ET.Element, ns: NamespaceMap
) -> TransactionScope:
    """Henter de mest brukte feltene fra et bilag."""

    date_element = _find(transaction, "n1:TransactionDate", ns)
    tx_date = _ensure_date(date_element.text if date_element is not None else None)
    voucher_description, transaction_description = _extract_transaction_descriptions(
        transaction, ns
    )
    period_year, period_number = _extract_transaction_period(transaction, ns)
    return TransactionScope(
        date=tx_date,
        voucher_description=voucher_description,
        transaction_description=transaction_description,
        period_year=period_year,
        period_number=period_number,
    )


def _first_text(element: ET.Element, paths: Tuple[str, ...], ns: NamespaceMap) -> str:
    """Returnerer tekstinnhold fra første matchende path."""

    for path in paths:
        candidate = _find(element, path, ns)
        if candidate is not None and candidate.text:
            cleaned = _clean_text(candidate.text)
            if cleaned:
                return cleaned
    return ""


def _transaction_in_scope(
    scope: TransactionScope,
    *,
    start_date: Optional[date],
    end_date: Optional[date],
    year: Optional[int],
    last_period: Optional[int],
    use_range: bool,
) -> bool:
    """Avgjør om bilaget skal være med i analysen."""

    if use_range:
        if scope.date is None:
            return False
        if start_date and scope.date < start_date:
            return False
        if end_date and scope.date > end_date:
            return False
        return True

    if year is None:
        return False

    period_year = scope.period_year if scope.period_year is not None else None
    if period_year is None and scope.date is not None:
        period_year = scope.date.year
    if period_year is None or period_year != year:
        return False

    if last_period is None:
        return True

    period_number = scope.period_number if scope.period_number is not None else None
    if period_number is None and scope.date is not None:
        period_number = scope.date.month
    return period_number is not None and period_number <= last_period


def _resolve_transaction_customer(
    transaction: ET.Element,
    ns: NamespaceMap,
    lines: List[ET.Element],
    scope: TransactionScope,
    description_customer_map: Dict[str, str],
) -> Optional[str]:
    """Finn best mulig CustomerID for bilaget."""

    transaction_customer_id = get_tx_customer_id(transaction, ns, lines=lines)
    if transaction_customer_id:
        return transaction_customer_id
    return _lookup_description_customer(
        scope.voucher_description,
        scope.transaction_description,
        description_customer_map,
    )


def _aggregate_transaction_lines(
    transaction: ET.Element,
    lines: List[ET.Element],
    ns: NamespaceMap,
    *,
    include_suppliers: bool,
    description_customer_map: Dict[str, str],
    scope: TransactionScope,
    transaction_customer_id: Optional[str],
) -> TransactionLineAggregation:
    """Samler opp summer per bilag før fordeling av mva."""

    gross_per_customer: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    vat_share_per_customer: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    vat_total = Decimal("0")
    vat_found = False
    has_revenue_account = False
    revenue_total = Decimal("0")
    purchase_total = Decimal("0")
    has_purchase = False
    line_summaries: List[Tuple[str, Optional[str], Decimal, Decimal]] = []
    fallback_customer_id: Optional[str] = transaction_customer_id

    for line in lines:
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
                            scope.voucher_description,
                            scope.transaction_description,
                            description_customer_map,
                        )
                if fallback_customer_id is None:
                    fallback_customer_id = get_tx_customer_id(
                        transaction, ns, lines=lines
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

        if include_suppliers and normalized and _is_cost_account(normalized):
            has_purchase = True
            purchase_total += debit - credit

    return TransactionLineAggregation(
        gross_per_customer=gross_per_customer,
        vat_share_per_customer=vat_share_per_customer,
        vat_total=vat_total,
        vat_found=vat_found,
        has_revenue_account=has_revenue_account,
        revenue_total=revenue_total,
        purchase_total=purchase_total,
        has_purchase=has_purchase,
        transaction_customer_id=transaction_customer_id,
        line_summaries=line_summaries,
    )


def _apply_revenue_diff(
    gross_per_customer: Dict[str, Decimal],
    aggregation: TransactionLineAggregation,
) -> Dict[str, Decimal]:
    expected_gross_total = aggregation.revenue_total + aggregation.vat_total
    gross_sum = sum(gross_per_customer.values(), Decimal("0"))
    if aggregation.has_revenue_account and expected_gross_total != gross_sum:
        diff = expected_gross_total - gross_sum
        if diff != 0:
            target_customer: Optional[str] = aggregation.transaction_customer_id
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
    return gross_per_customer


def _prepare_gross_amounts(
    aggregation: TransactionLineAggregation,
) -> Tuple[Dict[str, Decimal], Dict[str, Decimal]]:
    gross_per_customer = {
        customer_id: amount
        for customer_id, amount in aggregation.gross_per_customer.items()
        if amount != 0
    }
    if not gross_per_customer and aggregation.transaction_customer_id:
        fallback_gross = Decimal("0")
        used_revenue_basis = False
        for normalized, normalized_digits, debit, credit in aggregation.line_summaries:
            if normalized and _is_revenue_account(normalized):
                fallback_gross += credit - debit
                used_revenue_basis = True
                continue
            if normalized_digits and normalized_digits.startswith("27"):
                fallback_gross += credit - debit
                used_revenue_basis = True
        if used_revenue_basis and fallback_gross != 0:
            gross_per_customer[aggregation.transaction_customer_id] = fallback_gross
    if not gross_per_customer:
        return {}, {}

    gross_per_customer = _apply_revenue_diff(gross_per_customer, aggregation)
    vat_share_per_customer = {
        customer_id: share
        for customer_id, share in aggregation.vat_share_per_customer.items()
        if share > 0 and customer_id in gross_per_customer
    }
    return gross_per_customer, vat_share_per_customer


def _build_share_basis(
    gross_per_customer: Dict[str, Decimal],
    vat_share_per_customer: Dict[str, Decimal],
) -> Tuple[Dict[str, Decimal], Decimal]:
    vat_share_total = sum(vat_share_per_customer.values(), Decimal("0"))
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
    return share_basis_per_customer, share_total


def _update_customer_totals(
    gross_per_customer: Dict[str, Decimal],
    share_basis_per_customer: Dict[str, Decimal],
    share_total: Decimal,
    vat_total: Decimal,
    customer_totals: Dict[str, Decimal],
    customer_counts: Dict[str, int],
) -> None:
    for customer_id, gross_amount in gross_per_customer.items():
        share_basis = share_basis_per_customer.get(customer_id, Decimal("0"))
        if share_basis == 0 or share_total == 0:
            continue
        share = share_basis / share_total
        net_amount = gross_amount - (vat_total * share)
        if net_amount == 0:
            continue
        customer_totals[customer_id] += net_amount
        customer_counts[customer_id] += 1


def _compute_customer_sales_map(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    start_date: Optional[date],
    end_date: Optional[date],
    year: Optional[int],
    last_period: Optional[int],
    include_suppliers: bool = False,
) -> Tuple[Dict[str, Decimal], Dict[str, int], Dict[str, Decimal], Dict[str, int]]:
    """Returnerer netto salg per kunde og (valgfritt) kostnader per leverandør."""

    customer_totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    customer_counts: Dict[str, int] = defaultdict(int)
    supplier_totals: Dict[str, Decimal] = (
        defaultdict(lambda: Decimal("0")) if include_suppliers else {}
    )
    supplier_counts: Dict[str, int] = defaultdict(int) if include_suppliers else {}
    use_range = start_date is not None or end_date is not None
    description_customer_map = _build_description_customer_map(root, ns)

    for transaction in _iter_transactions(root, ns):
        lines_list = list(_findall(transaction, "n1:Line", ns))
        if not lines_list:
            continue

        scope = _build_transaction_scope(transaction, ns)
        if not _transaction_in_scope(
            scope,
            start_date=start_date,
            end_date=end_date,
            year=year,
            last_period=last_period,
            use_range=use_range,
        ):
            continue

        transaction_customer_id = _resolve_transaction_customer(
            transaction,
            ns,
            lines_list,
            scope,
            description_customer_map,
        )
        aggregation = _aggregate_transaction_lines(
            transaction,
            lines_list,
            ns,
            include_suppliers=include_suppliers,
            description_customer_map=description_customer_map,
            scope=scope,
            transaction_customer_id=transaction_customer_id,
        )

        if include_suppliers and aggregation.has_purchase:
            supplier_id = get_tx_supplier_id(transaction, ns, lines=lines_list)
            if supplier_id:
                supplier_totals[supplier_id] += aggregation.purchase_total
                supplier_counts[supplier_id] += 1

        if not aggregation.vat_found and not aggregation.has_revenue_account:
            continue

        gross_per_customer, vat_share_per_customer = _prepare_gross_amounts(aggregation)
        if not gross_per_customer:
            continue

        share_basis_per_customer, share_total = _build_share_basis(
            gross_per_customer, vat_share_per_customer
        )
        if share_total == 0:
            continue

        _update_customer_totals(
            gross_per_customer,
            share_basis_per_customer,
            share_total,
            aggregation.vat_total,
            customer_totals,
            customer_counts,
        )

    return customer_totals, customer_counts, supplier_totals, supplier_counts


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

    (
        customer_totals,
        customer_counts,
        supplier_totals,
        supplier_counts,
    ) = _compute_customer_sales_map(
        root,
        ns,
        start_date=start_date,
        end_date=end_date,
        year=year,
        last_period=last_period if not use_range else None,
        include_suppliers=True,
    )

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

    totals, counts, _, _ = _compute_customer_sales_map(
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


def extract_credit_notes(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    months: Sequence[int] = tuple(range(1, 13)),
    year: Optional[int] = None,
) -> "pd.DataFrame":
    """Henter kreditnotaer i angitte måneder for 3xxx-konti gjennom året."""

    pandas = _require_pandas()
    month_filter = {month for month in months if isinstance(month, int)}
    if not month_filter:
        month_filter = set(range(1, 13))

    rows: List[Dict[str, object]] = []

    for transaction in _iter_transactions(root, ns):
        scope = _build_transaction_scope(transaction, ns)
        tx_date = scope.date
        if tx_date is None or tx_date.month not in month_filter:
            continue
        if year is not None and tx_date.year != year:
            continue

        revenue_total = Decimal("0")
        accounts: List[str] = []
        for line in _findall(transaction, "n1:Line", ns):
            account_element = _find(line, "n1:AccountID", ns)
            account_text = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account_text:
                continue

            normalized = _normalize_account_key(account_text) or account_text
            if not _is_revenue_account(normalized):
                continue

            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)
            revenue_total += credit - debit
            accounts.append(normalized)

        if revenue_total >= 0 or not accounts:
            continue

        document_number = _first_text(
            transaction,
            (
                "n1:DocumentNumber",
                "n1:SourceDocumentID",
                "n1:DocumentReference/n1:DocumentNumber",
                "n1:DocumentReference/n1:ID",
                "n1:SourceID",
            ),
            ns,
        )

        description = scope.voucher_description or scope.transaction_description
        unique_accounts = sorted(set(accounts))
        rows.append(
            {
                "Dato": tx_date,
                "Bilagsnr": document_number or "—",
                "Beskrivelse": description or "—",
                "Kontoer": ", ".join(unique_accounts) if unique_accounts else "—",
                "Beløp": float(abs(revenue_total)),
            }
        )

    if not rows:
        return pandas.DataFrame(
            columns=["Dato", "Bilagsnr", "Beskrivelse", "Kontoer", "Beløp"]
        )

    df = pandas.DataFrame(rows)
    df["Beløp"] = df["Beløp"].astype(float).round(2)
    df.sort_values("Dato", inplace=True)
    return df.reset_index(drop=True)


def analyze_sales_receivable_correlation(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    year: Optional[int] = None,
) -> SalesReceivableCorrelation:
    """Summerer salg etter om bilaget har motpost på 1500."""

    pandas = _require_pandas()
    with_receivable = Decimal("0")
    without_receivable = Decimal("0")
    missing_rows: List[Dict[str, object]] = []

    use_range = date_from is not None or date_to is not None

    for transaction in _iter_transactions(root, ns):
        scope = _build_transaction_scope(transaction, ns)
        if not _transaction_in_scope(
            scope,
            start_date=date_from,
            end_date=date_to,
            year=year,
            last_period=None,
            use_range=use_range,
        ):
            continue

        revenue_total = Decimal("0")
        has_receivable = False
        revenue_accounts: set[str] = set()
        counter_accounts: set[str] = set()

        for line in _findall(transaction, "n1:Line", ns):
            account_element = _find(line, "n1:AccountID", ns)
            account_text = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account_text:
                continue

            normalized = _normalize_account_key(account_text) or account_text
            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)

            if normalized.startswith("1500") and (debit != 0 or credit != 0):
                has_receivable = True

            if _is_revenue_account(normalized):
                delta = credit - debit
                revenue_total += delta
                if delta != 0:
                    revenue_accounts.add(normalized)
            elif debit != 0 or credit != 0:
                counter_accounts.add(normalized)

        if revenue_total == 0:
            continue

        if has_receivable:
            with_receivable += revenue_total
        else:
            without_receivable += revenue_total
            document_number = _first_text(
                transaction,
                (
                    "n1:DocumentNumber",
                    "n1:SourceDocumentID",
                    "n1:DocumentReference/n1:DocumentNumber",
                    "n1:DocumentReference/n1:ID",
                    "n1:TransactionID",
                    "n1:SourceID",
                ),
                ns,
            )
            description = scope.voucher_description or scope.transaction_description
            missing_rows.append(
                {
                    "Dato": scope.date,
                    "Bilagsnr": document_number or "—",
                    "Beskrivelse": description or "—",
                    "Kontoer": ", ".join(sorted(revenue_accounts)) or "—",
                    "Motkontoer": ", ".join(sorted(counter_accounts)) or "—",
                    "Beløp": _format_decimal(revenue_total),
                }
            )

    if missing_rows:
        missing_df = pandas.DataFrame(missing_rows)
        missing_df["Beløp"] = missing_df["Beløp"].astype(float).round(2)
        missing_df.sort_values("Dato", inplace=True)
        missing_df.reset_index(drop=True, inplace=True)
    else:
        missing_df = pandas.DataFrame(
            columns=[
                "Dato",
                "Bilagsnr",
                "Beskrivelse",
                "Kontoer",
                "Motkontoer",
                "Beløp",
            ]
        )

    return SalesReceivableCorrelation(
        with_receivable_total=_format_decimal(with_receivable),
        without_receivable_total=_format_decimal(without_receivable),
        missing_sales=missing_df,
    )


def _extract_receivable_balance(
    trial_balance: Optional["pd.DataFrame"], column: str
) -> Optional[float]:
    if trial_balance is None:
        return None
    if column not in trial_balance or "Konto_int" not in trial_balance:
        return None
    receivable_rows = trial_balance.loc[trial_balance["Konto_int"] == 1500]
    if receivable_rows.empty:
        return None
    value = receivable_rows.iloc[0].get(column)
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _is_bank_account(account: str) -> bool:
    normalized = _normalize_account_key(account) or account
    if not normalized:
        return False
    return normalized.startswith("19") or normalized.startswith("2380")


def analyze_receivable_postings(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    year: Optional[int] = None,
    trial_balance: Optional["pd.DataFrame"] = None,
) -> ReceivablePostingAnalysis:
    """Summerer bevegelser på konto 1500 fordelt på motposter."""

    pandas = _require_pandas()

    start_date = _ensure_date(date_from)
    end_date = _ensure_date(date_to)
    use_range = start_date is not None or end_date is not None

    opening_balance = _extract_receivable_balance(trial_balance, "IB_netto")
    closing_balance = _extract_receivable_balance(trial_balance, "UB_netto")

    sales_total = Decimal("0")
    bank_total = Decimal("0")
    other_total = Decimal("0")
    other_rows: List[Dict[str, object]] = []

    for transaction in _iter_transactions(root, ns):
        scope = _build_transaction_scope(transaction, ns)
        if not _transaction_in_scope(
            scope,
            start_date=start_date,
            end_date=end_date,
            year=year,
            last_period=None,
            use_range=use_range,
        ):
            continue

        receivable_lines: List[Tuple[str, Decimal]] = []
        revenue_found = False
        bank_found = False
        counter_accounts: set[str] = set()

        for line in _findall(transaction, "n1:Line", ns):
            account_element = _find(line, "n1:AccountID", ns)
            account_text = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account_text:
                continue

            normalized = _normalize_account_key(account_text) or account_text
            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)
            amount = debit - credit

            if normalized.startswith("1500"):
                if amount == 0:
                    continue
                receivable_lines.append((normalized, amount))
                continue

            if _is_revenue_account(normalized):
                revenue_found = True
            if _is_bank_account(normalized):
                bank_found = True
            if debit != 0 or credit != 0:
                counter_accounts.add(normalized)

        if not receivable_lines:
            continue

        receivable_amount = sum(
            (amount for _, amount in receivable_lines), Decimal("0")
        )
        if revenue_found:
            sales_total += receivable_amount
        elif bank_found:
            bank_total += receivable_amount
        else:
            other_total += receivable_amount
            document_number = _first_text(
                transaction,
                (
                    "n1:DocumentNumber",
                    "n1:SourceDocumentID",
                    "n1:DocumentReference/n1:DocumentNumber",
                    "n1:DocumentReference/n1:ID",
                    "n1:TransactionID",
                    "n1:SourceID",
                ),
                ns,
            )
            description = scope.voucher_description or scope.transaction_description
            receivable_accounts = sorted({account for account, _ in receivable_lines})
            other_rows.append(
                {
                    "Dato": scope.date,
                    "Bilagsnr": document_number or "—",
                    "Beskrivelse": description or "—",
                    "Kontoer": ", ".join(receivable_accounts) or "—",
                    "Motkontoer": ", ".join(sorted(counter_accounts)) or "—",
                    "Beløp": _format_decimal(receivable_amount),
                }
            )

    other_df = pandas.DataFrame(
        other_rows,
        columns=[
            "Dato",
            "Bilagsnr",
            "Beskrivelse",
            "Kontoer",
            "Motkontoer",
            "Beløp",
        ],
    )
    if not other_df.empty:
        other_df["Beløp"] = other_df["Beløp"].astype(float).round(2)
        other_df.sort_values("Dato", inplace=True)
        other_df.reset_index(drop=True, inplace=True)

    return ReceivablePostingAnalysis(
        opening_balance=opening_balance,
        sales_counter_total=_format_decimal(sales_total),
        bank_counter_total=_format_decimal(bank_total),
        other_counter_total=_format_decimal(other_total),
        closing_balance=closing_balance,
        unclassified_rows=other_df,
    )


def _extract_bank_balance(
    trial_balance: Optional["pd.DataFrame"], column: str
) -> Optional[float]:
    if trial_balance is None:
        return None
    if column not in trial_balance:
        return None

    if "Konto_int" in trial_balance:
        account_series = trial_balance["Konto_int"].astype(str)
    elif "Konto" in trial_balance:
        account_series = trial_balance["Konto"].astype(str)
    else:
        return None

    bank_rows = trial_balance.loc[
        account_series.str.startswith("19") | account_series.str.startswith("2380")
    ]
    if bank_rows.empty:
        return None

    total_value = bank_rows[column].sum()
    try:
        return round(float(total_value), 2)
    except (TypeError, ValueError):
        return None


def analyze_bank_postings(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    year: Optional[int] = None,
    trial_balance: Optional["pd.DataFrame"] = None,
) -> BankPostingAnalysis:
    """Summerer bankbevegelser fordelt på motpost kundefordringer."""

    pandas = _require_pandas()
    start_date = _ensure_date(date_from)
    end_date = _ensure_date(date_to)
    use_range = start_date is not None or end_date is not None

    opening_balance = _extract_bank_balance(trial_balance, "IB_netto")
    closing_balance = _extract_bank_balance(trial_balance, "UB_netto")

    with_receivable = Decimal("0")
    without_receivable = Decimal("0")
    mismatched_rows: List[Dict[str, object]] = []

    for transaction in _iter_transactions(root, ns):
        scope = _build_transaction_scope(transaction, ns)
        if not _transaction_in_scope(
            scope,
            start_date=start_date,
            end_date=end_date,
            year=year,
            last_period=None,
            use_range=use_range,
        ):
            continue

        bank_total = Decimal("0")
        receivable_total = Decimal("0")
        has_receivable = False
        bank_accounts: set[str] = set()
        receivable_accounts: set[str] = set()

        for line in _findall(transaction, "n1:Line", ns):
            account_element = _find(line, "n1:AccountID", ns)
            account_text = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account_text:
                continue

            normalized = _normalize_account_key(account_text) or account_text
            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)

            if normalized.startswith("1500") and (debit != 0 or credit != 0):
                has_receivable = True
                receivable_accounts.add(normalized)
                receivable_total += debit - credit

            if _is_bank_account(normalized):
                delta = debit - credit
                if delta != 0:
                    bank_total += delta
                    bank_accounts.add(normalized)

        if bank_total == 0:
            continue

        if has_receivable:
            with_receivable += bank_total

            mismatch = bank_total + receivable_total
            rounded_mismatch = mismatch.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if rounded_mismatch != 0:
                document_number = _first_text(
                    transaction,
                    (
                        "n1:DocumentNumber",
                        "n1:SourceDocumentID",
                        "n1:DocumentReference/n1:DocumentNumber",
                        "n1:DocumentReference/n1:ID",
                        "n1:TransactionID",
                        "n1:SourceID",
                    ),
                    ns,
                )
                description = scope.voucher_description or scope.transaction_description
                mismatched_rows.append(
                    {
                        "Dato": scope.date,
                        "Bilagsnr": document_number or "—",
                        "Beskrivelse": description or "—",
                        "Bank": _format_decimal(bank_total),
                        "Kundefordringer": _format_decimal(receivable_total),
                        "Differanse": _format_decimal(rounded_mismatch),
                        "Bankkontoer": ", ".join(sorted(bank_accounts)) or "—",
                        "Kundefordringskontoer": ", ".join(sorted(receivable_accounts))
                        or "—",
                    }
                )
        else:
            without_receivable += bank_total

    if mismatched_rows:
        mismatch_df = pandas.DataFrame(
            mismatched_rows,
            columns=[
                "Dato",
                "Bilagsnr",
                "Beskrivelse",
                "Bank",
                "Kundefordringer",
                "Differanse",
                "Bankkontoer",
                "Kundefordringskontoer",
            ],
        )
        mismatch_df["Bank"] = mismatch_df["Bank"].astype(float).round(2)
        mismatch_df["Kundefordringer"] = (
            mismatch_df["Kundefordringer"].astype(float).round(2)
        )
        mismatch_df["Differanse"] = mismatch_df["Differanse"].astype(float).round(2)
        mismatch_df.sort_values("Dato", inplace=True)
        mismatch_df.reset_index(drop=True, inplace=True)
    else:
        mismatch_df = pandas.DataFrame(
            columns=[
                "Dato",
                "Bilagsnr",
                "Beskrivelse",
                "Bank",
                "Kundefordringer",
                "Differanse",
                "Bankkontoer",
                "Kundefordringskontoer",
            ]
        )

    return BankPostingAnalysis(
        opening_balance=opening_balance,
        with_receivable_total=_format_decimal(with_receivable),
        without_receivable_total=_format_decimal(without_receivable),
        closing_balance=closing_balance,
        mismatched_rows=mismatch_df,
    )
