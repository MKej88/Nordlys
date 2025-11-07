"""SAF-T verktøy for kunde- og leverandøranalyse av hovedbok med eksportfunksjoner."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import numbers
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

import pandas as pd


_NS_FLAG_KEY = "__has_namespace__"
_NS_CACHE_KEY = "__plain_cache__"


def parse_saft(path: str | Path) -> Tuple[ET.ElementTree, Dict[str, str]]:
    """Leser SAF-T XML og oppdager default namespace dynamisk."""

    xml_path = Path(path)
    tree = ET.parse(xml_path)
    root = tree.getroot()
    namespace: Dict[str, str] = {"n1": ""}
    has_namespace = False
    if root.tag.startswith("{") and "}" in root.tag:
        uri = root.tag.split("}", 1)[0][1:]
        namespace["n1"] = uri
        has_namespace = bool(uri)
    else:
        namespace.pop("n1")

    namespace[_NS_FLAG_KEY] = has_namespace
    namespace[_NS_CACHE_KEY] = {}
    return tree, namespace


def _has_namespace(ns: Dict[str, str]) -> bool:
    flag = ns.get(_NS_FLAG_KEY)
    if isinstance(flag, bool):
        return flag
    # Fallback dersom parse_saft ikke har satt flagget (bakoverkompatibilitet i tester)
    return bool({k: v for k, v in ns.items() if k not in {_NS_FLAG_KEY, _NS_CACHE_KEY}})


def _normalize_path(path: str, ns: Dict[str, str]) -> str:
    if _has_namespace(ns):
        return path

    cache = ns.get(_NS_CACHE_KEY)
    if isinstance(cache, dict):
        cached = cache.get(path)
        if cached is not None:
            return cached

    normalized = path.replace("n1:", "")

    if isinstance(cache, dict):
        cache[path] = normalized
    else:
        ns[_NS_CACHE_KEY] = {path: normalized}
    return normalized


def _find(element: ET.Element, path: str, ns: Dict[str, str]) -> Optional[ET.Element]:
    normalized = _normalize_path(path, ns)
    if _has_namespace(ns):
        return element.find(normalized, ns)
    return element.find(normalized)


def _findall(element: ET.Element, path: str, ns: Dict[str, str]) -> Iterable[ET.Element]:
    normalized = _normalize_path(path, ns)
    if _has_namespace(ns):
        return element.findall(normalized, ns)
    return element.findall(normalized)


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _to_decimal(value: Optional[str]) -> Decimal:
    if value is None:
        return Decimal("0")
    cleaned = value.replace("\xa0", "").replace(" ", "").strip()
    if not cleaned:
        return Decimal("0")
    if cleaned.count(",") == 1 and cleaned.count(".") == 0:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def get_amount(line: ET.Element, which: str, ns: Dict[str, str]) -> Decimal:
    """Returnerer beløp fra DebitAmount/CreditAmount med støtte for nestet Amount."""

    element = _find(line, f"n1:{which}", ns)
    if element is None:
        return Decimal("0")
    text_value = _clean_text(element.text)
    if text_value is not None:
        return _to_decimal(text_value)
    nested = _find(element, "n1:Amount", ns)
    if nested is not None:
        nested_text = _clean_text(nested.text)
        if nested_text is not None:
            return _to_decimal(nested_text)
    return Decimal("0")


def _account_startswith(line: ET.Element, prefix: str, ns: Dict[str, str]) -> bool:
    element = _find(line, "n1:AccountID", ns)
    account = _clean_text(element.text if element is not None else None)
    if not account:
        return False
    digits = "".join(ch for ch in account if ch.isdigit())
    if digits:
        return digits.startswith(prefix)
    return account.startswith(prefix)


def _line_customer_id(line: ET.Element, ns: Dict[str, str]) -> Optional[str]:
    element = _find(line, "n1:CustomerID", ns)
    return _clean_text(element.text if element is not None else None)


def _dimensions_customer_id(line: ET.Element, ns: Dict[str, str]) -> Optional[str]:
    element = _find(line, "n1:Dimensions/n1:CustomerID", ns)
    return _clean_text(element.text if element is not None else None)


def _analysis_customer_id(line: ET.Element, ns: Dict[str, str]) -> Optional[str]:
    for analysis in _findall(line, "n1:Dimensions/n1:Analysis", ns):
        type_element = _find(analysis, "n1:Type", ns)
        type_text = _clean_text(type_element.text if type_element is not None else None)
        if not type_text:
            continue
        lower = type_text.lower()
        if not any(keyword in lower for keyword in ("customer", "kunde", "cust")):
            continue
        id_element = _find(analysis, "n1:ID", ns)
        identifier = _clean_text(id_element.text if id_element is not None else None)
        if identifier:
            return identifier
    return None


def _line_supplier_id(line: ET.Element, ns: Dict[str, str]) -> Optional[str]:
    for tag in ("n1:SupplierID", "n1:SupplierAccountID"):
        element = _find(line, tag, ns)
        identifier = _clean_text(element.text if element is not None else None)
        if identifier:
            return identifier
    supplier_element = _find(line, "n1:Supplier", ns)
    if supplier_element is not None:
        nested = _find(supplier_element, "n1:SupplierID", ns)
        if nested is not None:
            identifier = _clean_text(nested.text)
            if identifier:
                return identifier
    return None


def _dimensions_supplier_id(line: ET.Element, ns: Dict[str, str]) -> Optional[str]:
    element = _find(line, "n1:Dimensions/n1:SupplierID", ns)
    return _clean_text(element.text if element is not None else None)


def _analysis_supplier_id(line: ET.Element, ns: Dict[str, str]) -> Optional[str]:
    for analysis in _findall(line, "n1:Dimensions/n1:Analysis", ns):
        type_element = _find(analysis, "n1:Type", ns)
        type_text = _clean_text(type_element.text if type_element is not None else None)
        if not type_text:
            continue
        lower = type_text.lower()
        if not any(keyword in lower for keyword in ("supplier", "leverand", "supp")):
            continue
        id_element = _find(analysis, "n1:ID", ns)
        identifier = _clean_text(id_element.text if id_element is not None else None)
        if identifier:
            return identifier
    return None


def get_tx_customer_id(
    transaction: ET.Element,
    ns: Dict[str, str],
    *,
    lines: Optional[Iterable[ET.Element]] = None,
) -> Optional[str]:
    """Bestemmer kunde-ID for en transaksjon etter prioritert logikk."""

    if lines is None:
        lines_seq = list(_findall(transaction, "n1:Line", ns))
    elif isinstance(lines, list):
        lines_seq = lines
    else:
        lines_seq = list(lines)

    if not lines_seq:
        return None

    first_customer_id: Optional[str] = None
    first_dimensions_id: Optional[str] = None
    first_analysis_id: Optional[str] = None

    have_all_non_priority_ids = False

    for line in lines_seq:
        line_customer_id: Optional[str] = None

        if _account_startswith(line, "15", ns):
            line_customer_id = _line_customer_id(line, ns)
            if line_customer_id:
                return line_customer_id

        if have_all_non_priority_ids:
            continue

        if first_customer_id is None:
            if line_customer_id is None:
                line_customer_id = _line_customer_id(line, ns)
            if line_customer_id:
                first_customer_id = line_customer_id

        if first_dimensions_id is None:
            customer_id = _dimensions_customer_id(line, ns)
            if customer_id:
                first_dimensions_id = customer_id

        if first_analysis_id is None:
            customer_id = _analysis_customer_id(line, ns)
            if customer_id:
                first_analysis_id = customer_id

        have_all_non_priority_ids = (
            first_customer_id is not None
            and first_dimensions_id is not None
            and first_analysis_id is not None
        )

    if first_customer_id:
        return first_customer_id
    if first_dimensions_id:
        return first_dimensions_id
    if first_analysis_id:
        return first_analysis_id

    return None


def get_tx_supplier_id(
    transaction: ET.Element,
    ns: Dict[str, str],
    *,
    lines: Optional[Iterable[ET.Element]] = None,
) -> Optional[str]:
    """Bestemmer leverandør-ID for en transaksjon etter prioritert logikk."""

    if lines is None:
        lines_seq = list(_findall(transaction, "n1:Line", ns))
    elif isinstance(lines, list):
        lines_seq = lines
    else:
        lines_seq = list(lines)

    if not lines_seq:
        return None

    first_supplier_id: Optional[str] = None
    first_dimensions_id: Optional[str] = None
    first_analysis_id: Optional[str] = None

    have_all_non_priority_ids = False

    for line in lines_seq:
        line_supplier_id: Optional[str] = None

        if _account_startswith(line, "24", ns):
            line_supplier_id = _line_supplier_id(line, ns)
            if line_supplier_id:
                return line_supplier_id

        if have_all_non_priority_ids:
            continue

        if first_supplier_id is None:
            if line_supplier_id is None:
                line_supplier_id = _line_supplier_id(line, ns)
            if line_supplier_id:
                first_supplier_id = line_supplier_id

        if first_dimensions_id is None:
            supplier_id = _dimensions_supplier_id(line, ns)
            if supplier_id:
                first_dimensions_id = supplier_id

        if first_analysis_id is None:
            supplier_id = _analysis_supplier_id(line, ns)
            if supplier_id:
                first_analysis_id = supplier_id

        have_all_non_priority_ids = (
            first_supplier_id is not None
            and first_dimensions_id is not None
            and first_analysis_id is not None
        )

    if first_supplier_id:
        return first_supplier_id
    if first_dimensions_id:
        return first_dimensions_id
    if first_analysis_id:
        return first_analysis_id

    supplier_info = _find(transaction, "n1:SupplierInfo/n1:SupplierID", ns)
    if supplier_info is not None:
        supplier_id = _clean_text(supplier_info.text)
        if supplier_id:
            return supplier_id

    return None


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _build_parent_map(root: ET.Element) -> Dict[ET.Element, Optional[ET.Element]]:
    parent_map: Dict[ET.Element, Optional[ET.Element]] = {}
    for parent in root.iter():
        for child in parent:
            parent_map[child] = parent
    return parent_map


def build_customer_name_map(
    root: ET.Element,
    ns: Dict[str, str],
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

    lookup_map = parent_map if parent_map is not None else _build_parent_map(root)

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
    ns: Dict[str, str],
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

    lookup_map = parent_map if parent_map is not None else _build_parent_map(root)

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


def _iter_transactions(root: ET.Element, ns: Dict[str, str]) -> Iterable[ET.Element]:
    entries = _find(root, "n1:GeneralLedgerEntries", ns)
    if entries is None:
        return []
    for journal in _findall(entries, "n1:Journal", ns):
        for transaction in _findall(journal, "n1:Transaction", ns):
            yield transaction


def compute_customer_supplier_totals(
    root: ET.Element,
    ns: Dict[str, str],
    *,
    year: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Beregner kundesalg og leverandørkjøp i ett pass gjennom SAF-T-transaksjonene."""

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
            account_text = _clean_text(account_element.text if account_element is not None else None)
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

    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None
    if customer_totals or supplier_totals:
        parent_map = _build_parent_map(root)

    if not customer_totals:
        customer_df = pd.DataFrame(columns=["Kundenr", "Kundenavn", "Omsetning eks mva"])
    else:
        customer_names = build_customer_name_map(root, ns, parent_map=parent_map)
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
        customer_df = pd.DataFrame(customer_rows)
        if not customer_df.empty:
            customer_df["Omsetning eks mva"] = customer_df["Omsetning eks mva"].astype(float).round(2)
            customer_df = customer_df.sort_values("Omsetning eks mva", ascending=False).reset_index(drop=True)

    if not supplier_totals:
        supplier_df = pd.DataFrame(columns=["Leverandørnr", "Leverandørnavn", "Innkjøp eks mva"])
    else:
        supplier_names = build_supplier_name_map(root, ns, parent_map=parent_map)
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
        supplier_df = pd.DataFrame(supplier_rows)
        if not supplier_df.empty:
            supplier_df["Innkjøp eks mva"] = supplier_df["Innkjøp eks mva"].astype(float).round(2)
            supplier_df = supplier_df.sort_values("Innkjøp eks mva", ascending=False).reset_index(drop=True)

    return customer_df, supplier_df


