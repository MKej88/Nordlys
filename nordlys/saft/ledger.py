"""Hjelpere for enkel hovedbokvisning per konto."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Sequence

from .models import CostVoucher

__all__ = [
    "LedgerRow",
    "build_ledger_rows",
    "filter_ledger_rows",
]


@dataclass(frozen=True)
class LedgerRow:
    """Én linje i hovedbokvisningen."""

    dato: str
    bilagsnr: str
    transaksjons_id: str
    konto: str
    kontonavn: str
    tekst: str
    motkontoer: str
    debet: float
    kredit: float


def build_ledger_rows(vouchers: Sequence[CostVoucher]) -> List[LedgerRow]:
    """Bygger en flat liste med posteringer fra alle bilag."""

    rows: List[LedgerRow] = []

    for voucher in vouchers:
        dato = _format_date(voucher.transaction_date)
        bilagsnr = (voucher.document_number or "").strip() or "—"
        transaksjons_id = (voucher.transaction_id or "").strip() or "—"

        accounts = [line.account.strip() for line in voucher.lines if line.account]
        unique_accounts = sorted({account for account in accounts if account})

        for line in voucher.lines:
            konto = (line.account or "").strip() or "—"
            kontonavn = (line.account_name or "").strip() or "—"
            tekst = (line.description or voucher.description or "").strip() or "—"

            motkontoer = [acc for acc in unique_accounts if acc != konto]
            motkonto_txt = ", ".join(motkontoer) if motkontoer else "—"

            rows.append(
                LedgerRow(
                    dato=dato,
                    bilagsnr=bilagsnr,
                    transaksjons_id=transaksjons_id,
                    konto=konto,
                    kontonavn=kontonavn,
                    tekst=tekst,
                    motkontoer=motkonto_txt,
                    debet=float(line.debit),
                    kredit=float(line.credit),
                )
            )

    rows.sort(key=lambda row: (row.dato, row.bilagsnr, row.transaksjons_id, row.konto))
    return rows


def filter_ledger_rows(rows: Iterable[LedgerRow], query: str) -> List[LedgerRow]:
    """Filtrerer hovedboklinjer på kontonummer eller kontonavn."""

    cleaned = query.strip()
    if not cleaned:
        return list(rows)

    lowered = cleaned.lower()
    digit_query = "".join(char for char in cleaned if char.isdigit())

    filtered: List[LedgerRow] = []
    for row in rows:
        konto = row.konto.strip()
        konto_digits = "".join(char for char in konto if char.isdigit())
        konto_match = False

        if digit_query:
            konto_match = konto_digits.startswith(digit_query)
        else:
            konto_match = lowered in konto.lower()

        if konto_match or lowered in row.kontonavn.lower():
            filtered.append(row)

    return filtered


def _format_date(value: date | None) -> str:
    if value is None:
        return "—"
    return value.isoformat()
