from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableView,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWidgets import QWIDGETSIZE_MAX
except ImportError:  # PySide6 < 6.7
    QWIDGETSIZE_MAX = 16777215

from ... import regnskap
from ...utils import format_currency, format_difference, lazy_pandas
from ..delegates import (
    AnalysisTableDelegate,
    CompactRowDelegate,
    BOTTOM_BORDER_ROLE,
    TOP_BORDER_ROLE,
)
from ..helpers import SignalBlocker
from ..models import SaftTableCell, SaftTableModel, SaftTableSource
from ..tables import (
    apply_compact_row_heights,
    compact_row_base_height,
    create_table_widget,
    populate_table,
    suspend_table_updates,
)
from ..widgets import CardFrame

pd = lazy_pandas()

__all__ = [
    "SummaryPage",
    "ComparisonPage",
    "RegnskapsanalysePage",
    "SammenstillingsanalysePage",
]


class SummaryPage(QWidget):
    """Side for vesentlighetsvurdering med tabell og forklaring."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.table = create_table_widget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Nøkkel", "Beløp"])
        self.card.add_widget(self.table)

        layout.addWidget(self.card)
        layout.addStretch(1)

    def update_summary(self, summary: Optional[Dict[str, float]]) -> None:
        if not summary:
            self.table.setRowCount(0)
            return
        rows = [
            ("Relevante beløp", None),
            ("EBIT", summary.get("ebit")),
            ("Årsresultat", summary.get("arsresultat")),
            ("Eiendeler (UB)", summary.get("eiendeler_UB_brreg")),
            ("Gjeld (UB)", summary.get("gjeld_UB_brreg")),
            ("Balanseavvik (Brreg)", summary.get("balanse_diff_brreg")),
        ]
        populate_table(self.table, ["Nøkkel", "Beløp"], rows, money_cols={1})


class ComparisonPage(QWidget):
    """Sammenstilling mellom SAF-T og Regnskapsregisteret."""

    def __init__(
        self,
        title: str = "Regnskapsanalyse",
        subtitle: str = "Sammenligner SAF-T data med nøkkeltall hentet fra Regnskapsregisteret.",
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.table = create_table_widget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            [
                "Nøkkel",
                "SAF-T",
                "Brreg",
                "Avvik",
            ]
        )
        self.card.add_widget(self.table)
        layout.addWidget(self.card)
        layout.addStretch(1)

    def update_comparison(
        self,
        rows: Optional[
            Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]
        ],
    ) -> None:
        if not rows:
            self.table.setRowCount(0)
            return
        formatted_rows = [
            (
                label,
                format_currency(saf_v),
                format_currency(brreg_v),
                format_difference(saf_v, brreg_v),
            )
            for label, saf_v, brreg_v, _ in rows
        ]
        populate_table(
            self.table,
            ["Nøkkel", "SAF-T", "Brreg", "Avvik"],
            formatted_rows,
            money_cols={1, 2, 3},
        )


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
