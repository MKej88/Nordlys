"""PySide6-basert GUI for Nordlys."""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, cast

import pandas as pd
from PySide6.QtCore import (
    QObject,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QBrush, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
)

from ..brreg import fetch_brreg, find_first_by_exact_endkey, map_brreg_metrics
from ..constants import APP_TITLE
from ..saft import (
    CustomerInfo,
    SaftHeader,
    SaftValidationResult,
    SupplierInfo,
    ns4102_summary_from_tb,
    parse_customers,
    parse_saldobalanse,
    parse_saft_header,
    parse_suppliers,
    validate_saft_against_xsd,
)
from ..saft_customers import (
    compute_purchases_per_supplier,
    compute_sales_per_customer,
    parse_saft,
)
from ..utils import format_currency, format_difference


REVISION_TASKS: Dict[str, List[str]] = {
    "rev.innkjop": [
        "Avstem leverandørreskontro mot hovedbok",
        "Analysér kredittider og identifiser avvik",
        "Undersøk store engangskjøp",
    ],
    "rev.lonn": [
        "Kontroller lønnsarter og arbeidsgiveravgift",
        "Stem av mot a-meldinger",
        "Bekreft feriepengene",
    ],
    "rev.kostnad": [
        "Kartlegg større kostnadsdrivere",
        "Analyser periodiseringer",
        "Vurder avgrensninger mot investeringer",
    ],
    "rev.driftsmidler": [
        "Bekreft nyanskaffelser",
        "Stem av avskrivninger mot regnskap",
        "Test disposisjoner ved salg/utrangering",
    ],
    "rev.finans": [
        "Avstem bank og lånesaldo",
        "Test renteberegning og covenants",
        "Bekreft finansielle instrumenter",
    ],
    "rev.varelager": [
        "Vurder telling og lagerforskjeller",
        "Test nedskrivninger",
        "Analyser bruttomarginer",
    ],
    "rev.salg": [
        "Analysér omsetning mot kunderegister",
        "Bekreft vesentlige kontrakter",
        "Test cut-off rundt periodeslutt",
    ],
    "rev.mva": [
        "Stem av mva-koder mot innleverte oppgaver",
        "Kontroller mva-grunnlag",
        "Verifiser justeringer og korrigeringer",
    ],
}


NAV_ICON_FILENAMES: Dict[str, str] = {
    "dashboard": "dashboard.svg",
    "plan.saldobalanse": "balance-scale.svg",
    "plan.kontroll": "shield-check.svg",
    "plan.vesentlighet": "target.svg",
    "plan.regnskapsanalyse": "analytics.svg",
    "plan.sammenstilling": "layers.svg",
    "rev.innkjop": "shopping-bag.svg",
    "rev.lonn": "people.svg",
    "rev.kostnad": "coins.svg",
    "rev.driftsmidler": "gear.svg",
    "rev.finans": "bank.svg",
    "rev.varelager": "boxes.svg",
    "rev.salg": "trend-up.svg",
    "rev.mva": "percent.svg",
}


_ICON_CACHE: Dict[str, Optional[QIcon]] = {}


def _icon_for_navigation(key: str) -> Optional[QIcon]:
    """Returnerer ikon for navigasjonsnøkkelen dersom tilgjengelig."""

    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    filename = NAV_ICON_FILENAMES.get(key)
    if not filename:
        _ICON_CACHE[key] = None
        return None

    icon_path = Path(__file__).resolve().parent.parent / "resources" / "icons" / filename
    if not icon_path.exists():
        _ICON_CACHE[key] = None
        return None

    icon = QIcon(str(icon_path))
    _ICON_CACHE[key] = icon
    return icon


@dataclass
class SaftLoadResult:
    """Resultatobjekt fra bakgrunnslasting av SAF-T."""

    file_path: str
    header: Optional[SaftHeader]
    dataframe: pd.DataFrame
    customers: Dict[str, CustomerInfo]
    customer_sales: Optional[pd.DataFrame]
    suppliers: Dict[str, SupplierInfo]
    supplier_purchases: Optional[pd.DataFrame]
    summary: Optional[Dict[str, float]]
    validation: SaftValidationResult


class SaftLoadWorker(QObject):
    """Arbeider som laster og validerer SAF-T i bakgrunnen."""

    finished: Signal = Signal(object)
    error: Signal = Signal(str)

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self._file_path = file_path

    @Slot()
    def run(self) -> None:
        try:
            tree, ns = parse_saft(self._file_path)
            root = tree.getroot()
            header = parse_saft_header(root)
            dataframe = parse_saldobalanse(root)
            customers = parse_customers(root)
            suppliers = parse_suppliers(root)

            def _parse_date(value: Optional[str]) -> Optional[date]:
                if value is None:
                    return None
                text = value.strip()
                if not text:
                    return None
                try:
                    return date.fromisoformat(text)
                except ValueError:
                    try:
                        return datetime.strptime(text, "%Y-%m-%d").date()
                    except ValueError:
                        return None

            period_start = _parse_date(header.period_start) if header else None
            period_end = _parse_date(header.period_end) if header else None
            customer_sales: Optional[pd.DataFrame] = None
            supplier_purchases: Optional[pd.DataFrame] = None
            if period_start or period_end:
                customer_sales = compute_sales_per_customer(
                    root,
                    ns,
                    date_from=period_start,
                    date_to=period_end,
                )
                supplier_purchases = compute_purchases_per_supplier(
                    root,
                    ns,
                    date_from=period_start,
                    date_to=period_end,
                )
            else:
                analysis_year: Optional[int] = None
                if header and header.fiscal_year:
                    try:
                        analysis_year = int(header.fiscal_year)
                    except (TypeError, ValueError):
                        analysis_year = None
                if analysis_year is None and header and header.period_end:
                    parsed_end = _parse_date(header.period_end)
                    if parsed_end:
                        analysis_year = parsed_end.year
                if analysis_year is None:
                    for tx in root.findall('.//n1:GeneralLedgerEntries/n1:Journal/n1:Transaction', ns):
                        date_element = tx.find('n1:TransactionDate', ns)
                        if date_element is not None and date_element.text:
                            parsed = _parse_date(date_element.text)
                            if parsed:
                                analysis_year = parsed.year
                                break
                if analysis_year is not None:
                    customer_sales = compute_sales_per_customer(root, ns, year=analysis_year)
                    supplier_purchases = compute_purchases_per_supplier(
                        root,
                        ns,
                        year=analysis_year,
                    )

            summary = ns4102_summary_from_tb(dataframe)
            validation = validate_saft_against_xsd(
                self._file_path,
                header.file_version if header else None,
            )
            result = SaftLoadResult(
                file_path=self._file_path,
                header=header,
                dataframe=dataframe,
                customers=customers,
                customer_sales=customer_sales,
                suppliers=suppliers,
                supplier_purchases=supplier_purchases,
                summary=summary,
                validation=validation,
            )
            self.finished.emit(result)
        except Exception as exc:  # pragma: no cover - presenteres i GUI
            self.error.emit(str(exc))


def _create_table_widget() -> QTableWidget:
    table = QTableWidget()
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.setObjectName("cardTable")
    return table