def compute_sales_per_customer(
    root: ET.Element,
    ns: Dict[str, str],
    *,
    year: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
) -> pd.DataFrame:
    """Beregner omsetning eksklusiv mva per kunde basert på alle 3xxx-konti."""

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

    transactions = _findall(root, ".//n1:GeneralLedgerEntries/n1:Journal/n1:Transaction", ns)
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
            account = _clean_text(account_element.text if account_element is not None else None)
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
        return pd.DataFrame(columns=["Kundenr", "Kundenavn", "Omsetning eks mva"])

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

    df = pd.DataFrame(rows)
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
    ns: Dict[str, str],
    *,
    year: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
) -> pd.DataFrame:
    """Beregner innkjøp eksklusiv mva per leverandør basert på kostnadskonti."""

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

    transactions = _findall(root, ".//n1:GeneralLedgerEntries/n1:Journal/n1:Transaction", ns)
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
            account = _clean_text(account_element.text if account_element is not None else None)
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
        return pd.DataFrame(columns=["Leverandørnr", "Leverandørnavn", "Innkjøp eks mva"])

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

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["Innkjøp eks mva"] = df["Innkjøp eks mva"].astype(float).round(2)
    df = df.sort_values("Innkjøp eks mva", ascending=False).reset_index(drop=True)
    return df


