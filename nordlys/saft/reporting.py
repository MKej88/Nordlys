"""Rapporter og DataFrame-uttrekk fra SAF-T transaksjoner."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
_REFERENCE_DEDUP_WINDOW_DAYS = 7


@dataclass
class _CounterpartyTransaction:
    """Liten hjelpecontainer for summeringer per kunde/leverandør."""

    party_id: str
    amount: Decimal
    date: Optional[date]
    reference: Optional[str]
    order: int


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


def _get_transaction_reference(
    transaction: ET.Element, ns: NamespaceMap
) -> Optional[str]:
    """Prøver flere felt for å finne en felles referanse for bilaget."""

    paths = (
        "n1:ReferenceNumber",
        "n1:DocumentReference/n1:ReferenceNumber",
        "n1:DocumentReference/n1:DocumentNumber",
        "n1:DocumentReference/n1:ID",
        "n1:DocumentNumber",
        "n1:SourceDocumentID",
        "n1:TransactionID",
    )
    for path in paths:
        element = _find(transaction, path, ns)
        if element is None:
            continue
        text = _clean_text(element.text)
        if text:
            return text
    return None


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


def _resolve_period(
    year: Optional[int],
    date_from: Optional[object],
    date_to: Optional[object],
) -> Tuple[Optional[date], Optional[date], bool]:
    start_date = _ensure_date(date_from)
    end_date = _ensure_date(date_to)
    use_range = start_date is not None or end_date is not None
    if use_range:
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date
    elif year is None:
        raise ValueError("Angi enten year eller date_from/date_to.")
    return start_date, end_date, use_range


def _collect_customer_transactions(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    year: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
) -> List[_CounterpartyTransaction]:
    start_date, end_date, use_range = _resolve_period(year, date_from, date_to)
    transactions: List[_CounterpartyTransaction] = []
    order = 0

    for transaction in _iter_transactions(root, ns):
        lines_list = list(_findall(transaction, "n1:Line", ns))
        if not lines_list:
            continue

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

        customer_id = get_tx_customer_id(transaction, ns, lines=lines_list)
        if not customer_id:
            continue

        transaction_total = Decimal("0")
        has_income = False
        for line in lines_list:
            account_element = _find(line, "n1:AccountID", ns)
            account = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account:
                continue
            digits = "".join(ch for ch in account if ch.isdigit())
            normalized = digits or account
            if not normalized.startswith("3"):
                continue
            has_income = True
            credit = get_amount(line, "CreditAmount", ns)
            debit = get_amount(line, "DebitAmount", ns)
            transaction_total += credit - debit

        if not has_income:
            continue

        transactions.append(
            _CounterpartyTransaction(
                party_id=customer_id,
                amount=transaction_total,
                date=tx_date,
                reference=_get_transaction_reference(transaction, ns),
                order=order,
            )
        )
        order += 1

    return transactions


def _collect_supplier_transactions(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    year: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
) -> List[_CounterpartyTransaction]:
    start_date, end_date, use_range = _resolve_period(year, date_from, date_to)
    transactions: List[_CounterpartyTransaction] = []
    order = 0

    for transaction in _iter_transactions(root, ns):
        lines_list = list(_findall(transaction, "n1:Line", ns))
        if not lines_list:
            continue

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

        supplier_id = get_tx_supplier_id(transaction, ns, lines=lines_list)
        if not supplier_id:
            continue

        transaction_total = Decimal("0")
        has_cost = False
        for line in lines_list:
            account_element = _find(line, "n1:AccountID", ns)
            account = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account or not _is_cost_account(account):
                continue
            has_cost = True
            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)
            transaction_total += debit - credit

        if not has_cost:
            continue

        transactions.append(
            _CounterpartyTransaction(
                party_id=supplier_id,
                amount=transaction_total,
                date=tx_date,
                reference=_get_transaction_reference(transaction, ns),
                order=order,
            )
        )
        order += 1

    return transactions


def _deduplicate_by_reference(
    transactions: List[_CounterpartyTransaction],
) -> List[_CounterpartyTransaction]:
    grouped: Dict[Tuple[str, str, int], List[_CounterpartyTransaction]] = defaultdict(
        list
    )
    unique: List[_CounterpartyTransaction] = []

    for transaction in transactions:
        if transaction.reference:
            grouped[
                (
                    transaction.party_id,
                    transaction.reference,
                    _amount_sign(transaction.amount),
                )
            ].append(transaction)
        else:
            unique.append(transaction)

    for group in grouped.values():
        if len(group) == 1:
            unique.append(group[0])
            continue
        unique.extend(_collapse_reference_group(group))

    return unique


def _collapse_reference_group(
    group: List[_CounterpartyTransaction],
) -> List[_CounterpartyTransaction]:
    if len(group) <= 1:
        return group

    sorted_group = sorted(
        group,
        key=lambda tx: (
            tx.date is None,
            tx.date or date.min,
            tx.order,
        ),
    )

    collapsed: List[List[_CounterpartyTransaction]] = []
    current_bucket: List[_CounterpartyTransaction] = []

    for transaction in sorted_group:
        if not current_bucket:
            current_bucket.append(transaction)
            continue

        previous = current_bucket[-1]
        if _dates_within_dedup_window(previous.date, transaction.date):
            current_bucket.append(transaction)
            continue

        collapsed.append(current_bucket)
        current_bucket = [transaction]

    if current_bucket:
        collapsed.append(current_bucket)

    return [_pick_latest_record(bucket) for bucket in collapsed]


def _amount_sign(amount: Decimal) -> int:
    if amount > 0:
        return 1
    if amount < 0:
        return -1
    return 0


def _dates_within_dedup_window(
    previous: Optional[date],
    current: Optional[date],
) -> bool:
    if previous is None or current is None:
        return True
    return (current - previous) <= timedelta(days=_REFERENCE_DEDUP_WINDOW_DAYS)


def _pick_latest_record(
    group: List[_CounterpartyTransaction],
) -> _CounterpartyTransaction:
    base_date = date.min
    return max(
        group,
        key=lambda tx: (
            tx.date or base_date,
            tx.order,
            abs(tx.amount),
        ),
    )


def compute_customer_supplier_totals(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    year: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None,
) -> Tuple["pd.DataFrame", "pd.DataFrame"]:
    """Beregner kundesalg og leverandørkjøp i ett pass gjennom transaksjonene."""

    pandas = _require_pandas()

    customer_transactions = _deduplicate_by_reference(
        _collect_customer_transactions(
            root, ns, year=year, date_from=date_from, date_to=date_to
        )
    )
    supplier_transactions = _deduplicate_by_reference(
        _collect_supplier_transactions(
            root, ns, year=year, date_from=date_from, date_to=date_to
        )
    )

    customer_totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    customer_counts: Dict[str, int] = defaultdict(int)
    supplier_totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    supplier_counts: Dict[str, int] = defaultdict(int)

    for transaction in customer_transactions:
        customer_totals[transaction.party_id] += transaction.amount
        customer_counts[transaction.party_id] += 1

    for transaction in supplier_transactions:
        supplier_totals[transaction.party_id] += transaction.amount
        supplier_counts[transaction.party_id] += 1

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
            rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            customer_rows.append(
                {
                    "Kundenr": customer_id,
                    "Kundenavn": customer_names.get(customer_id, ""),
                    "Omsetning eks mva": float(rounded),
                    "Transaksjoner": customer_counts.get(customer_id, 0),
                }
            )
        customer_df = pandas_module.DataFrame(customer_rows)
        if not customer_df.empty:
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
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
) -> "pd.DataFrame":
    """Beregner omsetning eksklusiv mva per kunde basert på alle 3xxx-konti."""

    pandas = _require_pandas()

    transactions = _deduplicate_by_reference(
        _collect_customer_transactions(
            root, ns, year=year, date_from=date_from, date_to=date_to
        )
    )
    if not transactions:
        return pandas.DataFrame(columns=["Kundenr", "Kundenavn", "Omsetning eks mva"])

    totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts: Dict[str, int] = defaultdict(int)

    for transaction in transactions:
        totals[transaction.party_id] += transaction.amount
        counts[transaction.party_id] += 1

    name_map = build_customer_name_map(root, ns)
    rows = []
    for customer_id, amount in totals.items():
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rows.append(
            {
                "Kundenr": customer_id,
                "Kundenavn": name_map.get(customer_id, ""),
                "Omsetning eks mva": float(rounded),
                "Transaksjoner": counts.get(customer_id, 0),
            }
        )

    df = pandas.DataFrame(rows)
    if df.empty:
        return df
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

    transactions = _deduplicate_by_reference(
        _collect_supplier_transactions(
            root, ns, year=year, date_from=date_from, date_to=date_to
        )
    )
    if not transactions:
        return pandas.DataFrame(
            columns=["Leverandørnr", "Leverandørnavn", "Innkjøp eks mva"]
        )

    totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts: Dict[str, int] = defaultdict(int)

    for transaction in transactions:
        totals[transaction.party_id] += transaction.amount
        counts[transaction.party_id] += 1

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
