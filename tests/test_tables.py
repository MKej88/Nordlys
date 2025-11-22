from __future__ import annotations

from typing import Generator

import pytest

try:  # pragma: no cover - miljøavhengig
    from PySide6.QtWidgets import QApplication
except (ImportError, OSError) as exc:  # pragma: no cover - miljøavhengig
    pytest.skip(f"PySide6 er ikke tilgjengelig: {exc}", allow_module_level=True)

from nordlys.ui.tables import create_table_widget, populate_table


@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_populate_table_filters_zero_rows(qapp: QApplication) -> None:
    table = create_table_widget()
    columns = ["Kategori", "2024", "2023", "Endring"]
    rows = [
        ("Eiendeler", "", "", ""),
        ("Immaterielle eiendeler", 0, 0, 0),
        ("Kontanter, bankinnskudd o.l.", 100, 0, 100),
    ]

    populate_table(table, columns, rows, money_cols={1, 2, 3}, hide_zero_rows=True)

    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "Eiendeler"
    assert table.item(1, 0).text() == "Kontanter, bankinnskudd o.l."


def test_populate_table_keeps_zero_rows_when_disabled(qapp: QApplication) -> None:
    table = create_table_widget()
    columns = ["Kategori", "2024", "2023", "Endring"]
    rows = [
        ("Eiendeler", "", "", ""),
        ("Immaterielle eiendeler", 0, 0, 0),
    ]

    populate_table(table, columns, rows, money_cols={1, 2, 3})

    assert table.rowCount() == 2
    assert table.item(1, 0).text() == "Immaterielle eiendeler"
