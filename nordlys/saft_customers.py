"""SAF-T verktøy for omsetning per kunde basert på hovedbok."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
import xml.etree.ElementTree as ET

import pandas as pd


def parse_saft(path: str | Path) -> Tuple[ET.ElementTree, Dict[str, str]]:
    """Leser SAF-T XML og oppdager default namespace dynamisk."""

    xml_path = Path(path)
    tree = ET.parse(xml_path)
    root = tree.getroot()
    namespace: Dict[str, str] = {}
    if root.tag.startswith("{") and "}" in root.tag:
        uri = root.tag.split("}", 1)[0][1:]
        namespace = {"n1": uri}
    return tree, namespace


def _has_namespace(ns: Dict[str, str]) -> bool:
    return bool(ns) and any(ns.values())


def _normalize_path(path: str, ns: Dict[str, str]) -> str:
    return path if _has_namespace(ns) else path.replace("n1:", "")


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


def get_tx_customer_id(transaction: ET.Element, ns: Dict[str, str]) -> Optional[str]:
    """Bestemmer kunde-ID for en transaksjon etter prioritert logikk."""

    lines = list(_findall(transaction, "n1:Line", ns))
    if not lines:
        return None

    # 1) Linje på AR-konto 15xx med CustomerID
    for line in lines:
        if _account_startswith(line, "15", ns):
            customer_id = _line_customer_id(line, ns)
            if customer_id:
                return customer_id

    # 2) Første CustomerID hvor som helst
    for line in lines:
        customer_id = _line_customer_id(line, ns)
        if customer_id:
            return customer_id

    # 3) Dimensions/CustomerID
    for line in lines:
        customer_id = _dimensions_customer_id(line, ns)
        if customer_id:
            return customer_id

    # 4) Dimensions/Analysis med type ~ kunde
    for line in lines:
        customer_id = _analysis_customer_id(line, ns)
        if customer_id:
            return customer_id

    return None


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def build_customer_name_map(root: ET.Element, ns: Dict[str, str]) -> Dict[str, str]:
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

    parent_map: Dict[ET.Element, Optional[ET.Element]] = {}
    for parent in root.iter():
        for child in parent:
            parent_map[child] = parent

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
            current = parent_map.get(current)
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
        export_df.to_csv(xlsx_path, index=False, encoding="utf-8-sig")
    return csv_path, xlsx_path


__all__ = [
    "parse_saft",
    "get_amount",
    "get_tx_customer_id",
    "build_customer_name_map",
    "compute_sales_per_customer",
    "save_outputs",
]
