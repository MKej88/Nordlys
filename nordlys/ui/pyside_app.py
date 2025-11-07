"""PySide6-basert GUI for Nordlys."""
from __future__ import annotations

import math
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, cast

import pandas as pd
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QTextCursor, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGraphicsDropShadowEffect,
    QHeaderView,
    QHBoxLayout,
    QLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QStyledItemDelegate,
)

from ..brreg import fetch_brreg, map_brreg_metrics
from ..constants import APP_TITLE
from ..industry_groups import (
    IndustryClassification,
    classify_from_brreg_json,
    classify_from_orgnr,
    load_cached_brreg,
)
from ..regnskap import compute_balance_analysis, compute_result_analysis, prepare_regnskap_dataframe
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
from ..saft_customers import compute_customer_supplier_totals, parse_saft
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
    "import": "import.svg",
    "dashboard": "dashboard.svg",
    "plan.saldobalanse": "balance-scale.svg",
    "plan.kontroll": "shield-check.svg",
    "plan.regnskapsanalyse": "analytics.svg",
    "plan.vesentlighet": "target.svg",
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
    analysis_year: Optional[int]
    summary: Optional[Dict[str, float]]
    validation: SaftValidationResult
    brreg_json: Optional[Dict[str, object]]
    brreg_map: Optional[Dict[str, Optional[float]]]
    brreg_error: Optional[str]
    industry: Optional[IndustryClassification]
    industry_error: Optional[str]


def load_saft_file(file_path: str) -> SaftLoadResult:
    """Laster en enkelt SAF-T-fil og returnerer resultatet."""

    tree, ns = parse_saft(file_path)
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
    analysis_year: Optional[int] = None
    customer_sales: Optional[pd.DataFrame] = None
    supplier_purchases: Optional[pd.DataFrame] = None
    if period_start or period_end:
        customer_sales, supplier_purchases = compute_customer_supplier_totals(
            root,
            ns,
            date_from=period_start,
            date_to=period_end,
        )
        if period_end:
            analysis_year = period_end.year
        elif period_start:
            analysis_year = period_start.year
    else:
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
            customer_sales, supplier_purchases = compute_customer_supplier_totals(
                root,
                ns,
                year=analysis_year,
            )

    summary = ns4102_summary_from_tb(dataframe)
    validation = validate_saft_against_xsd(
        file_path,
        header.file_version if header else None,
    )

    brreg_json: Optional[Dict[str, object]] = None
    brreg_map: Optional[Dict[str, Optional[float]]] = None
    brreg_error: Optional[str] = None
    industry: Optional[IndustryClassification] = None
    industry_error: Optional[str] = None
    if header and header.orgnr:
        with ThreadPoolExecutor(max_workers=2) as executor:
            brreg_future = executor.submit(fetch_brreg, header.orgnr)
            industry_future = executor.submit(
                classify_from_orgnr,
                header.orgnr,
                header.company_name,
            )

            try:
                brreg_json = brreg_future.result()
                brreg_map = map_brreg_metrics(brreg_json)
            except Exception as exc:  # pragma: no cover - nettverksfeil vises i GUI
                brreg_error = str(exc)

            try:
                industry = industry_future.result()
            except Exception as exc:  # pragma: no cover - nettverksfeil vises i GUI
                industry_error = str(exc)
                cached: Optional[Dict[str, object]]
                try:
                    cached = load_cached_brreg(header.orgnr)
                except Exception:
                    cached = None
                if cached:
                    try:
                        industry = classify_from_brreg_json(
                            header.orgnr,
                            header.company_name,
                            cached,
                        )
                        industry_error = None
                    except Exception as cache_exc:  # pragma: no cover - sjelden
                        industry_error = str(cache_exc)
    elif header:
        industry_error = "SAF-T mangler organisasjonsnummer."

    return SaftLoadResult(
        file_path=file_path,
        header=header,
        dataframe=dataframe,
        customers=customers,
        customer_sales=customer_sales,
        suppliers=suppliers,
        supplier_purchases=supplier_purchases,
        analysis_year=analysis_year,
        summary=summary,
        validation=validation,
        brreg_json=brreg_json,
        brreg_map=brreg_map,
        brreg_error=brreg_error,
        industry=industry,
        industry_error=industry_error,
    )


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
            result = load_saft_file(self._file_path)
            self.finished.emit(result)
        except Exception as exc:  # pragma: no cover - presenteres i GUI
            self.error.emit(str(exc))


class MultiSaftLoadWorker(QObject):
    """Laster flere SAF-T-filer sekvensielt i bakgrunnen."""

    finished: Signal = Signal(object)
    error: Signal = Signal(str)

    def __init__(self, file_paths: Sequence[str]) -> None:
        super().__init__()
        self._file_paths = list(file_paths)

    @Slot()
    def run(self) -> None:
        results: List[SaftLoadResult] = []
        try:
            for path in self._file_paths:
                result = load_saft_file(path)
                results.append(result)
        except Exception as exc:  # pragma: no cover - feil vises i GUI
            failed_index = len(results)
            if 0 <= failed_index < len(self._file_paths):
                failed_path = Path(self._file_paths[failed_index]).name
                message = f"Feil ved lesing av {failed_path}: {exc}"
            else:
                message = str(exc)
            self.error.emit(message)
            return
        self.finished.emit(results)


def _create_table_widget() -> QTableWidget:
    table = QTableWidget()
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.setObjectName("cardTable")
    return table


TOP_BORDER_ROLE = Qt.UserRole + 41
BOTTOM_BORDER_ROLE = Qt.UserRole + 42


class _AnalysisTableDelegate(QStyledItemDelegate):
    """Tegner egendefinerte grenser for analysene."""

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        super().paint(painter, option, index)
        if index.data(TOP_BORDER_ROLE):
            painter.save()
            pen = QPen(QColor(15, 23, 42))
            pen.setWidth(2)
            painter.setPen(pen)
            rect = option.rect
            painter.drawLine(rect.topLeft(), rect.topRight())
            painter.restore()
        if index.data(BOTTOM_BORDER_ROLE):
            painter.save()
            pen = QPen(QColor(15, 23, 42))
            pen.setWidth(2)
            painter.setPen(pen)
            rect = option.rect
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())
            painter.restore()


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
        layout.setSizeConstraint(QLayout.SetMinimumSize)

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
        self.body_layout.setSizeConstraint(QLayout.SetMinimumSize)
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


