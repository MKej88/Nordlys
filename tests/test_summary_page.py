from __future__ import annotations

from typing import Generator

import pytest

try:  # pragma: no cover - miljøavhengig
    from PySide6.QtWidgets import QApplication, QLineEdit, QAbstractItemView
    from PySide6.QtCore import QEvent, Qt, QPointF
    from PySide6.QtGui import QMouseEvent
except (ImportError, OSError) as exc:  # pragma: no cover - miljøavhengig
    pytest.skip(f"PySide6 er ikke tilgjengelig: {exc}", allow_module_level=True)

from nordlys.industry_groups import IndustryClassification
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
        "resultat_for_skatt": 100.0,
        "eiendeler_UB": 500.0,
        "egenkapital_UB": 250.0,
    }

    page.update_summary(summary)

    assert page.metrics_table.rowCount() == 6
    assert page.metrics_table.item(0, 0).text() == "Driftsinntekter i år"
    assert page.metrics_table.item(0, 1).text() == "1 000"
    assert page.metrics_table.item(0, 3).text() == "5"
    assert page.metrics_table.item(1, 1).text() == "800"

    percent_item = page.metrics_table.item(0, 2)
    assert percent_item is not None
    assert percent_item.text() == "0.50%"


def test_percent_columns_are_editable_and_centered(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary({"sum_inntekter": 1000.0})

    percent_item = page.metrics_table.item(0, 2)
    assert percent_item is not None
    assert percent_item.flags() & Qt.ItemIsEditable
    assert percent_item.textAlignment() == Qt.AlignHCenter | Qt.AlignVCenter

    amount_item = page.metrics_table.item(0, 1)
    assert amount_item is not None
    assert not (amount_item.flags() & Qt.ItemIsEditable)


def test_percent_edit_recalculates_amounts(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary({"sum_inntekter": 1000.0})

    percent_item = page.metrics_table.item(0, 2)
    assert percent_item is not None

    percent_item.setText("3")

    updated_percent = page.metrics_table.item(0, 2)
    assert updated_percent is not None
    assert updated_percent.text() == "3.00%"

    minimum_item = page.metrics_table.item(0, 3)
    assert minimum_item is not None
    assert minimum_item.text() == "30"


def test_editor_prefills_existing_value(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary({"sum_inntekter": 1000.0})

    delegate = page.metrics_table.itemDelegate()
    model_index = page.metrics_table.model().index(0, 2)
    editor = delegate.createEditor(
        page.metrics_table, page.metrics_table.viewOptions(), model_index
    )
    delegate.setEditorData(editor, model_index)

    assert isinstance(editor, QLineEdit)
    assert editor.text() == "0.50%"


def test_negative_values_are_hidden(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary({"sum_inntekter": -500.0, "egenkapital_UB": -10.0})

    amount_item = page.metrics_table.item(0, 1)
    equity_item = page.metrics_table.item(5, 1)

    assert amount_item is not None
    assert amount_item.text() == "—"

    assert equity_item is not None
    assert equity_item.text() == "—"


def test_industry_label_updates(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    classification = IndustryClassification(
        orgnr="123456789",
        name="Test AS",
        naringskode="62.01",
        description="Programmering",
        sn2="62",
        group="IT-tjenester",
        source="Brreg",
    )

    page.update_summary({"sum_inntekter": 100.0}, industry=classification)

    assert page.industry_label.text() == "Bransje: IT-tjenester"


def test_threshold_table_allows_manual_values(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary(None)

    editable_cell = page.threshold_table.item(0, 1)
    assert editable_cell is not None
    assert editable_cell.flags() & Qt.ItemIsEditable

    type_cell = page.threshold_table.item(0, 0)
    assert type_cell is not None
    assert not (type_cell.flags() & Qt.ItemIsEditable)


def test_row_height_is_increased_for_visibility(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary({"sum_inntekter": 1000.0})

    metrics_header = page.metrics_table.verticalHeader()
    threshold_header = page.threshold_table.verticalHeader()

    assert metrics_header.defaultSectionSize() >= 32
    assert threshold_header.defaultSectionSize() >= 32
    assert page.metrics_table.rowHeight(0) >= 32
    assert page.threshold_table.rowHeight(0) >= 32


def test_tables_use_full_height_without_scrollbars(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary({"sum_inntekter": 1000.0})

    assert page.metrics_table.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert page.threshold_table.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert page.metrics_table.minimumHeight() > 0


def test_editor_expands_and_restores_row_height(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary({"sum_inntekter": 1000.0})

    delegate = page.metrics_table.itemDelegate()
    model_index = page.metrics_table.model().index(0, 2)
    editor = delegate.createEditor(
        page.metrics_table, page.metrics_table.viewOptions(), model_index
    )
    base_height = page.metrics_table.rowHeight(0)

    QApplication.sendEvent(editor, QEvent(QEvent.FocusIn))
    expanded_height = page.metrics_table.rowHeight(0)
    assert expanded_height >= base_height

    QApplication.sendEvent(editor, QEvent(QEvent.FocusOut))
    restored_height = page.metrics_table.rowHeight(0)
    assert restored_height == base_height
    delegate.destroyEditor(editor, model_index)


def test_click_outside_closes_editor(qapp: QApplication) -> None:
    page = SummaryPage("Vesentlighet", "Test")
    page.update_summary({"sum_inntekter": 1000.0})

    percent_item = page.metrics_table.item(0, 2)
    assert percent_item is not None

    page.metrics_table.editItem(percent_item)
    delegate = page.metrics_table.itemDelegate()
    editor = getattr(delegate, "active_editor", None)

    assert isinstance(editor, QLineEdit)
    assert page.metrics_table.state() == QAbstractItemView.EditingState

    click_event = QMouseEvent(
        QEvent.MouseButtonPress,
        QPointF(1, 1),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(page.industry_label, click_event)
    qapp.processEvents()

    assert getattr(delegate, "active_editor", None) is None
    assert page.metrics_table.state() != QAbstractItemView.EditingState
