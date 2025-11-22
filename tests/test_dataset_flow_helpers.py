import importlib
import sys
import types
from collections.abc import Generator
from decimal import Decimal
from typing import Callable, Optional

import pytest


class _LazyModule(types.ModuleType):
    def __getattr__(self, name: str):  # type: ignore[override]
        dummy = type(name, (_DummyBase,), {})
        setattr(self, name, dummy)
        return dummy


class _DummyMeta(type):
    def __getattr__(self, name: str):  # type: ignore[override]
        return 0

    def __call__(cls, *args, **kwargs):  # type: ignore[override]
        return super().__call__(*args, **kwargs)


class _DummyBase(metaclass=_DummyMeta):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name: str):  # type: ignore[override]
        return 0

    def __call__(self, *args, **kwargs):  # type: ignore[override]
        return None


class _Signal:
    def __init__(self, *args, **kwargs):
        pass

    def connect(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass


class _Qt:
    UserRole = 256
    DisplayRole = 0

    def __getattr__(self, name: str):  # type: ignore[override]
        return 0


def _create_pyside6_stubs() -> dict[str, types.ModuleType]:
    pyside_stub = types.ModuleType("PySide6")
    pyside_stub.__path__ = []  # type: ignore[attr-defined]
    qtwidgets = _LazyModule("PySide6.QtWidgets")
    qtgui = _LazyModule("PySide6.QtGui")
    qtcore = _LazyModule("PySide6.QtCore")
    qtcore.Signal = _Signal
    qtcore.Qt = _Qt()

    return {
        "PySide6": pyside_stub,
        "PySide6.QtWidgets": qtwidgets,
        "PySide6.QtGui": qtgui,
        "PySide6.QtCore": qtcore,
    }


@pytest.fixture()
def trial_balance_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[
    Callable[[Optional[dict[str, Decimal]], Optional[str]], Optional[tuple[str, str]]],
    None,
    None,
]:
    modules: Optional[dict[str, types.ModuleType]] = None
    if "PySide6" not in sys.modules:
        modules = _create_pyside6_stubs()
        for name, module in modules.items():
            monkeypatch.setitem(sys.modules, name, module)
        importlib.invalidate_caches()

    from nordlys.ui.data_controller.dataset_flow import format_trial_balance_misc_entry

    yield format_trial_balance_misc_entry

    if modules:
        for name in modules:
            sys.modules.pop(name, None)
        importlib.invalidate_caches()


def test_format_trial_balance_misc_entry_balanced(
    monkeypatch: pytest.MonkeyPatch, trial_balance_formatter
) -> None:
    monkeypatch.setattr(
        "nordlys.ui.data_controller.dataset_flow.SAFT_STREAMING_ENABLED", True
    )

    entry = trial_balance_formatter(
        {"debet": Decimal("1000"), "kredit": Decimal("1000"), "diff": Decimal("0")},
        error=None,
    )

    assert entry is not None
    title, content = entry
    assert title == "Prøvebalanse"
    assert "Debet: 1 000" in content
    assert "Kredit: 1 000" in content
    assert "Diff: 0 (OK)" in content


def test_format_trial_balance_misc_entry_error_precedence(
    monkeypatch: pytest.MonkeyPatch, trial_balance_formatter
) -> None:
    monkeypatch.setattr(
        "nordlys.ui.data_controller.dataset_flow.SAFT_STREAMING_ENABLED", True
    )

    entry = trial_balance_formatter(
        {"debet": Decimal("50")},
        error="Kontroll feilet",
    )

    assert entry == ("Prøvebalanse", "Kontroll feilet")


def test_format_trial_balance_misc_entry_streaming_disabled(
    monkeypatch: pytest.MonkeyPatch, trial_balance_formatter
) -> None:
    monkeypatch.setattr(
        "nordlys.ui.data_controller.dataset_flow.SAFT_STREAMING_ENABLED", False
    )

    entry = trial_balance_formatter(None, error=None)

    assert entry == ("Prøvebalanse", "Ikke beregnet (streaming er av).")
