"""Ansvarlig for responsiv layout i hovedvinduet."""

from __future__ import annotations

from typing import Optional, Set, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHeaderView,
    QMainWindow,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..settings import NAV_PANEL_WIDTH_OVERRIDE
from .navigation import NavigationPanel
from .widgets import CardFrame


class ResponsiveLayoutController:
    """Holder logikken for å justere marginer, kort og tabeller etter vindusstørrelse."""

    def __init__(
        self,
        window: QMainWindow,
        stack: QStackedWidget,
        content_layout: QVBoxLayout,
        nav_panel: NavigationPanel,
        scale_factor: float = 1.0,
    ) -> None:
        self._window = window
        self._stack = stack
        self._content_layout = content_layout
        self._nav_panel = nav_panel
        self._responsive_update_pending = False
        self._layout_mode: Optional[str] = None
        self._layout_signature: Optional[Tuple[str, int, int, int, int, int, int]] = (
            None
        )
        self._scale_factor = max(0.85, min(scale_factor, 1.1))

    def schedule_update(self) -> None:
        """Kjører en oppdatering i neste event-loop for å unngå hakkete UI."""

        if self._responsive_update_pending:
            return
        self._responsive_update_pending = True
        QTimer.singleShot(0, self._run_update)

    def update_layout(self) -> None:
        """Justerer marginer og tabeller basert på tilgjengelig bredde."""

        if self._content_layout is None:
            return
        available_width = (
            self._window.centralWidget().width()
            if self._window.centralWidget()
            else self._window.width()
        )
        width = max(self._window.width(), available_width)
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

        nav_width = self._scaled(nav_width)
        margin = self._scaled(margin)
        spacing = self._scaled(spacing)
        card_margin = self._scaled(card_margin)
        card_spacing = self._scaled(card_spacing)
        nav_spacing = self._scaled(nav_spacing)
        header_min = self._scaled(header_min)

        if NAV_PANEL_WIDTH_OVERRIDE is not None:
            nav_width = max(160, NAV_PANEL_WIDTH_OVERRIDE)

        layout_signature = (
            mode,
            nav_width,
            margin,
            spacing,
            card_margin,
            card_spacing,
            nav_spacing,
        )
        signature_changed = layout_signature != self._layout_signature

        self._layout_mode = mode

        if signature_changed:
            self._nav_panel.setMinimumWidth(nav_width)
            self._nav_panel.setMaximumWidth(nav_width)
            self._content_layout.setContentsMargins(margin, margin, margin, margin)
            self._content_layout.setSpacing(spacing)

            nav_layout = self._nav_panel.layout()
            if isinstance(nav_layout, QVBoxLayout):
                nav_padding = max(12, margin - 4)
                nav_layout.setContentsMargins(nav_padding, margin, nav_padding, margin)
                nav_layout.setSpacing(nav_spacing)

            for card in self._window.findChildren(CardFrame):
                layout = card.layout()
                if isinstance(layout, QVBoxLayout):
                    layout.setContentsMargins(
                        card_margin, card_margin, card_margin, card_margin
                    )
                    layout.setSpacing(max(card_spacing, 10))
                body_layout = getattr(card, "body_layout", None)
                if isinstance(body_layout, QVBoxLayout):
                    body_layout.setSpacing(max(card_spacing - 4, 8))

            self._layout_signature = layout_signature

        self._apply_table_sizing(header_min, width)

    # region interne hjelpere
    def _scaled(self, value: int) -> int:
        return max(1, int(round(value * self._scale_factor)))

    def _run_update(self) -> None:
        self._responsive_update_pending = False
        self.update_layout()

    def _apply_table_sizing(self, min_section_size: int, available_width: int) -> None:
        current_widget = self._stack.currentWidget()
        tables = current_widget.findChildren(QTableWidget) if current_widget else []

        if not tables:
            tables = self._window.findChildren(QTableWidget)
        if not tables:
            return

        for table in tables:
            if not table.isVisibleTo(self._window):
                self._ensure_visibility_update_hook(table)
                continue
            header = table.horizontalHeader()
            if header is None:
                continue
            column_count = header.count()
            if column_count <= 0:
                continue

            sizing_signature = (
                self._layout_mode,
                min_section_size,
                available_width,
                table.rowCount(),
                table.columnCount(),
            )
            if table.property("_responsive_signature") == sizing_signature:
                continue

            header.setStretchLastSection(False)
            header.setMinimumSectionSize(min_section_size)

            for col in range(column_count):
                if header.sectionResizeMode(col) != QHeaderView.ResizeToContents:
                    header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            if table.rowCount() and table.columnCount():
                table.resizeColumnsToContents()
            table.setProperty("_responsive_signature", sizing_signature)

    def _ensure_visibility_update_hook(self, table: QTableWidget) -> None:
        widget: Optional[QWidget] = table.parentWidget()
        while widget is not None:
            if isinstance(widget, (QTabWidget, QStackedWidget)):
                hooks: Set[int] = getattr(widget, "_responsive_update_hooks", set())
                if id(self) not in hooks:
                    widget.currentChanged.connect(
                        lambda *_args, _self=self: _self.schedule_update()
                    )
                    hooks = set(hooks)
                    hooks.add(id(self))
                    setattr(widget, "_responsive_update_hooks", hooks)
            widget = widget.parentWidget()

    # endregion
