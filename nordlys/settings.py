"""Felles innstillinger som leses fra miljøvariabler."""
from __future__ import annotations

import os

__all__ = [
    "SAFT_STREAMING_ENABLED",
    "SAFT_STREAMING_VALIDATE",
]


def _env_flag(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    normalized = value.strip().lower()
    return normalized in {"1", "true", "ja", "on", "yes"}


SAFT_STREAMING_ENABLED = _env_flag("NORDLYS_SAFT_STREAMING")
SAFT_STREAMING_VALIDATE = _env_flag("NORDLYS_SAFT_STREAMING_VALIDATE")
