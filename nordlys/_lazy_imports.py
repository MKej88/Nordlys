from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any, Optional


class LazyModule:
    """En enkel wrapper som importerer modul ved første bruk."""

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name
        self._module: Optional[ModuleType] = None

    def _load(self) -> ModuleType:
        if self._module is None:
            self._module = import_module(self._module_name)
        return self._module

    def module(self) -> ModuleType:
        """Returnerer den underliggende modulen, og importerer den ved behov."""

        return self._load()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._load(), item)

    def __dir__(self) -> list[str]:  # pragma: no cover - brukt for inspeksjon
        module = self._load()
        combined = set(dir(type(self))) | set(dir(module))
        return sorted(combined)


__all__ = ["LazyModule"]
