from __future__ import annotations

from typing import Generator

import pytest

try:  # pragma: no cover - miljøavhengig
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
except (ImportError, OSError) as exc:  # pragma: no cover - miljøavhengig
    pytest.skip(f"PySide6 er ikke tilgjengelig: {exc}", allow_module_level=True)

from nordlys.ui.pages.sammenstilling_page import _SortValueItem


@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_sort_value_item_prefers_numeric_user_role(qapp: QApplication) -> None:
    lower = _SortValueItem("900")
    higher = _SortValueItem("1 000")
    lower.setData(Qt.UserRole, 900.0)
    higher.setData(Qt.UserRole, 1000.0)

    assert lower < higher
    assert not (higher < lower)


def test_sort_value_item_falls_back_to_text(qapp: QApplication) -> None:
    first = _SortValueItem("Alpha")
    second = _SortValueItem("Beta")
    first.setData(Qt.UserRole, "Alpha")
    second.setData(Qt.UserRole, "Beta")

    assert first < second