class ImportPage(QWidget):
    """Viser importstatus og bransjeinnsikt."""

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.status_card = CardFrame("Status", "Hurtigoversikt over siste import og anbefalinger.")
        self.status_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.status_label = QLabel("Ingen SAF-T fil er lastet inn ennå.")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.status_card.add_widget(self.status_label)

        self.validation_label = QLabel("Ingen XSD-validering er gjennomført.")
        self.validation_label.setObjectName("statusLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.validation_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.status_card.add_widget(self.validation_label)

        self.brreg_label = QLabel("Regnskapsregister: ingen data importert ennå.")
        self.brreg_label.setObjectName("statusLabel")
        self.brreg_label.setWordWrap(True)
        self.brreg_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.brreg_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.status_card.add_widget(self.brreg_label)
        layout.addWidget(self.status_card)

        self.industry_card = CardFrame(
            "Bransjeinnsikt",
            "Vi finner næringskode og bransje automatisk etter import.",
        )
        self.industry_label = QLabel(
            "Importer en SAF-T-fil for å se hvilken bransje kunden havner i."
        )
        self.industry_label.setObjectName("statusLabel")
        self.industry_label.setWordWrap(True)
        self.industry_label.setTextFormat(Qt.RichText)
        self.industry_card.add_widget(self.industry_label)
        layout.addWidget(self.industry_card)

        self.log_card = CardFrame(
            "Importlogg",
            "Siste hendelser under import og validering.",
        )
        self.log_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("logField")
        self.log_output.setMinimumHeight(260)
        self.log_card.add_widget(self.log_output)
        layout.addWidget(self.log_card, 1)

        layout.addStretch(1)

    def update_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.updateGeometry()
        self.status_card.updateGeometry()

    def update_validation_status(self, result: Optional[SaftValidationResult]) -> None:
        if result is None:
            self.validation_label.setText("Ingen XSD-validering er gjennomført.")
            self.validation_label.updateGeometry()
            self.status_card.updateGeometry()
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
        self.validation_label.updateGeometry()
        self.status_card.updateGeometry()

    def update_brreg_status(self, message: str) -> None:
        self.brreg_label.setText(message)
        self.brreg_label.updateGeometry()
        self.status_card.updateGeometry()

    def update_industry(
        self,
        classification: Optional[IndustryClassification],
        error: Optional[str] = None,
    ) -> None:
        if error:
            self.industry_label.setText(
                textwrap.dedent(
                    f"""
                    <p><strong>Bransje ikke tilgjengelig:</strong> {error}</p>
                    <p>Prøv igjen når du har nettilgang, eller sjekk at SAF-T-filen inneholder
                    organisasjonsnummer.</p>
                    """
                ).strip()
            )
            return

        if classification is None:
            self.industry_label.setText(
                "Importer en SAF-T-fil for å se hvilken bransje kunden havner i."
            )
            return

        name = classification.name or "Ukjent navn"
        naringskode = classification.naringskode or "–"
        description = classification.description or "Ingen beskrivelse fra Brreg."
        sn2 = classification.sn2 or "–"
        text = textwrap.dedent(
            f"""
            <p><strong>{classification.group}</strong></p>
            <ul>
                <li><strong>Selskap:</strong> {name}</li>
                <li><strong>Org.nr:</strong> {classification.orgnr}</li>
                <li><strong>Næringskode:</strong> {naringskode} ({description})</li>
                <li><strong>SN2:</strong> {sn2}</li>
                <li><strong>Kilde:</strong> {classification.source}</li>
            </ul>
            """
        ).strip()
        self.industry_label.setText(text)

    def reset_log(self) -> None:
        self.log_output.clear()

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.log_output.appendPlainText(entry)
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)


