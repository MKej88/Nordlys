"""GUI-moduler for Nordlys."""

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = ["NordlysWindow", "create_app", "run"]

if TYPE_CHECKING:  # pragma: no cover - kun for typehjelp
    from .pyside_app import NordlysWindow, create_app, run


def __getattr__(name: str):  # pragma: no cover - enkel delegasjon
    if name in __all__:
        module = import_module(".pyside_app", __name__)
        return getattr(module, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
