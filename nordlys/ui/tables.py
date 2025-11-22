from __future__ import annotations

import math
from contextlib import contextmanager
from typing import Iterable, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
)

from ..helpers.lazy_imports import lazy_pandas
from .delegates import CompactRowDelegate

__all__ = [
    "create_table_widget",
    "apply_compact_row_heights",
    "populate_table",
    "suspend_table_updates",
    "format_money_norwegian",
    "format_integer_norwegian",
    "compact_row_base_height",
]

pd = lazy_pandas()


def create_table_widget() -> QTableWidget:
    table = QTableWidget()
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setFocusPolicy(Qt.NoFocus)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.setObjectName("cardTable")
    delegate = CompactRowDelegate(table)
    table.setItemDelegate(delegate)
    table._compact_delegate = delegate  # type: ignore[attr-defined]
    apply_compact_row_heights(table)
    return table


def apply_compact_row_heights(table: QTableWidget | QTableView) -> None:
    header = table.verticalHeader()
    if header is None:
        return
    minimum_height = compact_row_base_height(table)
    header.setMinimumSectionSize(minimum_height)
    header.setDefaultSectionSize(minimum_height)
    header.setSectionResizeMode(QHeaderView.Fixed)

    if isinstance(table, QTableWidget):
        row_count = table.rowCount()
        if row_count == 0:
            return
        for row in range(row_count):
            table.setRowHeight(row, minimum_height)
        return

    model = table.model()
    if model is None:
        return
    row_count = model.rowCount()
    if row_count == 0:
        return
    for row in range(row_count):
        header.resizeSection(row, minimum_height)


def populate_table(
    table: QTableWidget,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    money_cols: Optional[Iterable[int]] = None,
    hide_zero_rows: bool = False,
    zero_value_cols: Optional[Iterable[int]] = None,
) -> None:
    money_idx = set(money_cols or [])
    zero_value_idx = set(zero_value_cols or money_idx)
    row_buffer = list(rows)

    if hide_zero_rows and zero_value_idx:
        row_buffer = [
            row
            for row in row_buffer
            if not _all_numeric_columns_zero(row, zero_value_idx)
        ]

    table.setRowCount(0)
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)

    if not row_buffer:
        table.clearContents()
        apply_compact_row_heights(table)
        return

    sorting_enabled = table.isSortingEnabled()
    table.setSortingEnabled(False)
    table.setUpdatesEnabled(False)

    try:
        table.setRowCount(len(row_buffer))

        for row_idx, row in enumerate(row_buffer):
            for col_idx, value in enumerate(row):
                display = _format_value(value, col_idx in money_idx)
                item = QTableWidgetItem(display)
                if isinstance(value, (int, float)):
                    item.setData(Qt.UserRole, float(value))
                else:
                    item.setData(Qt.UserRole, None)
                if col_idx in money_idx or isinstance(value, (int, float)):
                    item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(row_idx, col_idx, item)
    finally:
        table.setUpdatesEnabled(True)
        table.setSortingEnabled(sorting_enabled)

    table.resizeColumnsToContents()
    apply_compact_row_heights(table)
    window = table.window()
    schedule_hook = getattr(window, "_schedule_responsive_update", None)
    if callable(schedule_hook):
        schedule_hook()


def format_money_norwegian(value: float) -> str:
    truncated = math.trunc(value)
    formatted = f"{truncated:,}"
    return formatted.replace(",", " ")


def format_integer_norwegian(value: float) -> str:
    formatted = f"{int(round(value)):,}"
    return formatted.replace(",", " ")


@contextmanager
def suspend_table_updates(table: QTableWidget):
    """Slår av oppdateringer midlertidig for å gjøre masseendringer raskere."""

    sorting_enabled = table.isSortingEnabled()
    updates_enabled = table.updatesEnabled()
    try:
        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        yield
    finally:
        table.setUpdatesEnabled(updates_enabled)
        table.setSortingEnabled(sorting_enabled)


def compact_row_base_height(table: QTableWidget | QTableView) -> int:
    metrics = table.fontMetrics()
    base_height = metrics.height() if metrics is not None else 0
    return max(12, base_height + 1)


def _format_value(value: object, money: bool) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and math.isnan(value):
        return "—"
    try:
        if isinstance(value, (float, int)) and pd.isna(value):
            return "—"
        if not isinstance(value, (float, int)) and pd.isna(value):  # type: ignore[arg-type]
            return "—"
    except NameError:
        pass
    except Exception:
        pass
    if isinstance(value, (int, float)):
        if money:
            return format_money_norwegian(float(value))
        numeric = float(value)
        if numeric.is_integer():
            return format_integer_norwegian(numeric)
        return format_money_norwegian(numeric)
    return str(value)


def _all_numeric_columns_zero(row: Sequence[object], numeric_cols: set[int]) -> bool:
    numeric_values = [_numeric_value(row, index) for index in numeric_cols]
    has_numeric = any(value is not None for value in numeric_values)
    if not has_numeric:
        return False
    return all((value or 0.0) == 0 for value in numeric_values if value is not None)


def _numeric_value(row: Sequence[object], index: int) -> Optional[float]:
    if index >= len(row):
        return None
    value = row[index]
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
