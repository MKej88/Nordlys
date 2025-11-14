"""Hjelpefunksjoner for SAF-T parsing, inkludert streaming av hovedbok."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import (
    Dict,
    Iterable,
    Iterator,
    List,
    MutableMapping,
    Optional,
    Tuple,
    TypedDict,
    cast,
)


_NS_FLAG_KEY = "__has_namespace__"
_NS_CACHE_KEY = "__plain_cache__"
_NS_ET_KEY = "__etree_namespace__"

NamespaceCache = Dict[str, Tuple[str, bool]]
NamespaceMap = MutableMapping[str, object]

_PREFIX_PATTERN = re.compile(r"([A-Za-z_][\w.-]*):")


class SaftEntry(TypedDict, total=False):
    """Representerer en linje fra SAF-T-filen."""

    journal_id: Optional[str]
    transaction_id: Optional[str]
    transaction_date: Optional[str]
    document_number: Optional[str]
    transaction_description: Optional[str]
    line_number: str
    line_description: Optional[str]
    account_id: Optional[str]
    debet: Decimal
    kredit: Decimal
    customer_id: Optional[str]
    supplier_id: Optional[str]


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


def parse_saft(path: str | Path) -> Tuple[ET.ElementTree, NamespaceMap]:
    """Leser SAF-T XML og oppdager default namespace dynamisk."""

    xml_path = Path(path)
    tree = cast(ET.ElementTree, ET.parse(xml_path))
    root = tree.getroot()
    if root is None:
        raise ValueError("SAF-T filen mangler et rot-element.")
    namespace: NamespaceMap = {"n1": ""}
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


def _has_namespace(ns: NamespaceMap) -> bool:
    flag = ns.get(_NS_FLAG_KEY)
    if isinstance(flag, bool):
        return flag
    return bool({k: v for k, v in ns.items() if k not in {_NS_FLAG_KEY, _NS_CACHE_KEY}})


def _et_namespace(ns: NamespaceMap) -> Dict[str, str]:
    cached_obj = ns.get(_NS_ET_KEY)
    if isinstance(cached_obj, dict):
        cached = cast(Dict[str, str], cached_obj)
        return cached

    namespace: Dict[str, str] = {}
    for key, value in ns.items():
        if key in {_NS_FLAG_KEY, _NS_CACHE_KEY, _NS_ET_KEY}:
            continue
        if isinstance(key, str) and isinstance(value, str):
            namespace[key] = value

    ns[_NS_ET_KEY] = namespace
    return namespace


def _normalize_path(path: str, ns: NamespaceMap) -> Tuple[str, bool]:
    cache_obj = ns.get(_NS_CACHE_KEY)
    cache: Optional[NamespaceCache]
    if isinstance(cache_obj, dict):
        cache = cast(NamespaceCache, cache_obj)
    else:
        cache = None
    if cache is not None:
        cached = cache.get(path)
        if cached is not None:
            return cached

    has_namespace = _has_namespace(ns)

    if not has_namespace:
        normalized = path.replace("n1:", "")
        result = (normalized, False)
    else:
        replacements: List[Tuple[str, str]] = []
        known_prefixes = set()
        for key, value in ns.items():
            if key in {_NS_FLAG_KEY, _NS_CACHE_KEY, _NS_ET_KEY}:
                continue
            if isinstance(key, str) and isinstance(value, str) and value:
                replacements.append((f"{key}:", f"{{{value}}}"))
                known_prefixes.add(key)

        if not replacements:
            result = (path, True)
        else:
            normalized = path
            needs_mapping = False
            for prefix, replacement in replacements:
                if prefix in normalized:
                    normalized = normalized.replace(prefix, replacement)
            for prefix, _ in replacements:
                if prefix in normalized:
                    needs_mapping = True
                    break

            if not needs_mapping:
                for match in _PREFIX_PATTERN.finditer(path):
                    candidate = match.group(1)
                    if candidate not in known_prefixes:
                        needs_mapping = True
                        break
            result = (normalized, needs_mapping)

    if cache is not None:
        cache[path] = result
    else:
        ns[_NS_CACHE_KEY] = {path: result}

    return result


def _find(element: ET.Element, path: str, ns: NamespaceMap) -> Optional[ET.Element]:
    normalized, needs_mapping = _normalize_path(path, ns)
    if needs_mapping:
        return element.find(normalized, _et_namespace(ns))
    return element.find(normalized)


def _findall(
    element: ET.Element,
    path: str,
    ns: NamespaceMap,
) -> Iterable[ET.Element]:
    normalized, needs_mapping = _normalize_path(path, ns)
    if needs_mapping:
        return element.findall(normalized, _et_namespace(ns))
    return element.findall(normalized)


def _to_decimal(value: Optional[str]) -> Decimal:
    if value is None:
        return Decimal("0")
    stripped = value.strip()
    if not stripped:
        return Decimal("0")
    text = "".join(ch for ch in stripped if not ch.isspace())
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

    customer_info = _find(transaction, "n1:CustomerInfo/n1:CustomerID", ns)
    if customer_info is not None:
        customer_id = _clean_text(customer_info.text)
        if customer_id:
            return customer_id

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


def _tag(prefix: str, *parts: str) -> str:
    if not prefix:
        return "/".join(parts)
    return "/".join(f"{prefix}{part}" for part in parts)


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
    cleaned = value.replace("\xa0", "").replace(" ", "").strip()
    if not cleaned:
        return None
    if cleaned.count(",") == 1 and cleaned.count(".") == 0:
        cleaned = cleaned.replace(",", ".")
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


def _ensure_validated(xml_path: Path) -> None:
    from . import validate_saft_against_xsd

    result = validate_saft_against_xsd(xml_path)
    if result.is_valid is False:
        details = result.details or "Ukjent valideringsfeil."
        raise ValueError(
            f"XSD-validering av SAF-T mislyktes for '{xml_path.name}': {details}"
        )
    if result.is_valid is None:
        details = result.details or (
            "XSD-validering er ikke tilgjengelig. Installer pakken 'xmlschema' "
            "for å aktivere validering."
        )
        raise RuntimeError(details)


def _yield_transaction_entries(
    transaction: ET.Element,
    *,
    journal_id: Optional[str],
    prefix: str,
    xml_path: Path,
) -> Iterator[SaftEntry]:
    transaction_id_tag = _tag(prefix, "TransactionID")
    transaction_date_tag = _tag(prefix, "TransactionDate")
    document_number_tag = _tag(prefix, "SourceDocumentID", "DocumentNumber")
    transaction_description_tag = _tag(prefix, "Description")
    line_path = _tag(prefix, "Line")
    line_number_tag = _tag(prefix, "LineNumber")
    account_id_tag = _tag(prefix, "AccountID")
    line_description_tag = _tag(prefix, "Description")
    debit_amount_tag = _tag(prefix, "DebitAmount")
    credit_amount_tag = _tag(prefix, "CreditAmount")
    amount_tag = _tag(prefix, "Amount")
    customer_id_tag = _tag(prefix, "CustomerID")
    supplier_id_tag = _tag(prefix, "SupplierID")

    transaction_id = _clean_text(transaction.findtext(transaction_id_tag))
    transaction_date = _clean_text(transaction.findtext(transaction_date_tag))
    document_number = _clean_text(transaction.findtext(document_number_tag))
    transaction_description = _clean_text(
        transaction.findtext(transaction_description_tag)
    )
    for index, line in enumerate(transaction.findall(line_path), start=1):
        line_number = _clean_text(line.findtext(line_number_tag)) or str(index)
        account_id = _clean_text(line.findtext(account_id_tag))
        line_description = _clean_text(line.findtext(line_description_tag))
        debit_elem = line.find(debit_amount_tag)
        credit_elem = line.find(credit_amount_tag)
        line_line = _sourceline(line)
        debit = _parse_amount_element(
            debit_elem,
            field="DebitAmount",
            line=line_line,
            amount_tag=amount_tag,
            xml_path=xml_path,
        )
        credit = _parse_amount_element(
            credit_elem,
            field="CreditAmount",
            line=line_line,
            amount_tag=amount_tag,
            xml_path=xml_path,
        )
        customer_id = _clean_text(line.findtext(customer_id_tag))
        supplier_id = _clean_text(line.findtext(supplier_id_tag))
        yield {
            "journal_id": journal_id,
            "transaction_id": transaction_id,
            "transaction_date": transaction_date,
            "document_number": document_number,
            "transaction_description": transaction_description,
            "line_number": line_number,
            "line_description": line_description,
            "account_id": account_id,
            "debet": debit,
            "kredit": credit,
            "customer_id": customer_id,
            "supplier_id": supplier_id,
        }


def iter_saft_entries(path: Path, validate: bool = False) -> Iterator[SaftEntry]:
    """Returnerer en iterator over alle hovedbokslinjer i en SAF-T-fil."""

    xml_path = Path(path)
    if not xml_path.exists():
        raise FileNotFoundError(f"Fant ikke SAF-T filen: {xml_path}")

    if validate:
        _ensure_validated(xml_path)

    def _generator() -> Iterator[SaftEntry]:
        try:
            context = ET.iterparse(str(xml_path), events=("start", "end"))
        except (OSError, ET.ParseError) as exc:
            raise ValueError(
                f"Kunne ikke åpne SAF-T filen '{xml_path}': {exc}"
            ) from exc

        prefix = ""
        stack: List[str] = []
        journal_id: Optional[str] = None

        try:
            for event, element in context:
                if event == "start":
                    stack.append(_local_name(element.tag))
                    if (
                        not prefix
                        and element.tag.startswith("{")
                        and "}" in element.tag
                    ):
                        uri = element.tag.split("}", 1)[0][1:]
                        if uri:
                            prefix = f"{{{uri}}}"
                    continue

                local = _local_name(element.tag)
                if local == "JournalID" and len(stack) >= 2 and stack[-2] == "Journal":
                    journal_id = _clean_text(element.text)
                elif local == "Journal":
                    journal_id = None
                elif local == "Transaction":
                    yield from _yield_transaction_entries(
                        element,
                        journal_id=journal_id,
                        prefix=prefix,
                        xml_path=xml_path,
                    )
                    element.clear()
                stack.pop()
        except ET.ParseError as exc:
            raise ValueError(
                f"Fant ikke gyldig XML i SAF-T filen '{xml_path}': {exc}"
            ) from exc

    return _generator()


def check_trial_balance(path: Path, validate: bool = False) -> Dict[str, Decimal]:
    """Summerer debet og kredit og rapporterer differansen."""

    total_debet = Decimal("0")
    total_kredit = Decimal("0")
    for entry in iter_saft_entries(path, validate=validate):
        total_debet += entry["debet"]
        total_kredit += entry["kredit"]
    diff = total_debet - total_kredit
    return {"debet": total_debet, "kredit": total_kredit, "diff": diff}


__all__ = [
    "SaftEntry",
    "parse_saft",
    "get_amount",
    "get_tx_customer_id",
    "get_tx_supplier_id",
    "iter_saft_entries",
    "check_trial_balance",
]
