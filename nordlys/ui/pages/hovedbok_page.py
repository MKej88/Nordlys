"""Side for enkel hovedbokvisning med kontosøk."""

from __future__ import annotations

from typing import List, Sequence

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from ...saft.ledger import (
    LedgerRow,
    StatementRow,
    build_ledger_rows,
    build_statement_rows,
    filter_ledger_rows,
    rows_for_voucher,
)
from ...saft.models import CostVoucher
from ..tables import create_table_widget, populate_table
from ..widgets import EmptyStateWidget

__all__ = ["HovedbokPage"]


class HovedbokPage(QWidget):
    """Viser alle føringer og lar brukeren filtrere på konto."""

    def __init__(self) -> None:
        super().__init__()

        self._all_rows: List[LedgerRow] = []
        self._statement_rows: List[StatementRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title_label = QLabel("Hovedbok")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        subtitle_label = QLabel(
            "Kontoutskrift med IB/UB. Dobbeltklikk på bilagslinje for å se "
            "motkontoer i bilagsdetalj."
        )
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Søk konto, f.eks. 3002")
        self.search_input.returnPressed.connect(self.apply_filter)

        self.search_button = QPushButton("Søk")
        self.search_button.clicked.connect(self.apply_filter)

        self.reset_button = QPushButton("Nullstill")
        self.reset_button.clicked.connect(self._reset_filter)

        controls.addWidget(QLabel("Konto"))
        controls.addWidget(self.search_input, 1)
        controls.addWidget(self.search_button)
        controls.addWidget(self.reset_button)
        layout.addLayout(controls)

        self.status_label = QLabel("Ingen føringer lastet inn.")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)

        self.empty_state = EmptyStateWidget(
            "Ingen føringer å vise",
            "Importer SAF-T og søk på konto for å se kontoutskrift.",
        )
        layout.addWidget(self.empty_state)

        self.table = create_table_widget()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setSortingEnabled(False)
        self.table.cellDoubleClicked.connect(self._open_voucher_dialog)
        self.table.hide()
        layout.addWidget(self.table, 1)

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
        if not self._all_rows:
            self._statement_rows = []
            self.empty_state.show()
            self.table.hide()
            self.table.setRowCount(0)
            self.status_label.setText("Ingen føringer lastet inn.")
            return

        if not rows:
            self._statement_rows = []
            self.empty_state.show()
            self.table.hide()
            self.status_label.setText(f"Fant ingen føringer for søk: {query.strip()}")
            return

        self._statement_rows = build_statement_rows(rows)
        table_rows = [
            (
                row.dato,
                row.bilag,
                row.tekst,
                row.beskrivelse,
                "",
                "",
                "",
                row.mva,
                row.mva_belop,
                row.belop,
            )
            for row in self._statement_rows
        ]
        columns = [
            "Dato",
            "Bilag",
            "Tekst",
            "Beskrivelse",
            "Prosjektkode",
            "Prosjekt",
            "Avdelingskode",
            "Mva",
            "Mva-beløp",
            "Beløp",
        ]

        populate_table(self.table, columns, table_rows, money_cols=(8, 9))
        self.table.show()
        self.empty_state.hide()

        if query.strip():
            self.status_label.setText(
                f"Viser {len(rows)} føringer med IB/UB for søk: {query.strip()}"
            )
        else:
            self.status_label.setText(
                f"Viser {len(rows)} føringer med IB/UB. Søk på konto for filtrering."
            )

    def _open_voucher_dialog(self, row_index: int, _column: int) -> None:
        if row_index < 0 or row_index >= len(self._statement_rows):
            return

        statement_row = self._statement_rows[row_index]
        if statement_row.source is None:
            return

        selected_row = statement_row.source
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
