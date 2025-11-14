"""Dataklasser for SAF-T analyser."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class VoucherLine:
    """Representerer én linje i et bilag fra hovedboken."""

    account: str
    account_name: Optional[str]
    description: Optional[str]
    vat_code: Optional[str]
    debit: float
    credit: float


@dataclass
class CostVoucher:
    """Inngående faktura hentet fra SAF-T til bruk i bilagskontroll."""

    transaction_id: Optional[str]
    document_number: Optional[str]
    transaction_date: Optional[date]
    supplier_id: Optional[str]
    supplier_name: Optional[str]
    description: Optional[str]
    amount: float
    lines: List[VoucherLine] = field(default_factory=list)


__all__ = ["VoucherLine", "CostVoucher"]
