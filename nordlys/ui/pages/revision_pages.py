from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable, List, Optional, Sequence, Tuple, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QTextOption
from PySide6.QtWidgets import (
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
from ..tables import (
    apply_compact_row_heights,
    compact_row_base_height,
    create_table_widget,
    populate_table,
)
from ..widgets import CardFrame, EmptyStateWidget, StatBadge

__all__ = [
    "ChecklistPage",
    "VoucherReviewResult",
    "CostVoucherReviewPage",
    "SalesArPage",
    "PurchasesApPage",
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


class CostVoucherReviewPage(QWidget):
    """Interaktiv side for bilagskontroll av kostnader."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
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
        self.spin_sample.setValue(10)
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

        self.tab_widget.addTab(input_container, "Inndata")
        self.tab_widget.setTabToolTip(
            0, "Velg hvor mange bilag du vil trekke og start kontrollen."
        )

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

        self.tab_widget.addTab(selection_container, "Utvalg")
        self.tab_widget.setTabToolTip(
            1, "Jobb deg gjennom bilagene og registrer vurderinger."
        )

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

        self.tab_widget.addTab(summary_container, "Oppsummering")
        self.tab_widget.setTabToolTip(
            2, "Se status og eksporter arbeidspapir når du er ferdig."
        )

        self.tab_widget.setTabEnabled(1, False)
        self.tab_widget.setTabEnabled(2, False)
        self.tab_widget.setCurrentIndex(0)

        self.detail_card.setEnabled(False)
        self._update_coverage_badges()

    def set_vouchers(self, vouchers: Sequence["saft_customers.CostVoucher"]) -> None:
        self._vouchers = list(vouchers)
        self._total_available_amount = self._sum_voucher_amounts(self._vouchers)
        self._sample = []
        self._results = []
        self._current_index = -1
        self._sample_started_at = None
        self.detail_card.setEnabled(False)
        self.btn_start_sample.setText("Start bilagskontroll")
        self._clear_current_display()
        self._refresh_summary_table(force_rebuild=True)
        self._update_total_amount_label()
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
            f"Resultat: {approved} godkjent / {rejected} ikke godkjent av {len(self._sample)} bilag."
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
            self.lbl_summary.setText(f"{completed_count} av {row_count} bilag vurdert.")
        else:
            self.lbl_summary.setText(f"Alle {row_count} bilag er kontrollert.")
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
        self.value_status.setText(text)
        self.value_status.setProperty("statusState", state)
        self.value_status.style().unpolish(self.value_status)
        self.value_status.style().polish(self.value_status)

    def _expand_rows_for_multiline_comments(self, table: QTableWidget) -> None:
        header = table.verticalHeader()
        if header is None:
            return
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

        self.top_card = CardFrame(
            "Topp kunder", "Identifiser kunder med høyest omsetning."
        )
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
        layout.addWidget(self.top_card, 1)

        self.set_controls_enabled(False)
        self.update_sales_reconciliation(None, None)

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
