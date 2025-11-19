"""Streaming av hovedbokslinjer og oppslag for kunder/leverandører."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from typing import Iterator, List, Optional, TypedDict

from .entry_helpers import (
    _parse_amount_element,
    _sourceline,
    get_amount,
    get_tx_customer_id,
    get_tx_supplier_id,
)
from .xml_helpers import _clean_text, _local_name
from .validation import ensure_saft_validated

__all__ = [
    "SaftEntry",
    "iter_saft_entries",
    "check_trial_balance",
    "get_amount",
    "get_tx_customer_id",
    "get_tx_supplier_id",
]


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


def _tag(prefix: str, *parts: str) -> str:
    if not prefix:
        return "/".join(parts)
    return "/".join(f"{prefix}{part}" for part in parts)


def _yield_transaction_entries(
    transaction: ET.Element,
    *,
    journal_id: Optional[str],
    prefix: str,
    xml_path: Path,
) -> Iterator[SaftEntry]:
    transaction_id_tag = _tag(prefix, "TransactionID")
    transaction_date_tag = _tag(prefix, "TransactionDate")
    document_number_tag = _tag(prefix, "DocumentNumber")
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
        ensure_saft_validated(xml_path)

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


def check_trial_balance(path: Path, validate: bool = False) -> dict[str, Decimal]:
    """Summerer debet og kredit og rapporterer differansen."""

    total_debet = Decimal("0")
    total_kredit = Decimal("0")
    for entry in iter_saft_entries(path, validate=validate):
        total_debet += entry["debet"]
        total_kredit += entry["kredit"]
    diff = total_debet - total_kredit
    return {"debet": total_debet, "kredit": total_kredit, "diff": diff}
