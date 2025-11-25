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


def compute_trial_balance(
    file_path: str, *, streaming_enabled: bool | None = None
) -> TrialBalanceResult:
    """Returner et tomt resultat uten streaming, eller beregn prøvebalanse.

    Når ``streaming_enabled`` er ``False`` (eller
    ``NORDLYS_SAFT_STREAMING`` er deaktivert og argumentet ikke er gitt)
    returneres et tomt ``TrialBalanceResult`` uten balanse eller feil. Dersom
    streaming er aktivert beregnes prøvebalansen, og eventuelle feil formidles
    via ``error``-feltet.
    """

    effective_streaming = (
        SAFT_STREAMING_ENABLED if streaming_enabled is None else streaming_enabled
    )

    if not effective_streaming:
        return TrialBalanceResult(balance=None, error=None)

    try:
        trial_balance = saft.check_trial_balance(
            Path(file_path), validate=SAFT_STREAMING_VALIDATE
        )
    except Exception as exc:  # pragma: no cover - robust mot eksterne feil
        return TrialBalanceResult(balance=None, error=str(exc))

    if trial_balance is None:
        return TrialBalanceResult(
            balance=None,
            error=(
                "Kunne ikke beregne prøvebalanse: mottok ingen data for "
                f"{Path(file_path).name}."
            ),
        )

    error: Optional[str] = None
    diff_value = trial_balance.get("diff")
    if diff_value is None:
        return TrialBalanceResult(
            balance=None,
            error=(
                "Kunne ikke beregne prøvebalanse: resultatet manglet diff-felt "
                f"for {Path(file_path).name}."
            ),
        )

    try:
        diff_decimal = Decimal(diff_value)
    except Exception as exc:  # pragma: no cover - robust mot uventede typer
        return TrialBalanceResult(
            balance=None,
            error=(
                "Kunne ikke tolke diff i prøvebalansen for "
                f"{Path(file_path).name}: {exc}."
            ),
        )

    if diff_decimal != Decimal("0"):
        error = "Prøvebalansen går ikke opp (diff {diff}) for {file}".format(
            diff=diff_decimal, file=Path(file_path).name
        )
    return TrialBalanceResult(balance=trial_balance, error=error)
