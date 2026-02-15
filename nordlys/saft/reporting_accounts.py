"""Rapporter som arbeider med kontonavn og kostnadsbilag."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from .entry_helpers import get_amount, get_tx_customer_id, get_tx_supplier_id
from .models import CostVoucher, VoucherLine
from .name_lookup import build_customer_name_map, build_supplier_name_map
from .reporting_utils import (
    _ensure_date,
    _format_decimal,
    _is_cost_account,
    _iter_transactions,
    _normalize_account_key,
)
from .xml_helpers import _clean_text, _find, _findall, NamespaceMap

__all__ = ["build_account_name_map", "extract_cost_vouchers", "extract_all_vouchers"]


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
        if not code:
            continue
        codes.append(code)
    if not codes:
        return None
    unique_codes = sorted(set(codes))
    return ", ".join(unique_codes)


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
        has_asset_line = False
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
            elif normalized_account and normalized_account.startswith(("11", "12")):
                has_asset_line = True
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

        if not has_cost_line and not has_asset_line:
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


def extract_all_vouchers(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    year: Optional[int] = None,
    date_from: Optional[object] = None,
    date_to: Optional[object] = None,
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None,
) -> List[CostVoucher]:
    """Henter alle bilag i valgt periode/år med linjer og mva-koder."""

    start_date = _ensure_date(date_from)
    end_date = _ensure_date(date_to)
    use_range = start_date is not None or end_date is not None
    if not use_range and year is None:
        raise ValueError("Angi enten year eller date_from/date_to.")

    supplier_names = build_supplier_name_map(root, ns, parent_map=parent_map)
    customer_names = build_customer_name_map(root, ns, parent_map=parent_map)
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
        customer_id = get_tx_customer_id(transaction, ns, lines=lines)
        counterparty_id = supplier_id or customer_id
        counterparty_name = None
        if supplier_id:
            counterparty_name = supplier_names.get(supplier_id)
        if counterparty_name is None and customer_id:
            counterparty_name = customer_names.get(customer_id)

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
                supplier_id=counterparty_id,
                supplier_name=counterparty_name,
                description=description,
                amount=_format_decimal(total),
                lines=voucher_lines,
            )
        )

    return vouchers
