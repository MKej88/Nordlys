"""Verktøy for sen import av tunge biblioteker."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd


class _LazyModule(ModuleType):
    """En enkel proxy som laster moduler på første bruk."""

    def __init__(self, module_name: str) -> None:
        super().__init__(module_name)
        self._module_name = module_name
        self._module: Optional[ModuleType] = None

    def _load(self) -> ModuleType:
        if self._module is None:
            self._module = import_module(self._module_name)
        return self._module

    def __getattr__(self, item: str) -> Any:
        return getattr(self._load(), item)

    def __setattr__(self, key: str, value: Any) -> None:
        if key in {"_module_name", "_module"}:
            super().__setattr__(key, value)
        else:
            setattr(self._load(), key, value)

    def __dir__(self) -> List[str]:
        return dir(self._load())


_PANDAS_PROXY: Optional[_LazyModule] = None
_LAZY_MODULES: Dict[str, _LazyModule] = {}


def lazy_pandas() -> "pd":
    """Returnerer en proxy som importerer ``pandas`` først når den brukes."""

    global _PANDAS_PROXY
    if _PANDAS_PROXY is None:
        _PANDAS_PROXY = _LazyModule("pandas")
    return cast("pd", _PANDAS_PROXY)


def lazy_import(module_name: str) -> ModuleType:
    """Returnerer en proxy som importerer modulen på første bruk."""

    if module_name not in _LAZY_MODULES:
        _LAZY_MODULES[module_name] = _LazyModule(module_name)
    return _LAZY_MODULES[module_name]


__all__ = ["lazy_import", "lazy_pandas"]
