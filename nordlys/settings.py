"""Felles innstillinger som leses fra miljøvariabler."""

from __future__ import annotations

import os
from typing import Optional

__all__ = [
    "SAFT_STREAMING_ENABLED",
    "SAFT_STREAMING_VALIDATE",
    "SAFT_HEAVY_PARALLEL",
    "NAV_PANEL_WIDTH_OVERRIDE",
]


def _env_flag(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    normalized = value.strip().lower()
    return normalized in {"1", "true", "ja", "on", "yes"}


def _env_int(name: str) -> Optional[int]:
    value = os.getenv(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


SAFT_STREAMING_ENABLED = _env_flag("NORDLYS_SAFT_STREAMING")
SAFT_STREAMING_VALIDATE = _env_flag("NORDLYS_SAFT_STREAMING_VALIDATE")
SAFT_HEAVY_PARALLEL = _env_flag("NORDLYS_SAFT_HEAVY_PARALLEL")
NAV_PANEL_WIDTH_OVERRIDE = _env_int("NORDLYS_NAV_WIDTH")
