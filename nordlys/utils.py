"""Generelle hjelpefunksjoner for konvertering og formatering."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from importlib import import_module
from types import ModuleType
from typing import Any, List, Optional, TYPE_CHECKING, cast

import math
import xml.etree.ElementTree as ET

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


def lazy_pandas() -> "pd":
    """Returnerer en proxy som importerer ``pandas`` først når den brukes."""

    global _PANDAS_PROXY
    if _PANDAS_PROXY is None:
        _PANDAS_PROXY = _LazyModule("pandas")
    return cast("pd", _PANDAS_PROXY)


def to_float(value: Optional[str]) -> float:
    """Prøver å tolke en verdi som flyttall og faller tilbake til 0."""
    if value in (None, ""):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0

    cleaned = text.replace(" ", "").replace("\xa0", "")
    if not cleaned:
        return 0.0

    allowed_chars = set("0123456789.,+-")
    if any(char not in allowed_chars for char in cleaned):
        return 0.0

    sign = ""
    if cleaned[0] in "+-":
        sign, cleaned = cleaned[0], cleaned[1:]
    elif cleaned[-1] in "+-":
        sign = cleaned[-1]
        cleaned = cleaned[:-1]

    cleaned = cleaned.strip()
    if not cleaned:
        return 0.0

    comma_pos = cleaned.rfind(",")
    dot_pos = cleaned.rfind(".")
    decimal_sep: Optional[str] = None

    if comma_pos != -1 and dot_pos != -1:
        decimal_sep = "," if comma_pos > dot_pos else "."
    elif comma_pos != -1 and len(cleaned) - comma_pos - 1 <= 2:
        decimal_sep = ","
    elif dot_pos != -1:
        decimal_sep = "."

    if decimal_sep:
        integer_part, fractional_part = cleaned.rsplit(decimal_sep, 1)
    else:
        integer_part, fractional_part = cleaned, ""

    integer_digits = integer_part.replace(",", "").replace(".", "")
    fractional_digits = fractional_part.replace(",", "").replace(".", "")

    normalized = sign + (integer_digits or "0")
    if fractional_digits:
        normalized = f"{normalized}.{fractional_digits}"

    try:
        return float(normalized)
    except ValueError:
        return 0.0


def text_or_none(element: Optional[ET.Element]) -> Optional[str]:
    """Returnerer tekstinnholdet hvis elementet finnes og har tekst."""
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def findall_any_namespace(inv: ET.Element, localname: str) -> List[ET.Element]:
    """Returnerer alle under-elementer med gitt lokale navn uansett namespace."""
    matches: List[ET.Element] = []
    for elem in inv.iter():
        if elem.tag.split('}')[-1].lower() == localname.lower():
            matches.append(elem)
    return matches


def format_currency(value: Optional[float]) -> str:
    """Formatterer beløp til heltall med tusenskilletegn."""
    rounded = _round_half_up(value)
    if rounded is None:
        return "—"
    return f"{rounded:,.0f}"


def format_difference(a: Optional[float], b: Optional[float]) -> str:
    """Formatterer differansen mellom to beløp."""
    try:
        difference = float(a) - float(b)
    except Exception:
        return "—"

    rounded = _round_half_up(difference)
    if rounded is None:
        return "—"
    return f"{rounded:,.0f}"


def _round_half_up(value: Optional[float]) -> Optional[int]:
    """Runder til nærmeste heltall med kommersielt avrunding (0.5 -> 1)."""

    if value is None:
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(numeric):
        return None

    try:
        decimal_value = Decimal(str(numeric))
        quantized = decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None

    return int(quantized)


__all__ = [
    "to_float",
    "text_or_none",
    "findall_any_namespace",
    "format_currency",
    "format_difference",
    "lazy_pandas",
]