class AnimatedStackedWidget(QStackedWidget):
    """QStackedWidget med fade-animasjon mellom sider."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._fade_duration = 320
        self._animating = False
        self._current_animation: Optional[QPropertyAnimation] = None

    def setCurrentIndex(self, index: int) -> None:  # type: ignore[override]
        widget = self.widget(index)
        if widget is None:
            return
        self.setCurrentWidget(widget)

    def setCurrentWidget(self, widget: QWidget) -> None:  # type: ignore[override]
        if widget is None:
            return
        current = self.currentWidget()
        if current is widget or current is None:
            effect = self._ensure_opacity_effect(widget)
            if effect is not None:
                effect.setOpacity(1.0)
            super().setCurrentWidget(widget)
            return

        if self._animating:
            super().setCurrentWidget(widget)
            effect = self._ensure_opacity_effect(widget)
            if effect is not None:
                effect.setOpacity(1.0)
            self._animating = False
            self._current_animation = None
            return

        current_effect = self._ensure_opacity_effect(current)
        target_effect = self._ensure_opacity_effect(widget)

        if current_effect is None or target_effect is None:
            super().setCurrentWidget(widget)
            return

        self._animating = True
        target_effect.setOpacity(0.0)

        fade_out = QPropertyAnimation(current_effect, b"opacity", self)
        fade_out.setDuration(self._fade_duration)
        fade_out.setStartValue(current_effect.opacity())
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.OutCubic)

        def _on_fade_out_finished() -> None:
            super(AnimatedStackedWidget, self).setCurrentWidget(widget)

            fade_in = QPropertyAnimation(target_effect, b"opacity", self)
            fade_in.setDuration(self._fade_duration)
            fade_in.setStartValue(target_effect.opacity())
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.OutCubic)

            def _on_fade_in_finished() -> None:
                current_effect.setOpacity(1.0)
                target_effect.setOpacity(1.0)
                self._animating = False
                self._current_animation = None

            fade_in.finished.connect(_on_fade_in_finished)
            fade_in.start()
            self._current_animation = fade_in

        fade_out.finished.connect(_on_fade_out_finished)
        fade_out.start()
        self._current_animation = fade_out

    def _ensure_opacity_effect(self, widget: QWidget) -> Optional[QGraphicsOpacityEffect]:
        effect = widget.graphicsEffect()
        if effect is None:
            opacity_effect = QGraphicsOpacityEffect(widget)
            opacity_effect.setOpacity(1.0)
            widget.setGraphicsEffect(opacity_effect)
            return opacity_effect
        if isinstance(effect, QGraphicsOpacityEffect):
            return effect
        return None


class CardFrame(QFrame):
    """Visuelt kort med tittel og valgfritt innhold."""

    def __init__(self, title: str, subtitle: Optional[str] = None) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setAttribute(Qt.WA_StyledBackground, True)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(15, 23, 42, 32))
        self.setGraphicsEffect(shadow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        layout.addWidget(self.title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("cardSubtitle")
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(12)
        layout.addLayout(self.body_layout)

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def add_layout(self, sub_layout: QHBoxLayout | QVBoxLayout | QGridLayout) -> None:
        self.body_layout.addLayout(sub_layout)


class StatBadge(QFrame):
    """Kompakt komponent for presentasjon av et nøkkeltall."""

    def __init__(self, title: str, description: str) -> None:
        super().__init__()
        self.setObjectName("statBadge")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("statTitle")
        layout.addWidget(self.title_label)

        self.value_label = QLabel("–")
        self.value_label.setObjectName("statValue")
        layout.addWidget(self.value_label)

        self.description_label = QLabel(description)
        self.description_label.setObjectName("statDescription")
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class DashboardPage(QWidget):
    """Viser nøkkeltall for selskapet."""

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.status_card = CardFrame("Status", "Hurtigoversikt over siste import og anbefalinger.")
        self.status_label = QLabel("Ingen SAF-T fil er lastet inn ennå.")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_card.add_widget(self.status_label)

        self.validation_label = QLabel("Ingen XSD-validering er gjennomført.")
        self.validation_label.setObjectName("statusLabel")
        self.validation_label.setWordWrap(True)
        self.status_card.add_widget(self.validation_label)
        layout.addWidget(self.status_card)

        self.kpi_card = CardFrame(
            "Nøkkeltallsanalyse",
            "Marginer og balanseindikatorer basert på innlastet SAF-T.",
        )
        self.kpi_grid = QGridLayout()
        self.kpi_grid.setHorizontalSpacing(16)
        self.kpi_grid.setVerticalSpacing(16)
        self.kpi_card.add_layout(self.kpi_grid)

        self.kpi_badges: Dict[str, StatBadge] = {}
        for idx, (key, title, desc) in enumerate(
            [
                ("revenue", "Driftsinntekter", "Sum av kontogruppe 3xxx."),
                ("ebitda_margin", "EBITDA-margin", "EBITDA i prosent av driftsinntekter."),
                ("ebit_margin", "EBIT-margin", "Driftsresultat i prosent av driftsinntekter."),
                ("result_margin", "Resultatmargin", "Årsresultat i prosent av driftsinntekter."),
                ("balance_gap", "Balanseavvik", "Differanse mellom eiendeler og gjeld."),
            ]
        ):
            badge = StatBadge(title, desc)
            row = idx // 3
            col = idx % 3
            self.kpi_grid.addWidget(badge, row, col)
            self.kpi_badges[key] = badge

        layout.addWidget(self.kpi_card)

        self.summary_card = CardFrame("Finansiell oversikt", "Oppsummerte nøkkeltall fra SAF-T.")
        self.summary_table = _create_table_widget()
        self.summary_table.setColumnCount(2)
        self.summary_table.setHorizontalHeaderLabels(["Nøkkel", "Beløp"])
        self.summary_card.add_widget(self.summary_table)
        layout.addWidget(self.summary_card)

        layout.addStretch(1)

    def update_status(self, message: str) -> None:
        self.status_label.setText(message)

    def update_validation_status(self, result: Optional[SaftValidationResult]) -> None:
        if result is None:
            self.validation_label.setText("Ingen XSD-validering er gjennomført.")
            return

        if result.version_family:
            version_txt = result.version_family
            if result.audit_file_version and result.audit_file_version != result.version_family:
                version_txt = f"{result.version_family} (AuditFileVersion: {result.audit_file_version})"
        else:
            version_txt = result.audit_file_version or "ukjent"

        status_parts = [f"SAF-T versjon: {version_txt}"]
        if result.is_valid is True:
            status_parts.append("XSD-validering: OK")
        elif result.is_valid is False:
            status_parts.append("XSD-validering: FEILET")
        else:
            status_parts.append("XSD-validering: Ikke tilgjengelig")

        message = " · ".join(status_parts)
        if result.details:
            first_line = result.details.strip().splitlines()[0]
            message = f"{message}\nDetaljer: {first_line}"
        self.validation_label.setText(message)

    def update_summary(self, summary: Optional[Dict[str, float]]) -> None:
        if not summary:
            self.summary_table.setRowCount(0)
            self._update_kpis(None)
            return
        rows = [
            ("Driftsinntekter (3xxx)", summary.get("driftsinntekter")),
            ("Varekostnad (4xxx)", summary.get("varekostnad")),
            ("Lønn (5xxx)", summary.get("lonn")),
            ("Andre driftskostnader", summary.get("andre_drift")),
            ("EBITDA", summary.get("ebitda")),
            ("Avskrivninger", summary.get("avskrivninger")),
            ("EBIT", summary.get("ebit")),
            ("Netto finans", summary.get("finans_netto")),
            ("Skatt", summary.get("skattekostnad")),
            ("Årsresultat", summary.get("arsresultat")),
            ("Eiendeler (UB)", summary.get("eiendeler_UB")),
            ("Gjeld (UB)", summary.get("gjeld_UB")),
            ("Balanseavvik", summary.get("balanse_diff")),
        ]
        _populate_table(self.summary_table, ["Nøkkel", "Beløp"], rows, money_cols={1})
        self._update_kpis(summary)


    def _update_kpis(self, summary: Optional[Dict[str, float]]) -> None:
        def set_badge(key: str, value: Optional[str]) -> None:
            badge = self.kpi_badges.get(key)
            if badge:
                badge.set_value(value or "—")

        if not summary:
            for key in self.kpi_badges:
                set_badge(key, None)
            return

        revenue_value = summary.get("driftsinntekter")
        revenue = revenue_value or 0.0
        ebitda = summary.get("ebitda")
        ebit = summary.get("ebit")
        result = summary.get("arsresultat")

        set_badge("revenue", format_currency(revenue_value) if revenue_value is not None else "—")

        def percent(value: Optional[float]) -> Optional[str]:
            if value is None or not revenue:
                return None
            try:
                return f"{(value / revenue) * 100:,.1f} %"
            except ZeroDivisionError:
                return None

        set_badge("ebitda_margin", percent(ebitda))
        set_badge("ebit_margin", percent(ebit))
        set_badge("result_margin", percent(result))
        set_badge(
            "balance_gap",
            format_difference(summary.get("eiendeler_UB"), summary.get("gjeld_UB")),
        )


class DataFramePage(QWidget):
    """Generisk side som viser en pandas DataFrame."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        frame_builder: Optional[Callable[[pd.DataFrame], pd.DataFrame]] = None,
        money_columns: Optional[Sequence[str]] = None,
        header_mode: QHeaderView.ResizeMode = QHeaderView.Stretch,
        full_window: bool = False,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card: Optional[CardFrame] = None
        self.info_label = QLabel("Last inn en SAF-T fil for å vise data.")
        self.info_label.setObjectName("infoLabel")

        self.table = _create_table_widget()
        self.table.horizontalHeader().setSectionResizeMode(header_mode)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.hide()

        if full_window:
            title_label = QLabel(title)
            title_label.setObjectName("pageTitle")
            layout.addWidget(title_label)

            if subtitle:
                subtitle_label = QLabel(subtitle)
                subtitle_label.setObjectName("pageSubtitle")
                subtitle_label.setWordWrap(True)
                layout.addWidget(subtitle_label)

            layout.addWidget(self.info_label)
            layout.addWidget(self.table, 1)
        else:
            self.card = CardFrame(title, subtitle)
            self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.card.add_widget(self.info_label)
            self.card.add_widget(self.table)
            layout.addWidget(self.card)
            layout.addStretch(1)

        self._frame_builder = frame_builder
        self._money_columns = tuple(money_columns or [])
        self._auto_resize_columns = header_mode == QHeaderView.ResizeToContents

    def set_dataframe(self, df: Optional[pd.DataFrame]) -> None:
        if df is None or df.empty:
            self.table.hide()
            self.info_label.show()
            self.table.setRowCount(0)
            return

        work = df
        if self._frame_builder is not None:
            work = self._frame_builder(df)

        columns = list(work.columns)
        rows = [tuple(work.iloc[i][column] for column in columns) for i in range(len(work))]
        money_idx = {columns.index(col) for col in self._money_columns if col in columns}
        _populate_table(self.table, columns, rows, money_cols=money_idx)
        if self._auto_resize_columns:
            self.table.resizeColumnsToContents()
        self.table.show()
        self.info_label.hide()


