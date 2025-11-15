"""Hjelpefunksjoner for å beregne prøvebalanse for SAF-T."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional

from ..helpers.lazy_imports import lazy_import
from ..settings import SAFT_STREAMING_ENABLED, SAFT_STREAMING_VALIDATE

saft = lazy_import("nordlys.saft")


@dataclass
class TrialBalanceResult:
    """Resultat fra prøvebalanse-beregningen."""

    balance: Optional[Dict[str, Decimal]]
    error: Optional[str]


def compute_trial_balance(file_path: str) -> TrialBalanceResult:
    """Returner prøvebalansen hvis streaming er aktivert."""

    if not SAFT_STREAMING_ENABLED:
        return TrialBalanceResult(balance=None, error=None)

    try:
        trial_balance = saft.check_trial_balance(
            Path(file_path), validate=SAFT_STREAMING_VALIDATE
        )
    except Exception as exc:  # pragma: no cover - robust mot eksterne feil
        return TrialBalanceResult(balance=None, error=str(exc))

    error: Optional[str] = None
    if trial_balance.get("diff") != Decimal("0"):
        error = "Prøvebalansen går ikke opp (diff {diff}) for {file}".format(
            diff=trial_balance["diff"], file=Path(file_path).name
        )
    return TrialBalanceResult(balance=trial_balance, error=error)