class DashboardPage(QWidget):
    """Viser nøkkeltall for selskapet."""

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

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
    filtered = result[columns]
    zero_mask = (
        filtered["IB"].abs().le(1e-9)
        & filtered["Endringer"].abs().le(1e-9)
        & filtered["UB"].abs().le(1e-9)
    )
    filtered = filtered[~zero_mask]
    return filtered.reset_index(drop=True)


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
        analysis_split = QHBoxLayout()
        analysis_split.setSpacing(24)
        analysis_split.setContentsMargins(0, 0, 0, 0)

        self.balance_section = QWidget()
        self.balance_section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
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
        self.balance_table = _create_table_widget()
        self.balance_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._configure_analysis_table(self.balance_table, font_point_size=9, row_height=20)
        balance_layout.addWidget(self.balance_table, 1)
        self.balance_table.hide()

        self.result_section = QWidget()
        self.result_section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
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
        self.result_table = _create_table_widget()
        self.result_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._configure_analysis_table(self.result_table, font_point_size=9, row_height=22)
        result_layout.addWidget(self.result_table, 1)
        self.result_table.hide()

        self._table_delegate = _AnalysisTableDelegate(self)
        self.balance_table.setItemDelegate(self._table_delegate)
        self.result_table.setItemDelegate(self._table_delegate)

        analysis_split.addWidget(self.balance_section, 1)
        analysis_split.addWidget(self.result_section, 1)
        analysis_split.setStretch(0, 1)
        analysis_split.setStretch(1, 1)
        self.analysis_card.add_layout(analysis_split)
        layout.addWidget(self.analysis_card, 1)

        self._prepared_df: Optional[pd.DataFrame] = None
        self._fiscal_year: Optional[str] = None

    def set_dataframe(self, df: Optional[pd.DataFrame], fiscal_year: Optional[str] = None) -> None:
        self._fiscal_year = fiscal_year.strip() if fiscal_year and fiscal_year.strip() else None
        if df is None or df.empty:
            self._prepared_df = None
            self._clear_balance_table()
            self._clear_result_table()
            return

        self._prepared_df = prepare_regnskap_dataframe(df)
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

    def _clear_result_table(self) -> None:
        self.result_table.hide()
        self.result_table.setRowCount(0)
        self.result_info.show()

    def _update_balance_table(self) -> None:
        if self._prepared_df is None or self._prepared_df.empty:
            self._clear_balance_table()
            return

        rows = compute_balance_analysis(self._prepared_df)
        current_label, previous_label = self._year_headers()
        table_rows: List[Tuple[object, object, object, object]] = []
        for row in rows:
            if row.is_header:
                table_rows.append((row.label, "", "", ""))
            else:
                table_rows.append((row.label, row.current, row.previous, row.change))
            if row.label == "Sum eiendeler" or row.label == "Sum egenkapital og gjeld":
                table_rows.append(("", "", "", ""))
        _populate_table(
            self.balance_table,
            ["Kategori", current_label, previous_label, "Endring"],
            table_rows,
            money_cols={1, 2, 3},
        )
        self.balance_info.hide()
        self.balance_table.show()
        self._apply_balance_styles()
        self._apply_change_coloring(self.balance_table)
        self._set_analysis_column_widths(self.balance_table)

    def _update_result_table(self) -> None:
        if self._prepared_df is None or self._prepared_df.empty:
            self._clear_result_table()
            return

        rows = compute_result_analysis(self._prepared_df)
        current_label, previous_label = self._year_headers()
        table_rows: List[Tuple[object, object, object, object]] = []
        for row in rows:
            if row.is_header:
                table_rows.append((row.label, "", "", ""))
            else:
                table_rows.append((row.label, row.current, row.previous, row.change))
        _populate_table(
            self.result_table,
            ["Kategori", current_label, previous_label, "Endring"],
            table_rows,
            money_cols={1, 2, 3},
        )
        self.result_info.hide()
        self.result_table.show()
        self._apply_change_coloring(self.result_table)
        self._set_analysis_column_widths(self.result_table)

    def _configure_analysis_table(
        self,
        table: QTableWidget,
        *,
        font_point_size: int,
        row_height: int,
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
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        table.verticalHeader().setDefaultSectionSize(row_height)
        table.setStyleSheet("QTableWidget::item { padding: 2px 6px; }")

    def _set_analysis_column_widths(self, table: QTableWidget) -> None:
        header = table.horizontalHeader()
        column_count = table.columnCount()
        if column_count == 0:
            return
        for col in range(column_count):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

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
        labels: List[str] = []
        for row_idx in range(self.balance_table.rowCount()):
            label_item = self.balance_table.item(row_idx, 0)
            labels.append(label_item.text().strip() if label_item else "")
        for row_idx in range(self.balance_table.rowCount()):
            label_text = labels[row_idx]
            if not label_text:
                continue
            is_bold = label_text in bold_labels
            has_bottom_border = label_text in bottom_border_labels
            has_top_border = label_text in top_border_labels
            next_label = labels[row_idx + 1] if row_idx + 1 < len(labels) else ""
            if has_bottom_border and next_label in top_border_labels and next_label:
                has_bottom_border = False
            for col_idx in range(self.balance_table.columnCount()):
                item = self.balance_table.item(row_idx, col_idx)
                if item is None:
                    continue
                font = item.font()
                font.setBold(is_bold)
                item.setFont(font)
                item.setData(BOTTOM_BORDER_ROLE, has_bottom_border)
                item.setData(TOP_BORDER_ROLE, has_top_border)
        self.balance_table.viewport().update()

    def _apply_change_coloring(self, table: QTableWidget) -> None:
        change_col = 3
        green = QBrush(QColor(21, 128, 61))
        red = QBrush(QColor(220, 38, 38))
        default_brush = QBrush(QColor(15, 23, 42))
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

    def update_comparison(
        self,
        _rows: Optional[Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]],
    ) -> None:
        return


