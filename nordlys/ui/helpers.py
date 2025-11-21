from __future__ import annotations

from types import TracebackType
from typing import Generic, TypeVar

from PySide6.QtCore import QObject

__all__ = ["SignalBlocker"]

T = TypeVar("T", bound=QObject)


class SignalBlocker(Generic[T]):
    """Context manager som blokkerer Qt-signaler midlertidig."""

    def __init__(self, obj: T) -> None:
        self._obj = obj
        self._was_blocked = obj.signalsBlocked()
        obj.blockSignals(True)

    def __enter__(self) -> "SignalBlocker[T]":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._obj.blockSignals(self._was_blocked)
