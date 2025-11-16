"""GUI-moduler for Nordlys."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = ["NordlysWindow", "create_app", "run"]

if TYPE_CHECKING:  # pragma: no cover - kun for typehjelp
    from .pyside_app import NordlysWindow, create_app, run


def __getattr__(name: str):  # pragma: no cover - enkel lazy loading
    if name in __all__:
        module = import_module("nordlys.ui.pyside_app")
        return getattr(module, name)
    raise AttributeError(f"module 'nordlys.ui' has no attribute {name!r}")
