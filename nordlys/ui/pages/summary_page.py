"""Vesentlighetsside for Nordlys UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..delegates import CompactRowDelegate
from ..tables import (
    compact_row_base_height,
    create_table_widget,
    format_money_norwegian,
    populate_table,
)
from ..helpers import SignalBlocker
from ..widgets import CardFrame

if TYPE_CHECKING:
    from ...industry_groups import IndustryClassification

__all__ = ["SummaryPage"]


@dataclass(frozen=True)
class _MetricSetting:
    label: str
    min_percent: float
    max_percent: float
    amount: Optional[float]


def _format_percent(value: float) -> str:
    return f"{value:.2f}%"


def _parse_percent(text: str) -> Optional[float]:
    sanitized = (text or "").replace("%", "").replace(" ", "").replace(",", ".")
    if not sanitized:
        return None
    try:
        return float(sanitized)
    except ValueError:
        return None


def _percentage_of(amount: Optional[float], percent: float) -> Optional[float]:
    if amount is None:
        return None
    return amount * percent / 100


def _sanitize_amount(amount: Optional[float]) -> Optional[float]:
    if amount is None:
        return None
    return amount if amount >= 0 else None


def _set_row_heights(table: QTableWidget, height: int) -> None:
    header: QHeaderView = table.verticalHeader()
    header.setMinimumSectionSize(height)
    header.setDefaultSectionSize(height)
    header.setSectionResizeMode(QHeaderView.Fixed)
    for row in range(table.rowCount()):
        table.setRowHeight(row, height)


def _fit_table_height(table: QTableWidget) -> None:
    header = table.horizontalHeader()
    header_height = header.height() if header is not None else 0
    margins = table.contentsMargins()
    frame_height = table.frameWidth() * 2
    row_heights = sum(table.rowHeight(row) for row in range(table.rowCount()))
    total_height = header_height + row_heights + frame_height
    total_height += margins.top() + margins.bottom()
    table.setMinimumHeight(total_height)


class _MetricRowBuilder:
    def __init__(self, summary: Mapping[str, float]):
        self._summary = summary

    def build_rows(self) -> list[tuple[object, ...]]:
        rows: list[tuple[object, ...]] = []
        for setting in self._metric_settings():
            sanitized = _sanitize_amount(setting.amount)
            rows.append(
                (
                    setting.label,
                    sanitized,
                    _format_percent(setting.min_percent),
                    _percentage_of(sanitized, setting.min_percent),
                    _format_percent(setting.max_percent),
                    _percentage_of(sanitized, setting.max_percent),
                )
            )
        return rows

    def _metric_settings(self) -> Iterable[_MetricSetting]:
        return [
            _MetricSetting("Driftsinntekter i år", 0.5, 2.0, self._sum_inntekter()),
            _MetricSetting(
                "Bruttofortjeneste",
                1.0,
                1.5,
                self._bruttofortjeneste(),
            ),
            _MetricSetting(
                "Driftsinntekter i fjor",
                0.5,
                1.5,
                self._first_number(
                    self._get_number("driftsinntekter_fjor"),
                    self._get_number("sum_inntekter_fjor"),
                ),
            ),
            _MetricSetting(
                "Overskudd",
                5.0,
                10.0,
                self._first_number(
                    self._get_number("resultat_for_skatt"),
                    self._get_number("arsresultat"),
                ),
            ),
            _MetricSetting("Sum eiendeler", 1.0, 3.0, self._get_number("eiendeler_UB")),
            _MetricSetting(
                "Egenkapital",
                5.0,
                10.0,
                self._get_number("egenkapital_UB"),
            ),
        ]

    def _sum_inntekter(self) -> Optional[float]:
        return self._first_number(
            self._get_number("sum_inntekter"),
            self._get_number("driftsinntekter"),
        )

    def _bruttofortjeneste(self) -> Optional[float]:
        inntekter = self._sum_inntekter()
        varekostnad = self._get_number("varekostnad")
        if inntekter is None or varekostnad is None:
            return None
        return inntekter - varekostnad

    def _get_number(self, key: str) -> Optional[float]:
        value = self._summary.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first_number(*values: Optional[float]) -> Optional[float]:
        for value in values:
            if value is not None:
                return value
        return None


class _SummaryMetricsTable:
    def __init__(self) -> None:
        self.table = create_table_widget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Type", "Beløp", "% fra", "Minimum", "% til", "Maksimum"]
        )
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.delegate = _ExpandingReadableDelegate(self.table)
        self.table.setItemDelegate(self.delegate)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self._populating = False
        self.table.itemChanged.connect(self._on_item_changed)

    def populate(self, summary: Mapping[str, float]) -> None:
        rows = _MetricRowBuilder(summary).build_rows()
        with SignalBlocker(self.table):
            self._populating = True
            populate_table(
                self.table,
                ["Type", "Beløp", "% fra", "Minimum", "% til", "Maksimum"],
                rows,
                money_cols={1, 3, 5},
            )
            self._populating = False
        self._lock_percent_columns()
        _set_row_heights(self.table, 32)
        _fit_table_height(self.table)

    def fit_height(self) -> None:
        _fit_table_height(self.table)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._populating or item.column() not in {2, 4}:
            return

        percent = _parse_percent(item.text())
        if percent is None:
            return

        self._populating = True
        try:
            item.setText(_format_percent(percent))
            amount = self._metric_amount(item.row())
            target_col = 3 if item.column() == 2 else 5
            updated_value = _percentage_of(amount, percent)
            self._update_money_cell(item.row(), target_col, updated_value)
        finally:
            self._populating = False

    def _metric_amount(self, row: int) -> Optional[float]:
        amount_item = self.table.item(row, 1)
        if amount_item is None:
            return None
        data = amount_item.data(Qt.UserRole)
        try:
            return float(data) if data is not None else None
        except (TypeError, ValueError):
            return None

    def _lock_percent_columns(self) -> None:
        percent_columns = {2, 4}
        row_count = self.table.rowCount()
        col_count = self.table.columnCount()
        for row in range(row_count):
            for col in range(col_count):
                item = self.table.item(row, col)
                if item is None:
                    continue
                if col in percent_columns:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def _update_money_cell(
        self, row: int, column: int, value: Optional[float]
    ) -> None:
        target = self.table.item(row, column)
        if target is None:
            target = QTableWidgetItem()
            target.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.table.setItem(row, column, target)
        target.setData(Qt.UserRole, value if value is not None else None)
        display = format_money_norwegian(value) if value is not None else "—"
        target.setText(display)


class _SummaryThresholdTable:
    def __init__(self) -> None:
        self.table = create_table_widget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                "Type",
                "Vesentlighet",
                "Arb.ves",
                "Ubetydelig feilinfo",
                "Utført av",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.delegate = _ExpandingReadableDelegate(self.table)
        self.table.setItemDelegate(self.delegate)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self._populate_rows(["Ordinær", "Skatter og avgifter"])
        _set_row_heights(self.table, 32)
        _fit_table_height(self.table)

    def fit_height(self) -> None:
        _fit_table_height(self.table)

    def _populate_rows(self, labels: Sequence[str]) -> None:
        self.table.setRowCount(len(labels))
        for row, label in enumerate(labels):
            label_item = QTableWidgetItem(label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, label_item)
            for col in range(1, self.table.columnCount()):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                self.table.setItem(row, col, item)


class SummaryPage(QWidget):
    """Side for vesentlighetsvurdering med tabell og forklaring."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.industry_label = QLabel("Bransje: —")
        self.industry_label.setObjectName("statusLabel")
        self.industry_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._metrics_section = _SummaryMetricsTable()
        self.metrics_table = self._metrics_section.table
        self._metrics_delegate = self._metrics_section.delegate

        self._threshold_section = _SummaryThresholdTable()
        self.threshold_table = self._threshold_section.table
        self._threshold_delegate = self._threshold_section.delegate

        self.card.add_widget(self.industry_label)
        self.card.add_widget(self.metrics_table)
        self.card.add_widget(self.threshold_table)

        layout.addWidget(self.card, 1)

        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

    def update_summary(
        self,
        summary: Optional[Mapping[str, float]],
        *,
        industry: Optional["IndustryClassification"] = None,
        industry_error: Optional[str] = None,
    ) -> None:
        self._update_industry_label(industry, industry_error)
        self._metrics_section.populate(summary or {})
        self._threshold_section.fit_height()

    def _update_industry_label(
        self,
        industry: Optional["IndustryClassification"],
        error: Optional[str],
    ) -> None:
        if error:
            self.industry_label.setText(f"Bransje: ikke tilgjengelig ({error})")
            return
        if industry and industry.group:
            self.industry_label.setText(f"Bransje: {industry.group}")
            return
        if industry:
            self.industry_label.setText("Bransje: Ukjent bransje")
            return
        self.industry_label.setText("Bransje: —")

    def eventFilter(  # type: ignore[override]
        self, watched: object, event: QEvent | None
    ) -> bool:
        if event is not None and event.type() == QEvent.MouseButtonPress:
            self._close_editor_on_click(watched, event)
        return super().eventFilter(watched, event)

    def _close_editor_on_click(self, target: object, event: QEvent) -> None:
        if not isinstance(event, QMouseEvent):
            return

        for table, delegate in (
            (self.metrics_table, self._metrics_delegate),
            (self.threshold_table, self._threshold_delegate),
        ):
            editor = delegate.active_editor
            if editor is None:
                continue

            if isinstance(target, QWidget) and (
                target is editor or editor.isAncestorOf(target)
            ):
                continue

            editor.clearFocus()
            self.setFocus(Qt.MouseFocusReason)
            QApplication.sendEvent(editor, QEvent(QEvent.FocusOut))

            if table.state() == QAbstractItemView.EditingState:
                current_item = table.currentItem()
                if current_item is not None:
                    table.closePersistentEditor(current_item)
            delegate.active_editor = None


