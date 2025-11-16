"""Rapporter og DataFrame-uttrekk fra SAF-T transaksjoner."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, TYPE_CHECKING

from ..helpers.lazy_imports import lazy_pandas
from .entry_stream import get_amount, get_tx_customer_id, get_tx_supplier_id
from .models import CostVoucher, VoucherLine
from .name_lookup import (
    build_customer_name_map,
    build_parent_map,
    build_supplier_name_map,
)
from .xml_helpers import _clean_text, _find, _findall, NamespaceMap

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd

__all__ = [
    "compute_customer_supplier_totals",
    "compute_sales_per_customer",
    "compute_purchases_per_supplier",
    "extract_cost_vouchers",
    "build_account_name_map",
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
        return []
    transactions: List[ET.Element] = []
    for journal in _findall(entries, "n1:Journal", ns):
        for transaction in _findall(journal, "n1:Transaction", ns):
            transactions.append(transaction)
    return transactions


def _format_decimal(value: Decimal) -> float:
    """Konverterer Decimal til float med to desimaler og bankers avrunding."""

    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _normalize_account_key(account: str) -> Optional[str]:
    """Fjerner ikke-numeriske tegn fra kontonummer for enklere oppslag."""

    digits = "".join(ch for ch in account if ch.isdigit())
    return digits or None


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

        gross_per_customer: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        vat_total = Decimal("0")
        vat_found = False
        has_revenue_account = False
        fallback_customer_id: Optional[str] = None

        for line in lines_list:
            account_element = _find(line, "n1:AccountID", ns)
            account_text = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account_text:
                continue

            normalized = _normalize_account_key(account_text) or account_text

            if _is_revenue_account(normalized):
                has_revenue_account = True
            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)

            customer_id = _extract_line_customer_id(line, ns)
            is_customer_balance_account = normalized.startswith("1")

            if normalized == "1500" or is_customer_balance_account:
                if not customer_id:
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
        if not gross_per_customer:
            continue

        gross_total = sum(gross_per_customer.values(), Decimal("0"))
        if gross_total == 0:
            continue

        for customer_id, gross_amount in gross_per_customer.items():
            share = gross_amount / gross_total
            net_amount = gross_amount - (vat_total * share)
            if net_amount == 0:
                continue
            totals[customer_id] += net_amount
            counts[customer_id] += 1

    return totals, counts


def build_account_name_map(
    root: ET.Element, ns: NamespaceMap
) -> Dict[str, Optional[str]]:
    """Bygger oppslagstabell fra kontonummer til kontonavn."""

    mapping: Dict[str, Optional[str]] = {}
    accounts_root = _find(root, "n1:MasterFiles/n1:GeneralLedgerAccounts", ns)
    if accounts_root is None:
        return mapping

    for account in _findall(accounts_root, "n1:Account", ns):
        id_element = _find(account, "n1:AccountID", ns)
        account_id = _clean_text(id_element.text if id_element is not None else None)
        if not account_id:
            continue
        name_element = _find(account, "n1:AccountDescription", ns)
        account_name = _clean_text(
            name_element.text if name_element is not None else None
        )
        mapping[account_id] = account_name
        normalized = _normalize_account_key(account_id)
        if normalized and normalized not in mapping:
            mapping[normalized] = account_name

    return mapping


def _extract_vat_code(line: ET.Element, ns: NamespaceMap) -> Optional[str]:
    """Henter mva-kode fra en bilagslinje, dersom tilgjengelig."""

    codes: List[str] = []
    for tax_info in _findall(line, "n1:TaxInformation", ns):
        code_element = _find(tax_info, "n1:TaxCode", ns)
        code = _clean_text(code_element.text if code_element is not None else None)
        if not code:
            type_element = _find(tax_info, "n1:TaxType", ns)
            code = _clean_text(type_element.text if type_element is not None else None)
        if code and code not in codes:
            codes.append(code)

    if not codes:
        return None
    return ", ".join(codes)


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
    if df.empty:
        return df
    df["Innkjøp eks mva"] = df["Innkjøp eks mva"].astype(float).round(2)
    return df.sort_values("Innkjøp eks mva", ascending=False).reset_index(drop=True)


def extract_cost_vouchers(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    year: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None,
) -> List[CostVoucher]:
    """Henter kostnadsbilag med leverandørtilknytning fra SAF-T."""

    start_date = _ensure_date(date_from)
    end_date = _ensure_date(date_to)
    use_range = start_date is not None or end_date is not None
    if not use_range and year is None:
        raise ValueError("Angi enten year eller date_from/date_to.")

    supplier_names = build_supplier_name_map(root, ns, parent_map=parent_map)
    account_names = build_account_name_map(root, ns)
    vouchers: List[CostVoucher] = []

    def _first_text(element: ET.Element, paths: Sequence[str]) -> Optional[str]:
        for path in paths:
            candidate = _find(element, path, ns)
            if candidate is None:
                continue
            text = _clean_text(candidate.text)
            if text:
                return text
        return None

    for transaction in _iter_transactions(root, ns):
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

        lines = list(_findall(transaction, "n1:Line", ns))
        if not lines:
            continue

        supplier_id = get_tx_supplier_id(transaction, ns, lines=lines)
        if not supplier_id:
            continue

        has_cost_line = False
        voucher_lines: List[VoucherLine] = []
        total = Decimal("0")

        for line in lines:
            account_element = _find(line, "n1:AccountID", ns)
            account = (
                _clean_text(
                    account_element.text if account_element is not None else None
                )
                or ""
            )
            normalized_account = _normalize_account_key(account) if account else None
            account_name = account_names.get(account) if account else None
            if account_name is None and normalized_account:
                account_name = account_names.get(normalized_account)
            description_element = _find(line, "n1:Description", ns)
            description = _clean_text(
                description_element.text if description_element is not None else None
            )
            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)
            vat_code = _extract_vat_code(line, ns)

            if _is_cost_account(account):
                has_cost_line = True
                total += debit - credit

            voucher_lines.append(
                VoucherLine(
                    account=account or "—",
                    account_name=account_name,
                    description=description,
                    vat_code=vat_code,
                    debit=_format_decimal(debit),
                    credit=_format_decimal(credit),
                )
            )

        if not has_cost_line:
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
        )
        transaction_id = _first_text(transaction, ("n1:TransactionID",))
        description = _first_text(transaction, ("n1:Description",))

        vouchers.append(
            CostVoucher(
                transaction_id=transaction_id,
                document_number=document_number,
                transaction_date=tx_date,
                supplier_id=supplier_id,
                supplier_name=supplier_names.get(supplier_id),
                description=description,
                amount=_format_decimal(total),
                lines=voucher_lines,
            )
        )

    return vouchers
