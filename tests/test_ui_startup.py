"""Tester oppstartssperrer i GUI-et."""

from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip(
    "PySide6.QtWidgets",
    reason="PySide6 er ikke tilgjengelig i testmiljøet",
    exc_type=ImportError,
)
QApplication = QtWidgets.QApplication

from nordlys.ui.pyside_app import NordlysWindow


def _ensure_qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_ensure_startup_completed_skips_when_in_progress(monkeypatch) -> None:
    _ensure_qt_app()
    window = NordlysWindow()

    called = False

    def _fake_finish() -> None:
        nonlocal called
        called = True

    window._startup_in_progress = True  # type: ignore[attr-defined]
    monkeypatch.setattr(window, "_finish_startup", _fake_finish)

    window._ensure_startup_completed()

    window.close()
    assert not called


def test_schedule_startup_no_timer_when_in_progress() -> None:
    _ensure_qt_app()
    window = NordlysWindow()

    window._startup_in_progress = True  # type: ignore[attr-defined]
    window._schedule_startup()

    try:
        assert window._startup_timer is None  # type: ignore[attr-defined]
    finally:
        window.close()
