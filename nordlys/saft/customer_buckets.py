"""Konstanter for kunstige kunder som fanger opp kontantsalg uten kunde."""

from __future__ import annotations

from typing import Dict

__all__ = ["DESCRIPTION_BUCKET_MAP"]

# Mapper nøkkelord i VoucherDescription til kunstige CustomerID-er
DESCRIPTION_BUCKET_MAP: Dict[str, str] = {
    "annet": "A",
    "diverse": "D",
}