class _ExpandingReadableDelegate(CompactRowDelegate):
    _ROW_PROPERTY = "_summary_row"

    def __init__(self, parent: QTableWidget) -> None:
        super().__init__(parent)
        self._original_heights: dict[int, int] = {}
        self.active_editor: QLineEdit | None = None

    def createEditor(self, parent, option, index):  # type: ignore[override]
        editor = QLineEdit(parent)
        palette = editor.palette()
        palette.setColor(QPalette.Text, QColor("#0f172a"))
        palette.setColor(QPalette.PlaceholderText, QColor("#94a3b8"))
        palette.setColor(QPalette.Base, QColor("#ffffff"))
        palette.setColor(QPalette.Highlight, QColor("#bfdbfe"))
        palette.setColor(QPalette.HighlightedText, QColor("#0f172a"))
        editor.setPalette(palette)
        editor.setAttribute(Qt.WA_StyledBackground, True)
        editor.setAutoFillBackground(True)
        editor.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        editor.setTextMargins(6, 0, 6, 0)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setProperty(self._ROW_PROPERTY, index.row())
        editor.installEventFilter(self)
        self.active_editor = editor
        return editor

    def setEditorData(self, editor, index):  # type: ignore[override]
        if isinstance(editor, QLineEdit):
            text = index.data(Qt.DisplayRole)
            editor.setText(str(text) if text is not None else "")
            editor.selectAll()
            return
        super().setEditorData(editor, index)

    def destroyEditor(self, editor, index):  # type: ignore[override]
        if isinstance(editor, QLineEdit):
            self._restore_row_height(editor)
            if self.active_editor is editor:
                self.active_editor = None
        super().destroyEditor(editor, index)

    def eventFilter(self, obj, event):  # type: ignore[override]
        if isinstance(obj, QLineEdit):
            if event.type() == QEvent.FocusIn:
                self._expand_row_for_editor(obj)
            elif event.type() in {QEvent.FocusOut, QEvent.Hide}:
                self._restore_row_height(obj)
        return super().eventFilter(obj, event)

    def _expand_row_for_editor(self, editor: QLineEdit) -> None:
        table = self.parent()
        if not isinstance(table, QTableWidget):
            return
        row = editor.property(self._ROW_PROPERTY)
        if not isinstance(row, int):
            return
        header = table.verticalHeader()
        if header is None:
            return
        base_height = header.sectionSize(row)
        if row not in self._original_heights:
            self._original_heights[row] = base_height
        desired_height = max(
            base_height,
            editor.sizeHint().height() + 4,
            compact_row_base_height(table) + 4,
        )
        if desired_height <= base_height:
            return
        header.resizeSection(row, desired_height)
        table.setRowHeight(row, desired_height)

    def _restore_row_height(self, editor: QLineEdit) -> None:
        table = self.parent()
        if not isinstance(table, QTableWidget):
            return
        row = editor.property(self._ROW_PROPERTY)
        if not isinstance(row, int):
            return
        header = table.verticalHeader()
        if header is None:
            return
        current_height = header.sectionSize(row)
        original_height = self._original_heights.pop(row, current_height)
        header.resizeSection(row, original_height)
        table.setRowHeight(row, original_height)
