"""Headerkomponent for Nordlys-vinduet."""

from __future__ import annotations

from typing import Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from .config import PRIMARY_UI_FONT_FAMILY

DatasetEntry = Tuple[str, str]

__all__ = ["HeaderBar", "DatasetEntry"]


class HeaderBar(QWidget):
    """Øverste kontrollrad for side-tittel, datasettswitcher og handlinger."""

    open_requested = Signal()
    export_requested = Signal()
    export_pdf_requested = Signal()
    dataset_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("headerBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(18, 12, 18, 12)

        self.title_label = QLabel("Import")
        self.title_label.setObjectName("pageTitle")
        title_font = self.title_label.font()
        title_font.setFamily(PRIMARY_UI_FONT_FAMILY)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label, 1)

        self.dataset_combo = QComboBox()
        self.dataset_combo.setObjectName("datasetCombo")
        self.dataset_combo.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.dataset_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.dataset_combo.setPlaceholderText("Velg datasett")
        self.dataset_combo.setToolTip(
            "Når du har importert flere SAF-T-filer kan du raskt bytte aktive data her."
        )
        self.dataset_combo.setVisible(False)
        self.dataset_combo.currentIndexChanged.connect(self._emit_dataset_change)
        layout.addWidget(self.dataset_combo)

        self.btn_open = QPushButton("Åpne SAF-T XML …")
        self.btn_open.clicked.connect(self.open_requested)
        layout.addWidget(self.btn_open)

        self.btn_export = QPushButton("Eksporter rapport (Excel)")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_requested)
        layout.addWidget(self.btn_export)

        self.btn_export_pdf = QPushButton("Eksporter rapport (PDF)")
        self.btn_export_pdf.setEnabled(False)
        self.btn_export_pdf.clicked.connect(self.export_pdf_requested)
        layout.addWidget(self.btn_export_pdf)

    # region API
    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_open_enabled(self, enabled: bool) -> None:
        self.btn_open.setEnabled(enabled)

    def set_export_enabled(self, enabled: bool) -> None:
        self.btn_export.setEnabled(enabled)
        self.btn_export_pdf.setEnabled(enabled)

    def set_dataset_enabled(self, enabled: bool) -> None:
        self.dataset_combo.setEnabled(enabled)

    def set_dataset_items(
        self, entries: Sequence[DatasetEntry], current_key: str | None
    ) -> None:
        combo = self.dataset_combo
        combo.blockSignals(True)
        combo.clear()
        for key, label in entries:
            combo.addItem(label, userData=key)
        combo.setVisible(bool(entries))
        if current_key is not None:
            self.select_dataset(current_key)
        combo.blockSignals(False)

    def select_dataset(self, key: str) -> None:
        combo = self.dataset_combo
        previous_state = combo.blockSignals(True)
        for idx in range(combo.count()):
            if combo.itemData(idx) == key:
                combo.setCurrentIndex(idx)
                break
        combo.blockSignals(previous_state)

    def current_dataset_key(self) -> str | None:
        idx = self.dataset_combo.currentIndex()
        if idx < 0:
            return None
        key = self.dataset_combo.itemData(idx)
        return key if isinstance(key, str) else None

    def clear_datasets(self) -> None:
        combo = self.dataset_combo
        combo.blockSignals(True)
        combo.clear()
        combo.setVisible(False)
        combo.blockSignals(False)

    # endregion

    def _emit_dataset_change(self, index: int) -> None:
        if index < 0:
            return
        key = self.dataset_combo.itemData(index)
        if isinstance(key, str):
            self.dataset_changed.emit(key)
