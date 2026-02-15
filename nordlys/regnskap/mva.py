"""Helpers for finding VAT treatment deviations in cost vouchers."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

from ..saft.models import CostVoucher

_MISSING_VAT_CODE = "Ingen"

__all__ = [
    "VatDeviation",
    "VatDeviationAccountSummary",
    "find_vat_deviations",
    "summarize_vat_deviations",
]


@dataclass(frozen=True)
class VatDeviation:
    """Represents one voucher that deviates from dominant VAT treatment."""

    account: str
    account_name: str
    expected_vat_code: str
    observed_vat_code: str
    voucher_number: str
    transaction_date: Optional[date]
    supplier: str
    voucher_amount: float
    description: str
    expected_count: int
    total_count: int


@dataclass(frozen=True)
class VatDeviationAccountSummary:
    """Summary per account for deviating VAT treatment."""

    account: str
    account_name: str
    expected_vat_code: str
    deviation_count: int
    deviation_amount: float
    expected_count: int
    total_count: int


@dataclass
class _LineAccumulator:
    account_name: str = ""
    description: str = ""
    vat_codes: set[str] = field(default_factory=set)
    amount: float = 0.0


@dataclass(frozen=True)
class _VoucherAccountVat:
    account: str
    account_name: str
    observed_vat_code: str
    voucher_number: str
    transaction_date: Optional[date]
    supplier: str
    voucher_amount: float
    description: str


def find_vat_deviations(
    vouchers: Sequence[CostVoucher], *, minimum_observations: int = 2
) -> List[VatDeviation]:
    """Find vouchers where VAT treatment deviates from the account norm."""

    effective_minimum = max(2, int(minimum_observations))
    entries = _collect_voucher_account_entries(vouchers)

    per_account: Dict[str, List[_VoucherAccountVat]] = defaultdict(list)
    for entry in entries:
        per_account[entry.account].append(entry)

    deviations: List[VatDeviation] = []
    for account, account_entries in per_account.items():
        if len(account_entries) < effective_minimum:
            continue

        counts = Counter(entry.observed_vat_code for entry in account_entries)
        if len(counts) < 2:
            continue

        ranked_codes = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        expected_code, expected_count = ranked_codes[0]
        second_count = ranked_codes[1][1]
        if expected_count <= second_count:
            continue

        total_count = len(account_entries)
        for entry in account_entries:
            if entry.observed_vat_code == expected_code:
                continue
            deviations.append(
                VatDeviation(
                    account=account,
                    account_name=entry.account_name,
                    expected_vat_code=expected_code,
                    observed_vat_code=entry.observed_vat_code,
                    voucher_number=entry.voucher_number,
                    transaction_date=entry.transaction_date,
                    supplier=entry.supplier,
                    voucher_amount=entry.voucher_amount,
                    description=entry.description,
                    expected_count=expected_count,
                    total_count=total_count,
                )
            )

    return sorted(deviations, key=_deviation_sort_key)


def summarize_vat_deviations(
    deviations: Sequence[VatDeviation],
) -> List[VatDeviationAccountSummary]:
    """Aggregate deviation rows to one summary per account."""

    grouped: Dict[tuple[str, str], List[VatDeviation]] = defaultdict(list)
    for item in deviations:
        grouped[(item.account, item.expected_vat_code)].append(item)

    summaries: List[VatDeviationAccountSummary] = []
    for (account, expected_vat_code), items in grouped.items():
        first = items[0]
        summaries.append(
            VatDeviationAccountSummary(
                account=account,
                account_name=first.account_name,
                expected_vat_code=expected_vat_code,
                deviation_count=len(items),
                deviation_amount=sum(entry.voucher_amount for entry in items),
                expected_count=first.expected_count,
                total_count=first.total_count,
            )
        )

    return sorted(summaries, key=lambda item: item.account)


def _collect_voucher_account_entries(
    vouchers: Sequence[CostVoucher],
) -> List[_VoucherAccountVat]:
    entries: List[_VoucherAccountVat] = []
    for voucher in vouchers:
        per_account: Dict[str, _LineAccumulator] = {}
        for line in voucher.lines:
            account = _normalize_text(line.account)
            if not account:
                continue

            accumulator = per_account.setdefault(account, _LineAccumulator())
            if not accumulator.account_name:
                accumulator.account_name = _normalize_text(line.account_name)
            if not accumulator.description:
                accumulator.description = _normalize_text(line.description)
            accumulator.vat_codes.add(_normalize_vat_code(line.vat_code))
            accumulator.amount += _safe_amount(line.debit) - _safe_amount(line.credit)

        if not per_account:
            continue

        voucher_number = _voucher_number(voucher)
        supplier = _voucher_supplier(voucher)
        voucher_description = _normalize_text(voucher.description)

        for account, accumulator in per_account.items():
            observed_vat = " + ".join(sorted(accumulator.vat_codes))
            account_name = accumulator.account_name or "Ukjent konto"
            description = voucher_description or accumulator.description
            account_amount = abs(accumulator.amount)
            entries.append(
                _VoucherAccountVat(
                    account=account,
                    account_name=account_name,
                    observed_vat_code=observed_vat,
                    voucher_number=voucher_number,
                    transaction_date=voucher.transaction_date,
                    supplier=supplier,
                    voucher_amount=account_amount,
                    description=description,
                )
            )
    return entries


def _normalize_vat_code(value: Optional[str]) -> str:
    text = _normalize_text(value)
    if not text:
        return _MISSING_VAT_CODE
    parts = [_normalize_text(part) for part in text.split(",")]
    non_empty_parts = [part for part in parts if part]
    if not non_empty_parts:
        return _MISSING_VAT_CODE
    unique_parts = sorted(set(non_empty_parts))
    return ", ".join(unique_parts)


def _normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _voucher_number(voucher: CostVoucher) -> str:
    return (
        _normalize_text(voucher.document_number)
        or _normalize_text(voucher.transaction_id)
        or "Uten bilagsnummer"
    )


def _voucher_supplier(voucher: CostVoucher) -> str:
    return (
        _normalize_text(voucher.supplier_name)
        or _normalize_text(voucher.supplier_id)
        or "Ukjent leverandør"
    )


def _safe_amount(value: Optional[float]) -> float:
    try:
        amount = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(amount):
        return 0.0
    return amount


def _deviation_sort_key(item: VatDeviation) -> tuple[str, int, date, str]:
    has_no_date = 1 if item.transaction_date is None else 0
    sort_date = item.transaction_date or date.min
    return (item.account, has_no_date, sort_date, item.voucher_number)
