from __future__ import annotations

from typing import Generator

import pytest

try:  # pragma: no cover - miljøavhengig
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit
except (ImportError, OSError) as exc:  # pragma: no cover - miljøavhengig
    pytest.skip(f"PySide6 er ikke tilgjengelig: {exc}", allow_module_level=True)

import pandas as pd

from nordlys.ui.pages.sammenstilling_page import (
    SammenstillingsanalysePage,
    _SortValueItem,
)


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


def test_click_outside_closes_comment_editor(qapp: QApplication) -> None:
    page = SammenstillingsanalysePage()
    df = pd.DataFrame(
        {
            "Konto": ["4000"],
            "Kontonavn": ["Test"],
            "UB": [100.0],
            "forrige": [50.0],
        }
    )

    page.set_dataframe(df, fiscal_year="2024")

    comment_item = page.cost_table.item(0, 5)
    assert comment_item is not None

    page.cost_table.editItem(comment_item)
    delegate = page.cost_table.itemDelegateForColumn(5)
    editor = getattr(delegate, "active_editor", None)

    assert isinstance(editor, QLineEdit)
    assert page.cost_table.state() == QAbstractItemView.EditingState

    click_event = QMouseEvent(
        QEvent.MouseButtonPress,
        QPointF(1, 1),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(page.cost_card, click_event)
    qapp.processEvents()

    assert getattr(delegate, "active_editor", None) is None
    assert page.cost_table.state() != QAbstractItemView.EditingState
