"""PySide6-basert GUI for Nordlys."""
from __future__ import annotations

import math
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
import random
from datetime import date, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple, TYPE_CHECKING, cast
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QTextCursor, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
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
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QStyledItemDelegate,
    QTabWidget,
)

try:
    from PySide6.QtWidgets import QWIDGETSIZE_MAX
except ImportError:  # PySide6 < 6.7
    QWIDGETSIZE_MAX = 16777215

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
from ..saft_customers import (
    CostVoucher,
    build_parent_map,
    compute_customer_supplier_totals,
    extract_cost_vouchers,
    parse_saft,
)
from ..utils import format_currency, format_difference, lazy_pandas

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd

pd = lazy_pandas()


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
    cost_vouchers: List[CostVoucher]
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
    cost_vouchers: List[CostVoucher] = []
    parent_map: Optional[Dict[object, Optional[object]]] = None
    if period_start or period_end:
        parent_map = build_parent_map(root)
        customer_sales, supplier_purchases = compute_customer_supplier_totals(
            root,
            ns,
            date_from=period_start,
            date_to=period_end,
            parent_map=parent_map,
        )
        cost_vouchers = extract_cost_vouchers(
            root,
            ns,
            date_from=period_start,
            date_to=period_end,
            parent_map=parent_map,
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
            if parent_map is None:
                parent_map = build_parent_map(root)
            customer_sales, supplier_purchases = compute_customer_supplier_totals(
                root,
                ns,
                year=analysis_year,
                parent_map=parent_map,
            )
            cost_vouchers = extract_cost_vouchers(
                root,
                ns,
                year=analysis_year,
                parent_map=parent_map,
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
                fetched_json, fetch_error = brreg_future.result()
                if fetch_error:
                    brreg_error = fetch_error
                else:
                    brreg_json = fetched_json
                    if brreg_json is not None:
                        brreg_map = map_brreg_metrics(brreg_json)
                    else:
                        brreg_error = 'Fikk ikke noe data fra Brønnøysundregistrene.'
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
        cost_vouchers=cost_vouchers,
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
    table.setFocusPolicy(Qt.NoFocus)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.setObjectName("cardTable")
    delegate = _CompactRowDelegate(table)
    table.setItemDelegate(delegate)
    table._compact_delegate = delegate  # type: ignore[attr-defined]
    _apply_compact_row_heights(table)
    return table


TOP_BORDER_ROLE = Qt.UserRole + 41
BOTTOM_BORDER_ROLE = Qt.UserRole + 42


class _CompactRowDelegate(QStyledItemDelegate):
    """Gir tabellrader som krymper rundt innholdet."""

    def sizeHint(self, option, index):  # type: ignore[override]
        hint = super().sizeHint(option, index)
        metrics = option.fontMetrics
        if metrics is None:
            return hint

        text = index.data(Qt.DisplayRole)
        if isinstance(text, str) and text:
            lines = text.splitlines() or [""]
            content_height = metrics.height() * len(lines)
        else:
            content_height = metrics.height()

        desired_height = max(12, content_height + 2)
        if hint.height() > desired_height:
            hint.setHeight(desired_height)
        else:
            hint.setHeight(max(hint.height(), desired_height))
        return hint


class _AnalysisTableDelegate(_CompactRowDelegate):
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
        header_mode: QHeaderView.ResizeMode = QHeaderView.ResizeToContents,
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
        self.balance_table = _create_table_widget()
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
        self.result_table = _create_table_widget()
        self.result_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._configure_analysis_table(self.result_table, font_point_size=8)
        result_layout.addWidget(self.result_table)
        result_layout.setAlignment(self.result_table, Qt.AlignTop)
        result_layout.addStretch(1)
        self.result_table.hide()

        self._table_delegate = _AnalysisTableDelegate(self)
        self.balance_table.setItemDelegate(self._table_delegate)
        self.result_table.setItemDelegate(self._table_delegate)

        analysis_splitter = QSplitter(Qt.Horizontal)
        analysis_splitter.setHandleWidth(16)
        analysis_splitter.setChildrenCollapsible(False)
        analysis_splitter.setContentsMargins(0, 0, 0, 0)
        analysis_splitter.addWidget(self.balance_section)
        analysis_splitter.addWidget(self.result_section)
        analysis_splitter.setStretchFactor(0, 3)
        analysis_splitter.setStretchFactor(1, 2)
        analysis_splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        analysis_splitter.setOpaqueResize(True)
        self.analysis_card.add_widget(analysis_splitter)
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

        rows = compute_balance_analysis(self._prepared_df)
        current_label, previous_label = self._year_headers()
        table_rows: List[Tuple[object, object, object, object]] = []
        for row in rows:
            if row.is_header:
                table_rows.append((row.label, "", "", ""))
            else:
                table_rows.append((row.label, row.current, row.previous, row.change))
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
        self._lock_analysis_column_widths(self.balance_table)
        self._schedule_table_height_adjustment(self.balance_table)

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
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setStyleSheet("QTableWidget::item { padding: 0px 6px; }")
        _apply_compact_row_heights(table)

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
        table.resizeRowsToContents()
        header_height = table.horizontalHeader().height()
        rows_height = sum(table.rowHeight(row) for row in range(table.rowCount()))
        if rows_height <= 0:
            rows_height = sum(table.sizeHintForRow(row) for row in range(table.rowCount()))
        if rows_height <= 0:
            default_row = table.verticalHeader().defaultSectionSize() or 18
            rows_height = default_row * table.rowCount()
        grid_extra = max(0, table.rowCount() - 1)
        rows_height += grid_extra
        buffer = max(16, table.verticalHeader().defaultSectionSize() // 2)
        frame = table.frameWidth() * 2
        margins = table.contentsMargins()
        total = header_height + rows_height + buffer + frame + margins.top() + margins.bottom()
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

        self.cost_table = _create_table_widget()
        self.cost_table.setColumnCount(7)
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
        self.cost_table.setHorizontalHeaderLabels(
            [
                "Konto",
                "Kontonavn",
                "Nå",
                "I fjor",
                "Endring (kr)",
                "Endring (%)",
                "Kommentar",
            ]
        )
        self.cost_table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
        )
        header = self.cost_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        self.cost_table.itemChanged.connect(self._on_cost_item_changed)
        self.cost_table.hide()
        self.cost_card.add_widget(self.cost_table)

        layout.addWidget(self.cost_card, 1)

        self._prepared_df: Optional[pd.DataFrame] = None
        self._fiscal_year: Optional[str] = None
        self._cost_comments: Dict[str, str] = {}
        self._updating_cost_table = False

    def set_dataframe(self, df: Optional[pd.DataFrame], fiscal_year: Optional[str] = None) -> None:
        self._fiscal_year = fiscal_year.strip() if fiscal_year and fiscal_year.strip() else None
        self._cost_comments.clear()
        if df is None or df.empty:
            self._prepared_df = None
            self._clear_cost_table()
            return

        self._prepared_df = prepare_regnskap_dataframe(df)
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
        self.cost_table.setRowCount(0)
        self.cost_info.setText("Importer en SAF-T saldobalanse for å analysere kostnadskonti.")
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
        mask = konto_series.astype(str).str.strip().str.startswith(("4", "5", "6", "7", "8"))
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
        previous_values = pd.to_numeric(cost_df.get("forrige"), errors="coerce").fillna(0.0)

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
        self.cost_table.setHorizontalHeaderLabels(headers)

        konto_values = cost_df.get("konto", pd.Series("", index=cost_df.index)).astype(str).str.strip()
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
            rows.append((konto or "", navn or "", float(current), float(previous), change_value, change_percent))

        self._updating_cost_table = True
        try:
            self.cost_table.setRowCount(len(rows))
            for row_idx, (konto, navn, current, previous, change_value, change_percent) in enumerate(rows):
                konto_item = QTableWidgetItem(konto or "—")
                konto_item.setData(Qt.UserRole, konto)
                konto_item.setFlags(konto_item.flags() & ~Qt.ItemIsEditable)
                self.cost_table.setItem(row_idx, 0, konto_item)

                navn_item = QTableWidgetItem(navn or "—")
                navn_item.setFlags(navn_item.flags() & ~Qt.ItemIsEditable)
                self.cost_table.setItem(row_idx, 1, navn_item)

                current_item = QTableWidgetItem(format_currency(current))
                current_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                current_item.setData(Qt.UserRole, current)
                current_item.setFlags(current_item.flags() & ~Qt.ItemIsEditable)
                self.cost_table.setItem(row_idx, 2, current_item)

                previous_item = QTableWidgetItem(format_currency(previous))
                previous_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                previous_item.setData(Qt.UserRole, previous)
                previous_item.setFlags(previous_item.flags() & ~Qt.ItemIsEditable)
                self.cost_table.setItem(row_idx, 3, previous_item)

                change_item = QTableWidgetItem(format_currency(change_value))
                change_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                change_item.setData(Qt.UserRole, change_value)
                change_item.setFlags(change_item.flags() & ~Qt.ItemIsEditable)
                self.cost_table.setItem(row_idx, 4, change_item)

                percent_text = self._format_percent(change_percent)
                percent_item = QTableWidgetItem(percent_text)
                percent_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                percent_item.setData(Qt.UserRole, change_percent)
                percent_item.setFlags(percent_item.flags() & ~Qt.ItemIsEditable)
                self.cost_table.setItem(row_idx, 5, percent_item)

                comment_key = konto or f"row-{row_idx}"
                comment_text = self._cost_comments.get(comment_key, "")
                comment_item = QTableWidgetItem(comment_text)
                comment_item.setData(Qt.UserRole, comment_key)
                self.cost_table.setItem(row_idx, 6, comment_item)
        finally:
            self._updating_cost_table = False

        self.cost_info.hide()
        self.cost_table.show()
        self._cost_highlight_widget.show()
        self._apply_cost_highlighting()
        self.cost_table.scrollToTop()

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
        default_brush = QBrush()
        for row_idx in range(self.cost_table.rowCount()):
            change_item = self.cost_table.item(row_idx, 4)
            if change_item is None:
                continue
            value = change_item.data(Qt.UserRole)
            try:
                numeric = abs(float(value))
            except (TypeError, ValueError):
                numeric = 0.0
            highlight = threshold > 0.0 and numeric >= threshold
            brush = highlight_brush if highlight else default_brush
            for col_idx in range(self.cost_table.columnCount()):
                item = self.cost_table.item(row_idx, col_idx)
                if item is not None and col_idx != 6:
                    item.setBackground(brush)

    def _on_cost_threshold_changed(self, _value: float) -> None:
        if self.cost_table.isVisible():
            self._apply_cost_highlighting()

    def _on_cost_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_cost_table:
            return
        if item.column() != 6:
            return
        key = item.data(Qt.UserRole)
        if not key:
            konto_item = self.cost_table.item(item.row(), 0)
            key = konto_item.data(Qt.UserRole) if konto_item else None
        if not key:
            return
        text = item.text().strip()
        if text:
            self._cost_comments[str(key)] = text
        else:
            self._cost_comments.pop(str(key), None)


class SignalBlocker:
    """Hjelpeklasse som midlertidig skrur av signaler for en QObject."""

    def __init__(self, obj: QObject) -> None:
        self._obj = obj
        self._was_blocked = obj.signalsBlocked()
        obj.blockSignals(True)

    def __enter__(self) -> "SignalBlocker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._obj.blockSignals(self._was_blocked)


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


@dataclass
class VoucherReviewResult:
    """Resultat fra vurdering av et enkelt bilag."""

    voucher: CostVoucher
    status: str
    comment: str


class CostVoucherReviewPage(QWidget):
    """Interaktiv side for bilagskontroll av kostnader."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self._vouchers: List[CostVoucher] = []
        self._sample: List[CostVoucher] = []
        self._results: List[Optional[VoucherReviewResult]] = []
        self._current_index: int = -1
        self._sample_started_at: Optional[datetime] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("costTabs")
        layout.addWidget(self.tab_widget)

        input_container = QWidget()
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(24)

        self.control_card = CardFrame(title, subtitle)
        self.control_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        intro_label = QLabel(
            "Velg et tilfeldig utvalg av inngående fakturaer og dokumenter vurderingen din."
        )
        intro_label.setWordWrap(True)
        self.control_card.add_widget(intro_label)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(QLabel("Antall i utvalg:"))
        self.spin_sample = QSpinBox()
        self.spin_sample.setRange(1, 200)
        self.spin_sample.setValue(5)
        controls.addWidget(self.spin_sample)
        controls.addStretch(1)
        self.btn_start_sample = QPushButton("Start bilagskontroll")
        self.btn_start_sample.clicked.connect(self._on_start_sample)
        controls.addWidget(self.btn_start_sample)
        self.control_card.add_layout(controls)

        self.lbl_available = QLabel("Ingen bilag tilgjengelig.")
        self.lbl_available.setObjectName("infoLabel")
        self.control_card.add_widget(self.lbl_available)

        input_layout.addWidget(self.control_card, 0, Qt.AlignTop)
        input_layout.addStretch(1)

        self.tab_widget.addTab(input_container, "Innput")

        selection_container = QWidget()
        selection_layout = QVBoxLayout(selection_container)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        selection_layout.setSpacing(24)

        self.detail_card = CardFrame("Gjennomgang av bilag")
        self.detail_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lbl_progress = QLabel("Ingen bilag valgt.")
        self.lbl_progress.setObjectName("statusLabel")
        self.detail_card.add_widget(self.lbl_progress)

        meta_grid = QGridLayout()
        meta_grid.setHorizontalSpacing(24)
        meta_grid.setVerticalSpacing(8)
        meta_labels = [
            ("Leverandør", "value_supplier"),
            ("Dokument", "value_document"),
            ("Dato", "value_date"),
            ("Beløp (kostnad)", "value_amount"),
            ("Beskrivelse", "value_description"),
            ("Status", "value_status"),
        ]
        for row, (label_text, attr_name) in enumerate(meta_labels):
            label = QLabel(label_text)
            label.setObjectName("infoLabel")
            meta_grid.addWidget(label, row, 0)
            value_label = QLabel("–")
            value_label.setObjectName("statusLabel")
            value_label.setWordWrap(True)
            meta_grid.addWidget(value_label, row, 1)
            setattr(self, attr_name, value_label)

        self.detail_card.add_layout(meta_grid)

        self.value_status = cast(QLabel, getattr(self, "value_status"))
        self._update_status_display(None)

        self.table_lines = _create_table_widget()
        self.table_lines.setColumnCount(6)
        self.table_lines.setHorizontalHeaderLabels(
            ["Konto", "Kontonavn", "MVA-kode", "Tekst", "Debet", "Kredit"]
        )
        self.table_lines.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_lines.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_lines.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_lines.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_lines.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_lines.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.detail_card.add_widget(self.table_lines)

        comment_label = QLabel("Kommentar (frivillig):")
        comment_label.setObjectName("infoLabel")
        self.detail_card.add_widget(comment_label)

        self.txt_comment = QPlainTextEdit()
        self.txt_comment.setPlaceholderText("Noter funn eller videre oppfølging for bilaget.")
        self.txt_comment.setFixedHeight(100)
        self.detail_card.add_widget(self.txt_comment)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        self.btn_prev = QPushButton("Forrige")
        self.btn_prev.setObjectName("navButton")
        self.btn_prev.clicked.connect(self._on_previous_clicked)
        button_row.addWidget(self.btn_prev)
        button_row.addStretch(1)
        self.btn_reject = QPushButton("Ikke godkjent")
        self.btn_reject.setObjectName("rejectButton")
        self.btn_reject.clicked.connect(self._on_reject_clicked)
        button_row.addWidget(self.btn_reject)
        self.btn_approve = QPushButton("Godkjent")
        self.btn_approve.setObjectName("approveButton")
        self.btn_approve.clicked.connect(self._on_approve_clicked)
        button_row.addWidget(self.btn_approve)
        button_row.addStretch(1)
        self.btn_next = QPushButton("Neste")
        self.btn_next.setObjectName("navButton")
        self.btn_next.clicked.connect(self._on_next_clicked)
        button_row.addWidget(self.btn_next)
        self.detail_card.add_layout(button_row)

        selection_layout.addWidget(self.detail_card)

        self.tab_widget.addTab(selection_container, "Utvalg")

        summary_container = QWidget()
        summary_layout = QVBoxLayout(summary_container)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(24)

        self.summary_card = CardFrame("Oppsummering av kontrollerte bilag")
        self.summary_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lbl_summary = QLabel("Ingen bilag kontrollert ennå.")
        self.lbl_summary.setObjectName("statusLabel")
        self.summary_card.add_widget(self.lbl_summary)

        self.summary_table = _create_table_widget()
        self.summary_table.setColumnCount(6)
        self.summary_table.setHorizontalHeaderLabels(
            ["Bilag", "Dato", "Leverandør", "Beløp", "Status", "Kommentar"]
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.summary_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.summary_table.setVisible(False)
        self.summary_card.add_widget(self.summary_table)

        self.btn_export_pdf = QPushButton("Eksporter arbeidspapir (PDF)")
        self.btn_export_pdf.setObjectName("exportPdfButton")
        self.btn_export_pdf.clicked.connect(self._on_export_pdf)
        self.btn_export_pdf.setEnabled(False)
        self.summary_card.add_widget(self.btn_export_pdf)

        summary_layout.addWidget(self.summary_card, 1)

        self.tab_widget.addTab(summary_container, "Oppsummering")

        self.tab_widget.setTabEnabled(1, False)
        self.tab_widget.setTabEnabled(2, False)
        self.tab_widget.setCurrentIndex(0)

        self.detail_card.setEnabled(False)

    def set_vouchers(self, vouchers: Sequence[CostVoucher]) -> None:
        self._vouchers = list(vouchers)
        self._sample = []
        self._results = []
        self._current_index = -1
        self._sample_started_at = None
        self.detail_card.setEnabled(False)
        self.btn_start_sample.setText("Start bilagskontroll")
        self._clear_current_display()
        self._refresh_summary_table()
        self.tab_widget.setCurrentIndex(0)
        self.tab_widget.setTabEnabled(1, False)
        self.tab_widget.setTabEnabled(2, False)
        count = len(self._vouchers)
        if count:
            self.lbl_available.setText(
                f"Tilgjengelige inngående fakturaer: {count} bilag klar for kontroll."
            )
            self.btn_start_sample.setEnabled(True)
        else:
            self.lbl_available.setText("Ingen kostnadsbilag tilgjengelig i valgt periode.")
            self.btn_start_sample.setEnabled(False)
        self._update_navigation_state()

    def _on_start_sample(self) -> None:
        if not self._vouchers:
            QMessageBox.information(
                self,
                "Ingen bilag",
                "Det finnes ingen inngående fakturaer å kontrollere for valgt datasett.",
            )
            return

        sample_size = min(int(self.spin_sample.value()), len(self._vouchers))
        if sample_size <= 0:
            QMessageBox.information(self, "Ingen utvalg", "Velg et antall større enn null.")
            return

        self._sample = random.sample(self._vouchers, sample_size)
        self._results = [None] * len(self._sample)
        self._current_index = 0
        self._sample_started_at = datetime.now()
        self.detail_card.setEnabled(True)
        self.summary_table.setVisible(False)
        self.btn_export_pdf.setEnabled(False)
        self.lbl_summary.setText("Ingen bilag kontrollert ennå.")
        self.btn_start_sample.setText("Start nytt utvalg")
        self.tab_widget.setTabEnabled(1, True)
        self.tab_widget.setTabEnabled(2, False)
        self.tab_widget.setCurrentIndex(1)
        self._update_status_display(None)
        self._refresh_summary_table()
        self._show_current_voucher()

    def _show_current_voucher(self) -> None:
        if self._current_index < 0 or self._current_index >= len(self._sample):
            self._finish_review()
            return

        voucher = self._sample[self._current_index]
        total = len(self._sample)
        self.lbl_progress.setText(f"Bilag {self._current_index + 1} av {total}")
        supplier_text = voucher.supplier_name or voucher.supplier_id or "–"
        if voucher.supplier_name and voucher.supplier_id:
            supplier_text = f"{voucher.supplier_name} ({voucher.supplier_id})"
        self.value_supplier.setText(supplier_text or "–")
        document_text = voucher.document_number or voucher.transaction_id or "Uten bilagsnummer"
        self.value_document.setText(document_text)
        self.value_date.setText(self._format_date(voucher.transaction_date))
        self.value_amount.setText(self._format_amount(voucher.amount))
        self.value_description.setText(voucher.description or "–")

        self.table_lines.setRowCount(len(voucher.lines))
        for row, line in enumerate(voucher.lines):
            self.table_lines.setItem(row, 0, QTableWidgetItem(line.account or "–"))
            account_name_item = QTableWidgetItem(line.account_name or "–")
            account_name_item.setToolTip(line.account_name or "")
            self.table_lines.setItem(row, 1, account_name_item)
            vat_item = QTableWidgetItem(line.vat_code or "–")
            self.table_lines.setItem(row, 2, vat_item)
            self.table_lines.setItem(row, 3, QTableWidgetItem(line.description or ""))
            debit_item = QTableWidgetItem(self._format_amount(line.debit))
            debit_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.table_lines.setItem(row, 4, debit_item)
            credit_item = QTableWidgetItem(self._format_amount(line.credit))
            credit_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.table_lines.setItem(row, 5, credit_item)

        self.table_lines.resizeRowsToContents()
        current_result = self._get_current_result()
        if current_result and current_result.comment:
            self.txt_comment.setPlainText(current_result.comment)
        else:
            self.txt_comment.clear()
        self._update_status_display(current_result.status if current_result else None)
        self.txt_comment.setFocus()
        self._update_navigation_state()

    def _on_approve_clicked(self) -> None:
        self._record_decision("Godkjent")

    def _on_reject_clicked(self) -> None:
        self._record_decision("Ikke godkjent")

    def _on_previous_clicked(self) -> None:
        if not self._sample or self._current_index <= 0:
            return
        self._save_current_comment()
        self._current_index -= 1
        self._show_current_voucher()

    def _on_next_clicked(self) -> None:
        if not self._sample:
            return
        self._save_current_comment()
        if self._current_index < len(self._sample) - 1:
            self._current_index += 1
            self._show_current_voucher()
            return
        if self.detail_card.isEnabled() and self._all_results_completed():
            self._finish_review()
            return
        next_unreviewed = self._find_next_unreviewed()
        if next_unreviewed is not None and next_unreviewed != self._current_index:
            self._current_index = next_unreviewed
            self._show_current_voucher()
        else:
            self._update_navigation_state()

    def _record_decision(self, status: str) -> None:
        if self._current_index < 0 or self._current_index >= len(self._sample):
            return

        voucher = self._sample[self._current_index]
        comment = self.txt_comment.toPlainText().strip()
        self._results[self._current_index] = VoucherReviewResult(
            voucher=voucher,
            status=status,
            comment=comment,
        )
        self._update_status_display(status)
        self._refresh_summary_table()
        next_index = self._current_index + 1
        if next_index < len(self._sample):
            self._current_index = next_index
            self._show_current_voucher()
            return

        if self._all_results_completed():
            self._finish_review()
            return

        next_unreviewed = self._find_next_unreviewed()
        if next_unreviewed is not None:
            self._current_index = next_unreviewed
            self._show_current_voucher()
        else:
            self._update_navigation_state()

    def _finish_review(self) -> None:
        if not self._sample:
            self._clear_current_display()
            return
        if not self._all_results_completed():
            self._update_navigation_state()
            return

        completed_results = [
            cast(VoucherReviewResult, result)
            for result in self._results
            if result is not None
        ]
        approved = sum(1 for result in completed_results if result.status == "Godkjent")
        rejected = len(completed_results) - approved
        current_result = self._get_current_result()
        self.lbl_progress.setText("Kontroll fullført – du kan fortsatt bla mellom bilagene.")
        if current_result:
            self._update_status_display(current_result.status)
        else:
            self._update_status_display(None)
        self._refresh_summary_table()
        self.lbl_summary.setText(
            f"Resultat: {approved} godkjent / {rejected} ikke godkjent av {len(self._sample)} bilag."
        )
        self.summary_table.setVisible(True)
        self.btn_export_pdf.setEnabled(True)
        self.tab_widget.setTabEnabled(2, True)
        self.tab_widget.setCurrentIndex(2)
        self._update_navigation_state()

    def _refresh_summary_table(self) -> None:
        if not self._sample:
            self.summary_table.setRowCount(0)
            self.summary_table.setVisible(False)
            self.btn_export_pdf.setEnabled(False)
            self.lbl_summary.setText("Ingen bilag kontrollert ennå.")
            self.tab_widget.setTabEnabled(2, False)
            return

        self.summary_table.setVisible(True)
        self.summary_table.setRowCount(len(self._sample))
        completed_count = sum(1 for result in self._results if result is not None)
        if completed_count == 0:
            self.lbl_summary.setText("Ingen bilag kontrollert ennå.")
        elif completed_count < len(self._sample):
            self.lbl_summary.setText(
                f"{completed_count} av {len(self._sample)} bilag vurdert."
            )
        else:
            self.lbl_summary.setText(f"Alle {len(self._sample)} bilag er kontrollert.")
        self.tab_widget.setTabEnabled(2, True)

        for row, voucher in enumerate(self._sample):
            bilag_text = voucher.document_number or voucher.transaction_id or "Bilag"
            self.summary_table.setItem(row, 0, QTableWidgetItem(bilag_text))
            self.summary_table.setItem(
                row,
                1,
                QTableWidgetItem(self._format_date(voucher.transaction_date)),
            )
            supplier_text = voucher.supplier_name or voucher.supplier_id or "–"
            if voucher.supplier_name and voucher.supplier_id:
                supplier_text = f"{voucher.supplier_name} ({voucher.supplier_id})"
            self.summary_table.setItem(row, 2, QTableWidgetItem(supplier_text))
            amount_item = QTableWidgetItem(self._format_amount(voucher.amount))
            amount_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.summary_table.setItem(row, 3, amount_item)
            result = self._results[row] if row < len(self._results) else None
            status_text = result.status if result else "Ikke vurdert"
            comment_text = result.comment if result and result.comment else ""
            self.summary_table.setItem(row, 4, QTableWidgetItem(status_text))
            self.summary_table.setItem(row, 5, QTableWidgetItem(comment_text))

        self.btn_export_pdf.setEnabled(
            completed_count == len(self._sample) and completed_count > 0
        )
        self.summary_table.resizeRowsToContents()

    def _get_current_result(self) -> Optional[VoucherReviewResult]:
        if 0 <= self._current_index < len(self._results):
            return self._results[self._current_index]
        return None

    def _save_current_comment(self) -> None:
        if not (0 <= self._current_index < len(self._results)):
            return
        current = self._results[self._current_index]
        if current is None:
            return
        comment = self.txt_comment.toPlainText().strip()
        if comment == current.comment:
            return
        self._results[self._current_index] = VoucherReviewResult(
            voucher=current.voucher,
            status=current.status,
            comment=comment,
        )
        self._refresh_summary_table()

    def _update_status_display(self, status: Optional[str]) -> None:
        if status == "Godkjent":
            state = "approved"
            text = "Godkjent"
        elif status == "Ikke godkjent":
            state = "rejected"
            text = "Ikke godkjent"
        else:
            state = "pending"
            text = "Ikke vurdert"
        self.value_status.setText(text)
        self.value_status.setProperty("statusState", state)
        self.value_status.style().unpolish(self.value_status)
        self.value_status.style().polish(self.value_status)

    def _find_next_unreviewed(self, start: int = 0) -> Optional[int]:
        if not self._sample:
            return None
        total = len(self._sample)
        for offset in range(start, total):
            if self._results[offset] is None:
                return offset
        for offset in range(0, start):
            if self._results[offset] is None:
                return offset
        return None

    def _all_results_completed(self) -> bool:
        return bool(self._sample) and all(result is not None for result in self._results)

    def _update_navigation_state(self) -> None:
        has_sample = bool(self._sample)
        total = len(self._sample)
        self.btn_prev.setEnabled(has_sample and self._current_index > 0)
        self.btn_next.setEnabled(has_sample and self._current_index < total - 1)

    def _clear_current_display(self) -> None:
        self.lbl_progress.setText("Ingen bilag valgt.")
        self.value_supplier.setText("–")
        self.value_document.setText("–")
        self.value_date.setText("–")
        self.value_amount.setText("–")
        self.value_description.setText("–")
        self._update_status_display(None)
        self.table_lines.setRowCount(0)
        self.txt_comment.clear()
        self._update_navigation_state()

    def _format_amount(self, value: Optional[float]) -> str:
        if value is None:
            return "–"
        try:
            return f"{float(value):,.2f}".replace(",", " ").replace(".", ",")
        except Exception:
            return "–"

    def _format_date(self, value: Optional[date]) -> str:
        if value is None:
            return "–"
        return value.strftime("%d.%m.%Y")

    def _on_export_pdf(self) -> None:
        if not self._results or any(result is None for result in self._results):
            QMessageBox.information(
                self,
                "Utvalget er ikke ferdig",
                "Fullfør kontrollen av alle bilag før du eksporterer arbeidspapiret.",
            )
            return

        default_name = f"bilagskontroll_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Lagre arbeidspapir",
            default_name,
            "PDF-filer (*.pdf)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".pdf"):
            file_path += ".pdf"

        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError:
            QMessageBox.warning(
                self,
                "Manglende avhengighet",
                "Kunne ikke importere reportlab. Installer pakken for å lage PDF-arbeidspapir.",
            )
            return

        styles = getSampleStyleSheet()
        story: List[object] = []
        doc = SimpleDocTemplate(
            file_path,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )

        story.append(Paragraph("Bilagskontroll – Kostnader", styles["Title"]))
        story.append(Spacer(1, 6 * mm))

        completed_results = [cast(VoucherReviewResult, result) for result in self._results]
        total_available = len(self._vouchers)
        sample_size = len(self._sample)
        timestamp = (
            self._sample_started_at.strftime("%d.%m.%Y %H:%M")
            if self._sample_started_at
            else datetime.now().strftime("%d.%m.%Y %H:%M")
        )
        approved = sum(1 for result in completed_results if result.status == "Godkjent")
        rejected = sum(1 for result in completed_results if result.status != "Godkjent")

        info_paragraphs = [
            f"Utvalg: {sample_size} av {total_available} tilgjengelige bilag.",
            f"Tidspunkt for kontroll: {timestamp}.",
            f"Resultat: {approved} godkjent / {rejected} ikke godkjent.",
        ]
        for line in info_paragraphs:
            story.append(Paragraph(line, styles["Normal"]))
        story.append(Spacer(1, 5 * mm))

        summary_data = [["Bilag", "Dato", "Leverandør", "Beløp", "Status", "Kommentar"]]
        for result in completed_results:
            voucher = result.voucher
            bilag_text = voucher.document_number or voucher.transaction_id or "Bilag"
            supplier_text = voucher.supplier_name or voucher.supplier_id or "–"
            if voucher.supplier_name and voucher.supplier_id:
                supplier_text = f"{voucher.supplier_name} ({voucher.supplier_id})"
            summary_data.append(
                [
                    bilag_text,
                    self._format_date(voucher.transaction_date),
                    supplier_text,
                    self._format_amount(voucher.amount),
                    result.status,
                    (result.comment or "").replace("\n", " "),
                ]
            )

        summary_table = Table(
            summary_data,
            colWidths=[30 * mm, 22 * mm, 60 * mm, 20 * mm, 25 * mm, None],
        )
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5f5")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                ]
            )
        )
        story.append(summary_table)
        story.append(Spacer(1, 6 * mm))

        for index, result in enumerate(completed_results, start=1):
            voucher = result.voucher
            heading = voucher.document_number or voucher.transaction_id or f"Bilag {index}"
            story.append(Paragraph(f"{index}. {heading}", styles["Heading3"]))

            meta_rows = [
                ["Dato", self._format_date(voucher.transaction_date)],
                ["Leverandør", voucher.supplier_name or voucher.supplier_id or "–"],
                ["Beløp (kostnad)", self._format_amount(voucher.amount)],
                ["Status", result.status],
            ]
            if voucher.description:
                meta_rows.insert(2, ["Beskrivelse", voucher.description])
            if result.comment:
                meta_rows.append(["Kommentar", result.comment])

            meta_table = Table(meta_rows, colWidths=[35 * mm, None])
            meta_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5f5")),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                    ]
                )
            )
            story.append(meta_table)

            line_data = [["Konto", "Kontonavn", "MVA-kode", "Tekst", "Debet", "Kredit"]]
            for line in voucher.lines:
                line_data.append(
                    [
                        line.account or "–",
                        line.account_name or "–",
                        line.vat_code or "–",
                        line.description or "",
                        self._format_amount(line.debit),
                        self._format_amount(line.credit),
                    ]
                )
            line_table = Table(
                line_data,
                colWidths=[20 * mm, 35 * mm, 18 * mm, None, 20 * mm, 20 * mm],
            )
            line_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0f2fe")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5f5")),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                    ]
                )
            )
            story.append(line_table)
            story.append(Spacer(1, 6 * mm))

        try:
            doc.build(story)
        except Exception as exc:  # pragma: no cover - filsystemfeil vises for bruker
            QMessageBox.warning(
                self,
                "Feil ved lagring",
                f"Klarte ikke å skrive PDF: {exc}",
            )
            return

        QMessageBox.information(
            self,
            "Arbeidspapir lagret",
            f"Arbeidspapiret ble lagret til {file_path}.",
        )

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
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = max(1100, int(available.width() * 0.82))
            height = max(720, int(available.height() * 0.82))
            self.resize(width, height)
        else:
            self.resize(1460, 940)
        # Sikrer at hovedvinduet kan maksimeres uten Qt-advarsler selv om enkelte
        # underliggende widgets har begrensende størrelseshint.
        self.setMinimumSize(1024, 680)
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
        self._cost_vouchers: List[CostVoucher] = []
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
        self.cost_review_page: Optional['CostVoucherReviewPage'] = None
        self.regnskap_page: Optional['RegnskapsanalysePage'] = None
        self.sammenstilling_page: Optional['SammenstillingsanalysePage'] = None
        self._navigation_initialized = False
        self._content_layout: Optional[QVBoxLayout] = None
        self._responsive_update_pending = False
        self._layout_mode: Optional[str] = None

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
        self._content_layout = content_layout

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
        self.stack.currentChanged.connect(lambda _: self._schedule_responsive_update())

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
            self._build_sammenstilling_page,
            attr="sammenstilling_page",
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
            elif key == "rev.kostnad":
                self._register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_cost_page(title, subtitle),
                    attr="cost_review_page",
                )
            else:
                self._register_lazy_page(
                    key,
                    lambda key=key, title=title, subtitle=subtitle: self._build_checklist_page(
                        key, title, subtitle
                    ),
                )

        QTimer.singleShot(0, self._populate_navigation)

    def _populate_navigation(self) -> None:
        if self._navigation_initialized:
            return
        self._navigation_initialized = True
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
        elif key == "plan.sammenstilling" and isinstance(widget, SammenstillingsanalysePage):
            fiscal_year = self._header.fiscal_year if self._header else None
            widget.set_dataframe(self._saft_df, fiscal_year)
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
        elif key == "rev.kostnad" and isinstance(widget, CostVoucherReviewPage):
            widget.set_vouchers(self._cost_vouchers)
        elif key in REVISION_TASKS and isinstance(widget, ChecklistPage):
            widget.set_items(REVISION_TASKS.get(key, []))
        self._schedule_responsive_update()

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

    def _build_sammenstilling_page(self) -> 'SammenstillingsanalysePage':
        return SammenstillingsanalysePage()

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

    def _build_cost_page(self, title: str, subtitle: str) -> 'CostVoucherReviewPage':
        page = CostVoucherReviewPage(title, subtitle)
        page.set_vouchers(self._cost_vouchers)
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
            QPushButton#approveButton { background-color: #16a34a; }
            QPushButton#approveButton:hover:!disabled { background-color: #15803d; }
            QPushButton#approveButton:pressed { background-color: #166534; }
            QPushButton#rejectButton { background-color: #dc2626; }
            QPushButton#rejectButton:hover:!disabled { background-color: #b91c1c; }
            QPushButton#rejectButton:pressed { background-color: #991b1b; }
            QPushButton#navButton { background-color: #0ea5e9; }
            QPushButton#navButton:hover:!disabled { background-color: #0284c7; }
            QPushButton#navButton:pressed { background-color: #0369a1; }
            QPushButton#exportPdfButton { background-color: #f97316; }
            QPushButton#exportPdfButton:hover:!disabled { background-color: #ea580c; }
            QPushButton#exportPdfButton:pressed { background-color: #c2410c; }
            #card { background-color: #ffffff; border-radius: 18px; border: 1px solid rgba(148, 163, 184, 0.28); }
            #cardTitle { font-size: 20px; font-weight: 600; color: #0f172a; letter-spacing: 0.2px; }
            #cardSubtitle { color: #64748b; font-size: 13px; line-height: 1.4; }
            #analysisSectionTitle { font-size: 16px; font-weight: 600; color: #0f172a; letter-spacing: 0.2px; }
            #pageTitle { font-size: 28px; font-weight: 700; color: #020617; letter-spacing: 0.4px; }
            #statusLabel { color: #1f2937; font-size: 14px; line-height: 1.5; }
            QLabel[statusState='approved'] { color: #166534; font-weight: 600; }
            QLabel[statusState='rejected'] { color: #b91c1c; font-weight: 600; }
            QLabel[statusState='pending'] { color: #64748b; font-weight: 500; }
            #infoLabel { color: #475569; font-size: 14px; }
            #cardTable { border: none; gridline-color: rgba(148, 163, 184, 0.35); background-color: transparent; alternate-background-color: #f8fafc; }
            QTableWidget { background-color: transparent; alternate-background-color: #f8fafc; }
            QTableWidget::item { padding: 1px 8px; }
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

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._schedule_responsive_update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_responsive_update()

    def _schedule_responsive_update(self) -> None:
        if self._responsive_update_pending:
            return
        self._responsive_update_pending = True
        QTimer.singleShot(0, self._run_responsive_update)

    def _run_responsive_update(self) -> None:
        self._responsive_update_pending = False
        self._update_responsive_layout()

    def _update_responsive_layout(self) -> None:
        if self._content_layout is None:
            return
        available_width = self.centralWidget().width() if self.centralWidget() else self.width()
        width = max(self.width(), available_width)
        if width <= 0:
            return

        if width < 1400:
            mode = "compact"
            nav_width = 210
            margin = 16
            spacing = 16
            card_margin = 18
            card_spacing = 12
            nav_spacing = 18
            header_min = 80
        elif width < 2000:
            mode = "medium"
            nav_width = 250
            margin = 28
            spacing = 22
            card_margin = 24
            card_spacing = 14
            nav_spacing = 22
            header_min = 100
        else:
            mode = "wide"
            nav_width = 300
            margin = 36
            spacing = 28
            card_margin = 28
            card_spacing = 16
            nav_spacing = 24
            header_min = 120

        self._layout_mode = mode
        self.nav_panel.setMinimumWidth(nav_width)
        self.nav_panel.setMaximumWidth(nav_width)
        self._content_layout.setContentsMargins(margin, margin, margin, margin)
        self._content_layout.setSpacing(spacing)

        nav_layout = self.nav_panel.layout()
        if isinstance(nav_layout, QVBoxLayout):
            nav_padding = max(12, margin - 4)
            nav_layout.setContentsMargins(nav_padding, margin, nav_padding, margin)
            nav_layout.setSpacing(nav_spacing)

        for card in self.findChildren(CardFrame):
            layout = card.layout()
            if isinstance(layout, QVBoxLayout):
                layout.setContentsMargins(card_margin, card_margin, card_margin, card_margin)
                layout.setSpacing(max(card_spacing, 10))
            body_layout = getattr(card, "body_layout", None)
            if isinstance(body_layout, QVBoxLayout):
                body_layout.setSpacing(max(card_spacing - 4, 8))

        self._apply_table_sizing(header_min)

    def _apply_table_sizing(self, min_section_size: int) -> None:
        tables = self.findChildren(QTableWidget)
        if not tables:
            return

        for table in tables:
            header = table.horizontalHeader()
            if header is None:
                continue
            column_count = header.count()
            if column_count <= 0:
                continue

            header.setStretchLastSection(False)
            header.setMinimumSectionSize(min_section_size)

            for col in range(column_count):
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            table.resizeColumnsToContents()

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
        self._cost_vouchers = list(result.cost_vouchers)

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
        if self.cost_review_page:
            self.cost_review_page.set_vouchers(self._cost_vouchers)

        vesentlig_page = cast(Optional[SummaryPage], getattr(self, "vesentlig_page", None))
        if vesentlig_page:
            vesentlig_page.update_summary(self._saft_summary)
        regnskap_page = cast(Optional[RegnskapsanalysePage], getattr(self, "regnskap_page", None))
        if regnskap_page:
            fiscal_year = self._header.fiscal_year if self._header else None
            regnskap_page.set_dataframe(df, fiscal_year)
        sammenstilling_page = cast(
            Optional[SammenstillingsanalysePage], getattr(self, "sammenstilling_page", None)
        )
        if sammenstilling_page:
            fiscal_year = self._header.fiscal_year if self._header else None
            sammenstilling_page.set_dataframe(df, fiscal_year)
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
        self._schedule_responsive_update()

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


def _compact_row_base_height(table: QTableWidget) -> int:
    metrics = table.fontMetrics()
    base_height = metrics.height() if metrics is not None else 0
    # Litt ekstra klaring for å hindre at tekst klippes i høyden.
    return max(12, base_height + 1)


def _apply_compact_row_heights(table: QTableWidget) -> None:
    header = table.verticalHeader()
    if header is None:
        return
    minimum_height = _compact_row_base_height(table)
    header.setMinimumSectionSize(minimum_height)
    header.setDefaultSectionSize(minimum_height)

    if table.rowCount() == 0:
        return

    table.resizeRowsToContents()
    for row in range(table.rowCount()):
        hint = table.sizeHintForRow(row)
        if hint <= 0:
            hint = minimum_height
        table.setRowHeight(row, max(minimum_height, hint))


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
            if col_idx in money_idx or isinstance(value, (int, float)):
                item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(row_idx, col_idx, item)

    table.resizeColumnsToContents()
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    _apply_compact_row_heights(table)
    window = table.window()
    schedule_hook = getattr(window, "_schedule_responsive_update", None)
    if callable(schedule_hook):
        schedule_hook()


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
