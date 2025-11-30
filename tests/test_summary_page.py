from __future__ import annotations

from typing import Generator

import pytest

try:  # pragma: no cover - miljøavhengig
    from PySide6.QtWidgets import QApplication
except (ImportError, OSError) as exc:  # pragma: no cover - miljøavhengig
    pytest.skip(f"PySide6 er ikke tilgjengelig: {exc}", allow_module_level=True)

from nordlys.ui.pages.summary_page import SummaryPage


@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_summary_page_empty_state(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")

    page.update_summary(None)

    assert page.table.rowCount() == 0
    assert not page.table.isVisible()
    assert page.empty_state.isVisible()


def test_summary_page_shows_table_when_data_exists(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    summary = {"ebit": 123.0, "arsresultat": 456.0}

    page.update_summary(summary)

    assert page.table.isVisible()
    assert not page.empty_state.isVisible()
    assert page.table.rowCount() > 0