def _standard_tb_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Bygger en norsk standard saldobalanse med nettoverdier."""

    work = df.copy()
    if "Konto_int" in work.columns:
        work = work.sort_values("Konto_int", na_position="last")
    elif "Konto" in work.columns:
        work = work.sort_values("Konto", na_position="last")

    if "IB_netto" not in work.columns:
        work["IB_netto"] = work.get("IB Debet", 0.0).fillna(0) - work.get("IB Kredit", 0.0).fillna(0)
    if "UB_netto" not in work.columns:
        work["UB_netto"] = work.get("UB Debet", 0.0).fillna(0) - work.get("UB Kredit", 0.0).fillna(0)

    work["Endringer"] = work["UB_netto"] - work["IB_netto"]

    columns = ["Konto", "Kontonavn", "IB", "Endringer", "UB"]
    konto = work["Konto"].fillna("") if "Konto" in work.columns else pd.Series([""] * len(work))
    navn = (
        work["Kontonavn"].fillna("")
        if "Kontonavn" in work.columns
        else pd.Series([""] * len(work))
    )

    result = pd.DataFrame({
        "Konto": konto.astype(str),
        "Kontonavn": navn.astype(str),
        "IB": work["IB_netto"].fillna(0.0),
        "Endringer": work["Endringer"].fillna(0.0),
        "UB": work["UB_netto"].fillna(0.0),
    })
    return result[columns].reset_index(drop=True)


class SummaryPage(QWidget):
    """Side for vesentlighetsvurdering med tabell og forklaring."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.table = _create_table_widget()
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
        _populate_table(self.table, ["Nøkkel", "Beløp"], rows, money_cols={1})


class ComparisonPage(QWidget):
    """Sammenstilling mellom SAF-T og Regnskapsregisteret."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(
            "Regnskapsanalyse",
            "Sammenligner SAF-T data med nøkkeltall hentet fra Regnskapsregisteret.",
        )
        self.table = _create_table_widget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Nøkkel",
            "SAF-T",
            "Brreg",
            "Avvik",
        ])
        self.card.add_widget(self.table)
        layout.addWidget(self.card)
        layout.addStretch(1)

    def update_comparison(
        self, rows: Optional[Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]]
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
        _populate_table(
            self.table,
            ["Nøkkel", "SAF-T", "Brreg", "Avvik"],
            formatted_rows,
            money_cols={1, 2, 3},
        )


class BrregPage(QWidget):
    """Visning av mapping mot Regnskapsregisteret og rådata."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.map_card = CardFrame("Brreg-nøkler", "Mapping mellom SAF-T og Regnskapsregisteret.")
        self.map_table = _create_table_widget()
        self.map_table.setColumnCount(2)
        self.map_table.setHorizontalHeaderLabels(["Felt", "Sti = Verdi"])
        self.map_card.add_widget(self.map_table)
        layout.addWidget(self.map_card)

        self.json_card = CardFrame("Detaljert JSON", "Rådata fra Regnskapsregisteret for videre analyse.")
        self.json_view = QTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setObjectName("jsonView")
        self.json_card.add_widget(self.json_view)
        layout.addWidget(self.json_card)
        layout.addStretch(1)

    def update_mapping(self, rows: Optional[Sequence[Tuple[str, str]]]) -> None:
        if not rows:
            self.map_table.setRowCount(0)
            return
        _populate_table(self.map_table, ["Felt", "Sti = Verdi"], rows)

    def update_json(self, data: Optional[Dict[str, object]]) -> None:
        if not data:
            self.json_view.clear()
            return
        self.json_view.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))


