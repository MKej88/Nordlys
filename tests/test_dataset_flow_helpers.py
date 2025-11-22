import sys
import types
from decimal import Decimal


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


pyside_stub = types.ModuleType("PySide6")
pyside_stub.__path__ = []  # type: ignore[attr-defined]
qtwidgets = _LazyModule("PySide6.QtWidgets")
qtgui = _LazyModule("PySide6.QtGui")
qtcore = _LazyModule("PySide6.QtCore")


class _Signal:
    def __init__(self, *args, **kwargs):
        pass

    def connect(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass


qtcore.Signal = _Signal


class _Qt:
    UserRole = 256
    DisplayRole = 0

    def __getattr__(self, name: str):  # type: ignore[override]
        return 0


qtcore.Qt = _Qt()

sys.modules["PySide6"] = pyside_stub
sys.modules["PySide6.QtWidgets"] = qtwidgets
sys.modules["PySide6.QtGui"] = qtgui
sys.modules["PySide6.QtCore"] = qtcore

from nordlys.ui.data_controller.dataset_flow import format_trial_balance_misc_entry


def test_format_trial_balance_misc_entry_balanced(monkeypatch) -> None:
    monkeypatch.setattr(
        "nordlys.ui.data_controller.dataset_flow.SAFT_STREAMING_ENABLED", True
    )

    entry = format_trial_balance_misc_entry(
        {"debet": Decimal("1000"), "kredit": Decimal("1000"), "diff": Decimal("0")},
        error=None,
    )

    assert entry is not None
    title, content = entry
    assert title == "Prøvebalanse"
    assert "Debet: 1 000" in content
    assert "Kredit: 1 000" in content
    assert "Diff: 0 (OK)" in content


def test_format_trial_balance_misc_entry_error_precedence(monkeypatch) -> None:
    monkeypatch.setattr(
        "nordlys.ui.data_controller.dataset_flow.SAFT_STREAMING_ENABLED", True
    )

    entry = format_trial_balance_misc_entry(
        {"debet": Decimal("50")},
        error="Kontroll feilet",
    )

    assert entry == ("Prøvebalanse", "Kontroll feilet")


def test_format_trial_balance_misc_entry_streaming_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "nordlys.ui.data_controller.dataset_flow.SAFT_STREAMING_ENABLED", False
    )

    entry = format_trial_balance_misc_entry(None, error=None)

    assert entry == ("Prøvebalanse", "Ikke beregnet (streaming er av).")
