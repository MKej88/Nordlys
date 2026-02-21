"""Side for enkel hovedbokvisning med kontosøk."""

from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...saft.ledger import (
    LedgerRow,
    build_ledger_rows,
    filter_ledger_rows,
    rows_for_voucher,
)
from ...saft.models import CostVoucher
from ..tables import create_table_widget, populate_table
from ..widgets import CardFrame, EmptyStateWidget

__all__ = ["HovedbokPage"]


class HovedbokPage(QWidget):
    """Viser alle føringer og lar brukeren filtrere på konto."""

    def __init__(self) -> None:
        super().__init__()

        self._all_rows: List[LedgerRow] = []
        self._visible_rows: List[LedgerRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(
            "Hovedbok",
            "Søk på konto for å se alle føringer. Dobbeltklikk på en linje "
            "for å åpne bilaget med motkontoer.",
        )

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.search_label = QLabel("Konto")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("F.eks. 3000 eller Salgsinntekt")
        self.search_input.returnPressed.connect(self.apply_filter)

        self.search_button = QPushButton("Søk")
        self.search_button.clicked.connect(self.apply_filter)

        self.reset_button = QPushButton("Nullstill")
        self.reset_button.clicked.connect(self._reset_filter)

        controls.addWidget(self.search_label)
        controls.addWidget(self.search_input, 1)
        controls.addWidget(self.search_button)
        controls.addWidget(self.reset_button)

        self.status_label = QLabel("Ingen føringer lastet inn.")
        self.status_label.setObjectName("mutedText")

        self.empty_state = EmptyStateWidget(
            "Ingen føringer å vise",
            "Importer SAF-T og søk på konto for å se posteringene.",
        )

        self.table = create_table_widget()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self._open_voucher_dialog)
        self.table.hide()

        controls_widget = QWidget()
        controls_widget.setLayout(controls)

        self.card.add_widget(controls_widget)
        self.card.add_widget(self.status_label)
        self.card.add_widget(self.empty_state)
        self.card.add_widget(self.table)

        layout.addWidget(self.card)
        layout.addStretch(1)

    def set_vouchers(self, vouchers: Sequence[CostVoucher]) -> None:
        """Oppdaterer sideinnholdet med nye bilag."""

        self._all_rows = build_ledger_rows(vouchers)
        self._render_rows(self._all_rows)

    def apply_filter(self) -> None:
        """Filtrerer tabellen basert på søketeksten."""

        query = self.search_input.text()
        filtered = filter_ledger_rows(self._all_rows, query)
        self._render_rows(filtered, query=query)

    def _reset_filter(self) -> None:
        self.search_input.clear()
        self._render_rows(self._all_rows)

    def _render_rows(self, rows: Sequence[LedgerRow], *, query: str = "") -> None:
        self._visible_rows = list(rows)

        if not self._all_rows:
            self.empty_state.show()
            self.table.hide()
            self.table.setRowCount(0)
            self.status_label.setText("Ingen føringer lastet inn.")
            return

        if not rows:
            self.empty_state.show()
            self.table.hide()
            if query.strip():
                self.status_label.setText(
                    f"Fant ingen føringer for søk: {query.strip()}"
                )
            else:
                self.status_label.setText("Ingen føringer å vise.")
            return

        table_rows = [
            (
                row.dato,
                row.bilagsnr,
                row.transaksjons_id,
                row.konto,
                row.kontonavn,
                row.tekst,
                row.debet,
                row.kredit,
            )
            for row in rows
        ]
        columns = [
            "Dato",
            "Bilag",
            "Transaksjon",
            "Konto",
            "Kontonavn",
            "Tekst",
            "Debet",
            "Kredit",
        ]

        populate_table(self.table, columns, table_rows, money_cols=(6, 7))
        self.table.show()
        self.empty_state.hide()

        if query.strip():
            self.status_label.setText(
                f"Viser {len(rows)} føringer for søk: {query.strip()}"
            )
        else:
            self.status_label.setText(
                f"Viser {len(rows)} føringer. Skriv konto for å filtrere."
            )

        self.table.sortItems(0, Qt.AscendingOrder)

    def _open_voucher_dialog(self, row_index: int, _column: int) -> None:
        if row_index < 0 or row_index >= len(self._visible_rows):
            return

        selected_row = self._visible_rows[row_index]
        voucher_rows = rows_for_voucher(self._all_rows, selected_row)
        if not voucher_rows:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Bilag {selected_row.bilagsnr}")
        dialog.resize(900, 500)

        layout = QVBoxLayout(dialog)
        info = QLabel(
            f"Dato: {selected_row.dato}   "
            f"Bilag: {selected_row.bilagsnr}   "
            f"Transaksjon: {selected_row.transaksjons_id}"
        )
        layout.addWidget(info)

        detail_table = create_table_widget()
        detail_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        detail_rows = [
            (
                row.konto,
                row.kontonavn,
                row.tekst,
                row.motkontoer,
                row.debet,
                row.kredit,
            )
            for row in voucher_rows
        ]
        populate_table(
            detail_table,
            ["Konto", "Kontonavn", "Tekst", "Motkontoer", "Debet", "Kredit"],
            detail_rows,
            money_cols=(4, 5),
        )
        layout.addWidget(detail_table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec()
