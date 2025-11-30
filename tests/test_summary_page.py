from __future__ import annotations

from typing import Generator

import pytest

try:  # pragma: no cover - miljøavhengig
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
except (ImportError, OSError) as exc:  # pragma: no cover - miljøavhengig
    pytest.skip(f"PySide6 er ikke tilgjengelig: {exc}", allow_module_level=True)

from nordlys.ui.pages.summary_page import SummaryPage


@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_summary_page_populates_metrics_table(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    summary = {
        "sum_inntekter": 1000.0,
        "varekostnad": 200.0,
        "arsresultat": 100.0,
        "eiendeler_UB": 500.0,
        "egenkapital_UB": 250.0,
    }

    page.update_summary(summary)

    assert page.metrics_table.rowCount() == 6
    assert page.metrics_table.item(0, 0).text() == "Driftsinntekter i år"
    assert page.metrics_table.item(0, 1).text() == "1 000"
    assert page.metrics_table.item(0, 3).text() == "5"
    assert page.metrics_table.item(1, 1).text() == "800"


def test_threshold_table_allows_manual_values(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary(None)

    editable_cell = page.threshold_table.item(0, 1)
    assert editable_cell is not None
    assert editable_cell.flags() & Qt.ItemIsEditable

    type_cell = page.threshold_table.item(0, 0)
    assert type_cell is not None
    assert not (type_cell.flags() & Qt.ItemIsEditable)