class BrregPage(QWidget):
    """Plassholder-side for sammenstillingsanalyse uten innhold."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

    def update_mapping(self, rows: Optional[Sequence[Tuple[str, str]]]) -> None:
        _ = rows

    def update_json(self, data: Optional[Dict[str, object]]) -> None:
        _ = data


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
        self.top_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.top_card.add_widget(self.top_table)
        self.top_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.top_card, 1)

        self.set_controls_enabled(False)

    def _handle_calc_clicked(self) -> None:
        rows = self._on_calc_top("3xxx", int(self.top_spin.value()))
        if rows:
            self.set_top_customers(rows)

    def set_checklist_items(self, items: Iterable[str]) -> None:
        # Sjekkpunkter støttes ikke lenger visuelt, men metoden beholdes for kompatibilitet.
        del items

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
        rows = self._on_calc_top("kostnadskonti", int(self.top_spin.value()))
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
        self._industry: Optional[IndustryClassification] = None
        self._industry_error: Optional[str] = None
        self._current_file: Optional[str] = None

        self._dataset_results: Dict[str, SaftLoadResult] = {}
        self._dataset_years: Dict[str, Optional[int]] = {}
        self._dataset_orgnrs: Dict[str, Optional[str]] = {}
        self._dataset_order: List[str] = []
        self._dataset_positions: Dict[str, int] = {}
        self._current_dataset_key: Optional[str] = None
        self._loading_files: List[str] = []

        self._load_thread: Optional[QThread] = None
        self._load_worker: Optional[QObject] = None
        self._progress_dialog: Optional[QProgressDialog] = None

        self._page_map: Dict[str, QWidget] = {}
        self._page_factories: Dict[str, Callable[[], QWidget]] = {}
        self._page_attributes: Dict[str, str] = {}
        self._latest_comparison_rows: Optional[
            Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]
        ] = None
        self.revision_pages: Dict[str, QWidget] = {}
        self.import_page: Optional['ImportPage'] = None
        self.sales_ar_page: Optional[SalesArPage] = None
        self.purchases_ap_page: Optional['PurchasesApPage'] = None
        self.regnskap_page: Optional['RegnskapsanalysePage'] = None

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
        root_layout.addWidget(self.nav_panel, 0)

        content_wrapper = QWidget()
        content_wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.setSpacing(24)
        root_layout.addWidget(content_wrapper, 1)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)

        self.title_label = QLabel("Import")
        self.title_label.setObjectName("pageTitle")
        header_layout.addWidget(self.title_label, 1)

        self.dataset_combo = QComboBox()
        self.dataset_combo.setObjectName("datasetCombo")
        self.dataset_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.dataset_combo.setVisible(False)
        self.dataset_combo.currentIndexChanged.connect(self._on_dataset_changed)
        header_layout.addWidget(self.dataset_combo)

        self.btn_open = QPushButton("Åpne SAF-T XML …")
        self.btn_open.clicked.connect(self.on_open)
        header_layout.addWidget(self.btn_open)

        self.btn_export = QPushButton("Eksporter rapport (Excel)")
        self.btn_export.clicked.connect(self.on_export)
        self.btn_export.setEnabled(False)
        header_layout.addWidget(self.btn_export)

        content_layout.addLayout(header_layout)

        self.info_card = CardFrame("Selskapsinformasjon")
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(24)
        info_grid.setVerticalSpacing(8)

        self.lbl_company = QLabel("Selskap: –")
        self.lbl_orgnr = QLabel("Org.nr: –")
        self.lbl_period = QLabel("Periode: –")
        info_grid.addWidget(self.lbl_company, 0, 0)
        info_grid.addWidget(self.lbl_orgnr, 0, 1)
        info_grid.addWidget(self.lbl_period, 0, 2)
        self.info_card.add_layout(info_grid)
        content_layout.addWidget(self.info_card)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)

        self._create_pages()

        status = QStatusBar()
        status.showMessage("Klar.")
        self.setStatusBar(status)

    def _create_pages(self) -> None:
        import_page = ImportPage()
        self._register_page("import", import_page, attr="import_page")

        self._register_lazy_page("dashboard", self._build_dashboard_page, attr="dashboard_page")
        self._register_lazy_page(
            "plan.saldobalanse",
            self._build_saldobalanse_page,
            attr="saldobalanse_page",
        )
        self._register_lazy_page(
            "plan.kontroll",
            self._build_kontroll_page,
            attr="kontroll_page",
        )
        self._register_lazy_page(
            "plan.regnskapsanalyse",
            self._build_regnskap_page,
            attr="regnskap_page",
        )
        self._register_lazy_page(
            "plan.vesentlighet",
            self._build_vesentlig_page,
            attr="vesentlig_page",
        )
        self._register_lazy_page(
            "plan.sammenstilling",
            self._build_brreg_page,
            attr="brreg_page",
        )

        revision_definitions = {
            "rev.innkjop": (
                "Innkjøp og leverandørgjeld",
                "Fokuser på varekjøp, kredittider og periodisering.",
            ),
            "rev.lonn": ("Lønn", "Kontroll av lønnskjøringer, skatt og arbeidsgiveravgift."),
            "rev.kostnad": ("Kostnad", "Analyse av driftskostnader og periodisering."),
            "rev.driftsmidler": (
                "Driftsmidler",
                "Verifikasjon av investeringer og avskrivninger.",
            ),
            "rev.finans": ("Finans og likvid", "Bank, finansielle instrumenter og kontantstrøm."),
            "rev.varelager": (
                "Varelager og varekjøp",
                "Telling, nedskrivninger og bruttomargin.",
            ),
            "rev.salg": (
                "Salg og kundefordringer",
                "Omsetning, cut-off og reskontro.",
            ),
            "rev.mva": ("MVA", "Kontroll av avgiftsbehandling og rapportering."),
        }
        for key, (title, subtitle) in revision_definitions.items():
            if key == "rev.salg":
                self._register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_sales_page(title, subtitle),
                    attr="sales_ar_page",
                )
            elif key == "rev.innkjop":
                self._register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_purchases_page(title, subtitle),
                    attr="purchases_ap_page",
                )
            else:
                self._register_lazy_page(
                    key,
                    lambda key=key, title=title, subtitle=subtitle: self._build_checklist_page(
                        key, title, subtitle
                    ),
                )

        self._populate_navigation()

    def _populate_navigation(self) -> None:
        nav = self.nav_panel
        import_item = nav.add_root("Import", "import")
        dashboard_item = nav.add_root("Dashboard", "dashboard")

        planning_root = nav.add_root("Planlegging")
        nav.add_child(planning_root, "Saldobalanse", "plan.saldobalanse")
        nav.add_child(planning_root, "Kontroll IB", "plan.kontroll")
        nav.add_child(planning_root, "Regnskapsanalyse", "plan.regnskapsanalyse")
        nav.add_child(planning_root, "Vesentlighetsvurdering", "plan.vesentlighet")
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
        nav.tree.setCurrentItem(import_item.item)

    def _register_page(self, key: str, widget: QWidget, *, attr: Optional[str] = None) -> None:
        self._page_map[key] = widget
        if attr:
            self._page_attributes[key] = attr
            setattr(self, attr, widget)
        self.stack.addWidget(widget)
        self._apply_page_state(key, widget)

    def _register_lazy_page(
        self, key: str, factory: Callable[[], QWidget], *, attr: Optional[str] = None
    ) -> None:
        self._page_factories[key] = factory
        if attr:
            self._page_attributes[key] = attr

    def _ensure_page(self, key: str) -> Optional[QWidget]:
        widget = self._page_map.get(key)
        if widget is not None:
            return widget
        return self._materialize_page(key)

    def _materialize_page(self, key: str) -> Optional[QWidget]:
        factory = self._page_factories.get(key)
        if factory is None:
            return None
        widget = factory()
        attr = self._page_attributes.get(key)
        self._register_page(key, widget, attr=attr)
        return widget

    def _apply_page_state(self, key: str, widget: QWidget) -> None:
        if key in REVISION_TASKS:
            self.revision_pages[key] = widget
        if key == "dashboard" and isinstance(widget, DashboardPage):
            widget.update_summary(self._saft_summary)
        elif key == "plan.saldobalanse" and isinstance(widget, DataFramePage):
            widget.set_dataframe(self._saft_df)
        elif key == "plan.kontroll" and isinstance(widget, ComparisonPage):
            widget.update_comparison(self._latest_comparison_rows)
        elif key == "plan.regnskapsanalyse" and isinstance(widget, RegnskapsanalysePage):
            fiscal_year = self._header.fiscal_year if self._header else None
            widget.set_dataframe(self._saft_df, fiscal_year)
            widget.update_comparison(self._latest_comparison_rows)
        elif key == "plan.vesentlighet" and isinstance(widget, SummaryPage):
            widget.update_summary(self._saft_summary)
        elif key == "plan.sammenstilling" and isinstance(widget, BrregPage):
            widget.update_mapping(None)
            widget.update_json(None)
        elif key == "rev.salg" and isinstance(widget, SalesArPage):
            widget.set_checklist_items(REVISION_TASKS.get(key, []))
            has_data = self._customer_sales is not None and not self._customer_sales.empty
            widget.set_controls_enabled(has_data)
            if not has_data:
                widget.clear_top_customers()
        elif key == "rev.innkjop" and isinstance(widget, PurchasesApPage):
            has_data = self._supplier_purchases is not None and not self._supplier_purchases.empty
            widget.set_controls_enabled(has_data)
            if not has_data:
                widget.clear_top_suppliers()
        elif key in REVISION_TASKS and isinstance(widget, ChecklistPage):
            widget.set_items(REVISION_TASKS.get(key, []))

    def _build_dashboard_page(self) -> 'DashboardPage':
        return DashboardPage()

    def _build_saldobalanse_page(self) -> DataFramePage:
        return DataFramePage(
            "Saldobalanse",
            "Viser saldobalansen slik den er rapportert i SAF-T.",
            frame_builder=_standard_tb_frame,
            money_columns=("IB", "Endringer", "UB"),
            header_mode=QHeaderView.ResizeToContents,
            full_window=True,
        )

    def _build_kontroll_page(self) -> ComparisonPage:
        return ComparisonPage(
            "Kontroll av inngående balanse",
            "Sammenligner SAF-T mot Regnskapsregisteret for å avdekke avvik i inngående balanse.",
        )

    def _build_regnskap_page(self) -> 'RegnskapsanalysePage':
        return RegnskapsanalysePage()

    def _build_vesentlig_page(self) -> SummaryPage:
        return SummaryPage(
            "Vesentlighetsvurdering",
            "Nøkkeltall som understøtter fastsettelse av vesentlighetsgrenser.",
        )

    def _build_brreg_page(self) -> BrregPage:
        return BrregPage()

    def _build_sales_page(self, title: str, subtitle: str) -> SalesArPage:
        page = SalesArPage(title, subtitle, self._on_calc_top_customers)
        page.set_checklist_items(REVISION_TASKS.get("rev.salg", []))
        has_data = self._customer_sales is not None and not self._customer_sales.empty
        page.set_controls_enabled(has_data)
        if not has_data:
            page.clear_top_customers()
        return page

    def _build_purchases_page(self, title: str, subtitle: str) -> 'PurchasesApPage':
        page = PurchasesApPage(title, subtitle, self._on_calc_top_suppliers)
        has_data = self._supplier_purchases is not None and not self._supplier_purchases.empty
        page.set_controls_enabled(has_data)
        if not has_data:
            page.clear_top_suppliers()
        return page

    def _build_checklist_page(self, key: str, title: str, subtitle: str) -> ChecklistPage:
        page = ChecklistPage(title, subtitle)
        page.set_items(REVISION_TASKS.get(key, []))
        return page

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget { font-family: 'Inter', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; font-size: 14px; color: #0f172a; }
            QMainWindow { background-color: #edf1f7; }
            #navPanel { background-color: #0b1120; color: #e2e8f0; border-right: 1px solid rgba(148, 163, 184, 0.18); }
            #logoLabel { font-size: 26px; font-weight: 700; letter-spacing: 0.6px; color: #f8fafc; }
            #navTree { background: transparent; border: none; color: #dbeafe; font-size: 14px; }
            #navTree:focus { outline: none; border: none; }
            QTreeWidget::item:focus { outline: none; }
            #navTree::item { height: 34px; padding: 6px 10px; border-radius: 10px; margin: 2px 0; }
            #navTree::item:selected { background-color: rgba(59, 130, 246, 0.35); color: #f8fafc; font-weight: 600; }
            #navTree::item:hover { background-color: rgba(59, 130, 246, 0.18); }
            QPushButton { background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #2563eb, stop:1 #1d4ed8); color: white; border-radius: 10px; padding: 10px 20px; font-weight: 600; letter-spacing: 0.2px; }
            QPushButton:focus { outline: none; }
            QPushButton:disabled { background-color: #94a3b8; color: #e5e7eb; }
            QPushButton:hover:!disabled { background-color: #1e40af; }
            QPushButton:pressed { background-color: #1d4ed8; }
            #card { background-color: #ffffff; border-radius: 18px; border: 1px solid rgba(148, 163, 184, 0.28); }
            #cardTitle { font-size: 20px; font-weight: 600; color: #0f172a; letter-spacing: 0.2px; }
            #cardSubtitle { color: #64748b; font-size: 13px; line-height: 1.4; }
            #analysisSectionTitle { font-size: 16px; font-weight: 600; color: #0f172a; letter-spacing: 0.2px; }
            #pageTitle { font-size: 28px; font-weight: 700; color: #020617; letter-spacing: 0.4px; }
            #statusLabel { color: #1f2937; font-size: 14px; line-height: 1.5; }
            #infoLabel { color: #475569; font-size: 14px; }
            #cardTable { border: none; gridline-color: rgba(148, 163, 184, 0.35); background-color: transparent; alternate-background-color: #f8fafc; }
            QTableWidget { background-color: transparent; alternate-background-color: #f8fafc; }
            QTableWidget::item { padding: 10px 8px; }
            QTableWidget::item:selected { background-color: rgba(37, 99, 235, 0.22); color: #0f172a; }
            QHeaderView::section { background-color: transparent; border: none; font-weight: 600; color: #1f2937; padding: 10px 6px; }
            QHeaderView::section:horizontal { border-bottom: 1px solid rgba(148, 163, 184, 0.45); }
            QListWidget#checklist { border: none; }
            QListWidget#checklist::item { padding: 12px 14px; margin: 4px 0; border-radius: 10px; }
            QListWidget#checklist::item:selected { background-color: rgba(37, 99, 235, 0.16); color: #0f172a; font-weight: 600; }
            QListWidget#checklist::item:hover { background-color: rgba(15, 23, 42, 0.05); }
            #statBadge { background-color: #f8fafc; border: 1px solid rgba(148, 163, 184, 0.35); border-radius: 16px; }
            #statTitle { font-size: 12px; font-weight: 600; color: #475569; text-transform: uppercase; letter-spacing: 1.2px; }
            #statValue { font-size: 26px; font-weight: 700; color: #0f172a; }
            #statDescription { font-size: 12px; color: #64748b; }
            QStatusBar { background: transparent; color: #475569; padding-right: 24px; border-top: 1px solid rgba(148, 163, 184, 0.3); }
            QComboBox, QSpinBox { background-color: #ffffff; border: 1px solid rgba(148, 163, 184, 0.5); border-radius: 8px; padding: 6px 10px; min-height: 32px; }
            QComboBox QAbstractItemView { border-radius: 8px; padding: 6px; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox::down-arrow { image: none; }
            QSpinBox::up-button, QSpinBox::down-button { border: none; background: transparent; width: 20px; }
            QToolTip { background-color: #0f172a; color: #f8fafc; border: none; padding: 8px 10px; border-radius: 8px; }
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
        file_names, _ = QFileDialog.getOpenFileNames(
            self,
            "Åpne SAF-T XML",
            str(Path.home()),
            "SAF-T XML (*.xml);;Alle filer (*)",
        )
        if not file_names:
            return
        self._loading_files = list(file_names)
        summary = (
            "Starter import av 1 SAF-T-fil"
            if len(file_names) == 1
            else f"Starter import av {len(file_names)} SAF-T-filer"
        )
        self._log_import_event(summary, reset=True)
        for name in file_names:
            self._log_import_event(f"Forbereder: {Path(name).name}")
        worker = MultiSaftLoadWorker(file_names)
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
        if len(self._loading_files) == 1:
            message = f"Laster SAF-T: {Path(self._loading_files[0]).name} …"
        elif len(self._loading_files) > 1:
            message = f"Laster {len(self._loading_files)} SAF-T-filer …"
        else:
            message = "Laster SAF-T …"
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
        self.btn_export.setEnabled(False if loading else has_data)
        if hasattr(self, "dataset_combo"):
            if loading:
                self.dataset_combo.setEnabled(False)
            else:
                self.dataset_combo.setEnabled(bool(self._dataset_order))
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

    def _log_import_event(self, message: str, *, reset: bool = False) -> None:
        if not getattr(self, "import_page", None):
            return
        if reset:
            self.import_page.reset_log()
        self.import_page.append_log(message)

    def _finalize_loading(self, status_message: Optional[str] = None) -> None:
        self._close_progress_dialog()
        self._set_loading_state(False)
        if status_message:
            self.statusBar().showMessage(status_message)
        self._loading_files = []

    @Slot(object)
    def _on_load_finished(self, result_obj: object) -> None:
        results: List[SaftLoadResult]
        if isinstance(result_obj, list):
            results = [cast(SaftLoadResult, item) for item in result_obj]
        else:
            results = [cast(SaftLoadResult, result_obj)]
        self._apply_saft_batch(results)
        self._finalize_loading()

    def _apply_saft_batch(self, results: Sequence[SaftLoadResult]) -> None:
        if not results:
            self._dataset_results = {}
            self._dataset_years = {}
            self._dataset_orgnrs = {}
            self._dataset_order = []
            self._dataset_positions = {}
            self._current_dataset_key = None
            self._update_dataset_selector()
            return

        self._dataset_results = {res.file_path: res for res in results}
        self._dataset_positions = {res.file_path: idx for idx, res in enumerate(results)}
        self._dataset_years = {
            res.file_path: self._resolve_dataset_year(res) for res in results
        }
        self._dataset_orgnrs = {
            res.file_path: self._resolve_dataset_orgnr(res) for res in results
        }
        self._dataset_order = self._sorted_dataset_keys()
        default_key = self._select_default_dataset_key()
        self._current_dataset_key = default_key
        self._update_dataset_selector()

        if default_key is None:
            return

        self._activate_dataset(default_key, log_event=True)
        if len(results) > 1:
            self._log_import_event(
                "Alle filer er lastet inn. Bruk årvelgeren for å bytte datasett."
            )

    def _resolve_dataset_year(self, result: SaftLoadResult) -> Optional[int]:
        if result.analysis_year is not None:
            return result.analysis_year
        header = result.header
        if header and header.fiscal_year:
            try:
                return int(str(header.fiscal_year).strip())
            except (TypeError, ValueError):
                return None
        return None

    def _resolve_dataset_orgnr(self, result: SaftLoadResult) -> Optional[str]:
        header = result.header
        if not header or not header.orgnr:
            return None
        raw_orgnr = str(header.orgnr).strip()
        if not raw_orgnr:
            return None
        normalized = "".join(ch for ch in raw_orgnr if ch.isdigit())
        if normalized:
            return normalized
        return raw_orgnr

    def _sorted_dataset_keys(self) -> List[str]:
        def sort_key(key: str) -> Tuple[int, int]:
            year = self._dataset_years.get(key)
            year_value = year if year is not None else 9999
            position = self._dataset_positions.get(key, 0)
            return (year_value, position)

        return sorted(self._dataset_results.keys(), key=sort_key)

    def _select_default_dataset_key(self) -> Optional[str]:
        if not self._dataset_order:
            return None
        for key in reversed(self._dataset_order):
            year = self._dataset_years.get(key)
            if year is not None:
                return key
        return self._dataset_order[-1]

    def _update_dataset_selector(self) -> None:
        if not hasattr(self, "dataset_combo"):
            return
        combo = self.dataset_combo
        combo.blockSignals(True)
        combo.clear()
        if not self._dataset_order:
            combo.setVisible(False)
            combo.blockSignals(False)
            return
        for key in self._dataset_order:
            result = self._dataset_results.get(key)
            if result is None:
                continue
            combo.addItem(self._dataset_label(result), userData=key)
        combo.setVisible(True)
        combo.setEnabled(bool(self._dataset_order))
        if self._current_dataset_key in self._dataset_order:
            combo.setCurrentIndex(self._dataset_order.index(self._current_dataset_key))
        combo.blockSignals(False)

    def _dataset_label(self, result: SaftLoadResult) -> str:
        year = self._dataset_years.get(result.file_path)
        if year is None and result.analysis_year is not None:
            year = result.analysis_year
        if year is not None:
            return str(year)
        header = result.header
        if header and header.fiscal_year and str(header.fiscal_year).strip():
            return str(header.fiscal_year).strip()
        position = self._dataset_positions.get(result.file_path)
        if position is not None:
            return str(position + 1)
        return "1"

    def _find_previous_dataset_key(self, current_key: str) -> Optional[str]:
        current_year = self._dataset_years.get(current_key)
        current_org = self._dataset_orgnrs.get(current_key)
        if current_year is None or not current_org:
            return None
        exact_year = current_year - 1
        for key, year in self._dataset_years.items():
            if key == current_key or year is None:
                continue
            if year == exact_year and self._dataset_orgnrs.get(key) == current_org:
                return key
        closest_key: Optional[str] = None
        closest_year: Optional[int] = None
        for key, year in self._dataset_years.items():
            if key == current_key or year is None:
                continue
            if self._dataset_orgnrs.get(key) != current_org:
                continue
            if year < current_year and (closest_year is None or year > closest_year):
                closest_key = key
                closest_year = year
        return closest_key

    def _prepare_dataframe_with_previous(
        self,
        current_df: pd.DataFrame,
        previous_df: Optional[pd.DataFrame],
    ) -> pd.DataFrame:
        work = current_df.copy()
        if previous_df is None:
            return work
        if "Konto" not in work.columns or "UB_netto" not in previous_df.columns:
            return work

        def _konto_key(value: object) -> str:
            if value is None:
                return ""
            try:
                if pd.isna(value):  # type: ignore[arg-type]
                    return ""
            except Exception:
                pass
            return str(value).strip()

        prev_work = previous_df.copy()
        if "Konto" not in prev_work.columns:
            return work
        prev_work["_konto_key"] = prev_work["Konto"].map(_konto_key)
        mapping = (
            prev_work.loc[prev_work["_konto_key"] != ""]
            .drop_duplicates("_konto_key")
            .set_index("_konto_key")["UB_netto"]
            .fillna(0.0)
        )

        work["forrige"] = work["Konto"].map(_konto_key).map(mapping).fillna(0.0)
        return work

    def _activate_dataset(self, key: str, *, log_event: bool = False) -> None:
        result = self._dataset_results.get(key)
        if result is None:
            return
        previous_key = self._find_previous_dataset_key(key)
        previous_result = (
            self._dataset_results.get(previous_key) if previous_key else None
        )
        self._current_dataset_key = key
        if hasattr(self, "dataset_combo") and key in self._dataset_order:
            combo = self.dataset_combo
            combo.blockSignals(True)
            combo.setCurrentIndex(self._dataset_order.index(key))
            combo.blockSignals(False)
        self._apply_saft_result(result, previous_result, log_event=log_event)
        if not log_event:
            self._log_import_event(f"Viser datasett: {self._dataset_label(result)}")

    def _on_dataset_changed(self, index: int) -> None:
        if index < 0 or index >= self.dataset_combo.count():
            return
        key = self.dataset_combo.itemData(index)
        if not isinstance(key, str):
            return
        if key == self._current_dataset_key:
            return
        self._activate_dataset(key)

    def _apply_saft_result(
        self,
        result: SaftLoadResult,
        previous_result: Optional[SaftLoadResult] = None,
        *,
        log_event: bool = False,
    ) -> None:
        self._header = result.header
        previous_df = previous_result.dataframe if previous_result is not None else None
        self._saft_df = self._prepare_dataframe_with_previous(result.dataframe, previous_df)
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

        df = self._saft_df if self._saft_df is not None else result.dataframe
        self._update_header_fields()
        saldobalanse_page = cast(Optional[DataFramePage], getattr(self, "saldobalanse_page", None))
        if saldobalanse_page:
            saldobalanse_page.set_dataframe(df)
        self._latest_comparison_rows = None
        kontroll_page = cast(Optional[ComparisonPage], getattr(self, "kontroll_page", None))
        if kontroll_page:
            kontroll_page.update_comparison(None)
        dashboard_page = cast(Optional[DashboardPage], getattr(self, "dashboard_page", None))
        if dashboard_page:
            dashboard_page.update_summary(self._saft_summary)

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
        dataset_label = self._dataset_label(result)
        status_bits = [
            company or "Ukjent selskap",
            f"Org.nr: {orgnr}" if orgnr else "Org.nr: –",
            f"Periode: {period}" if period else None,
            f"{account_count} konti analysert",
            f"Driftsinntekter: {revenue_txt}",
        ]
        if dataset_label:
            status_bits.append(f"Datasett: {dataset_label}")
        status_message = " · ".join(bit for bit in status_bits if bit)
        if getattr(self, "import_page", None):
            self.import_page.update_status(status_message)
        if log_event:
            self._log_import_event(
                f"{dataset_label or Path(result.file_path).name}: SAF-T lesing fullført. {account_count} konti analysert."
            )

        validation = result.validation
        if getattr(self, "import_page", None):
            self.import_page.update_validation_status(validation)
        if log_event:
            if validation.is_valid is True:
                self._log_import_event("XSD-validering fullført: OK.")
            elif validation.is_valid is False:
                self._log_import_event("XSD-validering feilet.")
            elif validation.is_valid is None and validation.details:
                self._log_import_event("XSD-validering: detaljer tilgjengelig, se importstatus.")
        if validation.is_valid is False:
            QMessageBox.warning(
                self,
                "XSD-validering feilet",
                validation.details or "Valideringen mot XSD feilet. Se Import-siden for detaljer.",
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

        vesentlig_page = cast(Optional[SummaryPage], getattr(self, "vesentlig_page", None))
        if vesentlig_page:
            vesentlig_page.update_summary(self._saft_summary)
        regnskap_page = cast(Optional[RegnskapsanalysePage], getattr(self, "regnskap_page", None))
        if regnskap_page:
            fiscal_year = self._header.fiscal_year if self._header else None
            regnskap_page.set_dataframe(df, fiscal_year)
        brreg_status = self._process_brreg_result(result)

        self.btn_export.setEnabled(True)
        status_parts = [f"Datasett aktivt: {dataset_label or Path(result.file_path).name}."]
        if len(self._dataset_order) > 1:
            status_parts.append(f"{len(self._dataset_order)} filer tilgjengelig.")
        if brreg_status:
            status_parts.append(brreg_status)
        self.statusBar().showMessage(" ".join(status_parts))

    def _process_brreg_result(self, result: SaftLoadResult) -> str:
        """Oppdaterer interne strukturer med data fra Regnskapsregisteret."""

        self._industry = result.industry
        self._industry_error = result.industry_error
        if getattr(self, "import_page", None):
            self.import_page.update_industry(result.industry, result.industry_error)

        self._brreg_json = result.brreg_json
        self._brreg_map = result.brreg_map

        if getattr(self, "brreg_page", None):
            self.brreg_page.update_mapping(None)
            self.brreg_page.update_json(None)

        if result.brreg_json is None:
            self._update_comparison_tables(None)
            if result.brreg_error:
                error_text = str(result.brreg_error).strip()
                if "\n" in error_text:
                    error_text = error_text.splitlines()[0]
                message = f"Regnskapsregister: import feilet ({error_text})."
            elif result.header and result.header.orgnr:
                message = "Regnskapsregister: import feilet."
            else:
                message = "Regnskapsregister: ikke tilgjengelig (mangler org.nr.)."
            if getattr(self, "import_page", None):
                self.import_page.update_brreg_status(message)
            self._log_import_event(message)
            return message

        if not self._saft_summary:
            self._update_comparison_tables(None)
            message = "Regnskapsregister: import vellykket, men ingen SAF-T-oppsummering å sammenligne."
            if getattr(self, "import_page", None):
                self.import_page.update_brreg_status(message)
            self._log_import_event(message)
            return message

        comparison_rows = self._build_brreg_comparison_rows()
        self._update_comparison_tables(comparison_rows)
        message = "Regnskapsregister: import vellykket."
        if getattr(self, "import_page", None):
            self.import_page.update_brreg_status(message)
        self._log_import_event(message)
        return message

    def _update_comparison_tables(
        self,
        rows: Optional[Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]],
    ) -> None:
        """Oppdaterer tabellene som sammenligner SAF-T med Regnskapsregisteret."""

        self._latest_comparison_rows = list(rows) if rows is not None else None
        kontroll_page = cast(Optional[ComparisonPage], getattr(self, "kontroll_page", None))
        if kontroll_page:
            kontroll_page.update_comparison(rows)
        regnskap_page = cast(Optional[RegnskapsanalysePage], getattr(self, "regnskap_page", None))
        if regnskap_page:
            regnskap_page.update_comparison(rows)

    def _build_brreg_comparison_rows(
        self,
    ) -> Optional[List[Tuple[str, Optional[float], Optional[float], Optional[float]]]]:
        """Konstruerer rader for sammenligning mot Regnskapsregisteret."""

        if not self._saft_summary or not self._brreg_map:
            return None

        return [
            (
                "Driftsinntekter",
                self._saft_summary.get("driftsinntekter"),
                self._brreg_map.get("driftsinntekter"),
                None,
            ),
            (
                "EBIT",
                self._saft_summary.get("ebit"),
                self._brreg_map.get("ebit"),
                None,
            ),
            (
                "Årsresultat",
                self._saft_summary.get("arsresultat"),
                self._brreg_map.get("arsresultat"),
                None,
            ),
            (
                "Eiendeler (UB)",
                self._saft_summary.get("eiendeler_UB_brreg"),
                self._brreg_map.get("eiendeler_UB"),
                None,
            ),
            (
                "Egenkapital (UB)",
                self._saft_summary.get("egenkapital_UB"),
                self._brreg_map.get("egenkapital_UB"),
                None,
            ),
            (
                "Gjeld (UB)",
                self._saft_summary.get("gjeld_UB_brreg"),
                self._brreg_map.get("gjeld_UB"),
                None,
            ),
        ]

    @Slot(str)
    def _on_load_error(self, message: str) -> None:
        self._finalize_loading("Feil ved lesing av SAF-T.")
        self._log_import_event(f"Feil ved lesing av SAF-T: {message}")
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
            self._log_import_event(f"Rapport eksportert: {Path(file_name).name}")
        except Exception as exc:  # pragma: no cover - vises i GUI
            self._log_import_event(f"Feil ved eksport: {exc}")
            QMessageBox.critical(self, "Feil ved eksport", str(exc))

    # endregion

    # region Navigasjon
    def _on_navigation_changed(self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        if current is None:
            return
        key = current.data(0, Qt.UserRole)
        if not key:
            return
        widget = self._ensure_page(key)
        if widget is None:
            return
        self.stack.setCurrentWidget(widget)
        self.title_label.setText(current.text(0))
        if hasattr(self, "info_card"):
            self.info_card.setVisible(key in {"dashboard", "import"})

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
            if isinstance(value, (int, float)):
                item.setData(Qt.UserRole, float(value))
            else:
                item.setData(Qt.UserRole, None)
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
    truncated = math.trunc(value)
    formatted = f"{truncated:,}"
    return formatted.replace(",", " ")


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
