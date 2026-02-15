from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime
from typing import (
    TYPE_CHECKING,
    Callable,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    cast,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QTextOption
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedLayout,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import saft_customers
from ...helpers.formatting import format_currency, format_difference
from ...regnskap.driftsmidler import (
    AssetAccession,
    AssetAccessionSummary,
    AssetMovement,
    CapitalizationCandidate,
    find_asset_accessions,
    find_capitalization_candidates,
    find_possible_disposals,
    summarize_asset_accessions_by_account,
)
from ...regnskap.mva import (
    VatDeviation,
    VatDeviationAccountSummary,
    find_vat_deviations,
    summarize_vat_deviations,
)
from ...saft.models import CostVoucher
from ..tables import (
    apply_compact_row_heights,
    compact_row_base_height,
    create_table_widget,
    populate_table,
)
from ..widgets import CardFrame, EmptyStateWidget, StatBadge

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd

__all__ = [
    "FixedAssetsPage",
    "ChecklistPage",
    "VoucherReviewResult",
    "CostVoucherReviewPage",
    "SalesArPage",
    "PurchasesApPage",
    "MvaDeviationPage",
]


def _requested_top_count(spin_box: QSpinBox) -> int:
    """Returner brukers valg etter at spinboxen har tolket inndata."""

    spin_box.interpretText()
    value = spin_box.value()
    return max(spin_box.minimum(), min(spin_box.maximum(), value))


@dataclass
class VoucherReviewResult:
    """Resultat fra vurdering av et enkelt bilag."""

    voucher: "saft_customers.CostVoucher"
    status: str
    comment: str


@dataclass(frozen=True)
class _MvaAccountVoucherRow:
    voucher_number: str
    transaction_date: Optional[date]
    supplier: str
    observed_vat_code: str
    counter_accounts: str
    voucher_amount: float
    description: str
    is_deviation: bool


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


class _MvaAccountDetailsDialog(QDialog):
    """Detaljvindu for avvikende bilag på én konto."""

    def __init__(
        self,
        *,
        account: str,
        account_name: str,
        expected_vat_code: str,
        rows: Sequence[_MvaAccountVoucherRow],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"MVA-avvik {account}")
        self.setModal(True)
        self.resize(1000, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        intro = QLabel(
            "Konto: "
            f"{account} ({account_name or 'Ukjent konto'})\n"
            f"Vanlig MVA-kode: {expected_vat_code}\n"
            f"Avvikende bilag: {len(rows)}"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        table = create_table_widget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(
            [
                "Bilag",
                "Dato",
                "Leverandør",
                "MVA-kode",
                "Motkonto",
                "Beløp",
                "Beskrivelse",
            ]
        )
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        table_rows = [
            (
                item.voucher_number,
                self._format_date(item.transaction_date),
                item.supplier,
                item.observed_vat_code,
                item.counter_accounts,
                item.voucher_amount,
                item.description or "—",
            )
            for item in sorted(rows, key=_mva_account_row_sort_key)
        ]
        populate_table(
            table,
            [
                "Bilag",
                "Dato",
                "Leverandør",
                "MVA-kode",
                "Motkonto",
                "Beløp",
                "Beskrivelse",
            ],
            table_rows,
            money_cols={5},
        )
        layout.addWidget(table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _format_date(value: Optional[date]) -> str:
        if value is None:
            return "—"
        return value.strftime("%d.%m.%Y")


def _mva_deviation_sort_key(item: VatDeviation) -> tuple[int, date, str]:
    has_no_date = 1 if item.transaction_date is None else 0
    sort_date = item.transaction_date or date.min
    return (has_no_date, sort_date, item.voucher_number)


def _mva_account_row_sort_key(item: _MvaAccountVoucherRow) -> tuple[int, date, str]:
    has_no_date = 1 if item.transaction_date is None else 0
    sort_date = item.transaction_date or date.min
    return (has_no_date, sort_date, item.voucher_number)


class MvaDeviationPage(QWidget):
    """Viser oppsummering av avvikende mva-behandling per konto."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self._deviations_by_account: dict[str, list[VatDeviation]] = {}
        self._account_names: dict[str, str] = {}
        self._expected_vat_by_account: dict[str, str] = {}
        self._vouchers: list[CostVoucher] = []
        self._all_deviations: list[VatDeviation] = []
        self._all_summaries: list[VatDeviationAccountSummary] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        intro = QLabel(
            "Siden viser oppsummering per konto med antall avvikende bilag og sum. "
            "Trykk 'Vis bilag' for detaljer."
        )
        intro.setWordWrap(True)
        self.card.add_widget(intro)

        self.status_label = QLabel("Ingen bilag tilgjengelig.")
        self.status_label.setObjectName("infoLabel")
        self.card.add_widget(self.status_label)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(10)
        self.chk_min_amount = QCheckBox("Vis kun avvik over sum:")
        self.chk_min_amount.toggled.connect(self._on_filter_toggled)
        self.spin_min_amount = QDoubleSpinBox()
        self.spin_min_amount.setRange(0, 1_000_000_000)
        self.spin_min_amount.setDecimals(0)
        self.spin_min_amount.setSingleStep(1000)
        self.spin_min_amount.setValue(10000)
        self.spin_min_amount.setSuffix(" kr")
        self.spin_min_amount.setGroupSeparatorShown(True)
        self.spin_min_amount.setEnabled(False)
        self.spin_min_amount.valueChanged.connect(
            lambda _value: self._apply_summary_filter()
        )
        filter_row.addWidget(self.chk_min_amount)
        filter_row.addWidget(self.spin_min_amount)
        filter_row.addStretch(1)
        self.card.add_layout(filter_row)

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(12)
        self.badge_accounts = StatBadge(
            "Kontoer med avvik",
            "Antall kontoer med avvikende MVA-behandling",
        )
        self.badge_vouchers = StatBadge(
            "Avvikende bilag",
            "Antall bilag som avviker fra vanlig MVA-kode",
        )
        self.badge_amount = StatBadge(
            "Sum alle kontoer",
            "Samlet beløp for avvikende bilag",
        )
        summary_row.addWidget(self.badge_accounts)
        summary_row.addWidget(self.badge_vouchers)
        summary_row.addWidget(self.badge_amount)
        summary_row.addStretch(1)
        self.card.add_layout(summary_row)

        self.empty_state = EmptyStateWidget(
            "Ingen avvik funnet",
            "Importer en SAF-T-fil for å se avvikende mva-behandling.",
            icon="✅",
        )
        self.empty_state.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )

        self.table = create_table_widget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            [
                "Konto",
                "Kontonavn",
                "Vanlig MVA-kode",
                "Avvikende bilag",
                "Sum avvik",
                "Antall bilag",
                "Detaljer",
            ]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 132)
        self.table.verticalHeader().setMinimumSectionSize(40)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.hide()

        self.card.add_widget(self.empty_state)
        self.card.add_widget(self.table)
        layout.addWidget(self.card, 1)
        self._set_summary_values(0, 0, 0.0)

    def set_vouchers(self, vouchers: Sequence[CostVoucher]) -> None:
        self._deviations_by_account = {}
        self._account_names = {}
        self._expected_vat_by_account = {}
        self._vouchers = list(vouchers)
        self._all_deviations = []
        self._all_summaries = []

        if not vouchers:
            self.status_label.setText("Ingen bilag tilgjengelig i valgt periode.")
            self.table.setRowCount(0)
            self._set_summary_values(0, 0, 0.0)
            self._toggle_table(False)
            self.chk_min_amount.setEnabled(False)
            self.spin_min_amount.setEnabled(False)
            return

        deviations = find_vat_deviations(vouchers)
        summaries = summarize_vat_deviations(deviations)
        self._all_deviations = list(deviations)
        self._all_summaries = list(summaries)
        if not summaries:
            self.status_label.setText("Fant ingen avvikende MVA-behandling per konto.")
            self.table.setRowCount(0)
            self._set_summary_values(0, 0, 0.0)
            self._toggle_table(False)
            self.chk_min_amount.setEnabled(False)
            self.spin_min_amount.setEnabled(False)
            return

        for item in deviations:
            account = item.account
            if account not in self._deviations_by_account:
                self._deviations_by_account[account] = []
            self._deviations_by_account[account].append(item)
            self._account_names[account] = item.account_name
            self._expected_vat_by_account[account] = item.expected_vat_code

        self.chk_min_amount.setEnabled(True)
        self.spin_min_amount.setEnabled(self.chk_min_amount.isChecked())
        self._apply_summary_filter()

    def _on_filter_toggled(self, checked: bool) -> None:
        self.spin_min_amount.setEnabled(checked)
        self._apply_summary_filter()

    def _apply_summary_filter(self) -> None:
        if not self._vouchers:
            return
        if not self._all_summaries:
            self.status_label.setText("Fant ingen avvikende MVA-behandling per konto.")
            self.table.setRowCount(0)
            self._set_summary_values(0, 0, 0.0)
            self._toggle_table(False)
            return

        if self.chk_min_amount.isChecked():
            minimum_sum = float(self.spin_min_amount.value())
            visible_summaries = [
                summary
                for summary in self._all_summaries
                if summary.deviation_amount >= minimum_sum
            ]
        else:
            minimum_sum = 0.0
            visible_summaries = list(self._all_summaries)

        if not visible_summaries:
            self.table.setRowCount(0)
            self._set_summary_values(0, 0, 0.0)
            self._toggle_table(False)
            self.status_label.setText(
                "Ingen kontoer med avvik over valgt beløpsgrense "
                f"({format_currency(minimum_sum)})."
            )
            return

        self.table.setRowCount(len(visible_summaries))
        for row, summary in enumerate(visible_summaries):
            self._set_text_item(row, 0, summary.account)
            self._set_text_item(row, 1, summary.account_name)
            self._set_text_item(row, 2, summary.expected_vat_code)
            self._set_text_item(row, 3, self._format_count(summary.deviation_count))
            self._set_text_item(row, 4, format_currency(summary.deviation_amount))
            self._set_text_item(row, 5, self._format_count(summary.total_count))

            button = QPushButton("Vis bilag")
            button.setObjectName("tableActionButton")
            button.setMinimumWidth(108)
            button.setMinimumHeight(30)
            button.clicked.connect(
                lambda _checked=False, account=summary.account: self._show_details(
                    account
                )
            )
            self.table.setCellWidget(row, 6, button)
            self.table.setRowHeight(row, 40)

        total_amount = sum(item.deviation_amount for item in visible_summaries)
        total_deviation_vouchers = sum(
            item.deviation_count for item in visible_summaries
        )
        self._set_summary_values(
            len(visible_summaries), total_deviation_vouchers, total_amount
        )
        if self.chk_min_amount.isChecked():
            self.status_label.setText(
                "Viser "
                f"{self._format_count(len(visible_summaries))} kontoer med MVA-avvik "
                f"over {format_currency(minimum_sum)}."
            )
        else:
            self.status_label.setText(
                f"Fant {self._format_count(len(visible_summaries))} kontoer med MVA-avvik."
            )
        self._toggle_table(True)

    def _set_summary_values(
        self, account_count: int, voucher_count: int, total_amount: float
    ) -> None:
        self.badge_accounts.set_value(self._format_count(account_count))
        self.badge_vouchers.set_value(self._format_count(voucher_count))
        self.badge_amount.set_value(format_currency(total_amount))

    def _show_details(self, account: str) -> None:
        expected_vat = self._expected_vat_by_account.get(account)
        if not expected_vat:
            return
        rows = [
            row
            for row in self._collect_account_rows(account, expected_vat)
            if row.is_deviation
        ]
        if not rows:
            return
        dialog = _MvaAccountDetailsDialog(
            account=account,
            account_name=self._account_names.get(account, ""),
            expected_vat_code=expected_vat,
            rows=rows,
            parent=self,
        )
        dialog.exec()

    def _collect_account_rows(
        self, account: str, expected_vat_code: str
    ) -> list[_MvaAccountVoucherRow]:
        rows: list[_MvaAccountVoucherRow] = []
        for voucher in self._vouchers:
            vat_codes: set[str] = set()
            counter_accounts: set[str] = set()
            has_account = False
            account_amount = 0.0
            for line in voucher.lines:
                line_account = (line.account or "").strip()
                if line_account != account:
                    if line_account:
                        counter_accounts.add(line_account)
                    continue
                has_account = True
                vat_code = (line.vat_code or "").strip()
                if vat_code:
                    vat_codes.update(
                        part.strip() for part in vat_code.split(",") if part.strip()
                    )
                else:
                    vat_codes.add("Ingen")
                account_amount += self._safe_amount(line.debit) - self._safe_amount(
                    line.credit
                )
            if not has_account:
                continue
            observed_vat_code = " + ".join(sorted(vat_codes)) if vat_codes else "Ingen"
            counter_text = (
                ", ".join(sorted(counter_accounts)) if counter_accounts else "—"
            )
            rows.append(
                _MvaAccountVoucherRow(
                    voucher_number=(
                        (voucher.document_number or "").strip()
                        or (voucher.transaction_id or "").strip()
                        or "Uten bilagsnummer"
                    ),
                    transaction_date=voucher.transaction_date,
                    supplier=(
                        (voucher.supplier_name or "").strip()
                        or (voucher.supplier_id or "").strip()
                        or "Ukjent leverandør"
                    ),
                    observed_vat_code=observed_vat_code,
                    counter_accounts=counter_text,
                    voucher_amount=abs(account_amount),
                    description=(voucher.description or "").strip(),
                    is_deviation=observed_vat_code != expected_vat_code,
                )
            )
        return rows

    @staticmethod
    def _safe_amount(value: Optional[float]) -> float:
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _set_text_item(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        if column in {3, 4, 5}:
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.table.setItem(row, column, item)

    @staticmethod
    def _format_count(value: int) -> str:
        return f"{value:,}".replace(",", " ")

    def _toggle_table(self, show_table: bool) -> None:
        if show_table:
            self.empty_state.hide()
            self.table.show()
            return
        self.table.hide()
        self.empty_state.show()


class _CostVoucherReviewModule(QWidget):
    """Håndterer én modul for bilagskontroll (random eller spesifikk)."""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        subtitle: str,
        *,
        is_specific: bool,
    ) -> None:
        super().__init__(parent)
        self._is_specific = is_specific
        self._vouchers: List["saft_customers.CostVoucher"] = []
        self._sample: List["saft_customers.CostVoucher"] = []
        self._results: List[Optional[VoucherReviewResult]] = []
        self._current_index: int = -1
        self._sample_started_at: Optional[datetime] = None
        self._total_available_amount: float = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("costModuleTabs")
        layout.addWidget(self.tab_widget)

        input_container = (
            self._build_specific_input_tab(title)
            if self._is_specific
            else self._build_random_input_tab(title, subtitle)
        )
        self.tab_widget.addTab(input_container, "Inndata")

        selection_container = self._build_selection_tab()
        self.tab_widget.addTab(selection_container, "Utvalg")

        summary_container = self._build_summary_tab()
        self.tab_widget.addTab(summary_container, "Oppsummering")

        self.tab_widget.setTabEnabled(1, False)
        self.tab_widget.setTabEnabled(2, False)
        self.tab_widget.setCurrentIndex(0)

        self.detail_card.setEnabled(False)
        self._update_coverage_badges()

    def _build_random_input_tab(self, title: str, subtitle: str) -> QWidget:
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
        self.spin_sample.setValue(10)
        self.spin_sample.setGroupSeparatorShown(True)
        controls.addWidget(self.spin_sample)
        controls.addStretch(1)
        self.btn_start_sample = QPushButton("Start bilagskontroll")
        self.btn_start_sample.clicked.connect(self._on_start_sample)
        controls.addWidget(self.btn_start_sample)
        self.control_card.add_layout(controls)

        self.lbl_available = QLabel("Ingen bilag tilgjengelig.")
        self.lbl_available.setObjectName("infoLabel")
        self.control_card.add_widget(self.lbl_available)

        self.lbl_total_amount = QLabel("Sum inngående faktura: —")
        self.lbl_total_amount.setObjectName("infoLabel")
        self.control_card.add_widget(self.lbl_total_amount)

        input_layout.addWidget(self.control_card, 0, Qt.AlignTop)
        input_layout.addStretch(1)
        return input_container

    def _build_specific_input_tab(self, title: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        card = CardFrame(
            title,
            "Velg bilag basert på regler som er relevante for revisjonen.",
        )
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        intro = QLabel(
            "Her kan du velge bilag basert på terskel, størrelse eller enkle "
            "avviksmønstre."
        )
        intro.setWordWrap(True)
        card.add_widget(intro)

        input_grid = QGridLayout()
        input_grid.setHorizontalSpacing(12)
        input_grid.setVerticalSpacing(12)
        input_grid.addWidget(QLabel("Terskel (kr):"), 0, 0)
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(0, 1_000_000_000)
        self.spin_threshold.setSingleStep(1_000)
        self.spin_threshold.setValue(100_000)
        self.spin_threshold.setSuffix(" kr")
        self.spin_threshold.setGroupSeparatorShown(True)
        self.spin_threshold.setFixedWidth(180)
        input_grid.addWidget(self.spin_threshold, 0, 1)
        self.btn_specific_threshold = QPushButton("Velg alle over terskel")
        self.btn_specific_threshold.clicked.connect(self._on_specific_threshold)
        input_grid.addWidget(self.btn_specific_threshold, 0, 2)

        input_grid.addWidget(QLabel("Topp (antall):"), 1, 0)
        self.spin_top = QSpinBox()
        self.spin_top.setRange(1, 5000)
        self.spin_top.setValue(10)
        self.spin_top.setGroupSeparatorShown(True)
        self.spin_top.setFixedWidth(180)
        input_grid.addWidget(self.spin_top, 1, 1)
        self.btn_specific_top = QPushButton("Velg topp beløp")
        self.btn_specific_top.clicked.connect(self._on_specific_top)
        input_grid.addWidget(self.btn_specific_top, 1, 2)
        input_grid.setColumnStretch(3, 1)
        card.add_layout(input_grid)

        quick_layout = QHBoxLayout()
        quick_layout.setSpacing(12)
        quick_layout.addWidget(QLabel("Hurtigvalg:"))
        self.btn_specific_round = QPushButton("Runde beløp")
        self.btn_specific_round.clicked.connect(self._on_specific_round)
        quick_layout.addWidget(self.btn_specific_round)
        self.btn_specific_missing_desc = QPushButton("Mangler beskrivelse")
        self.btn_specific_missing_desc.clicked.connect(self._on_specific_missing_desc)
        quick_layout.addWidget(self.btn_specific_missing_desc)
        self.btn_specific_no_ap = QPushButton("Uten leverandørgjeld")
        self.btn_specific_no_ap.clicked.connect(self._on_specific_no_ap)
        quick_layout.addWidget(self.btn_specific_no_ap)
        quick_layout.addStretch(1)
        card.add_layout(quick_layout)

        self.lbl_specific_available = QLabel("Ingen bilag tilgjengelig.")
        self.lbl_specific_available.setObjectName("infoLabel")
        card.add_widget(self.lbl_specific_available)

        self.lbl_specific_result = QLabel("Ingen utvalg gjort ennå.")
        self.lbl_specific_result.setObjectName("infoLabel")
        card.add_widget(self.lbl_specific_result)

        layout.addWidget(card, 0, Qt.AlignTop)
        layout.addStretch(1)
        return page

    def _build_selection_tab(self) -> QWidget:
        selection_container = QWidget()
        selection_layout = QVBoxLayout(selection_container)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        selection_layout.setSpacing(24)

        selection_content_row = QHBoxLayout()
        selection_content_row.setContentsMargins(0, 0, 0, 0)
        selection_content_row.setSpacing(24)
        selection_content_row.setAlignment(Qt.AlignTop)

        self.detail_card = CardFrame("Gjennomgang av bilag")
        self.detail_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lbl_progress = QLabel("Ingen bilag valgt.")
        self.lbl_progress.setObjectName("statusLabel")
        self.detail_card.add_widget(self.lbl_progress)

        meta_grid = QGridLayout()
        meta_grid.setContentsMargins(0, 0, 0, 0)
        meta_grid.setHorizontalSpacing(16)
        meta_grid.setVerticalSpacing(10)
        meta_grid.setColumnStretch(0, 0)
        meta_grid.setColumnStretch(1, 1)
        meta_labels = [
            ("Leverandør", "value_supplier"),
            ("Bilag", "value_document"),
            ("Dato", "value_date"),
            ("Beløp (kostnad)", "value_amount"),
            ("Beskrivelse", "value_description"),
            ("Status", "value_status"),
        ]
        for row, (label_text, attr_name) in enumerate(meta_labels):
            label = QLabel(label_text)
            label.setObjectName("infoLabel")
            label.setProperty("meta", True)
            meta_grid.addWidget(label, row, 0)
            value_label = QLabel("–")
            value_label.setObjectName("statusLabel")
            value_label.setWordWrap(True)
            meta_grid.addWidget(value_label, row, 1)
            setattr(self, attr_name, value_label)

        meta_section = QWidget()
        meta_section_layout = QVBoxLayout(meta_section)
        meta_section_layout.setContentsMargins(0, 0, 0, 0)
        meta_section_layout.setSpacing(8)
        meta_section_layout.addLayout(meta_grid)
        self.detail_card.add_widget(meta_section)

        divider = QFrame()
        divider.setObjectName("analysisDivider")
        divider.setFixedHeight(4)
        self.detail_card.add_widget(divider)

        self.value_status = cast(QLabel, getattr(self, "value_status"))
        self._update_status_display(None)

        self.table_lines = create_table_widget()
        self.table_lines.setColumnCount(6)
        self.table_lines.setHorizontalHeaderLabels(
            ["Konto", "Kontonavn", "MVA-kode", "Tekst", "Debet", "Kredit"]
        )
        self.table_lines.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.table_lines.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_lines.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.table_lines.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_lines.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents
        )
        self.table_lines.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeToContents
        )
        self.detail_card.add_widget(self.table_lines)

        comment_label = QLabel("Kommentar (frivillig):")
        comment_label.setObjectName("infoLabel")
        self.detail_card.add_widget(comment_label)

        self.txt_comment = QPlainTextEdit()
        self.txt_comment.setObjectName("commentInput")
        self.txt_comment.setPlaceholderText(
            "Noter funn eller videre oppfølging for bilaget."
        )
        palette = self.txt_comment.palette()
        palette.setColor(QPalette.Text, QColor("#0f172a"))
        palette.setColor(QPalette.PlaceholderText, QColor("#94a3b8"))
        palette.setColor(QPalette.Base, QColor("#ffffff"))
        self.txt_comment.setPalette(palette)
        self.txt_comment.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.txt_comment.setTabChangesFocus(True)
        self.txt_comment.setAttribute(Qt.WA_StyledBackground, True)
        self.txt_comment.setAutoFillBackground(True)
        self.txt_comment.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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

        selection_content_row.addWidget(self.detail_card, 1)

        stats_column_layout = QVBoxLayout()
        stats_column_layout.setContentsMargins(0, 0, 0, 0)
        stats_column_layout.setSpacing(12)
        stats_column_layout.setAlignment(Qt.AlignTop)

        selection_stats_layout = QHBoxLayout()
        selection_stats_layout.setContentsMargins(0, 0, 0, 0)
        selection_stats_layout.setSpacing(12)
        selection_stats_layout.addStretch(1)
        self.selection_badge_total_amount = StatBadge(
            "Sum inngående faktura",
            "Beløp fra innlastet fil",
        )
        self.selection_badge_reviewed_amount = StatBadge(
            "Sum kontrollert",
            "Kostnad på vurderte bilag",
        )
        self.selection_badge_coverage = StatBadge(
            "Dekning",
            "Andel av sum som er kontrollert",
        )
        selection_stats_layout.addWidget(self.selection_badge_total_amount)
        selection_stats_layout.addWidget(self.selection_badge_reviewed_amount)
        selection_stats_layout.addWidget(self.selection_badge_coverage)
        stats_column_layout.addLayout(selection_stats_layout)
        stats_column_layout.addStretch(1)
        selection_content_row.addLayout(stats_column_layout)

        selection_layout.addLayout(selection_content_row)
        return selection_container

    def _build_summary_tab(self) -> QWidget:
        summary_container = QWidget()
        summary_layout = QVBoxLayout(summary_container)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(24)

        self.summary_card = CardFrame("Oppsummering av kontrollerte bilag")
        self.summary_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        stats_layout = QHBoxLayout()
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(12)
        self.badge_total_amount = StatBadge(
            "Sum inngående faktura",
            "Beløp fra innlastet fil",
        )
        self.badge_reviewed_amount = StatBadge(
            "Sum kontrollert",
            "Kostnad på vurderte bilag",
        )
        self.badge_coverage = StatBadge(
            "Dekning",
            "Andel av sum som er kontrollert",
        )
        stats_layout.addWidget(self.badge_total_amount)
        stats_layout.addWidget(self.badge_reviewed_amount)
        stats_layout.addWidget(self.badge_coverage)
        stats_layout.addStretch(1)
        self.summary_card.add_layout(stats_layout)

        self.lbl_summary = QLabel("Ingen bilag kontrollert ennå.")
        self.lbl_summary.setObjectName("statusLabel")
        self.summary_card.add_widget(self.lbl_summary)

        self.summary_table = create_table_widget()
        self.summary_table.setColumnCount(6)
        self.summary_table.setHorizontalHeaderLabels(
            ["Bilag", "Dato", "Leverandør", "Beløp", "Status", "Kommentar"]
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.Stretch
        )
        self.summary_table.setVisible(False)
        self.summary_card.add_widget(self.summary_table)

        self.btn_export_pdf = QPushButton("Eksporter arbeidspapir (PDF)")
        self.btn_export_pdf.setObjectName("exportPdfButton")
        self.btn_export_pdf.clicked.connect(self._on_export_pdf)
        self.btn_export_pdf.setEnabled(False)
        self.summary_card.add_widget(self.btn_export_pdf)

        summary_layout.addWidget(self.summary_card, 1)
        return summary_container

    def set_vouchers(self, vouchers: Sequence["saft_customers.CostVoucher"]) -> None:
        self._vouchers = list(vouchers)
        self._total_available_amount = self._sum_voucher_amounts(self._vouchers)
        self._sample = []
        self._results = []
        self._current_index = -1
        self._sample_started_at = None
        self.detail_card.setEnabled(False)
        self._clear_current_display()
        self._refresh_summary_table(force_rebuild=True)
        self.tab_widget.setCurrentIndex(0)
        self.tab_widget.setTabEnabled(1, False)
        self.tab_widget.setTabEnabled(2, False)
        if self._is_specific:
            self._update_specific_available_label(len(self._vouchers))
            self.lbl_specific_result.setText("Ingen utvalg gjort ennå.")
        else:
            self._update_total_amount_label()
            count = len(self._vouchers)
            if count:
                formatted_count = self._format_count(count)
                self.lbl_available.setText(
                    "Tilgjengelige inngående fakturaer: "
                    f"{formatted_count} bilag klar for kontroll."
                )
                self.btn_start_sample.setEnabled(True)
            else:
                self.lbl_available.setText(
                    "Ingen kostnadsbilag tilgjengelig i valgt periode."
                )
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
            QMessageBox.information(
                self, "Ingen utvalg", "Velg et antall større enn null."
            )
            return

        self._start_review(random.sample(self._vouchers, sample_size))

    def _on_specific_threshold(self) -> None:
        if not self._ensure_specific_vouchers():
            return

        threshold = int(self.spin_threshold.value())
        if threshold <= 0:
            QMessageBox.information(
                self,
                "Ugyldig terskel",
                "Velg en terskel større enn null kroner.",
            )
            return

        selected = [
            voucher
            for voucher in self._vouchers
            if self._extract_amount(voucher.amount) >= threshold
        ]
        if not selected:
            QMessageBox.information(
                self,
                "Ingen treff",
                "Fant ingen bilag som er over terskelen.",
            )
            return

        self.lbl_specific_result.setText(
            "Valgt "
            f"{self._format_count(len(selected))} bilag over "
            f"{self._format_count(threshold)} kr."
        )
        self._start_review(selected)

    def _on_specific_top(self) -> None:
        if not self._ensure_specific_vouchers():
            return

        requested = int(self.spin_top.value())
        if requested <= 0:
            QMessageBox.information(
                self,
                "Ugyldig antall",
                "Velg et antall større enn null.",
            )
            return

        sorted_vouchers = sorted(
            self._vouchers,
            key=lambda voucher: self._extract_amount(voucher.amount),
            reverse=True,
        )
        selected = sorted_vouchers[: min(requested, len(sorted_vouchers))]
        if not selected:
            QMessageBox.information(
                self,
                "Ingen treff",
                "Fant ingen bilag å velge.",
            )
            return

        self.lbl_specific_result.setText(
            f"Valgt topp {self._format_count(len(selected))} bilag etter beløp."
        )
        self._start_review(selected)

    def _on_specific_round(self) -> None:
        if not self._ensure_specific_vouchers():
            return

        selected = [
            voucher for voucher in self._vouchers if self._is_round_amount(voucher)
        ]
        if not selected:
            QMessageBox.information(
                self,
                "Ingen treff",
                "Fant ingen bilag med runde beløp.",
            )
            return

        self.lbl_specific_result.setText(
            f"Valgt {self._format_count(len(selected))} bilag med runde beløp."
        )
        self._start_review(selected)

    def _on_specific_missing_desc(self) -> None:
        if not self._ensure_specific_vouchers():
            return

        selected = [
            voucher
            for voucher in self._vouchers
            if not (voucher.description or "").strip()
        ]
        if not selected:
            QMessageBox.information(
                self,
                "Ingen treff",
                "Fant ingen bilag uten beskrivelse.",
            )
            return

        self.lbl_specific_result.setText(
            f"Valgt {self._format_count(len(selected))} bilag uten beskrivelse."
        )
        self._start_review(selected)

    def _on_specific_no_ap(self) -> None:
        if not self._ensure_specific_vouchers():
            return

        selected = [
            voucher for voucher in self._vouchers if not self._has_ap_line(voucher)
        ]
        if not selected:
            QMessageBox.information(
                self,
                "Ingen treff",
                "Fant ingen bilag uten føring mot leverandørgjeld.",
            )
            return

        self.lbl_specific_result.setText(
            "Valgt "
            f"{self._format_count(len(selected))} bilag uten føring mot "
            "leverandørgjeld."
        )
        self._start_review(selected)

    def _ensure_specific_vouchers(self) -> bool:
        if not self._vouchers:
            QMessageBox.information(
                self,
                "Ingen bilag",
                "Det finnes ingen inngående fakturaer å velge ut.",
            )
            return False
        return True

    def _update_specific_available_label(self, count: int) -> None:
        if count:
            formatted_count = self._format_count(count)
            self.lbl_specific_available.setText(
                f"Tilgjengelige bilag: {formatted_count} kostnadsbilag klare for utvalg."
            )
            self.btn_specific_threshold.setEnabled(True)
            self.btn_specific_top.setEnabled(True)
            self.btn_specific_round.setEnabled(True)
            self.btn_specific_missing_desc.setEnabled(True)
            self.btn_specific_no_ap.setEnabled(True)
        else:
            self.lbl_specific_available.setText(
                "Ingen kostnadsbilag tilgjengelig i valgt periode."
            )
            self.btn_specific_threshold.setEnabled(False)
            self.btn_specific_top.setEnabled(False)
            self.btn_specific_round.setEnabled(False)
            self.btn_specific_missing_desc.setEnabled(False)
            self.btn_specific_no_ap.setEnabled(False)

    def _start_review(self, vouchers: Sequence["saft_customers.CostVoucher"]) -> None:
        if not vouchers:
            QMessageBox.information(
                self,
                "Ingen bilag",
                "Fant ingen bilag i utvalget.",
            )
            return

        self._sample = list(vouchers)
        self._results = [None] * len(self._sample)
        self._current_index = 0
        self._sample_started_at = datetime.now()
        self.detail_card.setEnabled(True)
        self.summary_table.setVisible(False)
        self.btn_export_pdf.setEnabled(False)
        self.lbl_summary.setText("Ingen bilag kontrollert ennå.")
        if not self._is_specific:
            self.btn_start_sample.setText("Start nytt utvalg")
        self.tab_widget.setTabEnabled(1, True)
        self.tab_widget.setTabEnabled(2, False)
        self.tab_widget.setCurrentIndex(1)
        self._update_status_display(None)
        self._refresh_summary_table(force_rebuild=True)
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
        document_text = (
            voucher.document_number or voucher.transaction_id or "Uten bilagsnummer"
        )
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
        self._refresh_summary_table(changed_row=self._current_index)
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
        self.lbl_progress.setText(
            "Kontroll fullført – du kan fortsatt bla mellom bilagene."
        )
        if current_result:
            self._update_status_display(current_result.status)
        else:
            self._update_status_display(None)
        self._refresh_summary_table(force_rebuild=True)
        self.lbl_summary.setText(
            "Resultat: "
            f"{self._format_count(approved)} godkjent / "
            f"{self._format_count(rejected)} ikke godkjent av "
            f"{self._format_count(len(self._sample))} bilag."
        )
        self.summary_table.setVisible(True)
        self.btn_export_pdf.setEnabled(True)
        self.tab_widget.setTabEnabled(2, True)
        self.tab_widget.setCurrentIndex(2)
        self._update_navigation_state()

    def _refresh_summary_table(
        self,
        changed_row: Optional[int] = None,
        *,
        force_rebuild: bool = False,
    ) -> None:
        if not self._sample:
            self.summary_table.setRowCount(0)
            self.summary_table.setVisible(False)
            self.btn_export_pdf.setEnabled(False)
            self.lbl_summary.setText("Ingen bilag kontrollert ennå.")
            self.tab_widget.setTabEnabled(2, False)
            self._update_coverage_badges()
            return

        table = self.summary_table
        table.setVisible(True)
        row_count = len(self._sample)
        needs_rebuild = force_rebuild or table.rowCount() != row_count
        if needs_rebuild:
            table.setRowCount(row_count)

        completed_count = sum(1 for result in self._results if result is not None)
        if completed_count == 0:
            self.lbl_summary.setText("Ingen bilag kontrollert ennå.")
        elif completed_count < row_count:
            self.lbl_summary.setText(
                f"{self._format_count(completed_count)} av "
                f"{self._format_count(row_count)} bilag vurdert."
            )
        else:
            self.lbl_summary.setText(
                f"Alle {self._format_count(row_count)} bilag er kontrollert."
            )
        self.tab_widget.setTabEnabled(2, True)

        if needs_rebuild or changed_row is None:
            rows_to_update: Iterable[int] = range(row_count)
        else:
            rows_to_update = [changed_row]

        for row in rows_to_update:
            voucher = self._sample[row]
            if needs_rebuild:
                bilag_text = (
                    voucher.document_number or voucher.transaction_id or "Bilag"
                )
                table.setItem(row, 0, QTableWidgetItem(bilag_text))
                table.setItem(
                    row,
                    1,
                    QTableWidgetItem(self._format_date(voucher.transaction_date)),
                )
                supplier_text = voucher.supplier_name or voucher.supplier_id or "–"
                if voucher.supplier_name and voucher.supplier_id:
                    supplier_text = f"{voucher.supplier_name} ({voucher.supplier_id})"
                table.setItem(row, 2, QTableWidgetItem(supplier_text))
                amount_item = QTableWidgetItem(self._format_amount(voucher.amount))
                amount_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                table.setItem(row, 3, amount_item)

            result = self._results[row] if row < len(self._results) else None
            status_text = result.status if result else "Ikke vurdert"
            comment_text = result.comment if result and result.comment else ""

            status_item = table.item(row, 4)
            if status_item is None:
                status_item = QTableWidgetItem()
                table.setItem(row, 4, status_item)
            status_item.setText(status_text)

            comment_item = table.item(row, 5)
            if comment_item is None:
                comment_item = QTableWidgetItem()
                table.setItem(row, 5, comment_item)
            comment_item.setText(comment_text)

        self.btn_export_pdf.setEnabled(
            completed_count == row_count and completed_count > 0
        )

        apply_compact_row_heights(table)
        self._expand_rows_for_multiline_comments(table)

        self._update_coverage_badges()

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
        self._refresh_summary_table(changed_row=self._current_index)

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
        self.value_status.setProperty("statusState", state)
        self.value_status.setText(text)
        self.value_status.style().unpolish(self.value_status)
        self.value_status.style().polish(self.value_status)

    def _expand_rows_for_multiline_comments(self, table: QTableWidget) -> None:
        header = table.verticalHeader()
        minimum_height = compact_row_base_height(table)
        row_count = table.rowCount()
        if row_count == 0:
            return
        comment_column = 5
        for row in range(row_count):
            item = table.item(row, comment_column)
            if item is None:
                continue
            text = item.text().strip()
            if "\n" not in text:
                continue
            header.setSectionResizeMode(row, QHeaderView.ResizeToContents)
            table.resizeRowToContents(row)
            header.setSectionResizeMode(row, QHeaderView.Fixed)
            if table.rowHeight(row) < minimum_height:
                table.setRowHeight(row, minimum_height)

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
        return bool(self._sample) and all(
            result is not None for result in self._results
        )

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

    @staticmethod
    def _format_count(value: int) -> str:
        return f"{value:,}".replace(",", " ")

    def _sum_voucher_amounts(
        self, vouchers: Iterable["saft_customers.CostVoucher"]
    ) -> float:
        total = 0.0
        for voucher in vouchers:
            total += self._extract_amount(voucher.amount)
        return total

    def _sum_reviewed_amount(self) -> float:
        total = 0.0
        for result in self._results:
            if result is None:
                continue
            total += self._extract_amount(result.voucher.amount)
        return total

    def _update_total_amount_label(self) -> None:
        formatted_total = format_currency(self._total_available_amount)
        self.lbl_total_amount.setText(f"Sum inngående faktura: {formatted_total}")

    @staticmethod
    def _extract_amount(value: Optional[float]) -> float:
        try:
            numeric = float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(numeric):
            return 0.0
        return numeric

    def _is_round_amount(self, voucher: "saft_customers.CostVoucher") -> bool:
        amount = round(abs(self._extract_amount(voucher.amount)), 2)
        if amount < 1000:
            return False
        return amount % 1000 == 0

    @staticmethod
    def _has_ap_line(voucher: "saft_customers.CostVoucher") -> bool:
        for line in voucher.lines:
            if line.account and line.account.startswith("24"):
                return True
        return False

    def _update_coverage_badges(self) -> None:
        total_available = self._total_available_amount
        reviewed = self._sum_reviewed_amount()
        total_text = format_currency(total_available)
        reviewed_text = format_currency(reviewed)
        for badge in (
            self.badge_total_amount,
            self.selection_badge_total_amount,
        ):
            badge.set_value(total_text)
        for badge in (
            self.badge_reviewed_amount,
            self.selection_badge_reviewed_amount,
        ):
            badge.set_value(reviewed_text)
        if total_available <= 0:
            coverage_text = "—"
        else:
            coverage = (reviewed / total_available) * 100
            coverage_text = f"{coverage:.1f} %"
        for badge in (
            self.badge_coverage,
            self.selection_badge_coverage,
        ):
            badge.set_value(coverage_text)
        if not self._is_specific:
            self._update_total_amount_label()

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
            from reportlab.platypus import (
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
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

        completed_results = [
            cast(VoucherReviewResult, result) for result in self._results
        ]
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
            "Utvalg: "
            f"{self._format_count(sample_size)} av "
            f"{self._format_count(total_available)} tilgjengelige bilag.",
            f"Tidspunkt for kontroll: {timestamp}.",
            "Resultat: "
            f"{self._format_count(approved)} godkjent / "
            f"{self._format_count(rejected)} ikke godkjent.",
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
            heading = (
                voucher.document_number or voucher.transaction_id or f"Bilag {index}"
            )
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
                        (
                            "INNERGRID",
                            (0, 0),
                            (-1, -1),
                            0.25,
                            colors.HexColor("#cbd5f5"),
                        ),
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
                        (
                            "INNERGRID",
                            (0, 0),
                            (-1, -1),
                            0.25,
                            colors.HexColor("#cbd5f5"),
                        ),
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


class CostVoucherReviewPage(QWidget):
    """Interaktiv side for bilagskontroll av kostnader."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.module_tabs = QTabWidget()
        self.module_tabs.setObjectName("costModules")
        layout.addWidget(self.module_tabs)

        self.random_module = _CostVoucherReviewModule(
            self,
            title,
            subtitle,
            is_specific=False,
        )
        self.module_tabs.addTab(self.random_module, "Tilfeldig utvalg")

        self.specific_module = _CostVoucherReviewModule(
            self,
            "Spesifikt utvalg",
            "",
            is_specific=True,
        )
        self.module_tabs.addTab(self.specific_module, "Spesifikt utvalg")

    def set_vouchers(self, vouchers: Sequence["saft_customers.CostVoucher"]) -> None:
        self.random_module.set_vouchers(vouchers)
        self.specific_module.set_vouchers(vouchers)


class FixedAssetsPage(QWidget):
    """Viser mulige tilganger, avganger og kostnader som kan aktiveres."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("fixedAssetTabs")
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        additions_page = self._build_accession_page()
        disposals_page = self._build_disposal_page()
        capitalizations_page = self._build_capitalization_page()

        self.tab_widget.addTab(additions_page, "Tilganger")
        self.tab_widget.addTab(disposals_page, "Avganger")
        self.tab_widget.addTab(capitalizations_page, "Burde aktiveres")

        layout.addWidget(self.tab_widget)

    def _build_accession_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        (
            self.addition_card,
            self.addition_table,
            self.addition_summary_table,
            self.addition_summary_label,
            self.addition_empty,
        ) = self._build_accession_card()
        self.addition_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._configure_full_width_table(self.addition_table)
        self._configure_full_width_table(self.addition_summary_table)

        page_layout.addWidget(self.addition_card, 1)
        return page

    def _build_disposal_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        (
            self.disposal_card,
            self.disposal_table,
            self.disposal_empty,
        ) = self._build_movement_card(
            "Mulige avganger",
            "Kontoer i 11xx-12xx som har saldo ved IB, men ikke ved UB.",
            "Ingen mulige avganger identifisert",
        )
        self.disposal_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._configure_full_width_table(self.disposal_table)

        page_layout.addWidget(self.disposal_card, 1)
        return page

    def _build_capitalization_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        self.capitalization_card = CardFrame(
            "Burde aktiveres",
            "Inngående faktura på 65xx over 30 000 som kan vurderes.",
        )
        self.capitalization_card.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.capitalization_table = create_table_widget()
        self.capitalization_table.setColumnCount(6)
        self.capitalization_table.setHorizontalHeaderLabels(
            [
                "Dato",
                "Leverandør",
                "Bilag",
                "Konto",
                "Beløp",
                "Beskrivelse",
            ]
        )
        self._configure_full_width_table(self.capitalization_table)
        self.capitalization_empty = EmptyStateWidget(
            "Ingen faktura over terskelen",
            "Importer en SAF-T-fil for å se kostnader som kan aktiveres.",
            icon="📄",
        )
        self.capitalization_table.hide()
        self.capitalization_card.add_widget(self.capitalization_empty)
        self.capitalization_card.add_widget(self.capitalization_table)

        page_layout.addWidget(self.capitalization_card, 1)
        return page

    def _configure_full_width_table(self, table: QTableWidget) -> None:
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def update_data(
        self,
        trial_balance: Optional["pd.DataFrame"],
        vouchers: Sequence[CostVoucher],
    ) -> None:
        additions = find_asset_accessions(vouchers)
        self._populate_accessions(additions)

        disposals = find_possible_disposals(trial_balance)
        self._populate_movements(self.disposal_table, self.disposal_empty, disposals)

        candidates = find_capitalization_candidates(vouchers)
        self._populate_capitalizations(candidates)

    def clear(self) -> None:
        self.update_data(None, [])

    def _build_accession_card(
        self,
    ) -> Tuple[
        CardFrame,
        QTableWidget,
        QTableWidget,
        QLabel,
        EmptyStateWidget,
    ]:
        card = CardFrame(
            "Tilganger",
            "Alle debetføringer mot 11xx-12xx-konti.",
        )
        if card.body_layout.count() > 0:
            last_item = card.body_layout.takeAt(card.body_layout.count() - 1)
            if last_item is not None and last_item.spacerItem():
                card._has_body_stretch = False  # type: ignore[attr-defined]

        content_container = QWidget()
        content_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        table = create_table_widget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(
            [
                "Konto",
                "Kontonavn",
                "Dato",
                "Bilag",
                "Leverandør",
                "Beskrivelse",
                "Beløp",
                "Kommentar",
            ]
        )
        empty = EmptyStateWidget(
            "Ingen tilganger funnet",
            "Importer en SAF-T-fil for å se nye investeringer i driftsmidler.",
            icon="🧾",
        )
        table.hide()
        content_layout.addWidget(empty, 1)
        content_layout.addWidget(table, 1)
        content_container.setLayout(content_layout)
        card.add_widget(content_container)
        card.body_layout.setStretchFactor(content_container, 1)

        summary_container = QWidget()
        summary_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        summary_layout = QVBoxLayout(summary_container)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(4)

        summary_label = QLabel("Summering per konto")
        summary_label.setObjectName("cardSubtitle")
        summary_table = create_table_widget()
        summary_table.setColumnCount(3)
        summary_table.setHorizontalHeaderLabels(["Konto", "Kontonavn", "Sum tilganger"])
        summary_label.hide()
        summary_table.hide()
        summary_layout.addWidget(summary_label)
        summary_layout.addWidget(summary_table)
        summary_container.setLayout(summary_layout)
        card.add_widget(summary_container)
        return card, table, summary_table, summary_label, empty

    def _build_movement_card(
        self, title: str, subtitle: str, empty_title: str
    ) -> Tuple[CardFrame, QTableWidget, EmptyStateWidget]:
        card = CardFrame(title, subtitle)
        table = create_table_widget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Konto", "Kontonavn", "IB", "UB", "Endring"])
        empty = EmptyStateWidget(
            empty_title,
            "Importer en SAF-T-fil for å analysere driftsmidler.",
            icon="📊",
        )
        table.hide()
        card.add_widget(empty)
        card.add_widget(table)
        return card, table, empty

    def _populate_movements(
        self,
        table: QTableWidget,
        empty_state: EmptyStateWidget,
        movements: Sequence[AssetMovement],
    ) -> None:
        rows = [
            (
                movement.account,
                movement.name,
                movement.opening_balance,
                movement.closing_balance,
                movement.change,
            )
            for movement in movements
        ]
        populate_table(
            table,
            ["Konto", "Kontonavn", "IB", "UB", "Endring"],
            rows,
            money_cols={2, 3, 4},
        )
        self._toggle_empty_state(table, empty_state, bool(rows))

    def _populate_accessions(self, accessions: Sequence[AssetAccession]) -> None:
        rows = [
            (
                accession.account,
                accession.account_name or "—",
                self._format_date(accession.date),
                accession.document,
                accession.supplier,
                accession.description or "—",
                accession.amount,
                accession.comment or "—",
            )
            for accession in accessions
        ]
        populate_table(
            self.addition_table,
            [
                "Konto",
                "Kontonavn",
                "Dato",
                "Bilag",
                "Leverandør",
                "Beskrivelse",
                "Beløp",
                "Kommentar",
            ],
            rows,
            money_cols={6},
        )

        summaries: Sequence[AssetAccessionSummary] = (
            summarize_asset_accessions_by_account(accessions)
        )
        summary_rows = [
            (
                summary.account,
                summary.account_name or "—",
                summary.total_amount,
            )
            for summary in summaries
        ]
        populate_table(
            self.addition_summary_table,
            ["Konto", "Kontonavn", "Sum tilganger"],
            summary_rows,
            money_cols={2},
        )

        has_rows = bool(rows)
        self._toggle_empty_state(self.addition_table, self.addition_empty, has_rows)
        self.addition_summary_label.setVisible(has_rows)
        self.addition_summary_table.setVisible(has_rows)

    def _populate_capitalizations(
        self, candidates: Sequence[CapitalizationCandidate]
    ) -> None:
        rows = [
            (
                self._format_date(candidate.date),
                candidate.supplier,
                candidate.document,
                candidate.account,
                candidate.amount,
                candidate.description or "—",
            )
            for candidate in candidates
        ]
        populate_table(
            self.capitalization_table,
            ["Dato", "Leverandør", "Bilag", "Konto", "Beløp", "Beskrivelse"],
            rows,
            money_cols={4},
        )
        self._toggle_empty_state(
            self.capitalization_table, self.capitalization_empty, bool(rows)
        )

    @staticmethod
    def _format_date(value: object) -> str:
        if isinstance(value, datetime):
            return value.strftime("%d.%m.%Y")
        if isinstance(value, date):
            return value.strftime("%d.%m.%Y")
        if value is None:
            return "—"
        return str(value)

    @staticmethod
    def _toggle_empty_state(
        table: QTableWidget, empty_state: EmptyStateWidget, has_rows: bool
    ) -> None:
        if has_rows:
            empty_state.hide()
            table.show()
        else:
            table.hide()
            empty_state.show()

    def _create_correlation_summary_table(self) -> QTableWidget:
        table = create_table_widget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Kategori", "Beløp", "Andel"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.setSortingEnabled(False)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        apply_compact_row_heights(table)
        return table


class SalesArPage(QWidget):
    """Revisjonsside for salg og kundefordringer med topp kunder og kreditnotaer."""

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

        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("salesTabs")
        layout.addWidget(self.tab_widget)

        sales_tab = self._build_sales_tab(title, subtitle)
        credit_note_tab = self._build_credit_note_tab()
        correlation_tab = self._build_correlation_tab()

        self.tab_widget.addTab(sales_tab, "Salg per kunde")
        self.tab_widget.addTab(credit_note_tab, "Kreditnotaer")
        self.tab_widget.addTab(correlation_tab, "Korrelasjonsanalyse")

        self.set_controls_enabled(False)
        self.update_sales_reconciliation(None, None)

    def _build_sales_tab(self, title: str, subtitle: str) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        self.top_card = CardFrame(title, subtitle)
        stats_layout = QHBoxLayout()
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(12)
        self.sales_badge = StatBadge(
            "Sum kundesalg",
            "Summerte inntekter per kunde (eks. mva)",
        )
        self.revenue_badge = StatBadge(
            "Sum salgskonti",
            "Driftsinntekter fra 3xxx-konti",
        )
        self.diff_badge = StatBadge(
            "Kontroll",
            "Avvik mellom kundesalg og salgskonti",
        )
        stats_layout.addWidget(self.sales_badge)
        stats_layout.addWidget(self.revenue_badge)
        stats_layout.addWidget(self.diff_badge)
        stats_layout.addStretch(1)
        self.top_card.add_layout(stats_layout)

        self.balance_hint = QLabel(
            "Kontroll av kundesalg er ikke tilgjengelig før et datasett er aktivt."
        )
        self.balance_hint.setObjectName("infoLabel")
        self.balance_hint.setWordWrap(True)
        self.top_card.add_widget(self.balance_hint)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(QLabel("Antall:"))
        self.top_spin = QSpinBox()
        self.top_spin.setRange(1, 9999)
        self.top_spin.setValue(10)
        controls.addWidget(self.top_spin)
        controls.addStretch(1)
        self.calc_button = QPushButton("Beregn topp kunder")
        self.calc_button.clicked.connect(self._handle_calc_clicked)
        controls.addWidget(self.calc_button)
        self.top_card.add_layout(controls)

        self.empty_state = EmptyStateWidget(
            "Ingen kundedata ennå",
            "Importer en SAF-T-fil og velg datasettet for å se hvilke kunder som skiller seg ut.",
            icon="👥",
        )
        self.empty_state.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )

        self.top_table = create_table_widget()
        self.top_table.setColumnCount(4)
        self.top_table.setHorizontalHeaderLabels(
            [
                "Kundenr",
                "Kundenavn",
                "Fakturaer",
                "Omsetning (eks. mva)",
            ]
        )
        self.top_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.top_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.top_table.hide()

        self.top_card.add_widget(self.empty_state)
        self.top_card.add_widget(self.top_table)
        self.top_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        page_layout.addWidget(self.top_card, 1)

        return page

    def _build_credit_note_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        credit_subtitle = (
            "Fang opp kreditnotaer ført mot salgskonti (3xxx) og se fordeling per "
            "måned."
        )
        self.credit_card = CardFrame("Kreditnotaer", credit_subtitle)
        self.credit_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(12)
        self.credit_card.add_layout(nav_layout)

        self._section_buttons: List[QPushButton] = []
        self.section_stack = QStackedLayout()

        section_titles = ["Liste", "Per måned"]
        for index, title in enumerate(section_titles):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setObjectName("analysisSectionButton")
            button.clicked.connect(
                lambda _checked, idx=index: self._set_active_section(idx)
            )
            nav_layout.addWidget(button)
            self._section_buttons.append(button)
        nav_layout.addStretch(1)

        nav_container = QWidget()
        nav_container.setLayout(self.section_stack)
        self.credit_card.add_widget(nav_container)

        list_section = QWidget()
        list_layout = QVBoxLayout(list_section)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        self.list_empty = EmptyStateWidget(
            "Ingen kreditnotaer", "Last inn og aktiver en SAF-T fil for å se data."
        )
        self.list_empty.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.list_table = create_table_widget()
        self.list_table.setColumnCount(5)
        self.list_table.setHorizontalHeaderLabels(
            ["Dato", "Bilagsnr", "Beskrivelse", "Kontoer", "Beløp"]
        )
        self.list_table.setSortingEnabled(True)
        self.list_table.hide()
        list_layout.addWidget(self.list_empty)
        list_layout.addWidget(self.list_table)
        self.section_stack.addWidget(list_section)

        summary_section = QWidget()
        summary_layout = QVBoxLayout(summary_section)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)
        self.summary_empty = EmptyStateWidget(
            "Ingen fordeling", "Ingen kreditnotaer å vise per måned."
        )
        self.summary_empty.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.summary_table = create_table_widget()
        self.summary_table.setColumnCount(3)
        self.summary_table.setHorizontalHeaderLabels(
            ["Måned", "Antall", "Sum kreditnotaer"]
        )
        self.summary_table.setSortingEnabled(True)
        self.summary_table.hide()
        summary_layout.addWidget(self.summary_empty)
        summary_layout.addWidget(self.summary_table)
        self.section_stack.addWidget(summary_section)

        page_layout.addWidget(self.credit_card)
        self._set_active_section(0)

        return page

    def _build_correlation_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        self.correlation_tabs = QTabWidget()
        self.correlation_tabs.setObjectName("correlationTabs")

        sales_tab = self._build_sales_correlation_tab()
        self.correlation_tabs.addTab(sales_tab, "Salgsinntekter")

        receivables_tab = self._build_receivable_correlation_tab()
        self.correlation_tabs.addTab(receivables_tab, "Kundefordringer")

        bank_tab = self._build_bank_correlation_tab()
        self.correlation_tabs.addTab(bank_tab, "Bankinnskudd")

        summary_tab = self._build_correlation_summary_tab()
        self.correlation_tabs.addTab(summary_tab, "Oppsummering")

        page_layout.addWidget(self.correlation_tabs)

        return page

    def _handle_calc_clicked(self) -> None:
        rows = self._on_calc_top("3xxx", _requested_top_count(self.top_spin))
        if rows:
            self.set_top_customers(rows)

    def set_checklist_items(self, items: Iterable[str]) -> None:
        # Sjekkpunkter støttes ikke lenger visuelt, men metoden beholdes for kompatibilitet.
        del items

    def set_top_customers(self, rows: Iterable[Tuple[str, str, int, float]]) -> None:
        populate_table(
            self.top_table,
            ["Kundenr", "Kundenavn", "Transaksjoner", "Omsetning (eks. mva)"],
            rows,
            money_cols={3},
        )
        self.empty_state.hide()
        self.top_table.show()

    def clear_top_customers(self) -> None:
        self.top_table.setRowCount(0)
        self.top_table.hide()
        self.empty_state.show()

    def set_credit_notes(
        self,
        rows: Iterable[Tuple[str, str, str, str, float]],
        monthly_summary: Iterable[Tuple[str, int, float]],
    ) -> None:
        row_buffer = list(rows)
        populate_table(
            self.list_table,
            ["Dato", "Bilagsnr", "Beskrivelse", "Kontoer", "Beløp"],
            row_buffer,
            money_cols={4},
        )
        self._toggle_empty_state(self.list_table, self.list_empty, bool(row_buffer))
        self.list_table.setSortingEnabled(True)

        summary_buffer = list(monthly_summary)
        populate_table(
            self.summary_table,
            ["Måned", "Antall", "Sum kreditnotaer"],
            summary_buffer,
            money_cols={2},
        )
        self._toggle_empty_state(
            self.summary_table, self.summary_empty, bool(summary_buffer)
        )
        self.summary_table.setSortingEnabled(True)

    def clear_credit_notes(self) -> None:
        self.list_table.setRowCount(0)
        self.summary_table.setRowCount(0)
        self.list_table.hide()
        self.summary_table.hide()
        self.list_empty.show()
        self.summary_empty.show()
        self._set_active_section(0)

    def set_sales_correlation(
        self,
        with_receivable: Optional[float],
        without_receivable: Optional[float],
        missing_rows: Iterable[Tuple[str, str, str, str, str, float]],
        receivable_sales_total: Optional[float],
    ) -> None:
        self._update_correlation_summary(
            with_receivable, receivable_sales_total, without_receivable
        )
        rows = list(missing_rows or [])
        populate_table(
            self.missing_sales_table,
            [
                "Dato",
                "Bilagsnr",
                "Beskrivelse",
                "Kontoer",
                "Motkontoer",
                "Beløp",
            ],
            rows,
            money_cols={5},
        )
        self._toggle_empty_state(
            self.missing_sales_table, self.missing_sales_empty, bool(rows)
        )
        self.missing_sales_table.setSortingEnabled(True)

    def clear_sales_correlation(self) -> None:
        self._update_correlation_summary(None, None, None)
        self.missing_sales_table.setRowCount(0)
        self._toggle_empty_state(
            self.missing_sales_table, self.missing_sales_empty, False
        )

    def set_receivable_overview(
        self,
        analysis: Optional["saft_customers.ReceivablePostingAnalysis"],
        unclassified_rows: Iterable[Tuple[str, str, str, str, str, float]],
    ) -> None:
        self._update_receivable_summary(analysis)
        rows = list(unclassified_rows or [])
        populate_table(
            self.receivable_missing_table,
            [
                "Dato",
                "Bilagsnr",
                "Beskrivelse",
                "Kontoer",
                "Motkontoer",
                "Beløp",
            ],
            rows,
            money_cols={5},
        )
        self._toggle_empty_state(
            self.receivable_missing_table, self.receivable_missing_empty, bool(rows)
        )
        self.receivable_missing_table.setSortingEnabled(True)

    def clear_receivable_overview(self) -> None:
        self._update_receivable_summary(None)
        self.receivable_missing_table.setRowCount(0)
        self._toggle_empty_state(
            self.receivable_missing_table, self.receivable_missing_empty, False
        )

    def set_bank_overview(
        self,
        analysis: Optional["saft_customers.BankPostingAnalysis"],
        mismatch_rows: Iterable[Tuple[str, str, str, float, float, float, str, str]],
    ) -> None:
        self._update_bank_summary(analysis)

        rows = list(mismatch_rows or [])
        populate_table(
            self.bank_mismatch_table,
            [
                "Dato",
                "Bilagsnr",
                "Beskrivelse",
                "Bank",
                "Kundefordringer",
                "Differanse",
                "Bankkontoer",
                "Kundefordringskontoer",
            ],
            rows,
            money_cols={3, 4, 5},
        )
        self._toggle_empty_state(
            self.bank_mismatch_table, self.bank_mismatch_empty, bool(rows)
        )
        self.bank_mismatch_table.setSortingEnabled(True)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.calc_button.setEnabled(enabled)
        self.top_spin.setEnabled(enabled)

    def update_sales_reconciliation(
        self,
        sales_total: Optional[float],
        revenue_total: Optional[float],
    ) -> None:
        """Vis en enkel kontroll mellom kundesalg og salgskonti."""

        self.sales_badge.set_value(format_currency(sales_total))
        self.revenue_badge.set_value(format_currency(revenue_total))
        diff_text = format_difference(sales_total, revenue_total)
        if diff_text == "0":
            diff_display = "0 (OK)"
        elif diff_text == "—":
            diff_display = "—"
        else:
            diff_display = f"{diff_text} (avvik)"
        self.diff_badge.set_value(diff_display)

        if sales_total is None or revenue_total is None:
            self.balance_hint.setText(
                "Kontroll av kundesalg er ikke tilgjengelig før både "
                "kundedata og saldobalanse er lest inn."
            )
            return

        diff = sales_total - revenue_total
        abs_diff = abs(diff)
        tolerance = 0.5
        if abs_diff <= tolerance:
            self.balance_hint.setText(
                "Kontroll: OK – sum kundesalg matcher salgskonti (3xxx)."
            )
        elif diff > 0:
            self.balance_hint.setText(
                "Kontroll: Kundesalg overstiger salgskonti med "
                f"{format_currency(abs_diff)}."
            )
        else:
            self.balance_hint.setText(
                "Kontroll: Kundesalg ligger "
                f"{format_currency(abs_diff)} under salgskonti."
            )

    def _update_correlation_summary(
        self,
        sales_with_receivable: Optional[float],
        receivable_with_sales: Optional[float],
        sales_without_receivable: Optional[float],
    ) -> None:
        difference: Optional[float] = None
        percent_diff: Optional[float] = None
        if sales_with_receivable is not None and receivable_with_sales is not None:
            difference = round(sales_with_receivable - receivable_with_sales, 2)
            if sales_with_receivable != 0:
                percent_diff = round((difference / sales_with_receivable) * 100, 1)

        rows: List[Tuple[str, str, str]] = [
            (
                "Posteringer på salg med motkonto kundefordringer",
                format_currency(sales_with_receivable),
                "—",
            ),
            (
                "Posteringer på kundefordringer med motkonto salg",
                format_currency(receivable_with_sales),
                "—",
            ),
            (
                "Uforklart avvik",
                format_currency(difference),
                self._format_percent(percent_diff),
            ),
        ]

        if sales_without_receivable is not None:
            rows.append(
                (
                    "Salg uten motpost kundefordringer",
                    format_currency(sales_without_receivable),
                    "—",
                )
            )

        self._populate_correlation_summary_table(self.correlation_summary_table, rows)
        self._populate_correlation_summary_table(
            getattr(self, "correlation_sales_table", None), rows
        )

    def _format_percent(self, value: Optional[float]) -> str:
        if value is None or math.isnan(value):
            return "—"
        return f"{value:.1f} %"

    def _populate_correlation_summary_table(
        self, table: Optional[QTableWidget], rows: List[Tuple[str, str, str]]
    ) -> None:
        if table is None:
            return

        table.setRowCount(len(rows))
        for row_index, (label, value, percent) in enumerate(rows):
            label_item = QTableWidgetItem(label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
            value_item = QTableWidgetItem(value)
            value_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
            percent_item = QTableWidgetItem(percent)
            percent_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            percent_item.setFlags(percent_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row_index, 0, label_item)
            table.setItem(row_index, 1, value_item)
            table.setItem(row_index, 2, percent_item)

    def _create_correlation_summary_table(self) -> QTableWidget:
        table = create_table_widget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Kategori", "Beløp", "Andel"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.setSortingEnabled(False)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        apply_compact_row_heights(table)
        return table

    def _update_receivable_summary(
        self, analysis: Optional["saft_customers.ReceivablePostingAnalysis"]
    ) -> None:
        def _format(value: Optional[float]) -> str:
            return format_currency(value)

        if analysis is None:
            sales_total: Optional[float] = None
            bank_total: Optional[float] = None
            other_total: Optional[float] = None
            opening = None
            closing = None
            control = None
        else:
            sales_total = analysis.sales_counter_total
            bank_total = analysis.bank_counter_total
            other_total = analysis.other_counter_total
            opening = analysis.opening_balance
            closing = analysis.closing_balance
            control = analysis.control_total

        rows = [
            ("Inngående balanse (1500)", _format(opening)),
            ("Kundefordringer postert mot salgsinntekter", _format(sales_total)),
            ("Kundefordringer postert mot bank", _format(bank_total)),
            (
                "Kundefordringer uten motpost bank eller salg",
                _format(other_total),
            ),
            ("Utgående balanse (1500)", _format(closing)),
            (
                "Kontroll: IB + bevegelser – UB",
                _format(control),
            ),
        ]

        self.receivable_summary_table.setRowCount(len(rows))
        for row_index, (label, value) in enumerate(rows):
            label_item = QTableWidgetItem(label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
            value_item = QTableWidgetItem(value)
            value_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
            self.receivable_summary_table.setItem(row_index, 0, label_item)
            self.receivable_summary_table.setItem(row_index, 1, value_item)

    def _update_bank_summary(
        self, analysis: Optional["saft_customers.BankPostingAnalysis"]
    ) -> None:
        def _format(value: Optional[float]) -> str:
            return format_currency(value)

        if analysis is None:
            self.bank_summary_table.setRowCount(0)
            self.bank_summary_table.hide()
            self.bank_summary_empty.show()
            return

        rows = [
            ("Inngående balanse (bank)", _format(analysis.opening_balance)),
            (
                "Bankposteringer mot kundefordringer",
                _format(analysis.with_receivable_total),
            ),
            (
                "Bankposteringer uten motpost kundefordringer",
                _format(analysis.without_receivable_total),
            ),
            ("Utgående balanse (bank)", _format(analysis.closing_balance)),
            (
                "Kontroll: IB + bevegelser – UB",
                _format(analysis.control_total),
            ),
        ]

        populate_table(
            self.bank_summary_table, ["Kategori", "Sum"], rows, money_cols={1}
        )
        self.bank_summary_empty.hide()
        self.bank_summary_table.show()

    def _set_active_section(self, index: int) -> None:
        self.section_stack.setCurrentIndex(index)
        for idx, button in enumerate(self._section_buttons):
            button.setChecked(idx == index)

    @staticmethod
    def _toggle_empty_state(
        table: QTableWidget, empty_state: EmptyStateWidget, has_rows: bool
    ) -> None:
        if has_rows:
            empty_state.hide()
            table.show()
        else:
            table.hide()
            empty_state.show()

    def _build_correlation_summary_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        subtitle = (
            "Knytter salgsbilag på 3xxx-kontoer mot kundefordringer (1500)."
            " Viser et sammendrag av sammenligningen mellom posteringene."
        )
        self.correlation_summary_card = CardFrame("Korrelasjonsanalyse", subtitle)
        self.correlation_summary_card.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )

        intro_label = QLabel(
            "Summene under er hentet direkte fra SAF-T-transaksjonene og viser "
            "hvorvidt salgsføringer har motpost i kundefordringer."
        )
        intro_label.setWordWrap(True)
        self.correlation_summary_card.add_widget(intro_label)

        self.correlation_summary_table = self._create_correlation_summary_table()
        self.correlation_summary_card.add_widget(self.correlation_summary_table)

        page_layout.addWidget(self.correlation_summary_card)
        self._update_correlation_summary(None, None, None)

        return page

    def _build_sales_correlation_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        subtitle = (
            "Knytter salgsbilag på 3xxx-kontoer mot kundefordringer (1500)."
            " Viser bilag uten motpost."
        )
        self.correlation_card = CardFrame("Korrelasjonsanalyse", subtitle)
        self.correlation_card.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )

        intro_label = QLabel(
            "Her ser du salgsbilag som ikke har motpost i kundefordringer. "
            "Summene i oversikten ligger i fanen Oppsummering."
        )
        intro_label.setWordWrap(True)
        self.correlation_card.add_widget(intro_label)

        summary_title = QLabel("Korrelasjon mellom salg og kundefordringer")
        summary_title.setObjectName("analysisSectionTitle")

        self.correlation_sales_table = self._create_correlation_summary_table()

        summary_layout = QVBoxLayout()
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)
        summary_layout.addWidget(summary_title, 0, Qt.AlignLeft | Qt.AlignTop)
        summary_layout.addWidget(self.correlation_sales_table)

        self.correlation_card.add_layout(summary_layout)

        missing_title = QLabel("Salg uten motpost kundefordringer")
        missing_title.setObjectName("analysisSectionTitle")

        self.missing_sales_empty = EmptyStateWidget(
            "Ingen avvik",
            "Alle salgsbilag har motpost på kundefordringer (1500).",
            icon="✅",
        )
        self.missing_sales_empty.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Minimum
        )
        empty_layout = cast(QVBoxLayout, self.missing_sales_empty.layout())
        empty_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        empty_layout.setContentsMargins(12, 4, 12, 12)
        empty_layout.setSpacing(8)

        self.missing_sales_table = create_table_widget()
        self.missing_sales_table.setColumnCount(6)
        self.missing_sales_table.setHorizontalHeaderLabels(
            [
                "Dato",
                "Bilagsnr",
                "Beskrivelse",
                "Kontoer",
                "Motkontoer",
                "Beløp",
            ]
        )
        self.missing_sales_table.setSortingEnabled(True)
        self.missing_sales_table.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.missing_sales_table.hide()

        missing_section = QVBoxLayout()
        missing_section.setContentsMargins(0, 0, 0, 0)
        missing_section.setSpacing(4)
        missing_section.addWidget(missing_title, 0, Qt.AlignLeft | Qt.AlignTop)
        missing_section.addWidget(
            self.missing_sales_empty, 0, Qt.AlignLeft | Qt.AlignTop
        )
        missing_section.addWidget(self.missing_sales_table)
        missing_section.setStretch(2, 1)

        self.correlation_card.add_layout(missing_section)

        page_layout.addWidget(self.correlation_card)
        self._toggle_empty_state(
            self.missing_sales_table, self.missing_sales_empty, False
        )

        return page

    def _build_receivable_correlation_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        subtitle = (
            "Viser bevegelser på kundefordringer (1500) fordelt på motposter og "
            "en kontroll av balansen."
        )
        self.receivable_card = CardFrame("Kundefordringer", subtitle)
        self.receivable_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        intro_label = QLabel(
            "Tabellen under summerer posteringer på kundefordringer etter motpost. "
            "Kontroll-linjen beregner IB + bevegelser – UB."
        )
        intro_label.setWordWrap(True)
        self.receivable_card.add_widget(intro_label)

        self.receivable_summary_table = create_table_widget()
        self.receivable_summary_table.setColumnCount(2)
        self.receivable_summary_table.setHorizontalHeaderLabels(["Kategori", "Sum"])
        self.receivable_summary_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.receivable_summary_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.receivable_summary_table.setSortingEnabled(False)
        self.receivable_summary_table.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Minimum
        )
        apply_compact_row_heights(self.receivable_summary_table)
        self.receivable_card.add_widget(self.receivable_summary_table)

        missing_title = QLabel("Kundefordringer uten motpost bank eller salg")
        missing_title.setObjectName("analysisSectionTitle")

        self.receivable_missing_empty = EmptyStateWidget(
            "Ingen avvik",
            "Alle kundefordringer har motpost i bank eller salgsinntekter.",
            icon="✅",
        )
        self.receivable_missing_empty.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Minimum
        )
        missing_empty_layout = cast(QVBoxLayout, self.receivable_missing_empty.layout())
        missing_empty_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        missing_empty_layout.setContentsMargins(12, 4, 12, 12)
        missing_empty_layout.setSpacing(8)

        self.receivable_missing_table = create_table_widget()
        self.receivable_missing_table.setColumnCount(6)
        self.receivable_missing_table.setHorizontalHeaderLabels(
            [
                "Dato",
                "Bilagsnr",
                "Beskrivelse",
                "Kontoer",
                "Motkontoer",
                "Beløp",
            ]
        )
        self.receivable_missing_table.setSortingEnabled(True)
        self.receivable_missing_table.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.receivable_missing_table.hide()

        missing_layout = QVBoxLayout()
        missing_layout.setContentsMargins(0, 0, 0, 0)
        missing_layout.setSpacing(4)
        missing_layout.addWidget(missing_title, 0, Qt.AlignLeft | Qt.AlignTop)
        missing_layout.addWidget(
            self.receivable_missing_empty, 0, Qt.AlignLeft | Qt.AlignTop
        )
        missing_layout.addWidget(self.receivable_missing_table)
        missing_layout.setStretch(2, 1)

        self.receivable_card.add_layout(missing_layout)

        page_layout.addWidget(self.receivable_card)
        self._update_receivable_summary(None)
        self._toggle_empty_state(
            self.receivable_missing_table, self.receivable_missing_empty, False
        )

        return page

    def _build_bank_correlation_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(24)

        subtitle = (
            "Viser bankkonti (19xx/2380) fordelt på om de er postert mot "
            "kundefordringer eller ikke."
        )
        self.bank_card = CardFrame("Bankinnskudd", subtitle)
        self.bank_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        intro_label = QLabel(
            "Tabellen summerer IB, bevegelser og UB på bankkontoene. "
            "Kontroll-linjen beregner IB + bevegelser – UB."
        )
        intro_label.setWordWrap(True)
        self.bank_card.add_widget(intro_label)

        self.bank_summary_empty = EmptyStateWidget(
            "Ingen data",
            "Fant ingen bankbevegelser for valgt periode.",
        )
        self.bank_summary_empty.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )

        self.bank_summary_table = create_table_widget()
        self.bank_summary_table.setColumnCount(2)
        self.bank_summary_table.setHorizontalHeaderLabels(["Kategori", "Sum"])
        self.bank_summary_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.bank_summary_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.bank_summary_table.setSortingEnabled(False)
        self.bank_summary_table.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Minimum
        )
        apply_compact_row_heights(self.bank_summary_table)
        self.bank_summary_table.hide()

        self.bank_card.add_widget(self.bank_summary_empty)
        self.bank_card.add_widget(self.bank_summary_table)

        mismatch_title = QLabel(
            "Bankposteringer mot kundefordringer som ikke balanserer"
        )
        mismatch_title.setObjectName("analysisSectionTitle")

        self.bank_mismatch_empty = EmptyStateWidget(
            "Ingen avvik",
            "Bankposteringene mot kundefordringer balanserer.",
            icon="✅",
        )
        self.bank_mismatch_empty.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Minimum
        )

        self.bank_mismatch_table = create_table_widget()
        self.bank_mismatch_table.setColumnCount(8)
        self.bank_mismatch_table.setHorizontalHeaderLabels(
            [
                "Dato",
                "Bilagsnr",
                "Beskrivelse",
                "Bank",
                "Kundefordringer",
                "Differanse",
                "Bankkontoer",
                "Kundefordringskontoer",
            ]
        )
        self.bank_mismatch_table.setSortingEnabled(True)
        self.bank_mismatch_table.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.bank_mismatch_table.hide()

        mismatch_layout = QVBoxLayout()
        mismatch_layout.setContentsMargins(0, 0, 0, 0)
        mismatch_layout.setSpacing(4)
        mismatch_layout.addWidget(mismatch_title, 0, Qt.AlignLeft | Qt.AlignTop)
        mismatch_layout.addWidget(
            self.bank_mismatch_empty, 0, Qt.AlignLeft | Qt.AlignTop
        )
        mismatch_layout.addWidget(self.bank_mismatch_table)
        mismatch_layout.setStretch(2, 1)

        self.bank_card.add_layout(mismatch_layout)

        page_layout.addWidget(self.bank_card)
        return page

    def _build_placeholder_tab(self, title: str, message: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        placeholder = EmptyStateWidget(title, message, icon="ℹ️")
        placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(placeholder, 0, Qt.AlignTop)
        layout.addStretch(1)

        return page


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
        self.top_spin.setRange(1, 9999)
        self.top_spin.setValue(10)
        controls.addWidget(self.top_spin)
        controls.addStretch(1)
        self.calc_button = QPushButton("Beregn innkjøp per leverandør")
        self.calc_button.clicked.connect(self._handle_calc_clicked)
        controls.addWidget(self.calc_button)
        self.top_card.add_layout(controls)

        self.empty_state = EmptyStateWidget(
            "Ingen leverandørdata ennå",
            "Importer en SAF-T-fil og velg datasettet for å se hvilke leverandører som dominerer.",
            icon="🏷️",
        )
        self.empty_state.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )

        self.top_table = create_table_widget()
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
        self.top_table.hide()

        self.top_card.add_widget(self.empty_state)
        self.top_card.add_widget(self.top_table)
        self.top_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.top_card, 1)

        self.set_controls_enabled(False)

    def _handle_calc_clicked(self) -> None:
        rows = self._on_calc_top("kostnadskonti", _requested_top_count(self.top_spin))
        if rows:
            self.set_top_suppliers(rows)

    def set_top_suppliers(self, rows: Iterable[Tuple[str, str, int, float]]) -> None:
        populate_table(
            self.top_table,
            ["Leverandørnr", "Leverandørnavn", "Transaksjoner", "Innkjøp (eks. mva)"],
            rows,
            money_cols={3},
        )
        self.empty_state.hide()
        self.top_table.show()

    def clear_top_suppliers(self) -> None:
        self.top_table.setRowCount(0)
        self.top_table.hide()
        self.empty_state.show()

    def set_controls_enabled(self, enabled: bool) -> None:
        self.calc_button.setEnabled(enabled)
        self.top_spin.setEnabled(enabled)
