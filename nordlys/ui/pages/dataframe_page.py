from __future__ import annotations

from typing import Callable, Optional, Sequence, TYPE_CHECKING

from PySide6.QtWidgets import (
    QLabel,
    QHeaderView,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...helpers.lazy_imports import lazy_pandas
from ..tables import create_table_widget, populate_table
from ..widgets import CardFrame, EmptyStateWidget

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd
else:  # pragma: no cover - fallback for runtime
    pd = lazy_pandas()

__all__ = ["DataFramePage", "standard_tb_frame"]


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
        self.empty_state = EmptyStateWidget(
            "Ingen data å vise ennå",
            "Importer en SAF-T-fil eller velg et annet datasett for å fylle tabellen.",
        )
        self.table = create_table_widget()
        self.table.horizontalHeader().setSectionResizeMode(header_mode)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.hide()
        self.empty_state.show()

        if full_window:
            title_label = QLabel(title)
            title_label.setObjectName("pageTitle")
            layout.addWidget(title_label)

            if subtitle:
                subtitle_label = QLabel(subtitle)
                subtitle_label.setObjectName("pageSubtitle")
                subtitle_label.setWordWrap(True)
                layout.addWidget(subtitle_label)

            layout.addWidget(self.empty_state)
            layout.addWidget(self.table, 1)
        else:
            self.card = CardFrame(title, subtitle)
            self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.card.add_widget(self.empty_state)
            self.card.add_widget(self.table)
            layout.addWidget(self.card)
            layout.addStretch(1)

        self._frame_builder = frame_builder
        self._money_columns = tuple(money_columns or [])
        self._auto_resize_columns = header_mode == QHeaderView.ResizeToContents

    def set_dataframe(self, df: Optional[pd.DataFrame]) -> None:
        if df is None or df.empty:
            self.table.hide()
            self.empty_state.show()
            self.table.setRowCount(0)
            return

        work = df
        if self._frame_builder is not None:
            work = self._frame_builder(df)

        columns = list(work.columns)
        rows = [
            tuple(work.iloc[i][column] for column in columns) for i in range(len(work))
        ]
        money_idx = {
            columns.index(col) for col in self._money_columns if col in columns
        }
        populate_table(self.table, columns, rows, money_cols=money_idx)
        if self._auto_resize_columns:
            self.table.resizeColumnsToContents()
        self.table.show()
        self.empty_state.hide()


def standard_tb_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Bygger en norsk standard saldobalanse med nettoverdier."""

    work = df.copy()
    if "Konto_int" in work.columns:
        work = work.sort_values("Konto_int", na_position="last")
    elif "Konto" in work.columns:
        work = work.sort_values("Konto", na_position="last")

    if "IB_netto" not in work.columns:
        work["IB_netto"] = work.get("IB Debet", 0.0).fillna(0) - work.get(
            "IB Kredit", 0.0
        ).fillna(0)
    if "UB_netto" not in work.columns:
        work["UB_netto"] = work.get("UB Debet", 0.0).fillna(0) - work.get(
            "UB Kredit", 0.0
        ).fillna(0)

    work["Endringer"] = work["UB_netto"] - work["IB_netto"]

    columns = ["Konto", "Kontonavn", "IB", "Endringer", "UB"]
    konto = (
        work["Konto"].fillna("")
        if "Konto" in work.columns
        else pd.Series([""] * len(work))
    )
    navn = (
        work["Kontonavn"].fillna("")
        if "Kontonavn" in work.columns
        else pd.Series([""] * len(work))
    )

    result = pd.DataFrame(
        {
            "Konto": konto.astype(str),
            "Kontonavn": navn.astype(str),
            "IB": work["IB_netto"].fillna(0.0),
            "Endringer": work["Endringer"].fillna(0.0),
            "UB": work["UB_netto"].fillna(0.0),
        }
    )
    filtered = result[columns]

    numeric_view = filtered[["IB", "Endringer", "UB"]].apply(
        pd.to_numeric, errors="coerce"
    )
    has_numbers = numeric_view.notna().any(axis=1)
    filtered = filtered[has_numbers]

    if filtered.empty:
        return filtered.reset_index(drop=True)

    numeric_view = numeric_view.loc[filtered.index].fillna(0.0).abs()
    zero_mask = numeric_view.le(1e-9).all(axis=1)
    filtered = filtered[~zero_mask]
    return filtered.reset_index(drop=True)
