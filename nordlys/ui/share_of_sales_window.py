"""Lite vindu som viser label og tabell uten ekstra luft."""

from __future__ import annotations

from typing import Sequence

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .tables import create_table_widget

__all__ = ["ShareOfSalesWindow", "create_share_of_sales_window"]


class ShareOfSalesWindow(QWidget):
    """Vindu med label og tabell tett sammen i én layout."""

    def __init__(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
    ) -> None:
        super().__init__()
        self.setWindowTitle("% andel av salgsinntekter")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.title_label = QLabel("% andel av salgsinntekter")
        self.title_label.setObjectName("pageTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.table = create_table_widget()
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(list(headers))
        layout.addWidget(self.table)

        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.table.setItem(row_index, column_index, QTableWidgetItem(value))


def create_share_of_sales_window() -> ShareOfSalesWindow:
    """Lag et vindu med enkel demodata for rask testing."""

    headers = ["År", "Andel"]
    rows = [["2022", "47 %"], ["2021", "40 %"], ["Gjennomsnitt", "43,5 %"]]
    return ShareOfSalesWindow(headers, rows)


if __name__ == "__main__":
    app = QApplication([])
    window = create_share_of_sales_window()
    window.resize(360, 200)
    window.show()
    app.exec()
