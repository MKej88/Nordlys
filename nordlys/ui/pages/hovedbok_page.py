"""Side for enkel hovedbokvisning med kontosøk."""

from __future__ import annotations

from typing import Dict, List, Sequence, TYPE_CHECKING, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...helpers.lazy_imports import lazy_pandas
from ...saft.ledger import (
    LedgerRow,
    StatementRow,
    build_ledger_rows,
    build_statement_rows,
    rows_for_voucher,
)
from ...saft.models import CostVoucher
from ..tables import create_table_widget, populate_table

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd
else:  # pragma: no cover
    pd = lazy_pandas()

__all__ = ["HovedbokPage"]


class HovedbokPage(QWidget):
    """Viser alle føringer og lar brukeren filtrere på konto og bilag."""

    def __init__(self) -> None:
        super().__init__()

        self._all_rows: List[LedgerRow] = []
        self._statement_rows: List[StatementRow] = []
        self._table_source_rows: List[LedgerRow | None] = []
        self._account_balances: Dict[str, Tuple[float, float]] = {}
        self._account_names: Dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title_label = QLabel("Hovedbok")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        controls.addWidget(QLabel("Konto"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("F.eks. 1920")
        self.search_input.returnPressed.connect(self.apply_filter)
        controls.addWidget(self.search_input, 2)

        controls.addWidget(QLabel("Bilag"))
        self.voucher_search_input = QLineEdit()
        self.voucher_search_input.setPlaceholderText(
            "Søk bilagsnr eller transaksjonsnr"
        )
        self.voucher_search_input.returnPressed.connect(self.apply_filter)
        controls.addWidget(self.voucher_search_input, 2)

        self.search_button = QPushButton("Søk")
        self.search_button.clicked.connect(self.apply_filter)

        self.reset_button = QPushButton("Nullstill")
        self.reset_button.clicked.connect(self._reset_filter)

        controls.addWidget(self.search_button)
        controls.addWidget(self.reset_button)
        layout.addLayout(controls)

        self.result_panel = QFrame()
        self.result_panel.setObjectName("card")
        self.result_panel.setFrameShape(QFrame.StyledPanel)
        self.result_panel.setAttribute(Qt.WA_StyledBackground, True)
        self.result_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        panel_layout = QVBoxLayout(self.result_panel)
        panel_layout.setContentsMargins(18, 14, 18, 14)
        panel_layout.setSpacing(10)

        self.account_name_label = QLabel("")
        self.account_name_label.setObjectName("mutedText")
        panel_layout.addWidget(self.account_name_label)

        self.result_stack = QStackedWidget()
        self.result_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(self.result_stack, 1)

        empty_widget = QWidget()
        empty_layout = QVBoxLayout(empty_widget)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.addStretch(1)

        self.status_label = QLabel("Søk på konto eller bilag for å vise føringer.")
        self.status_label.setObjectName("mutedText")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.status_label)
        empty_layout.addStretch(1)

        self.result_stack.addWidget(empty_widget)

        self.table = create_table_widget()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setSortingEnabled(False)
        self.table.cellDoubleClicked.connect(self._open_voucher_dialog)
        self.result_stack.addWidget(self.table)
        self.result_stack.setCurrentWidget(empty_widget)
        layout.addWidget(self.result_panel, 1)

    def set_account_balances(self, df: "pd.DataFrame | None") -> None:
        """Lagrer IB/UB og navn per konto fra saldobalansen."""

        self._account_balances = {}
        self._account_names = {}
        if df is None or df.empty or "Konto" not in df.columns:
            return

        ib_series = self._net_series(df, "IB")
        ub_series = self._net_series(df, "UB")

        for idx in df.index:
            raw = df.at[idx, "Konto"]
            if raw is None or pd.isna(raw):
                continue
            account = str(raw).strip()
            if not account:
                continue

            ib = float(ib_series.get(idx, 0.0))
            ub = float(ub_series.get(idx, 0.0))
            self._account_balances[account] = (ib, ub)

            account_name = ""
            if "Kontonavn" in df.columns:
                raw_name = df.at[idx, "Kontonavn"]
                if raw_name is not None and not pd.isna(raw_name):
                    account_name = str(raw_name).strip()
            self._account_names[account] = account_name

    def set_vouchers(self, vouchers: Sequence[CostVoucher]) -> None:
        """Lagrer bilag, men viser ikke føringer før brukeren søker."""

        self._all_rows = build_ledger_rows(vouchers)
        self._clear_results()

    def apply_filter(self) -> None:
        """Filtrerer tabellen basert på konto og/eller bilag."""

        account_query = self.search_input.text().strip()
        voucher_query = self.voucher_search_input.text().strip().lower()

        if not account_query and not voucher_query:
            self._clear_results()
            self.status_label.setText("Søk på konto eller bilag for å vise føringer.")
            return

        rows = self._all_rows
        if account_query:
            if account_query not in self._account_balances:
                self._clear_results()
                self.account_name_label.setText("")
                self.status_label.setText(f"Konto ikke finnes: {account_query}")
                return

            rows = [row for row in rows if row.konto == account_query]
            account_name = self._account_names.get(account_query, "")
            if account_name:
                self.account_name_label.setText(
                    f"Konto: {account_query} – {account_name}"
                )
            else:
                self.account_name_label.setText(f"Konto: {account_query}")
        else:
            self.account_name_label.setText("")

        if voucher_query:
            rows = [
                row
                for row in rows
                if voucher_query in row.bilagsnr.lower()
                or voucher_query in row.transaksjons_id.lower()
            ]

        self._render_rows(
            rows, account_query=account_query, voucher_query=voucher_query
        )

    def _reset_filter(self) -> None:
        self.search_input.clear()
        self.voucher_search_input.clear()
        self.account_name_label.setText("")
        self._clear_results()
        self.status_label.setText("Søk på konto eller bilag for å vise føringer.")

    def _clear_results(self) -> None:
        self._statement_rows = []
        self._table_source_rows = []
        self.table.setRowCount(0)
        self.result_stack.setCurrentIndex(0)

    def _render_rows(
        self,
        rows: Sequence[LedgerRow],
        *,
        account_query: str,
        voucher_query: str,
    ) -> None:
        if not self._all_rows:
            self._clear_results()
            self.status_label.setText("Ingen føringer lastet inn.")
            return

        if not rows:
            self._clear_results()
            if account_query and voucher_query:
                self.status_label.setText(
                    f"Fant ingen føringer for konto {account_query} og bilag {voucher_query}."
                )
            elif voucher_query:
                self.status_label.setText(
                    f"Fant ingen føringer for bilag: {voucher_query}"
                )
            else:
                self.status_label.setText(
                    f"Fant ingen føringer for konto: {account_query}"
                )
            return

        if voucher_query:
            self._render_voucher_rows(rows)
        else:
            self._render_statement_rows(rows)

        self.result_stack.setCurrentWidget(self.table)
        self.status_label.setText(f"Viser {len(rows)} føringer.")

    def _render_statement_rows(self, rows: Sequence[LedgerRow]) -> None:
        self._statement_rows = build_statement_rows(
            rows, account_balances=self._account_balances
        )
        table_rows = [
            (
                row.dato,
                row.bilag,
                row.bilagstype,
                row.tekst,
                row.mva,
                row.mva_belop,
                row.belop,
                row.akkumulert_belop,
            )
            for row in self._statement_rows
        ]
        columns = [
            "Dato",
            "Bilag",
            "Bilagstype",
            "Tekst",
            "Mva",
            "Mva-beløp",
            "Beløp",
            "Akkumulert beløp",
        ]
        self._table_source_rows = [row.source for row in self._statement_rows]

        populate_table(self.table, columns, table_rows, money_cols=(5, 6, 7))
        self._mark_balance_rows_bold()

    def _render_voucher_rows(self, rows: Sequence[LedgerRow]) -> None:
        self._statement_rows = []
        self._table_source_rows = list(rows)
        table_rows = [
            (
                row.konto,
                row.kontonavn,
                row.bilagstype,
                row.beskrivelse,
                row.mva,
                row.mva_belop,
                row.debet,
                row.kredit,
            )
            for row in rows
        ]
        columns = [
            "Konto",
            "Kontonavn",
            "Bilagstype",
            "Beskrivelse",
            "Mva",
            "Mva-beløp",
            "Debet",
            "Kredit",
        ]
        populate_table(self.table, columns, table_rows, money_cols=(5, 6, 7))

    def _mark_balance_rows_bold(self) -> None:
        for row_idx, row in enumerate(self._statement_rows):
            if row.source is not None:
                continue
            for col_idx in range(self.table.columnCount()):
                item = self.table.item(row_idx, col_idx)
                if item is None:
                    continue
                font = item.font()
                font.setBold(True)
                item.setFont(font)

    def _open_voucher_dialog(self, row_index: int, _column: int) -> None:
        if row_index < 0 or row_index >= len(self._table_source_rows):
            return

        selected_row = self._table_source_rows[row_index]
        if selected_row is None:
            return
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
                row.bilagstype,
                row.beskrivelse,
                row.mva,
                row.mva_belop,
                row.debet,
                row.kredit,
            )
            for row in voucher_rows
        ]
        populate_table(
            detail_table,
            [
                "Konto",
                "Kontonavn",
                "Bilagstype",
                "Beskrivelse",
                "Mva",
                "Mva-beløp",
                "Debet",
                "Kredit",
            ],
            detail_rows,
            money_cols=(5, 6, 7),
        )
        layout.addWidget(detail_table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec()

    def _net_series(self, df: "pd.DataFrame", prefix: str) -> "pd.Series":
        net_col = f"{prefix}_netto"
        if net_col in df.columns:
            return pd.to_numeric(df[net_col], errors="coerce").fillna(0.0)

        debit_col = f"{prefix} Debet"
        credit_col = f"{prefix} Kredit"
        debit_series = pd.to_numeric(df.get(debit_col, 0.0), errors="coerce").fillna(
            0.0
        )
        credit_series = pd.to_numeric(df.get(credit_col, 0.0), errors="coerce").fillna(
            0.0
        )
        return debit_series - credit_series
