"""Nordlys-bibliotekets grensesnitt."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .constants import APP_TITLE, BRREG_URL_TMPL, ENHETSREGISTER_URL_TMPL, NS

__all__ = [
    'APP_TITLE',
    'BRREG_URL_TMPL',
    'ENHETSREGISTER_URL_TMPL',
    'NS',
    'brreg',
    'industry_groups',
    'saft',
    'utils',
]

_MODULE_MAP = {
    'brreg': 'nordlys.brreg',
    'industry_groups': 'nordlys.industry_groups',
    'saft': 'nordlys.saft',
    'utils': 'nordlys.utils',
}


def __getattr__(name: str) -> Any:
    """Last moduler først når de faktisk brukes."""

    if name in _MODULE_MAP:
        module = import_module(_MODULE_MAP[name])
        globals()[name] = module
        return module
    raise AttributeError(f"module 'nordlys' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__ + list(globals().keys())))