class ChecklistPage(QWidget):
    """Enkel sjekkliste for revisjonsområder."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("checklist")
        self.card.add_widget(self.list_widget)
        layout.addWidget(self.card)
        layout.addStretch(1)

    def set_items(self, items: Iterable[str]) -> None:
        self.list_widget.clear()
        for item in items:
            QListWidgetItem(item, self.list_widget)


class SalesArPage(QWidget):
    """Revisjonsside for salg og kundefordringer med topp kunder."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        on_calc_top: Callable[[str, int], Optional[List[Tuple[str, str, int, float]]]],
    ) -> None:
        super().__init__()
        self._on_calc_top = on_calc_top

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.top_card = CardFrame("Topp kunder", "Identifiser kunder med høyest omsetning.")
        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(QLabel("Kilde:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(["alle 3xxx"])
        self.source_combo.setEnabled(False)
        controls.addWidget(self.source_combo)
        controls.addWidget(QLabel("Antall:"))
        self.top_spin = QSpinBox()
        self.top_spin.setRange(5, 100)
        self.top_spin.setValue(10)
        controls.addWidget(self.top_spin)
        controls.addStretch(1)
        self.calc_button = QPushButton("Beregn topp kunder")
        self.calc_button.clicked.connect(self._handle_calc_clicked)
        controls.addWidget(self.calc_button)
        self.top_card.add_layout(controls)

        self.top_table = _create_table_widget()
        self.top_table.setColumnCount(4)
        self.top_table.setHorizontalHeaderLabels([
            "Kundenr",
            "Kundenavn",
            "Fakturaer",
            "Omsetning (eks. mva)",
        ])
        self.top_card.add_widget(self.top_table)
        layout.addWidget(self.top_card)

        self.card = CardFrame(title, subtitle)
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("checklist")
        self.card.add_widget(self.list_widget)
        layout.addWidget(self.card)

        layout.addStretch(1)

        self.set_controls_enabled(False)

    def _handle_calc_clicked(self) -> None:
        rows = self._on_calc_top(self.source_combo.currentText(), int(self.top_spin.value()))
        if rows:
            self.set_top_customers(rows)

    def set_checklist_items(self, items: Iterable[str]) -> None:
        self.list_widget.clear()
        for item in items:
            QListWidgetItem(item, self.list_widget)

    def set_top_customers(self, rows: Iterable[Tuple[str, str, int, float]]) -> None:
        _populate_table(
            self.top_table,
            ["Kundenr", "Kundenavn", "Transaksjoner", "Omsetning (eks. mva)"],
            rows,
            money_cols={3},
        )

    def clear_top_customers(self) -> None:
        self.top_table.setRowCount(0)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.calc_button.setEnabled(enabled)
        self.top_spin.setEnabled(enabled)


class PurchasesApPage(QWidget):
    """Revisjonsside for innkjøp og leverandørgjeld med topp leverandører."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        on_calc_top: Callable[[str, int], Optional[List[Tuple[str, str, int, float]]]],
    ) -> None:
        super().__init__()
        self._on_calc_top = on_calc_top

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.top_card = CardFrame(
            "Innkjøp per leverandør",
            "Identifiser leverandører med høyeste innkjøp.",
        )
        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(QLabel("Kilde:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(["alle kostnadskonti (4xxx–8xxx)"])
        self.source_combo.setEnabled(False)
        controls.addWidget(self.source_combo)
        controls.addWidget(QLabel("Antall:"))
        self.top_spin = QSpinBox()
        self.top_spin.setRange(5, 100)
        self.top_spin.setValue(10)
        controls.addWidget(self.top_spin)
        controls.addStretch(1)
        self.calc_button = QPushButton("Beregn innkjøp per leverandør")
        self.calc_button.clicked.connect(self._handle_calc_clicked)
        controls.addWidget(self.calc_button)
        self.top_card.add_layout(controls)

        self.top_table = _create_table_widget()
        self.top_table.setColumnCount(4)
        self.top_table.setHorizontalHeaderLabels(
            [
                "Leverandørnr",
                "Leverandørnavn",
                "Transaksjoner",
                "Innkjøp (eks. mva)",
            ]
        )
        header = self.top_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        self.top_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.top_card.add_widget(self.top_table)
        self.top_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.top_card, 1)

        self.set_controls_enabled(False)

    def _handle_calc_clicked(self) -> None:
        rows = self._on_calc_top(self.source_combo.currentText(), int(self.top_spin.value()))
        if rows:
            self.set_top_suppliers(rows)

    def set_top_suppliers(self, rows: Iterable[Tuple[str, str, int, float]]) -> None:
        _populate_table(
            self.top_table,
            ["Leverandørnr", "Leverandørnavn", "Transaksjoner", "Innkjøp (eks. mva)"],
            rows,
            money_cols={3},
        )

    def clear_top_suppliers(self) -> None:
        self.top_table.setRowCount(0)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.calc_button.setEnabled(enabled)
        self.top_spin.setEnabled(enabled)


@dataclass
class NavigationItem:
    key: str
    item: QTreeWidgetItem


class NavigationPanel(QFrame):
    """Sidepanel med navigasjonsstruktur."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("navPanel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(24)

        self.logo_label = QLabel("Nordlys")
        self.logo_label.setObjectName("logoLabel")
        layout.addWidget(self.logo_label)

        self.tree = QTreeWidget()
        self.tree.setObjectName("navTree")
        self.tree.setHeaderHidden(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setIndentation(12)
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.tree, 1)

    def add_root(self, title: str, key: str | None = None) -> NavigationItem:
        item = QTreeWidgetItem([title])
        if key:
            item.setData(0, Qt.UserRole, key)
            font = item.font(0)
            font.setPointSize(font.pointSize() + 1)
            font.setWeight(QFont.DemiBold)
            item.setFont(0, font)
            item.setForeground(0, QBrush(QColor("#f8fafc")))
            icon = _icon_for_navigation(key)
            if icon:
                item.setIcon(0, icon)
        else:
            font = item.font(0)
            font.setPointSize(max(font.pointSize() - 1, 9))
            font.setWeight(QFont.DemiBold)
            font.setCapitalization(QFont.AllUppercase)
            font.setLetterSpacing(QFont.PercentageSpacing, 115)
            item.setFont(0, font)
            item.setForeground(0, QBrush(QColor("#94a3b8")))
            item.setFlags(
                item.flags()
                & ~Qt.ItemIsSelectable
                & ~Qt.ItemIsDragEnabled
                & ~Qt.ItemIsDropEnabled
            )
        self.tree.addTopLevelItem(item)
        self.tree.expandItem(item)
        return NavigationItem(key or title.lower(), item)

    def add_child(self, parent: NavigationItem, title: str, key: str) -> NavigationItem:
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.UserRole, key)
        font = item.font(0)
        font.setWeight(QFont.Medium)
        item.setFont(0, font)
        item.setForeground(0, QBrush(QColor("#e2e8f0")))
        icon = _icon_for_navigation(key)
        if icon:
            item.setIcon(0, icon)
        parent.item.addChild(item)
        parent.item.setExpanded(True)
        return NavigationItem(key, item)


class NordlysWindow(QMainWindow):
    """Hovedvindu for PySide6-applikasjonen."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1460, 940)
        # Sikrer at hovedvinduet kan maksimeres uten Qt-advarsler selv om enkelte
        # underliggende widgets har begrensende størrelseshint.
        self.setMinimumSize(1100, 720)
        self.setMaximumSize(16777215, 16777215)

        self._saft_df: Optional[pd.DataFrame] = None
        self._saft_summary: Optional[Dict[str, float]] = None
        self._header: Optional[SaftHeader] = None
        self._brreg_json: Optional[Dict[str, object]] = None
        self._brreg_map: Optional[Dict[str, Optional[float]]] = None
        self._customers: Dict[str, CustomerInfo] = {}
        self._cust_name_by_nr: Dict[str, str] = {}
        self._cust_id_to_nr: Dict[str, str] = {}
        self._customer_sales: Optional[pd.DataFrame] = None
        self._suppliers: Dict[str, SupplierInfo] = {}
        self._sup_name_by_nr: Dict[str, str] = {}
        self._sup_id_to_nr: Dict[str, str] = {}
        self._supplier_purchases: Optional[pd.DataFrame] = None
        self._validation_result: Optional[SaftValidationResult] = None
        self._current_file: Optional[str] = None
        self._loading_file: Optional[str] = None

        self._load_thread: Optional[QThread] = None
        self._load_worker: Optional[SaftLoadWorker] = None
        self._progress_dialog: Optional[QProgressDialog] = None

        self._page_map: Dict[str, QWidget] = {}
        self.sales_ar_page: Optional[SalesArPage] = None
        self.purchases_ap_page: Optional['PurchasesApPage'] = None
        self._content_wrapper: Optional[QWidget] = None
        self._nav_opacity: Optional[QGraphicsOpacityEffect] = None
        self._content_opacity: Optional[QGraphicsOpacityEffect] = None
        self._intro_animation: Optional[QParallelAnimationGroup] = None
        self._intro_animation_ran = False

        self._setup_ui()
        self._apply_styles()

    # region UI
    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.nav_panel = NavigationPanel()
        self._nav_opacity = QGraphicsOpacityEffect(self.nav_panel)
        self._nav_opacity.setOpacity(0.0)
        self.nav_panel.setGraphicsEffect(self._nav_opacity)
        root_layout.addWidget(self.nav_panel, 0)

        content_wrapper = QWidget()
        content_wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.setSpacing(24)
        root_layout.addWidget(content_wrapper, 1)
        self._content_wrapper = content_wrapper
        self._content_opacity = QGraphicsOpacityEffect(content_wrapper)
        self._content_opacity.setOpacity(0.0)
        content_wrapper.setGraphicsEffect(self._content_opacity)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)

        self.title_label = QLabel("Dashboard")
        self.title_label.setObjectName("pageTitle")
        header_layout.addWidget(self.title_label, 1)

        self.btn_open = QPushButton("Åpne SAF-T XML …")
        self.btn_open.clicked.connect(self.on_open)
        header_layout.addWidget(self.btn_open)

        self.btn_brreg = QPushButton("Hent Regnskapsregisteret")
        self.btn_brreg.clicked.connect(self.on_brreg)
        self.btn_brreg.setEnabled(False)
        header_layout.addWidget(self.btn_brreg)

        self.btn_export = QPushButton("Eksporter rapport (Excel)")
        self.btn_export.clicked.connect(self.on_export)
        self.btn_export.setEnabled(False)
        header_layout.addWidget(self.btn_export)

        content_layout.addLayout(header_layout)

        info_card = CardFrame("Selskapsinformasjon")
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(24)
        info_grid.setVerticalSpacing(8)

        self.lbl_company = QLabel("Selskap: –")
        self.lbl_orgnr = QLabel("Org.nr: –")
        self.lbl_period = QLabel("Periode: –")
        info_grid.addWidget(self.lbl_company, 0, 0)
        info_grid.addWidget(self.lbl_orgnr, 0, 1)
        info_grid.addWidget(self.lbl_period, 0, 2)
        info_card.add_layout(info_grid)
        content_layout.addWidget(info_card)

        self.stack = AnimatedStackedWidget()
        content_layout.addWidget(self.stack, 1)

        self._create_pages()

        status = QStatusBar()
        status.showMessage("Klar.")
        self.setStatusBar(status)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._intro_animation_ran:
            self._intro_animation_ran = True
            QTimer.singleShot(60, self._play_intro_animation)

    def _play_intro_animation(self) -> None:
        if self._content_wrapper is None or self._nav_opacity is None or self._content_opacity is None:
            return

        nav_pos = self.nav_panel.pos()
        content_pos = self._content_wrapper.pos()

        start_nav = nav_pos - QPoint(48, 0)
        start_content = content_pos + QPoint(0, 28)

        self.nav_panel.move(start_nav)
        self._content_wrapper.move(start_content)

        nav_move = QPropertyAnimation(self.nav_panel, b"pos", self)
        nav_move.setDuration(520)
        nav_move.setStartValue(start_nav)
        nav_move.setEndValue(nav_pos)
        nav_move.setEasingCurve(QEasingCurve.OutCubic)

        content_move = QPropertyAnimation(self._content_wrapper, b"pos", self)
        content_move.setDuration(520)
        content_move.setStartValue(start_content)
        content_move.setEndValue(content_pos)
        content_move.setEasingCurve(QEasingCurve.OutCubic)

        nav_fade = QPropertyAnimation(self._nav_opacity, b"opacity", self)
        nav_fade.setDuration(520)
        nav_fade.setStartValue(self._nav_opacity.opacity())
        nav_fade.setEndValue(1.0)
        nav_fade.setEasingCurve(QEasingCurve.OutCubic)

        content_fade = QPropertyAnimation(self._content_opacity, b"opacity", self)
        content_fade.setDuration(520)
        content_fade.setStartValue(self._content_opacity.opacity())
        content_fade.setEndValue(1.0)
        content_fade.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(nav_move)
        group.addAnimation(content_move)
        group.addAnimation(nav_fade)
        group.addAnimation(content_fade)

        def _on_finished() -> None:
            self.nav_panel.move(nav_pos)
            self._content_wrapper.move(content_pos)
            self._nav_opacity.setOpacity(1.0)
            self._content_opacity.setOpacity(1.0)
            self._intro_animation = None

        group.finished.connect(_on_finished)
        group.start()
        self._intro_animation = group

    def _create_pages(self) -> None:
        dashboard = DashboardPage()
        self._register_page("dashboard", dashboard)
        self.stack.addWidget(dashboard)
        self.dashboard_page = dashboard

        saldobalanse_page = DataFramePage(
            "Saldobalanse",
            "Viser saldobalansen slik den er rapportert i SAF-T.",
            frame_builder=_standard_tb_frame,
            money_columns=("IB", "Endringer", "UB"),
            header_mode=QHeaderView.ResizeToContents,
            full_window=True,
        )
        self._register_page("plan.saldobalanse", saldobalanse_page)
        self.stack.addWidget(saldobalanse_page)
        self.saldobalanse_page = saldobalanse_page

        kontroll_page = DataFramePage(
            "Kontroll av inngående balanse",
            "Detaljert saldobalanse fra SAF-T for kvalitetssikring.",
        )
        self._register_page("plan.kontroll", kontroll_page)
        self.stack.addWidget(kontroll_page)
        self.kontroll_page = kontroll_page

        vesentlig_page = SummaryPage(
            "Vesentlighetsvurdering",
            "Nøkkeltall som understøtter fastsettelse av vesentlighetsgrenser.",
        )
        self._register_page("plan.vesentlighet", vesentlig_page)
        self.stack.addWidget(vesentlig_page)
        self.vesentlig_page = vesentlig_page

        regnskap_page = ComparisonPage()
        self._register_page("plan.regnskapsanalyse", regnskap_page)
        self.stack.addWidget(regnskap_page)
        self.regnskap_page = regnskap_page

        brreg_page = BrregPage()
        self._register_page("plan.sammenstilling", brreg_page)
        self.stack.addWidget(brreg_page)
        self.brreg_page = brreg_page

        self.revision_pages: Dict[str, QWidget] = {}
        for key, (title, subtitle) in {
            "rev.innkjop": ("Innkjøp og leverandørgjeld", "Fokuser på varekjøp, kredittider og periodisering."),
            "rev.lonn": ("Lønn", "Kontroll av lønnskjøringer, skatt og arbeidsgiveravgift."),
            "rev.kostnad": ("Kostnad", "Analyse av driftskostnader og periodisering."),
            "rev.driftsmidler": ("Driftsmidler", "Verifikasjon av investeringer og avskrivninger."),
            "rev.finans": ("Finans og likvid", "Bank, finansielle instrumenter og kontantstrøm."),
            "rev.varelager": ("Varelager og varekjøp", "Telling, nedskrivninger og bruttomargin."),
            "rev.salg": ("Salg og kundefordringer", "Omsetning, cut-off og reskontro."),
            "rev.mva": ("MVA", "Kontroll av avgiftsbehandling og rapportering."),
        }.items():
            if key == "rev.salg":
                page = SalesArPage(title, subtitle, self._on_calc_top_customers)
                self.sales_ar_page = page
            elif key == "rev.innkjop":
                page = PurchasesApPage(title, subtitle, self._on_calc_top_suppliers)
                self.purchases_ap_page = page
            else:
                page = ChecklistPage(title, subtitle)
            self.revision_pages[key] = page
            self._register_page(key, page)
            self.stack.addWidget(page)

        self._populate_navigation()

    def _populate_navigation(self) -> None:
        nav = self.nav_panel
        dashboard_item = nav.add_root("Dashboard", "dashboard")

        planning_root = nav.add_root("Planlegging")
        nav.add_child(planning_root, "Saldobalanse", "plan.saldobalanse")
        nav.add_child(planning_root, "Kontroll IB", "plan.kontroll")
        nav.add_child(planning_root, "Vesentlighetsvurdering", "plan.vesentlighet")
        nav.add_child(planning_root, "Regnskapsanalyse", "plan.regnskapsanalyse")
        nav.add_child(planning_root, "Sammenstillingsanalyse", "plan.sammenstilling")

        revision_root = nav.add_root("Revisjon")
        nav.add_child(revision_root, "Innkjøp og leverandørgjeld", "rev.innkjop")
        nav.add_child(revision_root, "Lønn", "rev.lonn")
        nav.add_child(revision_root, "Kostnad", "rev.kostnad")
        nav.add_child(revision_root, "Driftsmidler", "rev.driftsmidler")
        nav.add_child(revision_root, "Finans og likvid", "rev.finans")
        nav.add_child(revision_root, "Varelager og varekjøp", "rev.varelager")
        nav.add_child(revision_root, "Salg og kundefordringer", "rev.salg")
        nav.add_child(revision_root, "MVA", "rev.mva")

        nav.tree.currentItemChanged.connect(self._on_navigation_changed)
        nav.tree.setCurrentItem(dashboard_item.item)

        for key, items in REVISION_TASKS.items():
            page = self.revision_pages.get(key)
            if isinstance(page, SalesArPage):
                page.set_checklist_items(items)
            elif isinstance(page, ChecklistPage):
                page.set_items(items)

    def _register_page(self, key: str, widget: QWidget) -> None:
        self._page_map[key] = widget

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                font-family: 'Inter', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
                font-size: 14px;
                color: #0b132b;
            }
            QMainWindow {
                background-color: #eef2ff;
            }
            #navPanel {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #020617, stop:0.55 #0f172a, stop:1 #1d2a44);
                color: #e2e8f0;
                border-right: 1px solid rgba(148, 163, 184, 0.22);
            }
            #logoLabel {
                font-size: 28px;
                font-weight: 700;
                letter-spacing: 1px;
                color: #f8fafc;
                text-transform: uppercase;
            }
            #navTree {
                background: transparent;
                border: none;
                color: #dbeafe;
                font-size: 14px;
            }
            #navTree:focus { outline: none; border: none; }
            QTreeWidget::item:focus { outline: none; }
            #navTree::item {
                height: 36px;
                padding: 8px 12px;
                border-radius: 12px;
                margin: 3px 0;
            }
            #navTree::item:selected {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #38bdf8, stop:0.5 #6366f1, stop:1 #8b5cf6);
                color: #f8fafc;
                font-weight: 600;
            }
            #navTree::item:hover {
                background-color: rgba(59, 130, 246, 0.26);
            }
            QPushButton {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2dd4bf, stop:0.45 #38bdf8, stop:1 #6366f1);
                color: #f8fafc;
                border-radius: 12px;
                padding: 11px 22px;
                font-weight: 600;
                letter-spacing: 0.3px;
                border: 1px solid rgba(255, 255, 255, 0.18);
            }
            QPushButton:focus { outline: none; }
            QPushButton:disabled {
                background: rgba(148, 163, 184, 0.65);
                color: rgba(226, 232, 240, 0.9);
                border: none;
            }
            QPushButton:hover:!disabled {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #22d3ee, stop:0.5 #4f46e5, stop:1 #7c3aed);
            }
            QPushButton:pressed {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0ea5e9, stop:1 #4c1d95);
            }
            #card {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 rgba(226, 232, 240, 0.38));
                border-radius: 20px;
                border: 1px solid rgba(148, 163, 184, 0.28);
            }
            #card:hover {
                border: 1px solid rgba(99, 102, 241, 0.45);
            }
            #cardTitle {
                font-size: 21px;
                font-weight: 600;
                color: #0f172a;
                letter-spacing: 0.2px;
            }
            #cardSubtitle {
                color: #475569;
                font-size: 13px;
                line-height: 1.5;
            }
            #pageTitle {
                font-size: 30px;
                font-weight: 700;
                color: #111827;
                letter-spacing: 0.6px;
            }
            #statusLabel {
                color: #1f2937;
                font-size: 14px;
                line-height: 1.55;
            }
            #infoLabel { color: #475569; font-size: 14px; }
            #jsonView {
                background: #0f172a;
                color: #f8fafc;
                font-family: "Fira Code", monospace;
                border-radius: 14px;
                padding: 14px;
                border: 1px solid rgba(30, 41, 59, 0.8);
            }
            #cardTable {
                border: none;
                gridline-color: rgba(148, 163, 184, 0.35);
                background-color: transparent;
                alternate-background-color: rgba(226, 232, 240, 0.45);
            }
            QTableWidget { background-color: transparent; alternate-background-color: rgba(226, 232, 240, 0.45); }
            QTableWidget::item { padding: 10px 8px; }
            QTableWidget::item:selected {
                background: rgba(99, 102, 241, 0.22);
                color: #0f172a;
            }
            QHeaderView::section {
                background-color: transparent;
                border: none;
                font-weight: 600;
                color: #1f2937;
                padding: 10px 6px;
            }
            QHeaderView::section:horizontal {
                border-bottom: 1px solid rgba(148, 163, 184, 0.45);
            }
            QListWidget#checklist { border: none; }
            QListWidget#checklist::item {
                padding: 12px 14px;
                margin: 4px 0;
                border-radius: 12px;
            }
            QListWidget#checklist::item:selected {
                background: rgba(14, 165, 233, 0.18);
                color: #0f172a;
                font-weight: 600;
            }
            QListWidget#checklist::item:hover {
                background-color: rgba(15, 23, 42, 0.06);
            }
            #statBadge {
                background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(236, 254, 255, 0.85), stop:1 rgba(224, 231, 255, 0.9));
                border: 1px solid rgba(148, 163, 184, 0.35);
                border-radius: 18px;
            }
            #statTitle {
                font-size: 12px;
                font-weight: 600;
                color: #475569;
                text-transform: uppercase;
                letter-spacing: 1.2px;
            }
            #statValue {
                font-size: 28px;
                font-weight: 700;
                color: #0f172a;
            }
            #statDescription {
                font-size: 12px;
                color: #64748b;
            }
            QStatusBar {
                background: transparent;
                color: #475569;
                padding-right: 24px;
                border-top: 1px solid rgba(148, 163, 184, 0.3);
            }
            QComboBox, QSpinBox {
                background-color: rgba(255, 255, 255, 0.92);
                border: 1px solid rgba(148, 163, 184, 0.5);
                border-radius: 10px;
                padding: 6px 12px;
                min-height: 32px;
            }
            QComboBox QAbstractItemView {
                border-radius: 10px;
                padding: 6px;
                background-color: #ffffff;
                selection-background-color: rgba(99, 102, 241, 0.2);
            }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox::down-arrow { image: none; }
            QSpinBox::up-button, QSpinBox::down-button { border: none; background: transparent; width: 20px; }
            QScrollBar:vertical {
                width: 12px;
                background: transparent;
                margin: 6px 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(99, 102, 241, 0.45);
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(59, 130, 246, 0.6);
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            QToolTip {
                background-color: #0f172a;
                color: #f8fafc;
                border: none;
                padding: 8px 10px;
                border-radius: 8px;
            }
            """
        )

    # endregion

    # region Handlinger
    def on_open(self) -> None:
        if self._load_thread is not None:
            QMessageBox.information(
                self,
                "Laster allerede",
                "En SAF-T-fil lastes inn i bakgrunnen. Vent til prosessen er ferdig.",
            )
            return
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Åpne SAF-T XML",
            str(Path.home()),
            "SAF-T XML (*.xml);;Alle filer (*)",
        )
        if not file_name:
            return
        self._loading_file = file_name
        worker = SaftLoadWorker(file_name)
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(self._on_loader_started)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_load_finished)
        worker.error.connect(self._on_load_error)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._on_loader_thread_finished)
        thread.finished.connect(thread.deleteLater)

        self._load_worker = worker
        self._load_thread = thread
        thread.start()

    @Slot()
    def _on_loader_started(self) -> None:
        message = "Laster SAF-T …"
        if self._loading_file:
            message = f"Laster SAF-T: {Path(self._loading_file).name} …"
        self._set_loading_state(True, message)
        self._show_progress_dialog(message)

    def _show_progress_dialog(self, message: str) -> None:
        if self._progress_dialog is None:
            dialog = QProgressDialog(self)
            dialog.setCancelButton(None)
            dialog.setRange(0, 0)
            dialog.setAutoReset(False)
            dialog.setAutoClose(False)
            dialog.setWindowModality(Qt.WindowModal)
            dialog.setWindowTitle("Laster SAF-T")
            dialog.setMinimumWidth(360)
            self._progress_dialog = dialog
        if self._progress_dialog is not None:
            self._progress_dialog.setLabelText(message)
            self._progress_dialog.show()
            self._progress_dialog.raise_()
            self._progress_dialog.activateWindow()

    def _close_progress_dialog(self) -> None:
        if self._progress_dialog is None:
            return
        self._progress_dialog.hide()
        self._progress_dialog.deleteLater()
        self._progress_dialog = None

    def _set_loading_state(self, loading: bool, status_message: Optional[str] = None) -> None:
        self.btn_open.setEnabled(not loading)
        has_data = self._saft_df is not None
        self.btn_brreg.setEnabled(False if loading else has_data)
        self.btn_export.setEnabled(False if loading else has_data)
        if self.sales_ar_page:
            if loading:
                self.sales_ar_page.set_controls_enabled(False)
            else:
                has_customer_data = (
                    self._customer_sales is not None and not self._customer_sales.empty
                )
                self.sales_ar_page.set_controls_enabled(has_customer_data)
        if self.purchases_ap_page:
            if loading:
                self.purchases_ap_page.set_controls_enabled(False)
            else:
                has_supplier_data = (
                    self._supplier_purchases is not None and not self._supplier_purchases.empty
                )
                self.purchases_ap_page.set_controls_enabled(has_supplier_data)
        if status_message:
            self.statusBar().showMessage(status_message)

    def _finalize_loading(self, status_message: Optional[str] = None) -> None:
        self._close_progress_dialog()
        self._set_loading_state(False)
        if status_message:
            self.statusBar().showMessage(status_message)
        self._loading_file = None

    @Slot(object)
    def _on_load_finished(self, result_obj: object) -> None:
        result = cast(SaftLoadResult, result_obj)
        self._apply_saft_result(result)
        self._finalize_loading()

    def _apply_saft_result(self, result: SaftLoadResult) -> None:
        self._header = result.header
        self._saft_df = result.dataframe
        self._saft_summary = result.summary
        self._validation_result = result.validation
        self._current_file = result.file_path

        self._ingest_customers(result.customers)
        self._ingest_suppliers(result.suppliers)
        self._customer_sales = (
            result.customer_sales.copy() if result.customer_sales is not None else None
        )
        self._supplier_purchases = (
            result.supplier_purchases.copy()
            if result.supplier_purchases is not None
            else None
        )

        if self._customer_sales is not None and not self._customer_sales.empty:
            if "Kundenavn" in self._customer_sales.columns:
                mask = self._customer_sales["Kundenavn"].astype(str).str.strip() == ""
                if mask.any():
                    self._customer_sales.loc[mask, "Kundenavn"] = self._customer_sales.loc[mask, "Kundenr"].apply(
                        lambda value: self._lookup_customer_name(value, value) or value
                    )
            else:
                self._customer_sales["Kundenavn"] = self._customer_sales["Kundenr"].apply(
                    lambda value: self._lookup_customer_name(value, value) or value
                )
            ordered_cols = ["Kundenr", "Kundenavn", "Omsetning eks mva"]
            ordered_cols += [col for col in ["Transaksjoner"] if col in self._customer_sales.columns]
            remaining = [col for col in self._customer_sales.columns if col not in ordered_cols]
            self._customer_sales = self._customer_sales.loc[:, ordered_cols + remaining]

        if self._supplier_purchases is not None and not self._supplier_purchases.empty:
            if "Leverandørnavn" in self._supplier_purchases.columns:
                mask = self._supplier_purchases["Leverandørnavn"].astype(str).str.strip() == ""
                if mask.any():
                    self._supplier_purchases.loc[mask, "Leverandørnavn"] = self._supplier_purchases.loc[
                        mask, "Leverandørnr"
                    ].apply(lambda value: self._lookup_supplier_name(value, value) or value)
            else:
                self._supplier_purchases["Leverandørnavn"] = self._supplier_purchases["Leverandørnr"].apply(
                    lambda value: self._lookup_supplier_name(value, value) or value
                )
            ordered_sup_cols = ["Leverandørnr", "Leverandørnavn", "Innkjøp eks mva"]
            ordered_sup_cols += [
                col for col in ["Transaksjoner"] if col in self._supplier_purchases.columns
            ]
            remaining_sup = [
                col for col in self._supplier_purchases.columns if col not in ordered_sup_cols
            ]
            self._supplier_purchases = self._supplier_purchases.loc[
                :, ordered_sup_cols + remaining_sup
            ]

        df = result.dataframe
        self._update_header_fields()
        self.saldobalanse_page.set_dataframe(df)
        self.kontroll_page.set_dataframe(df)
        self.dashboard_page.update_summary(self._saft_summary)

        company = self._header.company_name if self._header else None
        orgnr = self._header.orgnr if self._header else None
        period = None
        if self._header:
            period = (
                f"{self._header.fiscal_year or '—'} P{self._header.period_start or '?'}–P{self._header.period_end or '?'}"
            )
        revenue_txt = (
            format_currency(self._saft_summary.get("driftsinntekter"))
            if self._saft_summary and self._saft_summary.get("driftsinntekter") is not None
            else "—"
        )
        account_count = len(df.index)
        status_bits = [
            company or "Ukjent selskap",
            f"Org.nr: {orgnr}" if orgnr else "Org.nr: –",
            f"Periode: {period}" if period else None,
            f"{account_count} konti analysert",
            f"Driftsinntekter: {revenue_txt}",
        ]
        self.dashboard_page.update_status(" · ".join(bit for bit in status_bits if bit))

        validation = result.validation
        self.dashboard_page.update_validation_status(validation)
        if validation.is_valid is False:
            QMessageBox.warning(
                self,
                "XSD-validering feilet",
                validation.details or "Valideringen mot XSD feilet. Se dashboard for detaljer.",
            )
        elif validation.is_valid is None and validation.details:
            QMessageBox.information(self, "XSD-validering", validation.details)

        if self.sales_ar_page:
            has_customer_data = (
                self._customer_sales is not None and not self._customer_sales.empty
            )
            self.sales_ar_page.set_controls_enabled(has_customer_data)
            self.sales_ar_page.clear_top_customers()
        if self.purchases_ap_page:
            has_supplier_data = (
                self._supplier_purchases is not None and not self._supplier_purchases.empty
            )
            self.purchases_ap_page.set_controls_enabled(has_supplier_data)
            self.purchases_ap_page.clear_top_suppliers()

        self.vesentlig_page.update_summary(self._saft_summary)
        self.regnskap_page.update_comparison(None)
        self.brreg_page.update_mapping(None)
        self.brreg_page.update_json(None)

        self.btn_brreg.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.statusBar().showMessage(f"SAF-T lastet: {result.file_path}")

    @Slot(str)
    def _on_load_error(self, message: str) -> None:
        self._finalize_loading("Feil ved lesing av SAF-T.")
        QMessageBox.critical(self, "Feil ved lesing av SAF-T", message)

    @Slot()
    def _on_loader_thread_finished(self) -> None:
        self._load_thread = None
        self._load_worker = None

    def _normalize_identifier(self, value: object) -> Optional[str]:
        if value is None:
            return None
        try:
            if pd.isna(value):  # type: ignore[arg-type]
                return None
        except Exception:
            pass
        text = str(value).strip()
        return text or None

    def _normalize_customer_key(self, value: object) -> Optional[str]:
        return self._normalize_identifier(value)

    def _normalize_supplier_key(self, value: object) -> Optional[str]:
        return self._normalize_identifier(value)

    def _ingest_customers(self, customers: Dict[str, CustomerInfo]) -> None:
        self._customers = {}
        self._cust_name_by_nr = {}
        self._cust_id_to_nr = {}
        for info in customers.values():
            name = (info.name or '').strip()
            raw_id = info.customer_id
            raw_number = info.customer_number or info.customer_id
            norm_id = self._normalize_customer_key(raw_id)
            norm_number = self._normalize_customer_key(raw_number)
            resolved_number = norm_number or norm_id or self._normalize_customer_key(raw_id)
            if not resolved_number and isinstance(raw_number, str) and raw_number.strip():
                resolved_number = raw_number.strip()
            if not resolved_number and isinstance(raw_id, str) and raw_id.strip():
                resolved_number = raw_id.strip()

            customer_key = norm_id or (raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None)
            if customer_key:
                self._customers[customer_key] = CustomerInfo(
                    customer_id=customer_key,
                    customer_number=resolved_number or customer_key,
                    name=name,
                )

            keys = {
                raw_id,
                norm_id,
                raw_number,
                norm_number,
                resolved_number,
            }
            keys = {key for key in keys if isinstance(key, str) and key}

            if resolved_number:
                norm_resolved = self._normalize_customer_key(resolved_number)
                all_number_keys = set(keys)
                if norm_resolved:
                    all_number_keys.add(norm_resolved)
                all_number_keys.add(resolved_number)
                for key in all_number_keys:
                    norm_key = self._normalize_customer_key(key)
                    if norm_key:
                        self._cust_id_to_nr[norm_key] = resolved_number
                    self._cust_id_to_nr[key] = resolved_number

            if name:
                for key in keys:
                    norm_key = self._normalize_customer_key(key)
                    if norm_key:
                        self._cust_name_by_nr[norm_key] = name
                    self._cust_name_by_nr[key] = name

    def _ingest_suppliers(self, suppliers: Dict[str, SupplierInfo]) -> None:
        self._suppliers = {}
        self._sup_name_by_nr = {}
        self._sup_id_to_nr = {}
        for info in suppliers.values():
            name = (info.name or "").strip()
            raw_id = info.supplier_id
            raw_number = info.supplier_number or info.supplier_id
            norm_id = self._normalize_supplier_key(raw_id)
            norm_number = self._normalize_supplier_key(raw_number)
            resolved_number = norm_number or norm_id or self._normalize_supplier_key(raw_id)
            if not resolved_number and isinstance(raw_number, str) and raw_number.strip():
                resolved_number = raw_number.strip()
            if not resolved_number and isinstance(raw_id, str) and raw_id.strip():
                resolved_number = raw_id.strip()

            supplier_key = norm_id or (raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None)
            if supplier_key:
                self._suppliers[supplier_key] = SupplierInfo(
                    supplier_id=supplier_key,
                    supplier_number=resolved_number or supplier_key,
                    name=name,
                )

            keys = {raw_id, norm_id, raw_number, norm_number, resolved_number}
            keys = {key for key in keys if isinstance(key, str) and key}

            if resolved_number:
                norm_resolved = self._normalize_supplier_key(resolved_number)
                all_number_keys = set(keys)
                if norm_resolved:
                    all_number_keys.add(norm_resolved)
                all_number_keys.add(resolved_number)
                for key in all_number_keys:
                    norm_key = self._normalize_supplier_key(key)
                    if norm_key:
                        self._sup_id_to_nr[norm_key] = resolved_number
                    self._sup_id_to_nr[key] = resolved_number

            if name:
                for key in keys:
                    norm_key = self._normalize_supplier_key(key)
                    if norm_key:
                        self._sup_name_by_nr[norm_key] = name
                    self._sup_name_by_nr[key] = name

    def _lookup_customer_name(self, number: object, customer_id: object) -> Optional[str]:
        number_key = self._normalize_customer_key(number)
        if number_key:
            name = self._cust_name_by_nr.get(number_key)
            if name:
                return name
        cid_key = self._normalize_customer_key(customer_id)
        if cid_key:
            info = self._customers.get(cid_key)
            if info and info.name:
                return info.name
            name = self._cust_name_by_nr.get(cid_key)
            if name:
                return name
        return None

    def _lookup_supplier_name(self, number: object, supplier_id: object) -> Optional[str]:
        number_key = self._normalize_supplier_key(number)
        if number_key:
            name = self._sup_name_by_nr.get(number_key)
            if name:
                return name
        sid_key = self._normalize_supplier_key(supplier_id)
        if sid_key:
            info = self._suppliers.get(sid_key)
            if info and info.name:
                return info.name
            name = self._sup_name_by_nr.get(sid_key)
            if name:
                return name
        return None

    def _safe_float(self, value: object) -> float:
        try:
            if pd.isna(value):  # type: ignore[arg-type]
                return 0.0
        except Exception:
            pass
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _on_calc_top_customers(self, source: str, topn: int) -> Optional[List[Tuple[str, str, int, float]]]:
        _ = source  # kilde er alltid 3xxx-transaksjoner
        if self._customer_sales is None or self._customer_sales.empty:
            QMessageBox.information(
                self,
                "Ingen inntektslinjer",
                "Fant ingen inntektslinjer på 3xxx-konti i SAF-T-filen.",
            )
            return None
        data = self._customer_sales.copy()
        data = data.sort_values("Omsetning eks mva", ascending=False).head(topn)
        rows: List[Tuple[str, str, int, float]] = []
        for _, row in data.iterrows():
            number = row.get("Kundenr")
            number_text = self._normalize_customer_key(number)
            if not number_text and isinstance(number, str):
                number_text = number.strip() or None
            name = row.get("Kundenavn") or self._lookup_customer_name(number, number)
            count_val = row.get("Transaksjoner", 0)
            try:
                count_int = int(count_val)
            except (TypeError, ValueError):
                count_int = 0
            rows.append(
                (
                    number_text or "—",
                    (name or "").strip() or "—",
                    count_int,
                    self._safe_float(row.get("Omsetning eks mva")),
                )
            )
        self.statusBar().showMessage(f"Topp kunder (3xxx) beregnet. N={topn}.")
        return rows

    def _on_calc_top_suppliers(self, source: str, topn: int) -> Optional[List[Tuple[str, str, int, float]]]:
        _ = source  # kilde er alltid kostnadskonti
        if self._supplier_purchases is None or self._supplier_purchases.empty:
            QMessageBox.information(
                self,
                "Ingen innkjøpslinjer",
                "Fant ingen innkjøpslinjer på kostnadskonti (4xxx–8xxx) i SAF-T-filen.",
            )
            return None
        data = self._supplier_purchases.copy()
        data = data.sort_values("Innkjøp eks mva", ascending=False).head(topn)
        rows: List[Tuple[str, str, int, float]] = []
        for _, row in data.iterrows():
            number = row.get("Leverandørnr")
            number_text = self._normalize_supplier_key(number)
            if not number_text and isinstance(number, str):
                number_text = number.strip() or None
            name = row.get("Leverandørnavn") or self._lookup_supplier_name(number, number)
            count_val = row.get("Transaksjoner", 0)
            try:
                count_int = int(count_val)
            except (TypeError, ValueError):
                count_int = 0
            rows.append(
                (
                    number_text or "—",
                    (name or "").strip() or "—",
                    count_int,
                    self._safe_float(row.get("Innkjøp eks mva")),
                )
            )
        self.statusBar().showMessage(
            f"Innkjøp per leverandør (kostnadskonti 4xxx–8xxx) beregnet. N={topn}."
        )
        return rows

    def on_brreg(self) -> None:
        if not self._header or not self._header.orgnr:
            QMessageBox.warning(self, "Mangler org.nr", "Fant ikke org.nr i SAF-T-headeren.")
            return
        orgnr = self._header.orgnr
        try:
            js = fetch_brreg(orgnr)
        except Exception as exc:  # pragma: no cover - vises i GUI
            QMessageBox.critical(self, "Feil ved henting", str(exc))
            return
        self._brreg_json = js
        self._brreg_map = map_brreg_metrics(js)

        rows: List[Tuple[str, str]] = []

        def add_row(label: str, prefer_keys: Iterable[str]) -> None:
            hit = find_first_by_exact_endkey(js, prefer_keys, disallow_contains=["egenkapitalOgGjeld"] if "sumEgenkapital" in prefer_keys else None)
            if not hit and "sumEiendeler" in prefer_keys:
                hit = find_first_by_exact_endkey(js, ["sumEgenkapitalOgGjeld"])
            rows.append((label, f"{hit[0]} = {hit[1]}" if hit else "—"))

        add_row("Eiendeler (UB)", ["sumEiendeler"])
        add_row("Egenkapital (UB)", ["sumEgenkapital"])
        add_row("Gjeld (UB)", ["sumGjeld"])
        add_row("Driftsinntekter", ["driftsinntekter", "sumDriftsinntekter", "salgsinntekter"])
        add_row("EBIT", ["driftsresultat", "ebit", "driftsresultatFoerFinans"])
        add_row("Årsresultat", ["arsresultat", "resultat", "resultatEtterSkatt"])

        self.brreg_page.update_mapping(rows)
        self.brreg_page.update_json(js)

        if not self._saft_summary:
            self.statusBar().showMessage("Brreg-data hentet, men ingen SAF-T oppsummering å sammenligne mot.")
            return

        cmp_rows = [
            (
                "Driftsinntekter",
                self._saft_summary.get("driftsinntekter"),
                self._brreg_map.get("driftsinntekter") if self._brreg_map else None,
                None,
            ),
            (
                "EBIT",
                self._saft_summary.get("ebit"),
                self._brreg_map.get("ebit") if self._brreg_map else None,
                None,
            ),
            (
                "Årsresultat",
                self._saft_summary.get("arsresultat"),
                self._brreg_map.get("arsresultat") if self._brreg_map else None,
                None,
            ),
            (
                "Eiendeler (UB)",
                self._saft_summary.get("eiendeler_UB_brreg"),
                self._brreg_map.get("eiendeler_UB") if self._brreg_map else None,
                None,
            ),
            (
                "Egenkapital (UB)",
                self._saft_summary.get("egenkapital_UB"),
                self._brreg_map.get("egenkapital_UB") if self._brreg_map else None,
                None,
            ),
            (
                "Gjeld (UB)",
                self._saft_summary.get("gjeld_UB_brreg"),
                self._brreg_map.get("gjeld_UB") if self._brreg_map else None,
                None,
            ),
        ]
        self.regnskap_page.update_comparison(cmp_rows)
        self.statusBar().showMessage("Data hentet fra Regnskapsregisteret.")

    def on_export(self) -> None:
        if self._saft_df is None:
            QMessageBox.warning(self, "Ingenting å eksportere", "Last inn SAF-T først.")
            return
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Eksporter rapport",
            str(Path.home() / "SAFT_rapport.xlsx"),
            "Excel (*.xlsx)",
        )
        if not file_name:
            return
        try:
            with pd.ExcelWriter(file_name, engine="xlsxwriter") as writer:
                self._saft_df.to_excel(writer, sheet_name="Saldobalanse", index=False)
                if self._saft_summary:
                    summary_df = pd.DataFrame([self._saft_summary]).T.reset_index()
                    summary_df.columns = ["Nøkkel", "Beløp"]
                    summary_df.to_excel(writer, sheet_name="NS4102_Sammendrag", index=False)
                if self._customer_sales is not None:
                    self._customer_sales.to_excel(writer, sheet_name="Sales_by_customer", index=False)
                if self._brreg_json:
                    pd.json_normalize(self._brreg_json).to_excel(writer, sheet_name="Brreg_JSON", index=False)
                if self._brreg_map:
                    map_df = pd.DataFrame(list(self._brreg_map.items()), columns=["Felt", "Verdi"])
                    map_df.to_excel(writer, sheet_name="Brreg_Mapping", index=False)
            self.statusBar().showMessage(f"Eksportert: {file_name}")
        except Exception as exc:  # pragma: no cover - vises i GUI
            QMessageBox.critical(self, "Feil ved eksport", str(exc))

    # endregion

    # region Navigasjon
    def _on_navigation_changed(self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        if current is None:
            return
        key = current.data(0, Qt.UserRole)
        if key and key in self._page_map:
            widget = self._page_map[key]
            self.stack.setCurrentWidget(widget)
            self.title_label.setText(current.text(0))

    # endregion

    # region Hjelpere
    def _update_header_fields(self) -> None:
        if not self._header:
            return
        self.lbl_company.setText(f"Selskap: {self._header.company_name or '–'}")
        self.lbl_orgnr.setText(f"Org.nr: {self._header.orgnr or '–'}")
        per = f"{self._header.fiscal_year or '–'} P{self._header.period_start or '?'}–P{self._header.period_end or '?'}"
        self.lbl_period.setText(f"Periode: {per}")

    # endregion


def _populate_table(
    table: QTableWidget,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    money_cols: Optional[Iterable[int]] = None,
) -> None:
    money_idx = set(money_cols or [])
    table.setRowCount(0)
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)

    for row_idx, row in enumerate(rows):
        table.insertRow(row_idx)
        for col_idx, value in enumerate(row):
            display = _format_value(value, col_idx in money_idx)
            item = QTableWidgetItem(display)
            if col_idx in money_idx:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(row_idx, col_idx, item)

    table.resizeRowsToContents()


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
            return _format_money_norwegian(float(value))
        numeric = float(value)
        return _format_integer_norwegian(numeric) if numeric.is_integer() else _format_money_norwegian(numeric)
    return str(value)


def _format_money_norwegian(value: float) -> str:
    formatted = f"{value:,.2f}"
    formatted = formatted.replace(",", " ")
    return formatted.replace(".", ",")


def _format_integer_norwegian(value: float) -> str:
    formatted = f"{int(round(value)):,}"
    return formatted.replace(",", " ")


def create_app() -> Tuple[QApplication, NordlysWindow]:
    """Fabrikkfunksjon for å opprette QApplication og hovedvindu."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    window = NordlysWindow()
    return app, window


def run() -> None:
    """Starter PySide6-applikasjonen på en trygg måte."""
    try:
        app, window = create_app()
        window.show()
        sys.exit(app.exec())
    except Exception as exc:  # pragma: no cover - fallback dersom Qt ikke starter
        print("Kritisk feil:", exc, file=sys.stderr)
        sys.exit(1)


__all__ = ["NordlysWindow", "create_app", "run"]
