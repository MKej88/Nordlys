"""Sammenstillingsside for kostnadskonti."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableView,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWidgets import QWIDGETSIZE_MAX
except ImportError:  # PySide6 < 6.7
    QWIDGETSIZE_MAX = 16777215

from ... import regnskap
from ...helpers.formatting import format_currency
from ...helpers.lazy_imports import lazy_pandas
from ..delegates import CompactRowDelegate
from ..helpers import SignalBlocker
from ..models import SaftTableCell, SaftTableModel, SaftTableSource
from ..tables import apply_compact_row_heights
from ..widgets import CardFrame

pd = lazy_pandas()

__all__ = ["SammenstillingsanalysePage"]


class SammenstillingsanalysePage(QWidget):
    """Side som viser detaljert sammenligning av kostnadskonti."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.cost_card = CardFrame(
            "Sammenligning av kostnadskonti",
            "Viser endringene mellom inneværende år og fjoråret for konti 4xxx–8xxx.",
        )
        self.cost_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.cost_info = QLabel(
            "Importer en SAF-T saldobalanse for å analysere kostnadskonti."
        )
        self.cost_info.setWordWrap(True)
        self.cost_card.add_widget(self.cost_info)

        self._cost_highlight_widget = QWidget()
        highlight_layout = QHBoxLayout(self._cost_highlight_widget)
        highlight_layout.setContentsMargins(0, 0, 0, 0)
        highlight_layout.setSpacing(12)
        highlight_label = QLabel("Marker konti med endring større enn:")
        highlight_label.setObjectName("infoLabel")
        self.cost_threshold = QDoubleSpinBox()
        self.cost_threshold.setDecimals(0)
        self.cost_threshold.setMaximum(1_000_000_000_000)
        self.cost_threshold.setSingleStep(10_000)
        self.cost_threshold.setSuffix(" kr")
        self.cost_threshold.valueChanged.connect(self._on_cost_threshold_changed)
        highlight_layout.addWidget(highlight_label)
        highlight_layout.addWidget(self.cost_threshold)
        highlight_layout.addStretch(1)
        self._cost_highlight_widget.hide()
        self.cost_card.add_widget(self._cost_highlight_widget)

        self._cost_headers = [
            "Konto",
            "Kontonavn",
            "Nå",
            "I fjor",
            "Endring (kr)",
            "Endring (%)",
            "Kommentar",
        ]

        self.cost_model = SaftTableModel(self)
        self.cost_model.set_window_size(200)
        self.cost_model.set_edit_callback(self._on_cost_cell_changed)

        self.cost_proxy = QSortFilterProxyModel(self)
        self.cost_proxy.setSourceModel(self.cost_model)
        self.cost_proxy.setDynamicSortFilter(True)
        self.cost_proxy.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.cost_proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.cost_proxy.setSortRole(Qt.UserRole)

        self.cost_table = QTableView()
        self.cost_table.setAlternatingRowColors(True)
        self.cost_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cost_table.setFocusPolicy(Qt.NoFocus)
        self.cost_table.setSortingEnabled(True)
        self.cost_table.setModel(self.cost_proxy)
        self.cost_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cost_table.setMinimumHeight(360)
        self.cost_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.cost_table.verticalScrollBar().setStyleSheet(
            "QScrollBar:vertical {"
            " background: #E2E8F0;"
            " width: 18px;"
            " margin: 6px 4px;"
            " border-radius: 9px;"
            "}"
            "QScrollBar::handle:vertical {"
            " background: #1D4ED8;"
            " border-radius: 9px;"
            " min-height: 32px;"
            "}"
            "QScrollBar::handle:vertical:hover {"
            " background: #1E3A8A;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            " height: 0;"
            "}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            " background: transparent;"
            "}"
        )
        self.cost_table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
        )
        header = self.cost_table.horizontalHeader()
        header.setMinimumSectionSize(0)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        self.cost_table.sortByColumn(0, Qt.AscendingOrder)
        vertical_header = self.cost_table.verticalHeader()
        vertical_header.setVisible(False)
        vertical_header.setSectionResizeMode(QHeaderView.Fixed)
        uniform_setter = getattr(self.cost_table, "setUniformRowHeights", None)
        if callable(uniform_setter):
            uniform_setter(True)
        delegate = CompactRowDelegate(self.cost_table)
        self.cost_table.setItemDelegate(delegate)
        self.cost_table._compact_delegate = delegate  # type: ignore[attr-defined]
        self.cost_model.set_source(SaftTableSource(self._cost_headers, []))
        apply_compact_row_heights(self.cost_table)
        self.cost_table.hide()
        self.cost_card.add_widget(self.cost_table)

        self.btn_cost_show_more = QPushButton("Vis mer")
        self.btn_cost_show_more.clicked.connect(self._on_cost_fetch_more)
        self.btn_cost_show_more.setVisible(False)
        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 6, 0, 0)
        button_layout.addStretch(1)
        button_layout.addWidget(self.btn_cost_show_more)
        self.cost_card.add_widget(button_row)

        layout.addWidget(self.cost_card, 1)

        self._prepared_df: Optional[pd.DataFrame] = None
        self._fiscal_year: Optional[str] = None
        self._cost_comments: Dict[str, str] = {}

    def set_dataframe(
        self, df: Optional[pd.DataFrame], fiscal_year: Optional[str] = None
    ) -> None:
        self._fiscal_year = (
            fiscal_year.strip() if fiscal_year and fiscal_year.strip() else None
        )
        self._cost_comments.clear()
        if df is None or df.empty:
            self._prepared_df = None
            self._clear_cost_table()
            return

        self._prepared_df = regnskap.prepare_regnskap_dataframe(df)
        self._update_cost_table()

    def _year_headers(self) -> Tuple[str, str]:
        if self._fiscal_year and self._fiscal_year.isdigit():
            current = self._fiscal_year
            previous = str(int(self._fiscal_year) - 1)
        else:
            current = self._fiscal_year or "Nå"
            previous = "I fjor"
        return current, previous

    def _clear_cost_table(self) -> None:
        self.cost_table.hide()
        self.cost_model.set_source(SaftTableSource(self._cost_headers, []))
        self._update_cost_show_more_visibility()
        apply_compact_row_heights(self.cost_table)
        self.cost_info.setText(
            "Importer en SAF-T saldobalanse for å analysere kostnadskonti."
        )
        self.cost_info.show()
        self._cost_highlight_widget.hide()
        self._cost_comments.clear()
        with SignalBlocker(self.cost_threshold):
            self.cost_threshold.setValue(0.0)

    def _update_cost_table(self) -> None:
        if self._prepared_df is None or self._prepared_df.empty:
            self._clear_cost_table()
            return

        prepared = self._prepared_df
        konto_series = prepared.get("konto", pd.Series("", index=prepared.index))
        mask = (
            konto_series.astype(str)
            .str.strip()
            .str.startswith(("4", "5", "6", "7", "8"))
        )
        cost_df = prepared.loc[mask].copy()

        if cost_df.empty:
            self.cost_table.hide()
            self.cost_info.setText(
                "Fant ingen kostnadskonti (4xxx–8xxx) i den importerte saldobalansen."
            )
            self.cost_info.show()
            self._cost_highlight_widget.hide()
            return

        cost_df.sort_values(
            by="konto",
            key=lambda s: s.astype(str).str.strip(),
            inplace=True,
        )

        current_values = pd.to_numeric(cost_df.get("UB"), errors="coerce").fillna(0.0)
        previous_values = pd.to_numeric(cost_df.get("forrige"), errors="coerce").fillna(
            0.0
        )

        current_label, previous_label = self._year_headers()
        headers = [
            "Konto",
            "Kontonavn",
            current_label,
            previous_label,
            "Endring (kr)",
            "Endring (%)",
            "Kommentar",
        ]

        konto_values = (
            cost_df.get("konto", pd.Series("", index=cost_df.index))
            .astype(str)
            .str.strip()
        )
        navn_series = cost_df.get("navn", pd.Series("", index=cost_df.index))
        navn_values = navn_series.fillna("").astype(str).str.strip()

        rows = []
        for row_idx, (konto, navn, current, previous) in enumerate(
            zip(konto_values, navn_values, current_values, previous_values)
        ):
            change_value = float(current - previous)
            previous_abs = abs(previous)
            if previous_abs > 1e-6:
                change_percent = (change_value / previous_abs) * 100.0
            elif abs(change_value) > 1e-6:
                change_percent = math.copysign(math.inf, change_value)
            else:
                change_percent = 0.0
            rows.append(
                (
                    konto or "",
                    navn or "",
                    float(current),
                    float(previous),
                    change_value,
                    change_percent,
                )
            )

        self._cost_headers = headers

        row_cells: list[list[SaftTableCell]] = []
        for row_idx, (
            konto,
            navn,
            current,
            previous,
            change_value,
            change_percent,
        ) in enumerate(rows):
            konto_display = konto or "—"
            konto_cell = SaftTableCell(
                value=konto_display,
                display=konto_display,
                sort_value=konto or "",
                alignment=Qt.AlignLeft | Qt.AlignVCenter,
            )
            navn_display = navn or "—"
            navn_cell = SaftTableCell(
                value=navn_display,
                display=navn_display,
                sort_value=navn or "",
                alignment=Qt.AlignLeft | Qt.AlignVCenter,
            )
            current_cell = SaftTableCell(
                value=current,
                display=format_currency(current),
                sort_value=current,
                alignment=Qt.AlignRight | Qt.AlignVCenter,
            )
            previous_cell = SaftTableCell(
                value=previous,
                display=format_currency(previous),
                sort_value=previous,
                alignment=Qt.AlignRight | Qt.AlignVCenter,
            )
            change_cell = SaftTableCell(
                value=change_value,
                display=format_currency(change_value),
                sort_value=change_value,
                alignment=Qt.AlignRight | Qt.AlignVCenter,
            )
            percent_cell = SaftTableCell(
                value=change_percent,
                display=self._format_percent(change_percent),
                sort_value=change_percent,
                alignment=Qt.AlignRight | Qt.AlignVCenter,
            )
            comment_key = konto or f"row-{row_idx}"
            comment_text = self._cost_comments.get(comment_key, "")
            comment_cell = SaftTableCell(
                value=comment_text,
                display=comment_text,
                sort_value=comment_text,
                editable=True,
                alignment=Qt.AlignLeft | Qt.AlignVCenter,
                user_value=comment_key,
            )
            row_cells.append(
                [
                    konto_cell,
                    navn_cell,
                    current_cell,
                    previous_cell,
                    change_cell,
                    percent_cell,
                    comment_cell,
                ]
            )

        source = SaftTableSource(headers, row_cells)
        self.cost_model.set_source(source)
        apply_compact_row_heights(self.cost_table)
        self.cost_info.hide()
        self.cost_table.show()
        self._cost_highlight_widget.show()
        self._update_cost_show_more_visibility()
        self._apply_cost_highlighting()
        self.cost_table.scrollToTop()
        self._auto_resize_cost_columns()

    @staticmethod
    def _format_percent(value: Optional[float]) -> str:
        if value is None:
            return "—"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "—"
        if math.isinf(numeric):
            return "∞ %" if numeric > 0 else "-∞ %"
        return f"{numeric:.1f} %"

    def _apply_cost_highlighting(self) -> None:
        threshold = float(self.cost_threshold.value())
        highlight_brush = QBrush(QColor(254, 243, 199))
        row_count = self.cost_model.rowCount()
        column_count = self.cost_model.columnCount()
        for row_idx in range(row_count):
            change_cell = self.cost_model.get_cell(row_idx, 4)
            if change_cell is None:
                continue
            raw_value = (
                change_cell.sort_value
                if change_cell.sort_value is not None
                else change_cell.value
            )
            try:
                numeric = abs(float(raw_value))
            except (TypeError, ValueError):
                numeric = 0.0
            highlight = threshold > 0.0 and numeric >= threshold
            brush = highlight_brush if highlight else None
            for col_idx in range(column_count):
                if col_idx == 6:
                    continue
                self.cost_model.set_cell_background(row_idx, col_idx, brush)
        self.cost_table.viewport().update()

    def _on_cost_threshold_changed(self, _value: float) -> None:
        if self.cost_table.isVisible():
            self._apply_cost_highlighting()

    def _update_cost_show_more_visibility(self) -> None:
        can_fetch_more = self.cost_model.canFetchMore()
        self.btn_cost_show_more.setVisible(can_fetch_more)
        self.btn_cost_show_more.setEnabled(can_fetch_more)

    def _on_cost_fetch_more(self) -> None:
        fetched = self.cost_model.fetch_more()
        if fetched:
            apply_compact_row_heights(self.cost_table)
            self._apply_cost_highlighting()
            self._auto_resize_cost_columns()
        self._update_cost_show_more_visibility()

    def _on_cost_cell_changed(self, row: int, column: int, cell: SaftTableCell) -> None:
        if column != 6:
            return
        key = cell.user_value
        if not key:
            konto_cell = self.cost_model.get_cell(row, 0)
            key = (
                konto_cell.sort_value
                if konto_cell and konto_cell.sort_value
                else (konto_cell.value if konto_cell else None)
            )
        if not key:
            return
        text_value = (
            cell.value if isinstance(cell.value, str) else str(cell.value or "")
        )
        text = text_value.strip()
        if text:
            self._cost_comments[str(key)] = text
        else:
            self._cost_comments.pop(str(key), None)

    def _auto_resize_cost_columns(self) -> None:
        """Tilpasser kolonnebreddene til innholdet uten å fjerne stretching."""

        header = self.cost_table.horizontalHeader()
        column_count = self.cost_model.columnCount()
        if column_count <= 0:
            return

        stretch_sections: List[int] = []
        for section in range(column_count):
            if header.sectionResizeMode(section) == QHeaderView.Stretch:
                stretch_sections.append(section)
                header.setSectionResizeMode(section, QHeaderView.ResizeToContents)

        target_widths: List[int] = []
        for section in range(column_count):
            self.cost_table.resizeColumnToContents(section)
            header_hint = header.sectionSizeHint(section)
            data_hint = self.cost_table.sizeHintForColumn(section)
            target_widths.append(max(header_hint, data_hint, 0))

        margin = header.style().pixelMetric(QStyle.PM_HeaderMargin, None, header)
        padding = max(0, margin) * 2
        for section, target in enumerate(target_widths):
            if target > 0:
                header.resizeSection(section, target + padding)

        for section in stretch_sections:
            header.setSectionResizeMode(section, QHeaderView.Stretch)
            target = target_widths[section]
            if target > 0:
                header.resizeSection(section, target + padding)

        header.setStretchLastSection(column_count - 1 in stretch_sections)
