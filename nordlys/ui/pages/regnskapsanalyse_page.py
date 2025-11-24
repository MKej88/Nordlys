"""Regnskapsanalyse-side for Nordlys UI."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QTableWidget,
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
from ..data_manager.dataset_store import SummarySnapshot
from ..delegates import BOTTOM_BORDER_ROLE, TOP_BORDER_ROLE
from ..delegates import AnalysisTableDelegate
from ..tables import (
    apply_compact_row_heights,
    compact_row_base_height,
    create_table_widget,
    populate_table,
    suspend_table_updates,
)
from ..widgets import CardFrame


@dataclass(frozen=True)
class KeyMetricDefinition:
    """Beskriver én nøkkeltallsberegning."""

    title: str
    calculator: Callable[
        [Mapping[str, float], Optional[Mapping[str, float]]], Optional[float]
    ]
    unit: str
    evaluator: Callable[[Optional[float]], str]


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
            (
                "Balanseposter, resultat og nøkkeltall samlet i én visning. "
                "Velg seksjonene under for å bytte fokus."
            ),
        )
        self.analysis_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._section_buttons: List[QPushButton] = []
        self._section_container = QWidget()
        section_layout = QVBoxLayout(self._section_container)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(16)

        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(12)
        section_layout.addLayout(nav_layout)

        self.section_stack = QStackedLayout()
        section_layout.addLayout(self.section_stack)

        for idx, title in enumerate(
            ["Siste 2 år", "Resultat flere år", "Nøkkeltall", "Oppsummering"]
        ):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda _checked, index=idx: self._set_active_section(index)
            )
            button.setObjectName("analysisSectionButton")
            nav_layout.addWidget(button)
            self._section_buttons.append(button)
        nav_layout.addStretch(1)

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
        result_layout.setSpacing(4)
        self.result_title = QLabel("Resultat")
        self.result_title.setObjectName("analysisSectionTitle")
        result_layout.addWidget(self.result_title)
        self.result_info = QLabel(
            "Importer en SAF-T saldobalanse for å beregne resultatpostene."
        )
        self.result_info.setWordWrap(True)
        result_layout.addWidget(self.result_info)
        self.result_table = create_table_widget()
        self.result_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._configure_analysis_table(self.result_table, font_point_size=8)
        result_layout.addWidget(self.result_table, 1)
        self.result_table.hide()

        self._table_delegate = AnalysisTableDelegate(self)
        self.balance_table.setItemDelegate(self._table_delegate)
        self.result_table.setItemDelegate(self._table_delegate)

        analysis_container = QWidget()
        analysis_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        analysis_layout = QHBoxLayout(analysis_container)
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.setSpacing(0)

        analysis_layout.addWidget(self.balance_section, 1)
        analysis_layout.addSpacing(24)
        analysis_layout.addWidget(self.result_section, 1)
        analysis_layout.setAlignment(self.balance_section, Qt.AlignTop)
        analysis_layout.setAlignment(self.result_section, Qt.AlignTop)

        last_two_widget = QWidget()
        last_two_layout = QVBoxLayout(last_two_widget)
        last_two_layout.setContentsMargins(0, 0, 0, 0)
        last_two_layout.setSpacing(0)
        last_two_layout.addWidget(analysis_container)
        self.section_stack.addWidget(last_two_widget)

        self.multi_year_widget = QWidget()
        multi_layout = QVBoxLayout(self.multi_year_widget)
        multi_layout.setContentsMargins(0, 0, 0, 0)
        multi_layout.setSpacing(10)
        multi_layout.setAlignment(Qt.AlignTop)
        self.multi_year_info = QLabel(
            "Importer flere SAF-T-filer for å sammenligne resultat over tid."
        )
        self.multi_year_info.setWordWrap(True)
        multi_layout.addWidget(self.multi_year_info)

        self.multi_year_table = create_table_widget()
        self.multi_year_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._configure_analysis_table(self.multi_year_table, font_point_size=8)
        self.multi_year_table.setItemDelegate(self._table_delegate)
        multi_layout.addWidget(self.multi_year_table)
        self.multi_year_table.hide()

        self.multi_year_share_container = QWidget()
        share_layout = QVBoxLayout(self.multi_year_share_container)
        share_layout.setContentsMargins(0, 8, 0, 0)
        share_layout.setSpacing(0)

        self.multi_year_share_label = QLabel("% andel av salgsinntekter")
        self.multi_year_share_label.setObjectName("analysisSectionTitle")
        self.multi_year_share_label.setContentsMargins(0, 0, 0, 0)
        self.multi_year_share_label.setProperty("tightSpacing", True)
        self.multi_year_share_label.style().unpolish(self.multi_year_share_label)
        self.multi_year_share_label.style().polish(self.multi_year_share_label)
        share_layout.addWidget(self.multi_year_share_label)

        self.multi_year_share_table = create_table_widget()
        self.multi_year_share_table.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )
        self._configure_analysis_table(self.multi_year_share_table, font_point_size=8)
        share_layout.addWidget(self.multi_year_share_table)

        multi_layout.addWidget(self.multi_year_share_container)
        multi_layout.addStretch(1)
        self.multi_year_share_table.hide()
        self.multi_year_share_container.hide()
        self.section_stack.addWidget(self.multi_year_widget)

        self.key_metrics_widget = QWidget()
        key_layout = QVBoxLayout(self.key_metrics_widget)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(12)
        self.key_metrics_intro = QLabel(
            "Nøkkeltallene nedenfor beregnes automatisk fra SAF-T-dataene. "
            "Tall og vurdering oppdateres når du bytter datasett."
        )
        self.key_metrics_intro.setWordWrap(True)
        self.key_metrics_intro.setObjectName("statusLabel")
        key_layout.addWidget(self.key_metrics_intro)

        self.key_metrics_table = create_table_widget()
        self.key_metrics_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._configure_analysis_table(self.key_metrics_table, font_point_size=9)
        key_layout.addWidget(self.key_metrics_table)
        self.key_metrics_table.hide()
        key_layout.addStretch(1)
        self.section_stack.addWidget(self.key_metrics_widget)

        self.summary_widget = QWidget()
        summary_layout = QVBoxLayout(self.summary_widget)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(12)
        self.summary_profit_label = self._create_summary_label("Lønnsomhet")
        self.summary_liquidity_label = self._create_summary_label("Likviditet")
        self.summary_soliditet_label = self._create_summary_label("Soliditet")
        self.summary_unusual_label = self._create_summary_label("Unormalt")
        self.summary_focus_label = self._create_summary_label("Fokus for revisjonen")
        for widget_label in (
            self.summary_profit_label,
            self.summary_liquidity_label,
            self.summary_soliditet_label,
            self.summary_unusual_label,
            self.summary_focus_label,
        ):
            summary_layout.addWidget(widget_label)
        summary_layout.addStretch(1)
        self.section_stack.addWidget(self.summary_widget)

        self.analysis_card.add_widget(self._section_container)
        layout.addWidget(self.analysis_card, 1)

        self._set_active_section(0)

        self._summary_history: List[SummarySnapshot] = []
        self._comparison_rows: Optional[
            Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]
        ] = None
        self._prepared_df: Optional[pd.DataFrame] = None
        self._fiscal_year: Optional[str] = None
        self.set_summary_history([])

    def _set_active_section(self, index: int) -> None:
        count = self.section_stack.count()
        if count == 0:
            return
        safe_index = max(0, min(index, count - 1))
        self.section_stack.setCurrentIndex(safe_index)
        for idx, button in enumerate(self._section_buttons):
            button.blockSignals(True)
            button.setChecked(idx == safe_index)
            button.blockSignals(False)

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

    def set_summary_history(self, snapshots: Sequence[SummarySnapshot]) -> None:
        self._summary_history = list(snapshots)
        self._update_multi_year_section()
        self._update_key_metrics_section()
        self._update_summary_section()

    def _year_headers(self) -> Tuple[str, str]:
        if self._fiscal_year and self._fiscal_year.isdigit():
            current = self._fiscal_year
            previous = str(int(self._fiscal_year) - 1)
        else:
            current = self._fiscal_year or "Nå"
            previous = "I fjor"
        return current, previous

    def _snapshot_column_label(self, snapshot: SummarySnapshot) -> str:
        base_label = str(snapshot.year) if snapshot.year is not None else snapshot.label
        label = base_label or "—"
        return f"{label}*" if snapshot.is_current else label

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
        spacer_after_labels = {
            "Sum eiendeler",
            "Sum egenkapital og gjeld",
            "Egenkapital",
            "Sum langsiktig gjeld",
        }
        for row in rows:
            if row.is_header:
                table_rows.append((row.label, "", "", ""))
            else:
                table_rows.append((row.label, row.current, row.previous, row.change))
                if row.label in spacer_after_labels:
                    table_rows.append(("", "", "", ""))
        populate_table(
            self.balance_table,
            ["Kategori", current_label, previous_label, "Endring"],
            table_rows,
            money_cols={1, 2, 3},
            hide_zero_rows=True,
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
            if row.label in {"Sum inntekter", "Annen kostnad"}:
                table_rows.append(("", "", "", ""))
        populate_table(
            self.result_table,
            ["Kategori", current_label, previous_label, "Endring"],
            table_rows,
            money_cols={1, 2, 3},
            hide_zero_rows=True,
        )
        self.result_info.hide()
        self.result_table.show()
        self._apply_change_coloring(self.result_table)
        self._apply_result_styles(self.result_table)
        self._lock_analysis_column_widths(self.result_table)
        self._schedule_table_height_adjustment(self.result_table)

    def _create_summary_label(self, title: str) -> QLabel:
        label = QLabel(self._summary_html(title, "Ingen vurdering tilgjengelig ennå."))
        label.setWordWrap(True)
        label.setObjectName("statusLabel")
        return label

    def _summary_html(self, title: str, body: str) -> str:
        return f"<b>{title}</b><br>{body}"

    def _active_snapshot(self) -> Optional[SummarySnapshot]:
        if not self._summary_history:
            return None
        for snapshot in self._summary_history:
            if snapshot.is_current:
                return snapshot
        return self._summary_history[-1]

    def _previous_snapshot(self) -> Optional[SummarySnapshot]:
        if len(self._summary_history) < 2:
            return None
        active = self._active_snapshot()
        if active is None:
            return self._summary_history[-1]
        try:
            index = self._summary_history.index(active)
        except ValueError:
            return None
        if index <= 0:
            return None
        return self._summary_history[index - 1]

    def _get_numeric(self, summary: Mapping[str, float], key: str) -> Optional[float]:
        value = summary.get(key)
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    def _result_margin(self, summary: Mapping[str, float]) -> Optional[float]:
        revenue = self._get_numeric(summary, "driftsinntekter")
        result = self._get_numeric(summary, "arsresultat")
        if revenue is None or abs(revenue) < 1e-6 or result is None:
            return None
        return (result / revenue) * 100

    def _format_percent(self, value: Optional[float]) -> str:
        if value is None:
            return "—"
        return f"{value:.1f} %"

    def _format_metric_value(self, value: Optional[float], unit: str) -> str:
        if value is None:
            return "—"
        if unit == "percent":
            return f"{value:.1f} %"
        if unit == "multiple":
            return f"{value:.2f}"
        return f"{value:.1f}"

    def _total_capital(self, summary: Mapping[str, float]) -> Optional[float]:
        equity = self._get_numeric(summary, "egenkapital_UB")
        debt = self._get_numeric(summary, "gjeld_UB")
        if equity is None and debt is None:
            return None
        return (equity or 0.0) + (debt or 0.0)

    def _key_metric_definitions(self) -> List[KeyMetricDefinition]:
        def good_if_at_least(threshold: float) -> Callable[[Optional[float]], str]:
            def verdict(value: Optional[float]) -> str:
                if value is None:
                    return "Mangler grunnlag"
                return "GOD" if value >= threshold else "SVAK"

            return verdict

        def good_if_above_zero_or_threshold(
            threshold: float,
        ) -> Callable[[Optional[float]], str]:
            def verdict(value: Optional[float]) -> str:
                if value is None:
                    return "Mangler grunnlag"
                if value < 0:
                    return "UNDERSKUDD"
                return "GOD" if value >= threshold else "SVAK"

            return verdict

        def healthy_if_at_most(
            threshold: float, *, bad_label: str = "IKKE SUNN", ok_label: str = "SUNN"
        ) -> Callable[[Optional[float]], str]:
            def verdict(value: Optional[float]) -> str:
                if value is None:
                    return "Mangler grunnlag"
                return ok_label if value <= threshold else bad_label

            return verdict

        def ratio(
            numerator_key: str, denominator_key: str
        ) -> Callable[
            [Mapping[str, float], Optional[Mapping[str, float]]], Optional[float]
        ]:
            def calculator(
                summary: Mapping[str, float], _previous: Optional[Mapping[str, float]]
            ) -> Optional[float]:
                return self._ratio(
                    self._get_numeric(summary, numerator_key),
                    self._get_numeric(summary, denominator_key),
                )

            return calculator

        def average_ratio(
            numerator_key: str,
            denominator_fn: Callable[[Mapping[str, float]], Optional[float]],
        ) -> Callable[
            [Mapping[str, float], Optional[Mapping[str, float]]], Optional[float]
        ]:
            def calculator(
                summary: Mapping[str, float],
                previous_summary: Optional[Mapping[str, float]],
            ) -> Optional[float]:
                denominator_values = [denominator_fn(summary)]
                if previous_summary is not None:
                    denominator_values.append(denominator_fn(previous_summary))
                denominator = self._average(denominator_values)
                if denominator is None or abs(denominator) < 1e-6:
                    return None
                numerator = self._get_numeric(summary, numerator_key)
                if numerator is None:
                    return None
                return (numerator / denominator) * 100

            return calculator

        def turnover_calculator(
            numerator_key: str,
            total_fn: Callable[[Mapping[str, float]], Optional[float]],
        ) -> Callable[
            [Mapping[str, float], Optional[Mapping[str, float]]], Optional[float]
        ]:
            def calculator(
                summary: Mapping[str, float],
                previous_summary: Optional[Mapping[str, float]],
            ) -> Optional[float]:
                denominator_values = [total_fn(summary)]
                if previous_summary is not None:
                    denominator_values.append(total_fn(previous_summary))
                denominator = self._average(denominator_values)
                if denominator is None or abs(denominator) < 1e-6:
                    return None
                numerator = self._get_numeric(summary, numerator_key)
                if numerator is None:
                    return None
                return numerator / denominator

            return calculator

        return [
            KeyMetricDefinition(
                title="Resultat av driften i %",
                calculator=ratio("ebit", "driftsinntekter"),
                unit="percent",
                evaluator=good_if_at_least(2.0),
            ),
            KeyMetricDefinition(
                title="Resultatmargin",
                calculator=ratio("arsresultat", "driftsinntekter"),
                unit="percent",
                evaluator=good_if_above_zero_or_threshold(2.0),
            ),
            KeyMetricDefinition(
                title="Kapitalens omløpshastighet",
                calculator=turnover_calculator("driftsinntekter", self._total_capital),
                unit="multiple",
                evaluator=good_if_at_least(2.0),
            ),
            KeyMetricDefinition(
                title="EK-rentabilitet før skatt i %",
                calculator=average_ratio("resultat_for_skatt", self._get_equity),
                unit="percent",
                evaluator=good_if_at_least(16.0),
            ),
            KeyMetricDefinition(
                title="EK-andel i %",
                calculator=ratio("egenkapital_UB", "eiendeler_UB"),
                unit="percent",
                evaluator=good_if_at_least(10.0),
            ),
            KeyMetricDefinition(
                title="Gjeldsgrad",
                calculator=turnover_calculator("gjeld_UB", self._get_equity),
                unit="multiple",
                evaluator=healthy_if_at_most(5.0),
            ),
            KeyMetricDefinition(
                title="Rentedekningsgrad",
                calculator=self._interest_coverage,
                unit="multiple",
                evaluator=good_if_at_least(2.0),
            ),
            KeyMetricDefinition(
                title="Tapsbuffer",
                calculator=ratio("egenkapital_UB", "driftsinntekter"),
                unit="percent",
                evaluator=good_if_at_least(10.0),
            ),
        ]

    def _get_equity(self, summary: Mapping[str, float]) -> Optional[float]:
        return self._get_numeric(summary, "egenkapital_UB")

    def _interest_coverage(
        self, summary: Mapping[str, float], _previous: Optional[Mapping[str, float]]
    ) -> Optional[float]:
        ebit = self._get_numeric(summary, "ebit")
        finanskost = self._get_numeric(summary, "finanskostnader")
        if finanskost is None or abs(finanskost) < 1e-6:
            return None
        base = ebit if ebit is not None else 0.0
        return (base + finanskost) / finanskost

    def _key_metric_rows(
        self,
        summary: Mapping[str, float],
        previous_summary: Optional[Mapping[str, float]],
    ) -> List[Tuple[object, object, object, object]]:
        rows: List[Tuple[object, object, object, object]] = []
        for definition in self._key_metric_definitions():
            current_value = definition.calculator(summary, previous_summary)
            previous_value = (
                definition.calculator(previous_summary, None)
                if previous_summary is not None
                else None
            )
            rows.append(
                (
                    definition.title,
                    self._format_metric_value(current_value, definition.unit),
                    self._format_metric_value(previous_value, definition.unit),
                    definition.evaluator(current_value),
                )
            )
        return rows

    def _update_multi_year_section(self) -> None:
        if not self._summary_history:
            self.multi_year_table.hide()
            self.multi_year_share_table.hide()
            self.multi_year_share_container.hide()
            self.multi_year_info.setText(
                "Importer ett eller flere datasett for å se historiske resultater."
            )
            self.multi_year_info.show()
            return

        columns = ["Kategori"] + [
            self._snapshot_column_label(snapshot) for snapshot in self._summary_history
        ]
        table_rows = self._multi_year_value_rows()

        money_cols = set(range(1, len(columns)))
        populate_table(
            self.multi_year_table, columns, table_rows, money_cols=money_cols
        )
        self._apply_result_styles(self.multi_year_table)
        self.multi_year_table.show()
        self.multi_year_info.hide()
        self._schedule_table_height_adjustment(self.multi_year_table, extra_padding=0)
        highlight_column = self._multi_year_active_column()
        share_highlight_column = self._populate_multi_year_share_table(
            columns, highlight_column
        )
        self._highlight_multi_year_column(self.multi_year_table, highlight_column)
        self._highlight_multi_year_column(
            self.multi_year_share_table, share_highlight_column
        )

    def _bruttofortjeneste(self, summary: Mapping[str, float]) -> Optional[float]:
        revenue = self._get_numeric(summary, "driftsinntekter")
        varekostnad = self._get_numeric(summary, "varekostnad")
        if revenue is None or varekostnad is None:
            return None
        return revenue - varekostnad

    def _multi_year_value_rows(self) -> List[List[object]]:
        snapshots = list(self._summary_history)
        row_specs: List[Tuple[str, Iterable[object]]] = []

        def _values_for(key: str) -> Iterable[object]:
            for snapshot in snapshots:
                yield self._get_numeric(snapshot.summary, key)

        row_specs.append(("Salgsinntekter", _values_for("salgsinntekter")))
        row_specs.append(("Annen inntekt", _values_for("annen_inntekt")))
        row_specs.append(("Sum inntekter", _values_for("sum_inntekter")))
        row_specs.append(("", ("" for _ in snapshots)))
        row_specs.append(("Varekostnad", _values_for("varekostnad")))
        row_specs.append(("Lønnskostnader", _values_for("lonn")))
        row_specs.append(("Av-/nedskrivning", _values_for("avskrivninger")))
        row_specs.append(("Andre driftskostnader", _values_for("andre_drift")))
        row_specs.append(("Annen kostnad", _values_for("annen_kost")))
        row_specs.append(("", ("" for _ in snapshots)))
        row_specs.append(("Finansinntekter", _values_for("finansinntekter")))
        row_specs.append(("Finanskostnader", _values_for("finanskostnader")))
        row_specs.append(("Resultat før skatt", _values_for("resultat_for_skatt")))

        rows: List[List[object]] = []
        for label, values in row_specs:
            row = [label]
            row.extend(values)
            rows.append(row)
        return rows

    def _populate_multi_year_share_table(
        self, columns: Sequence[str], highlight_column: Optional[int]
    ) -> Optional[int]:
        percent_rows: List[List[object]] = []
        include_average = len(columns) > 2
        share_columns: List[str] = list(columns)
        average_insert_at: Optional[int] = None
        spacer_insert_at: Optional[int] = None
        share_highlight_column = highlight_column
        if include_average and highlight_column is not None and highlight_column > 1:
            insertion_index = min(highlight_column, len(share_columns))
            share_columns.insert(insertion_index, "Gjennomsnitt")
            share_columns.insert(insertion_index + 1, "")
            average_insert_at = insertion_index
            spacer_insert_at = insertion_index + 1
            if (
                share_highlight_column is not None
                and share_highlight_column >= insertion_index
            ):
                share_highlight_column += 2
        elif include_average:
            average_insert_at = len(share_columns)
            share_columns.append("Gjennomsnitt")
        revenue_per_snapshot = [
            self._get_numeric(snapshot.summary, "salgsinntekter")
            or self._get_numeric(snapshot.summary, "sum_inntekter")
            or self._get_numeric(snapshot.summary, "driftsinntekter")
            for snapshot in self._summary_history
        ]

        def _percent_row(label: str, key: str) -> None:
            row: List[object] = [label]
            percentages: List[Optional[float]] = []
            for idx, snapshot in enumerate(self._summary_history):
                numerator = self._get_numeric(snapshot.summary, key)
                percent = self._ratio(numerator, revenue_per_snapshot[idx])
                percentages.append(percent)
            formatted = [self._format_percent(value) for value in percentages]
            values: List[object] = list(formatted)
            if include_average and average_insert_at is not None:
                avg_value = self._average_without_current(percentages)
                avg_text = self._format_percent(avg_value)
                values.insert(average_insert_at - 1, avg_text)
                if spacer_insert_at is not None:
                    values.insert(spacer_insert_at - 1, "")
            row.extend(values)
            percent_rows.append(row)

        _percent_row("Varekostnad", "varekostnad")
        _percent_row("Lønnskostnader", "lonn")
        _percent_row("Andre driftskostnader", "andre_drift")
        _percent_row("Annen kostnad", "annen_kost")
        _percent_row("Finanskostnader", "finanskostnader")

        money_cols = set(range(1, len(share_columns)))
        populate_table(
            self.multi_year_share_table,
            share_columns,
            percent_rows,
            money_cols=money_cols,
        )
        self.multi_year_share_table.show()
        self.multi_year_share_container.show()
        self._schedule_table_height_adjustment(
            self.multi_year_share_table, extra_padding=0
        )
        return share_highlight_column

    def _multi_year_active_column(self) -> Optional[int]:
        if not self._summary_history:
            return None
        for idx, snapshot in enumerate(self._summary_history):
            if snapshot.is_current:
                return idx + 1
        return len(self._summary_history)

    def _highlight_multi_year_column(
        self, table: QTableWidget, column: Optional[int]
    ) -> None:
        if column is None or table.columnCount() <= column:
            return
        highlight_brush = QBrush(QColor(59, 130, 246, 60))
        default_brush = QBrush()
        with suspend_table_updates(table):
            for col in range(1, table.columnCount()):
                header_item = table.horizontalHeaderItem(col)
                if header_item is not None:
                    font = header_item.font()
                    font.setBold(col == column)
                    header_item.setFont(font)
                for row in range(table.rowCount()):
                    item = table.item(row, col)
                    if item is None:
                        continue
                    font = item.font()
                    if col == column:
                        item.setBackground(highlight_brush)
                        font.setBold(True)
                    else:
                        item.setBackground(default_brush)
                        font.setBold(False)
                    item.setFont(font)
        table.viewport().update()

    def _update_key_metrics_section(self) -> None:
        active = self._active_snapshot()
        previous = self._previous_snapshot()
        if not active:
            self.key_metrics_intro.setText(
                "Importer et datasett for å se beregnede nøkkeltall med vurdering."
            )
            self.key_metrics_table.hide()
            return

        current_label, previous_label = self._year_headers()
        columns = ["Nøkkeltall", current_label, previous_label, "Vurdering"]
        previous_summary = previous.summary if previous is not None else None
        rows = self._key_metric_rows(active.summary, previous_summary)
        populate_table(self.key_metrics_table, columns, rows)
        self.key_metrics_intro.setText(
            "Tallene under er beregnet fra SAF-T og vurdert opp mot faste terskler."
        )
        self.key_metrics_table.show()
        self._schedule_table_height_adjustment(self.key_metrics_table, extra_padding=0)

    def _ratio(
        self, numerator: Optional[float], denominator: Optional[float]
    ) -> Optional[float]:
        if numerator is None or denominator is None or abs(denominator) < 1e-6:
            return None
        return (numerator / denominator) * 100

    def _average(self, values: Iterable[Optional[float]]) -> Optional[float]:
        valid = [value for value in values if value is not None]
        if not valid:
            return None
        return sum(valid) / len(valid)

    def _average_without_current(
        self, values: Sequence[Optional[float]]
    ) -> Optional[float]:
        if len(values) <= 1:
            return None
        return self._average(values[:-1])

    def _update_summary_section(self) -> None:
        active = self._active_snapshot()
        if not active:
            self.summary_profit_label.setText(
                self._summary_html("Lønnsomhet", "Ingen data er tilgjengelig ennå.")
            )
            self.summary_liquidity_label.setText(
                self._summary_html(
                    "Likviditet",
                    "Importer et datasett for å vurdere kontantstrøm.",
                )
            )
            self.summary_soliditet_label.setText(
                self._summary_html(
                    "Soliditet", "Ingen beregning uten eiendeler og egenkapital."
                )
            )
            self.summary_unusual_label.setText(
                self._summary_html(
                    "Unormalt",
                    "Ingen balanse- eller sammenligningstall er tilgjengelig.",
                )
            )
            self.summary_focus_label.setText(
                self._summary_html(
                    "Fokus for revisjonen",
                    "Ingen anbefalinger før et datasett er importert.",
                )
            )
            return

        summary = active.summary
        margin = self._result_margin(summary)
        profit_text = (
            "Resultatmargin kan ikke beregnes uten driftsinntekter."
            if margin is None
            else (
                f"Negativ resultatmargin på {self._format_percent(margin)} krever oppfølging."
                if margin < 0
                else f"Resultatmargin på {self._format_percent(margin)} viser positiv lønnsomhet."
            )
        )
        self.summary_profit_label.setText(self._summary_html("Lønnsomhet", profit_text))

        assets = self._get_numeric(summary, "eiendeler_UB")
        debt = self._get_numeric(summary, "gjeld_UB")
        if assets is not None and debt is not None and abs(debt) > 1e-6:
            liquidity_ratio = assets / debt
        else:
            liquidity_ratio = None
        if liquidity_ratio is None:
            liquidity_text = (
                "Likviditet kan ikke vurderes uten tall for eiendeler og gjeld."
            )
        else:
            liquidity_text = (
                f"Likviditetsindikator (eiendeler/gjeld) på {liquidity_ratio:.1f} tyder på at "
                "eiendelene dekker kortsiktige forpliktelser."
            )
        self.summary_liquidity_label.setText(
            self._summary_html("Likviditet", liquidity_text)
        )

        equity = self._get_numeric(summary, "egenkapital_UB")
        equity_ratio = self._ratio(equity, assets)
        if equity_ratio is None:
            solid_text = "Egenkapitalandel kan ikke beregnes uten eiendeler."
        elif equity_ratio < 25:
            solid_text = f"Lav egenkapitalandel på {self._format_percent(equity_ratio)} må følges opp."
        else:
            solid_text = f"Egenkapitalandel på {self._format_percent(equity_ratio)} vurderes som betryggende."
        self.summary_soliditet_label.setText(
            self._summary_html("Soliditet", solid_text)
        )

        balance_diff = self._get_numeric(summary, "balanse_diff")
        if balance_diff is None or abs(balance_diff) < 1:
            unusual_text = "Ingen balanseavvik er registrert i SAF-T-sammendraget."
        else:
            unusual_text = f"Balanseavvik på {format_currency(balance_diff)} bør undersøkes nærmere."
        comparison_notice = self._comparison_notice()
        if comparison_notice:
            unusual_text = f"{unusual_text} {comparison_notice}"
        self.summary_unusual_label.setText(self._summary_html("Unormalt", unusual_text))

        focus_reasons: List[str] = []
        if margin is not None and margin < 0:
            focus_reasons.append("Underskudd krever fokus på lønnsomhet.")
        if equity_ratio is not None and equity_ratio < 25:
            focus_reasons.append("Lav egenkapitalandel påvirker soliditeten.")
        if balance_diff is not None and abs(balance_diff) > 10000:
            focus_reasons.append("Betydelig balanseavvik må forklares.")
        if not focus_reasons:
            focus_text = "Ingen kritiske funn i nøkkeltallene for nåværende datasett."
        else:
            focus_text = " ".join(focus_reasons[:2])
        self.summary_focus_label.setText(
            self._summary_html("Fokus for revisjonen", focus_text)
        )

    def _comparison_notice(self) -> Optional[str]:
        if not self._comparison_rows:
            return None
        for label, saf_value, brreg_value, _ in self._comparison_rows:
            if (
                label.lower().startswith("driftsinntekter")
                and saf_value is not None
                and brreg_value is not None
            ):
                diff = saf_value - brreg_value
                if abs(diff) > 1000:
                    return (
                        "SAF-T avviker fra Regnskapsregisteret med "
                        f"{format_currency(diff)} på driftsinntekter."
                    )
        return None

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

    def _schedule_table_height_adjustment(
        self, table: QTableWidget, *, extra_padding: int = 16
    ) -> None:
        QTimer.singleShot(
            0,
            lambda tbl=table, padding=extra_padding: self._set_analysis_table_height(
                tbl, padding
            ),
        )

    def _set_analysis_table_height(
        self, table: QTableWidget, extra_padding: int = 16
    ) -> None:
        if table.rowCount() == 0:
            self._reset_analysis_table_height(table)
            return
        header_height = table.horizontalHeader().height()
        vertical_header = table.verticalHeader()
        rows_height = vertical_header.length() if vertical_header else 0
        if rows_height <= 0:
            rows_height = 0
            for row in range(table.rowCount()):
                height = table.rowHeight(row)
                if height <= 0 and vertical_header is not None:
                    height = vertical_header.sectionSize(row)
                if height <= 0:
                    height = compact_row_base_height(table)
                rows_height += height
        buffer = max(0, extra_padding)
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
            "Sum kortsiktig gjeld",
            "Langsiktig gjeld",
            "Kortsiktig gjeld",
            "Sum langsiktig gjeld",
        }
        bottom_border_labels = {
            "Eiendeler",
            "Egenkapital og gjeld",
            "Kontroll",
            "Kontanter, bankinnskudd o.l.",
            "Kortsiktig gjeld",
            "Sum eiendeler",
            "Sum egenkapital og gjeld",
            "Sum kortsiktig gjeld",
            "Langsiktig gjeld",
            "Sum langsiktig gjeld",
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

    def _apply_result_styles(self, table: QTableWidget) -> None:
        bold_labels = {"Sum inntekter", "Resultat før skatt"}
        bottom_border_labels = {"Annen inntekt", "Finanskostnader"}
        spacer_after_labels = {"Sum inntekter", "Annen kostnad"}
        base_height = compact_row_base_height(table)
        spacer_height = max(base_height + 6, int(base_height * 1.6))
        with suspend_table_updates(table):
            labels: List[str] = []
            for row_idx in range(table.rowCount()):
                label_item = table.item(row_idx, 0)
                labels.append(label_item.text().strip() if label_item else "")
            for row_idx, label_text in enumerate(labels):
                prev_label = labels[row_idx - 1] if row_idx > 0 else ""
                is_spacer_row = not label_text and prev_label in spacer_after_labels
                row_height = spacer_height if is_spacer_row else base_height
                if table.rowHeight(row_idx) < row_height:
                    table.setRowHeight(row_idx, row_height)
                is_bold = label_text in bold_labels
                has_bottom_border = label_text in bottom_border_labels
                for col_idx in range(table.columnCount()):
                    item = table.item(row_idx, col_idx)
                    if item is None:
                        continue
                    if col_idx == 0:
                        font = item.font()
                        font.setBold(is_bold)
                        item.setFont(font)
                    item.setData(BOTTOM_BORDER_ROLE, has_bottom_border)
                    item.setData(TOP_BORDER_ROLE, False)
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
        self._comparison_rows = list(_rows) if _rows else None
        self._update_summary_section()