def save_outputs(
    df: pd.DataFrame,
    base_path: str | Path,
    year: int | str,
    tag: str = "alle_3xxx",
) -> Tuple[Path, Path]:
    """Lagrer DataFrame til CSV (UTF-8-BOM) og XLSX."""

    output_dir = Path(base_path)
    if output_dir.is_file():
        output_dir = output_dir.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    year_text = str(year)
    csv_path = output_dir / f"salg_per_kunde_eks_mva_{year_text}_{tag}.csv"
    xlsx_path = output_dir / f"salg_per_kunde_eks_mva_{year_text}_{tag}.xlsx"

    export_df = df.copy()
    export_df["Omsetning eks mva"] = export_df["Omsetning eks mva"].astype(float).round(2)
    export_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    try:
        export_df.to_excel(xlsx_path, index=False)
    except ModuleNotFoundError:
        try:
            import xlsxwriter  # type: ignore  # noqa: F401
        except ModuleNotFoundError:
            _write_basic_xlsx(export_df, xlsx_path)
            return csv_path, xlsx_path
        with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
            export_df.to_excel(writer, index=False)
    return csv_path, xlsx_path


def _excel_column_letter(index: int) -> str:
    """Konverterer 1-basert kolonneindeks til Excel-kolonnebokstaver."""

    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result or "A"


