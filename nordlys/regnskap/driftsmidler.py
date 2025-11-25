"""Analysefunksjoner for driftsmidler basert på saldobalanse og kostnadsbilag."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

import pandas as pd

from nordlys.saft.models import CostVoucher


@dataclass(frozen=True)
class AssetMovement:
    """Beskriver en konto med endring i balansen."""

    account: str
    name: str
    opening_balance: float
    closing_balance: float
    change: float


@dataclass(frozen=True)
class CapitalizationCandidate:
    """Bilagslinje på 65xx som kan vurderes for aktivering."""

    date: Optional[object]
    supplier: str
    document: str
    account: str
    amount: float
    description: Optional[str]


def find_possible_accessions(tb: Optional[pd.DataFrame]) -> List[AssetMovement]:
    """Finn kontoer i 11xx-12xx der UB overstiger IB."""

    work = _prepare_asset_frame(tb)
    if work is None:
        return []

    mask = work["UB_netto"] > work["IB_netto"]
    return _build_movements(work.loc[mask])


def find_possible_disposals(tb: Optional[pd.DataFrame]) -> List[AssetMovement]:
    """Finn kontoer i 11xx-12xx som har IB men ingen UB."""

    work = _prepare_asset_frame(tb)
    if work is None:
        return []

    mask = (work["IB_netto"] != 0) & (work["UB_netto"] == 0)
    return _build_movements(work.loc[mask])


def find_capitalization_candidates(
    vouchers: Sequence[CostVoucher], *, threshold: float = 30_000.0
) -> List[CapitalizationCandidate]:
    """Hent kostnadsbilag på 65xx over gitt terskel."""

    candidates: List[CapitalizationCandidate] = []
    for voucher in vouchers:
        for line in voucher.lines:
            normalized_account = _normalize_account(line.account)
            if normalized_account is None or not normalized_account.startswith("65"):
                continue

            line_amount = (line.debit or 0.0) - (line.credit or 0.0)
            if line_amount < threshold:
                continue

            supplier = (voucher.supplier_name or voucher.supplier_id or "—").strip()
            document = (voucher.document_number or voucher.transaction_id or "—").strip()
            candidates.append(
                CapitalizationCandidate(
                    date=voucher.transaction_date,
                    supplier=supplier or "—",
                    document=document or "—",
                    account=line.account or "—",
                    amount=line_amount,
                    description=line.description,
                )
            )
    return candidates


def _prepare_asset_frame(tb: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if tb is None or tb.empty:
        return None
    required = {"Konto", "Kontonavn", "IB_netto", "UB_netto"}
    if not required.issubset(tb.columns):
        return None

    work = tb.loc[:, list(required)].copy()
    work["Konto"] = work["Konto"].apply(_normalize_account)  # type: ignore[assignment]
    work = work.dropna(subset=["Konto"])
    work["IB_netto"] = pd.to_numeric(work["IB_netto"], errors="coerce").fillna(0.0)
    work["UB_netto"] = pd.to_numeric(work["UB_netto"], errors="coerce").fillna(0.0)

    mask = work["Konto"].str.startswith(("11", "12"))
    filtered = work.loc[mask]
    if filtered.empty:
        return None
    return filtered


def _build_movements(rows: pd.DataFrame) -> List[AssetMovement]:
    movements: List[AssetMovement] = []
    for _, row in rows.sort_values("Konto").iterrows():
        account = str(row.get("Konto", "")).strip()
        name = str(row.get("Kontonavn", "")).strip()
        opening = float(row.get("IB_netto", 0.0))
        closing = float(row.get("UB_netto", 0.0))
        movements.append(
            AssetMovement(
                account=account,
                name=name,
                opening_balance=opening,
                closing_balance=closing,
                change=closing - opening,
            )
        )
    return movements


def _normalize_account(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "AssetMovement",
    "CapitalizationCandidate",
    "find_capitalization_candidates",
    "find_possible_accessions",
    "find_possible_disposals",
]
