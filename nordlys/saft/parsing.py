"""Streaming-parsing av SAF-T filer for lavere minnebruk."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterator, List, Optional


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


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


def _parse_decimal(
    value: Optional[str],
    *,
    field: str,
    line: Optional[int],
    xml_path: Path,
) -> Decimal:
    if value is None:
        return Decimal("0")
    text = value.strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - vanskelige å trigge i tester
        location = f" (linje {line})" if line is not None else ""
        raise ValueError(
            f"Ugyldig tall i {field}{location} i SAF-T filen "
            f"'{xml_path.name}': {text!r}"
        ) from exc


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
) -> Iterator[Dict[str, object]]:
    transaction_id = _clean_text(transaction.findtext(_tag(prefix, "TransactionID")))
    transaction_date = _clean_text(
        transaction.findtext(_tag(prefix, "TransactionDate"))
    )
    document_number = _clean_text(
        transaction.findtext(_tag(prefix, "SourceDocumentID", "DocumentNumber"))
    )
    transaction_description = _clean_text(
        transaction.findtext(_tag(prefix, "Description"))
    )
    line_path = _tag(prefix, "Line")
    for index, line in enumerate(transaction.findall(line_path), start=1):
        line_number = _clean_text(line.findtext(_tag(prefix, "LineNumber"))) or str(
            index
        )
        account_id = _clean_text(line.findtext(_tag(prefix, "AccountID")))
        line_description = _clean_text(line.findtext(_tag(prefix, "Description")))
        debit_elem = line.find(_tag(prefix, "DebitAmount"))
        credit_elem = line.find(_tag(prefix, "CreditAmount"))
        debit = _parse_decimal(
            debit_elem.text if debit_elem is not None else None,
            field="DebitAmount",
            line=_sourceline(debit_elem) or _sourceline(line),
            xml_path=xml_path,
        )
        credit = _parse_decimal(
            credit_elem.text if credit_elem is not None else None,
            field="CreditAmount",
            line=_sourceline(credit_elem) or _sourceline(line),
            xml_path=xml_path,
        )
        customer_id = _clean_text(line.findtext(_tag(prefix, "CustomerID")))
        supplier_id = _clean_text(line.findtext(_tag(prefix, "SupplierID")))
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


def iter_saft_entries(
    path: Path, validate: bool = False
) -> Iterator[Dict[str, object]]:
    """Returnerer en iterator over alle hovedbokslinjer i en SAF-T-fil."""

    xml_path = Path(path)
    if not xml_path.exists():
        raise FileNotFoundError(f"Fant ikke SAF-T filen: {xml_path}")

    if validate:
        _ensure_validated(xml_path)

    def _generator() -> Iterator[Dict[str, object]]:
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
        total_debet += entry.get("debet", Decimal("0"))
        total_kredit += entry.get("kredit", Decimal("0"))
    diff = total_debet - total_kredit
    return {"debet": total_debet, "kredit": total_kredit, "diff": diff}


__all__ = ["iter_saft_entries", "check_trial_balance"]
