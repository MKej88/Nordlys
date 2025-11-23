"""Hjelpefunksjoner for beløp og kunde-/leverandør-IDer i SAF-T."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Optional

from .xml_helpers import _clean_text, _find, _findall, NamespaceMap

__all__ = [
    "get_amount",
    "get_tx_customer_id",
    "get_tx_supplier_id",
    "_parse_amount_element",
]


def _to_decimal(value: str) -> Decimal:
    text = "".join(ch for ch in value if not ch.isspace())
    if not text:
        return Decimal("0")
    if text.count(",") == 1 and text.count(".") == 0:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Ugyldig tallverdi i SAF-T filen: {value!r}") from exc


def get_amount(line: ET.Element, which: str, ns: NamespaceMap) -> Decimal:
    """Henter debet/kredit beløp fra en linje med støtte for nested Amount."""

    element = _find(line, f"n1:{which}", ns)
    if element is None:
        return Decimal("0")
    text = _clean_text(element.text)
    if text is not None:
        return _to_decimal(text)
    amount_element = _find(element, "n1:Amount", ns)
    if amount_element is not None:
        amount_text = _clean_text(amount_element.text)
        if amount_text is not None:
            return _to_decimal(amount_text)
    return Decimal("0")


def _account_startswith(line: ET.Element, prefix: str, ns: NamespaceMap) -> bool:
    account = _find(line, "n1:AccountID", ns)
    account_text = _clean_text(account.text if account is not None else None)
    if not account_text:
        return False
    digits = "".join(ch for ch in account_text if ch.isdigit())
    normalized = digits or account_text
    return normalized.startswith(prefix)


def _line_customer_id(line: ET.Element, ns: NamespaceMap) -> Optional[str]:
    customer = _find(line, "n1:CustomerID", ns)
    if customer is None:
        return None
    return _clean_text(customer.text)


def _dimensions_customer_id(line: ET.Element, ns: NamespaceMap) -> Optional[str]:
    element = _find(line, "n1:Dimensions/n1:CustomerID", ns)
    return _clean_text(element.text if element is not None else None)


def _analysis_customer_id(line: ET.Element, ns: NamespaceMap) -> Optional[str]:
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


def get_tx_customer_id(
    transaction: ET.Element,
    ns: NamespaceMap,
    *,
    lines: Optional[Iterable[ET.Element]] = None,
) -> Optional[str]:
    """Henter kunde-ID for en transaksjon med flere fallback-strategier."""

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

    fallback_paths = (
        "n1:CustomerInfo/n1:CustomerID",
        "n1:Customer/n1:CustomerID",
        "n1:CustomerID",
    )
    for path in fallback_paths:
        element = _find(transaction, path, ns)
        customer_id = _clean_text(element.text if element is not None else None)
        if customer_id:
            return customer_id

    return None


def _line_supplier_id(line: ET.Element, ns: NamespaceMap) -> Optional[str]:
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


def _dimensions_supplier_id(line: ET.Element, ns: NamespaceMap) -> Optional[str]:
    element = _find(line, "n1:Dimensions/n1:SupplierID", ns)
    return _clean_text(element.text if element is not None else None)


def _analysis_supplier_id(line: ET.Element, ns: NamespaceMap) -> Optional[str]:
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


def get_tx_supplier_id(
    transaction: ET.Element,
    ns: NamespaceMap,
    *,
    lines: Optional[Iterable[ET.Element]] = None,
) -> Optional[str]:
    """Henter leverandør-ID for en transaksjon med flere fallback-strategier."""

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


def _sourceline(element: Optional[ET.Element]) -> Optional[int]:
    if element is None:
        return None
    line = getattr(element, "sourceline", None)
    if isinstance(line, int):
        return line
    return None


def _normalize_decimal_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = "".join(ch for ch in value if not ch.isspace())
    if not cleaned:
        return None
    comma_index = cleaned.rfind(",")
    dot_index = cleaned.rfind(".")

    if comma_index != -1 and dot_index != -1:
        if comma_index > dot_index:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif comma_index != -1:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    return cleaned


def _parse_decimal_text(
    value: Optional[str],
    *,
    field: str,
    line: Optional[int],
    xml_path: Path,
) -> Decimal:
    normalized = _normalize_decimal_text(value)
    if normalized is None:
        return Decimal("0")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:  # pragma: no cover - vanskelige å trigge i tester
        location = f" (linje {line})" if line is not None else ""
        raise ValueError(
            f"Ugyldig tall i {field}{location} i SAF-T filen "
            f"'{xml_path.name}': {value!r}"
        ) from exc


def _parse_amount_element(
    element: Optional[ET.Element],
    *,
    field: str,
    line: Optional[int],
    amount_tag: str,
    xml_path: Path,
) -> Decimal:
    if element is None:
        return Decimal("0")
    text = _clean_text(element.text)
    element_line = _sourceline(element)
    if text is not None:
        return _parse_decimal_text(
            text,
            field=field,
            line=element_line or line,
            xml_path=xml_path,
        )
    nested = element.find(amount_tag)
    if nested is not None:
        nested_text = _clean_text(nested.text)
        nested_line = _sourceline(nested)
        if nested_text is not None:
            return _parse_decimal_text(
                nested_text,
                field=field,
                line=nested_line or element_line or line,
                xml_path=xml_path,
            )
    return Decimal("0")
