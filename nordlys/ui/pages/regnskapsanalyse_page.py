"""Regnskapsanalyse-side for Nordlys UI."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWidgets import QWIDGETSIZE_MAX
except ImportError:  # PySide6 < 6.7
    QWIDGETSIZE_MAX = 16777215

from ... import regnskap
from ...utils import lazy_pandas
from ..delegates import BOTTOM_BORDER_ROLE, TOP_BORDER_ROLE
from ..tables import (
    apply_compact_row_heights,
    compact_row_base_height,
    create_table_widget,
    populate_table,
    suspend_table_updates,
)
from ..widgets import CardFrame

pd = lazy_pandas()

__all__ = ["RegnskapsanalysePage"]

class RegnskapsanalysePage(QWidget):
    """Visning som oppsummerer balanse og resultat fra saldobalansen."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.analysis_card = CardFrame(
            "Regnskapsanalyse",
            "Balansepostene til venstre og resultatpostene til høyre for enkel sammenligning.",
        )
        self.analysis_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.balance_section = QWidget()
        self.balance_section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        balance_layout = QVBoxLayout(self.balance_section)
        balance_layout.setContentsMargins(0, 0, 0, 0)
        balance_layout.setSpacing(4)
        self.balance_title = QLabel("Balanse")
        self.balance_title.setObjectName("analysisSectionTitle")
        balance_layout.addWidget(self.balance_title)
        self.balance_info = QLabel(
            "Importer en SAF-T saldobalanse for å se fordelingen av eiendeler og gjeld."
        )
        self.balance_info.setWordWrap(True)
        balance_layout.addWidget(self.balance_info)
        self.balance_table = create_table_widget()
        self.balance_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._configure_analysis_table(self.balance_table, font_point_size=8)
        balance_layout.addWidget(self.balance_table, 1)
        self.balance_table.hide()

        self.result_section = QWidget()
        self.result_section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        result_layout = QVBoxLayout(self.result_section)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(0)
        self.result_title = QLabel("Resultat")
        self.result_title.setObjectName("analysisSectionTitle")
        self.result_title.setContentsMargins(0, 0, 0, 4)
        result_layout.addWidget(self.result_title)
        self.result_info = QLabel(
            "Importer en SAF-T saldobalanse for å beregne resultatpostene."
        )
        self.result_info.setWordWrap(True)
        self.result_info.setContentsMargins(0, 0, 0, 4)
        result_layout.addWidget(self.result_info)
        self.result_table = create_table_widget()
        self.result_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._configure_analysis_table(self.result_table, font_point_size=8)
        result_layout.addWidget(self.result_table)
        result_layout.setAlignment(self.result_table, Qt.AlignTop)
        result_layout.addStretch(1)
        self.result_table.hide()

        self._table_delegate = AnalysisTableDelegate(self)
        self.balance_table.setItemDelegate(self._table_delegate)
        self.result_table.setItemDelegate(self._table_delegate)

        analysis_container = QWidget()
        analysis_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        analysis_layout = QHBoxLayout(analysis_container)
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.setSpacing(0)

        divider = QFrame()
        divider.setObjectName("analysisDivider")
        divider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        divider.setFrameShape(QFrame.NoFrame)
        divider.setFixedWidth(12)

        analysis_layout.addWidget(self.balance_section, 1)
        analysis_layout.addWidget(divider)
        analysis_layout.addWidget(self.result_section, 1)

        self.analysis_card.add_widget(analysis_container)
        layout.addWidget(self.analysis_card, 1)

        self._prepared_df: Optional[pd.DataFrame] = None
        self._fiscal_year: Optional[str] = None

    def set_dataframe(
        self, df: Optional[pd.DataFrame], fiscal_year: Optional[str] = None
    ) -> None:
        self._fiscal_year = (
            fiscal_year.strip() if fiscal_year and fiscal_year.strip() else None
        )
        if df is None or df.empty:
            self._prepared_df = None
            self._clear_balance_table()
            self._clear_result_table()
            return

        self._prepared_df = regnskap.prepare_regnskap_dataframe(df)
        self._update_balance_table()
        self._update_result_table()

    def _year_headers(self) -> Tuple[str, str]:
        if self._fiscal_year and self._fiscal_year.isdigit():
            current = self._fiscal_year
            previous = str(int(self._fiscal_year) - 1)
        else:
            current = self._fiscal_year or "Nå"
            previous = "I fjor"
        return current, previous

    def _clear_balance_table(self) -> None:
        self.balance_table.hide()
        self.balance_table.setRowCount(0)
        self.balance_info.show()
        self._reset_analysis_table_height(self.balance_table)

    def _clear_result_table(self) -> None:
        self.result_table.hide()
        self.result_table.setRowCount(0)
        self.result_info.show()
        self._reset_analysis_table_height(self.result_table)

    def _update_balance_table(self) -> None:
        if self._prepared_df is None or self._prepared_df.empty:
            self._clear_balance_table()
            return

        rows = regnskap.compute_balance_analysis(self._prepared_df)
        current_label, previous_label = self._year_headers()
        table_rows: List[Tuple[object, object, object, object]] = []
        for row in rows:
            if row.is_header:
                table_rows.append((row.label, "", "", ""))
            else:
                table_rows.append((row.label, row.current, row.previous, row.change))
        populate_table(
            self.balance_table,
            ["Kategori", current_label, previous_label, "Endring"],
            table_rows,
            money_cols={1, 2, 3},
        )
        self.balance_info.hide()
        self.balance_table.show()
        self._apply_balance_styles()
        self._apply_change_coloring(self.balance_table)
        self._lock_analysis_column_widths(self.balance_table)
        self._schedule_table_height_adjustment(self.balance_table)

    def _update_result_table(self) -> None:
        if self._prepared_df is None or self._prepared_df.empty:
            self._clear_result_table()
            return

        rows = regnskap.compute_result_analysis(self._prepared_df)
        current_label, previous_label = self._year_headers()
        table_rows: List[Tuple[object, object, object, object]] = []
        for row in rows:
            if row.is_header:
                table_rows.append((row.label, "", "", ""))
            else:
                table_rows.append((row.label, row.current, row.previous, row.change))
        populate_table(
            self.result_table,
            ["Kategori", current_label, previous_label, "Endring"],
            table_rows,
            money_cols={1, 2, 3},
        )
        self.result_info.hide()
        self.result_table.show()
        self._apply_change_coloring(self.result_table)
        self._lock_analysis_column_widths(self.result_table)
        self._schedule_table_height_adjustment(self.result_table)

    def _configure_analysis_table(
        self,
        table: QTableWidget,
        *,
        font_point_size: int,
    ) -> None:
        font = table.font()
        font.setPointSize(font_point_size)
        table.setFont(font)
        header = table.horizontalHeader()
        header_font = header.font()
        header_font.setPointSize(font_point_size)
        header.setFont(header_font)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(70)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        vertical_header = table.verticalHeader()
        vertical_header.setSectionResizeMode(QHeaderView.Fixed)
        setter = getattr(table, "setUniformRowHeights", None)
        if callable(setter):
            setter(True)
        table.setStyleSheet("QTableWidget::item { padding: 0px 6px; }")
        apply_compact_row_heights(table)

    def _lock_analysis_column_widths(self, table: QTableWidget) -> None:
        header = table.horizontalHeader()
        column_count = table.columnCount()
        if column_count == 0:
            return
        for col in range(column_count):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        table.resizeColumnsToContents()

    def _schedule_table_height_adjustment(self, table: QTableWidget) -> None:
        QTimer.singleShot(0, lambda tbl=table: self._set_analysis_table_height(tbl))

    def _set_analysis_table_height(self, table: QTableWidget) -> None:
        if table.rowCount() == 0:
            self._reset_analysis_table_height(table)
            return
        header_height = table.horizontalHeader().height()
        default_row = (
            table.verticalHeader().defaultSectionSize()
            or compact_row_base_height(table)
        )
        rows_height = default_row * table.rowCount()
        grid_extra = max(0, table.rowCount() - 1)
        rows_height += grid_extra
        buffer = max(16, default_row // 2)
        frame = table.frameWidth() * 2
        margins = table.contentsMargins()
        total = (
            header_height
            + rows_height
            + buffer
            + frame
            + margins.top()
            + margins.bottom()
        )
        table.setMinimumHeight(total)
        table.setMaximumHeight(total)

    def _reset_analysis_table_height(self, table: QTableWidget) -> None:
        table.setMinimumHeight(0)
        table.setMaximumHeight(QWIDGETSIZE_MAX)

    def _apply_balance_styles(self) -> None:
        bold_labels = {
            "Eiendeler",
            "Egenkapital og gjeld",
            "Avvik",
            "Sum eiendeler",
            "Sum egenkapital og gjeld",
        }
        bottom_border_labels = {
            "Eiendeler",
            "Egenkapital og gjeld",
            "Kontroll",
            "Kontanter, bankinnskudd o.l.",
            "Kortsiktig gjeld",
            "Sum eiendeler",
            "Sum egenkapital og gjeld",
        }
        top_border_labels = {"Eiendeler", "Sum eiendeler", "Sum egenkapital og gjeld"}
        table = self.balance_table
        with suspend_table_updates(table):
            labels: List[str] = []
            for row_idx in range(table.rowCount()):
                label_item = table.item(row_idx, 0)
                labels.append(label_item.text().strip() if label_item else "")
            for row_idx in range(table.rowCount()):
                label_text = labels[row_idx]
                if not label_text:
                    continue
                is_bold = label_text in bold_labels
                has_bottom_border = label_text in bottom_border_labels
                has_top_border = label_text in top_border_labels
                next_label = labels[row_idx + 1] if row_idx + 1 < len(labels) else ""
                if has_bottom_border and next_label in top_border_labels and next_label:
                    has_bottom_border = False
                for col_idx in range(table.columnCount()):
                    item = table.item(row_idx, col_idx)
                    if item is None:
                        continue
                    font = item.font()
                    font.setBold(is_bold)
                    item.setFont(font)
                    item.setData(BOTTOM_BORDER_ROLE, has_bottom_border)
                    item.setData(TOP_BORDER_ROLE, has_top_border)
        table.viewport().update()

    def _apply_change_coloring(self, table: QTableWidget) -> None:
        change_col = 3
        green = QBrush(QColor(21, 128, 61))
        red = QBrush(QColor(220, 38, 38))
        default_brush = QBrush(QColor(15, 23, 42))
        with suspend_table_updates(table):
            for row_idx in range(table.rowCount()):
                item = table.item(row_idx, change_col)
                if item is None:
                    continue
                label_item = table.item(row_idx, 0)
                label_text = label_item.text().strip().lower() if label_item else ""
                if label_text != "avvik":
                    item.setForeground(default_brush)
                    continue
                value = item.data(Qt.UserRole)
                if value is None:
                    item.setForeground(default_brush)
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    item.setForeground(default_brush)
                    continue
                if abs(numeric) < 1e-6:
                    item.setForeground(green)
                elif numeric < 0:
                    item.setForeground(red)
                else:
                    item.setForeground(green)
        table.viewport().update()

    def update_comparison(
        self,
        _rows: Optional[
            Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]
        ],
    ) -> None:
        return
