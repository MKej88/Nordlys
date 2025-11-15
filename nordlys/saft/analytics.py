"""Beregninger og analyser for SAF-T kunde- og leverandørdata."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, TYPE_CHECKING

from ..helpers.lazy_imports import lazy_pandas
from .models import CostVoucher, VoucherLine
from .parsing import (
    _clean_text,
    _find,
    _findall,
    _local_name,
    get_amount,
    get_tx_customer_id,
    get_tx_supplier_id,
    NamespaceMap,
)

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

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


def build_parent_map(root: ET.Element) -> Dict[ET.Element, Optional[ET.Element]]:
    """Bygger et oppslag fra barn til forelder for hele SAF-T-treet."""

    parent_map: Dict[ET.Element, Optional[ET.Element]] = {}
    for parent in root.iter():
        for child in parent:
            parent_map[child] = parent
    return parent_map


def build_customer_name_map(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None,
) -> Dict[str, str]:
    """Bygger oppslag fra CustomerID til navn med fallback når masterfil mangler."""

    names: Dict[str, str] = {}
    for customer in _findall(root, ".//n1:MasterFiles/n1:Customer", ns):
        cid_element = _find(customer, "n1:CustomerID", ns)
        cid = _clean_text(cid_element.text if cid_element is not None else None)
        name_element = _find(customer, "n1:Name", ns)
        if name_element is None:
            name_element = _find(customer, "n1:CompanyName", ns)
        if name_element is None:
            contact = _find(customer, "n1:Contact", ns)
            if contact is not None:
                name_element = _find(contact, "n1:Name", ns)
                if name_element is None:
                    name_element = _find(contact, "n1:ContactName", ns)
        name = _clean_text(name_element.text if name_element is not None else None)
        if cid and name and cid not in names:
            names[cid] = name

    lookup_map = parent_map if parent_map is not None else build_parent_map(root)

    def lookup_name(node: ET.Element) -> Optional[str]:
        current: Optional[ET.Element] = node
        visited = set()
        while current is not None and current not in visited:
            visited.add(current)
            tag_name = _local_name(current.tag).lower()
            if tag_name == "name":
                text = _clean_text(current.text)
                if text:
                    return text
            for child in current:
                if _local_name(child.tag).lower() == "name":
                    text = _clean_text(child.text)
                    if text:
                        return text
            current = lookup_map.get(current)
        return None

    for element in root.iter():
        if _local_name(element.tag) != "CustomerID":
            continue
        cid = _clean_text(element.text)
        if not cid or cid in names:
            continue
        name = lookup_name(element)
        if name:
            names[cid] = name

    return names


def build_supplier_name_map(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None,
) -> Dict[str, str]:
    """Bygger oppslag fra SupplierID til navn med fallback når masterfil mangler."""

    names: Dict[str, str] = {}
    for supplier in _findall(root, ".//n1:MasterFiles/n1:Supplier", ns):
        sid_element = _find(supplier, "n1:SupplierID", ns)
        sid = _clean_text(sid_element.text if sid_element is not None else None)
        name_element: Optional[ET.Element] = None
        for path in ("n1:SupplierName", "n1:Name", "n1:CompanyName"):
            candidate = _find(supplier, path, ns)
            if candidate is not None:
                name_element = candidate
                break
        if name_element is None:
            contact = _find(supplier, "n1:Contact", ns)
            if contact is not None:
                for path in ("n1:Name", "n1:ContactName"):
                    candidate = _find(contact, path, ns)
                    if candidate is not None:
                        name_element = candidate
                        break
        name = _clean_text(name_element.text if name_element is not None else None)
        if sid and name and sid not in names:
            names[sid] = name

    lookup_map = parent_map if parent_map is not None else build_parent_map(root)

    def lookup_name(node: ET.Element) -> Optional[str]:
        current: Optional[ET.Element] = node
        visited = set()
        while current is not None and current not in visited:
            visited.add(current)
            tag_name = _local_name(current.tag).lower()
            if tag_name == "name" or tag_name == "suppliername":
                text = _clean_text(current.text)
                if text:
                    return text
            for child in current:
                child_tag = _local_name(child.tag).lower()
                if child_tag in {"name", "suppliername"}:
                    text = _clean_text(child.text)
                    if text:
                        return text
            current = lookup_map.get(current)
        return None

    for element in root.iter():
        if _local_name(element.tag) != "SupplierID":
            continue
        sid = _clean_text(element.text)
        if not sid or sid in names:
            continue
        name = lookup_name(element)
        if name:
            names[sid] = name

    return names


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
        return
    for journal in _findall(entries, "n1:Journal", ns):
        for transaction in _findall(journal, "n1:Transaction", ns):
            yield transaction


def _format_decimal(value: Decimal) -> float:
    """Konverterer Decimal til float med to desimaler og bankers avrunding."""

    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _normalize_account_key(account: str) -> Optional[str]:
    """Fjerner ikke-numeriske tegn fra kontonummer for enklere oppslag."""

    digits = "".join(ch for ch in account if ch.isdigit())
    return digits or None


def build_account_name_map(
    root: ET.Element, ns: NamespaceMap
) -> Dict[str, Optional[str]]:
    """Bygger oppslagstabell fra kontonummer til kontonavn."""

    accounts_root = _find(root, "n1:MasterFiles/n1:GeneralLedgerAccounts", ns)
    mapping: Dict[str, Optional[str]] = {}
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

    customer_totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    customer_counts: Dict[str, int] = defaultdict(int)
    supplier_totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    supplier_counts: Dict[str, int] = defaultdict(int)

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

        sale_total = Decimal("0")
        purchase_total = Decimal("0")
        has_income = False
        has_purchase = False

        for line in lines_list:
            account_element = _find(line, "n1:AccountID", ns)
            account_text = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not account_text:
                continue

            digits = "".join(ch for ch in account_text if ch.isdigit())
            normalized = digits or account_text
            credit = get_amount(line, "CreditAmount", ns)
            debit = get_amount(line, "DebitAmount", ns)

            if normalized.startswith("3"):
                has_income = True
                sale_total += credit - debit

            if _is_cost_account(account_text):
                has_purchase = True
                purchase_total += debit - credit

        if has_income:
            customer_id = get_tx_customer_id(transaction, ns, lines=lines_list)
            if customer_id:
                customer_totals[customer_id] += sale_total
                customer_counts[customer_id] += 1

        if has_purchase:
            supplier_id = get_tx_supplier_id(transaction, ns, lines=lines_list)
            if supplier_id:
                supplier_totals[supplier_id] += purchase_total
                supplier_counts[supplier_id] += 1

    lookup_map = parent_map
    if (customer_totals or supplier_totals) and lookup_map is None:
        lookup_map = build_parent_map(root)

    if not customer_totals:
        customer_df = pandas.DataFrame(
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
        customer_df = pandas.DataFrame(customer_rows)
        if not customer_df.empty:
            customer_df["Omsetning eks mva"] = (
                customer_df["Omsetning eks mva"].astype(float).round(2)
            )
            customer_df = customer_df.sort_values(
                "Omsetning eks mva", ascending=False
            ).reset_index(drop=True)

    if not supplier_totals:
        supplier_df = pandas.DataFrame(
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
        supplier_df = pandas.DataFrame(supplier_rows)
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

        customer_id = get_tx_customer_id(transaction, ns)
        if not customer_id:
            continue

        lines = _findall(transaction, "n1:Line", ns)
        transaction_total = Decimal("0")
        has_income = False
        for line in lines:
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

        if has_income:
            totals[customer_id] += transaction_total
            counts[customer_id] += 1

    if not totals:
        return pandas.DataFrame(columns=["Kundenr", "Kundenavn", "Omsetning eks mva"])

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
    df = df.sort_values("Omsetning eks mva", ascending=False).reset_index(drop=True)
    return df


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
        has_purchase = False
        for line in lines:
            account_element = _find(line, "n1:AccountID", ns)
            account = _clean_text(
                account_element.text if account_element is not None else None
            )
            if not _is_cost_account(account or ""):
                continue
            has_purchase = True
            debit = get_amount(line, "DebitAmount", ns)
            credit = get_amount(line, "CreditAmount", ns)
            transaction_total += debit - credit

        if has_purchase:
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
    df = df.sort_values("Innkjøp eks mva", ascending=False).reset_index(drop=True)
    return df


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


__all__ = [
    "build_parent_map",
    "build_customer_name_map",
    "build_supplier_name_map",
    "compute_customer_supplier_totals",
    "compute_sales_per_customer",
    "compute_purchases_per_supplier",
    "build_account_name_map",
    "extract_cost_vouchers",
]