def _write_basic_xlsx(df: pd.DataFrame, path: Path) -> None:
    """Skriver en minimalistisk XLSX-fil uten eksterne avhengigheter."""

    path = Path(path)

    def build_cell(row_index: int, col_index: int, value: object) -> Optional[str]:
        if pd.isna(value):
            return None
        cell_ref = f"{_excel_column_letter(col_index)}{row_index}"
        if isinstance(value, bool):
            return f'<c r="{cell_ref}" t="b"><v>{int(value)}</v></c>'
        if isinstance(value, Decimal):
            return f'<c r="{cell_ref}"><v>{value}</v></c>'
        if isinstance(value, numbers.Integral):
            return f'<c r="{cell_ref}"><v>{int(value)}</v></c>'
        if isinstance(value, numbers.Real):
            return f'<c r="{cell_ref}"><v>{value}</v></c>'
        text = escape(str(value))
        return f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>'

    def build_header(row_index: int) -> str:
        cells = [
            f'<c r="{_excel_column_letter(col)}{row_index}" t="inlineStr"><is><t>{escape(str(header))}</t></is></c>'
            for col, header in enumerate(df.columns, start=1)
        ]
        return f'<row r="{row_index}">' + "".join(cells) + "</row>"

    def build_body(start_row: int) -> str:
        rows = []
        row_number = start_row
        for record in df.itertuples(index=False, name=None):
            cells = []
            for col_index, value in enumerate(record, start=1):
                cell = build_cell(row_number, col_index, value)
                if cell:
                    cells.append(cell)
            rows.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
            row_number += 1
        return "".join(rows)

    header_xml = build_header(1)
    body_xml = build_body(2)

    sheet_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        "<sheetData>"
        f"{header_xml}{body_xml}"
        "</sheetData>"
        "</worksheet>"
    )

    content_types_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>"
        "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
        "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>"
        "</Types>"
    )

    rels_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>"
        "</Relationships>"
    )

    workbook_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        "<sheets>"
        "<sheet name=\"Sheet1\" sheetId=\"1\" r:id=\"rId1\"/>"
        "</sheets>"
        "</workbook>"
    )

    workbook_rels_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>"
        "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
        "</Relationships>"
    )

    styles_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        "<fonts count=\"1\"><font/></fonts>"
        "<fills count=\"1\"><fill><patternFill patternType=\"none\"/></fill></fills>"
        "<borders count=\"1\"><border/></borders>"
        "<cellStyleXfs count=\"1\"><xf/></cellStyleXfs>"
        "<cellXfs count=\"1\"><xf xfId=\"0\"/></cellXfs>"
        "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>"
        "</styleSheet>"
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/styles.xml", styles_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


__all__ = [
    "parse_saft",
    "get_amount",
    "get_tx_customer_id",
    "get_tx_supplier_id",
    "build_customer_name_map",
    "build_supplier_name_map",
    "compute_customer_supplier_totals",
    "compute_sales_per_customer",
    "compute_purchases_per_supplier",
    "save_outputs",
]
