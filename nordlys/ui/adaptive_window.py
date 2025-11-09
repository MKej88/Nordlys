"""Responsivt hovedvindu for Nordlys."""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QModelIndex,
    QSettings,
    QSize,
    Qt,
    QSortFilterProxyModel,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDockWidget,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QSizePolicy,
    QSplitter,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..constants import APP_TITLE

ColumnDensity = Literal["compact", "comfortable"]
BreakpointMode = Literal["compact", "standard", "ultrawide"]


class LedgerTableModel(QAbstractTableModel):
    """Enkel tabellmodell med forhåndsformatert demodata."""

    headers: Sequence[str] = (
        "Dato",
        "Bilag",
        "Konto",
        "Tekst",
        "Debet",
        "Kredit",
        "MVA",
        "Prosjekt",
        "Avdeling",
        "BeløpNetto",
    )

    numeric_columns = {4, 5, 6, 9}

    def __init__(
        self,
        display_rows: Sequence[Sequence[str]],
        sort_rows: Sequence[Sequence[object]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._display_rows: List[Sequence[str]] = list(display_rows)
        self._sort_rows: List[Sequence[object]] = list(sort_rows)

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent and parent.isValid():
            return 0
        return len(self._display_rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent and parent.isValid():
            return 0
        return len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:  # noqa: D401
        """Returnerer ferdigformatert tekst samt råverdier for sortering."""

        if not index.isValid():
            return None

        row = index.row()
        column = index.column()

        if role == Qt.DisplayRole:
            return self._display_rows[row][column]
        if role == Qt.UserRole:
            return self._sort_rows[row][column]
        if role == Qt.TextAlignmentRole and column in self.numeric_columns:
            return Qt.AlignRight | Qt.AlignVCenter
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> object:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.headers[section]
        return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:  # noqa: D401
        """Tabellen er skrivebeskyttet men lar brukeren velge rader."""

        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    def update_rows(
        self,
        display_rows: Sequence[Sequence[str]],
        sort_rows: Sequence[Sequence[object]],
    ) -> None:
        """Oppdaterer datagrunnlaget og varsler tabellen."""

        self.beginResetModel()
        self._display_rows = list(display_rows)
        self._sort_rows = list(sort_rows)
        self.endResetModel()


class LedgerProxyModel(QSortFilterProxyModel):
    """Proxy-modell som støtter filtrering i alle kolonner."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._filter_text = ""
        self.setSortRole(Qt.UserRole)

    def set_filter_text(self, text: str) -> None:
        self._filter_text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        if not self._filter_text:
            return True
        model = self.sourceModel()
        if model is None:
            return True
        column_count = model.columnCount(parent)
        for column in range(column_count):
            index = model.index(row, column, parent)
            value = model.data(index, Qt.DisplayRole)
            if value is None:
                continue
            if self._filter_text in str(value).lower():
                return True
        return False


def load_svg_icon(name: str) -> QIcon:
    """Forsøker å laste et SVG-ikon fra ressurskatalogen."""

    try:
        icon_path = Path(__file__).resolve().parent.parent / "resources" / "icons" / f"{name}.svg"
        if icon_path.exists():
            return QIcon(str(icon_path))
    except Exception:
        pass
    return QIcon()


class AdaptiveMainWindow(QMainWindow):
    """Hovedvindu som skifter layout basert på skjermbredden."""

    def __init__(self) -> None:
        super().__init__()
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        self.setObjectName("AdaptiveMainWindow")
        self.setWindowTitle(APP_TITLE)
        self._settings = QSettings("Nordlys", "Nordlys")
        self._current_mode: BreakpointMode | None = None
        self._density_mode: ColumnDensity = "comfortable"
        self._is_fullscreen_table = False
        self._fullscreen_cache: Dict[str, object] = {}

        display_rows, sort_rows = self._generate_demo_rows()
        self._table_model = LedgerTableModel(display_rows, sort_rows, self)
        self._proxy_model = LedgerProxyModel(self)
        self._proxy_model.setSourceModel(self._table_model)

        self._column_actions: List[QAction] = []
        self._shortcuts: List[QShortcut] = []

        self._create_widgets()
        self._create_menus_and_toolbar()
        self._connect_shortcuts()
        self._restore_window_state()
        self._apply_breakpoint(force=True)

    # region Oppsett
    def _create_widgets(self) -> None:
        """Oppretter dokker, splitter og sentrale komponenter."""

        self.navigation_dock = QDockWidget("Navigasjon", self)
        self.navigation_dock.setObjectName("NavigationDock")
        self.navigation_list = QListWidget(self.navigation_dock)
        self.navigation_list.addItems(
            [
                "Oversikt",
                "Regnskap",
                "Kontroller",
                "Analyse",
            ]
        )
        self.navigation_dock.setWidget(self.navigation_list)
        self.navigation_dock.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.navigation_dock)

        self.insight_dock = QDockWidget("Innsikt", self)
        self.insight_dock.setObjectName("InsightDock")
        insight_wrapper = QWidget(self.insight_dock)
        insight_layout = QVBoxLayout(insight_wrapper)
        insight_label = QLabel(
            "Innsiktspanel\nPlassholder for diagrammer og nøkkeltall.", insight_wrapper
        )
        insight_label.setWordWrap(True)
        insight_layout.addWidget(insight_label)
        insight_layout.addStretch()
        self.insight_dock.setWidget(insight_wrapper)
        self.addDockWidget(Qt.RightDockWidgetArea, self.insight_dock)

        self.quick_toolbar = QToolBar("Hurtig", self)
        self.quick_toolbar.setObjectName("QuickToolbar")
        self.quick_toolbar.setMovable(False)
        self.quick_toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.quick_toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.LeftToolBarArea, self.quick_toolbar)
        self.quick_toolbar.hide()

        self.table_container = QWidget(self)
        table_layout = QVBoxLayout(self.table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(6)

        self.search_field = QLineEdit(self.table_container)
        self.search_field.setPlaceholderText("Søk i tabellen …")
        table_layout.addWidget(self.search_field)

        self.table_view = QTableView(self.table_container)
        self.table_view.setObjectName("LedgerTable")
        self.table_view.setModel(self._proxy_model)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setSelectionMode(QTableView.SingleSelection)
        self.table_view.setSortingEnabled(True)
        self._apply_uniform_row_heights()
        self.table_view.verticalHeader().setVisible(False)
        header = self.table_view.horizontalHeader()
        header.setSectionsMovable(True)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        QTimer.singleShot(0, lambda: header.setSectionResizeMode(QHeaderView.Interactive))
        table_layout.addWidget(self.table_view)

        self.detail_container = QWidget(self)
        detail_layout = QVBoxLayout(self.detail_container)
        detail_layout.setContentsMargins(12, 12, 12, 12)
        detail_layout.setSpacing(12)
        detail_label = QLabel(
            "Detaljpanel\nVelg en rad for å vise utdypende informasjon.",
            self.detail_container,
        )
        detail_label.setWordWrap(True)
        detail_layout.addWidget(detail_label)
        detail_layout.addStretch()

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.table_container)
        self.splitter.addWidget(self.detail_container)
        self.setCentralWidget(self.splitter)

        self.search_field.textChanged.connect(self._proxy_model.set_filter_text)

    def _create_menus_and_toolbar(self) -> None:
        """Setter opp menyer og handlingsknapper."""

        menu_bar = self.menuBar()
        view_menu = menu_bar.addMenu("Vis")
        self.columns_menu = QMenu("Kolonner", self)
        view_menu.addMenu(self.columns_menu)

        for column, title in enumerate(self._table_model.headers):
            action = QAction(title, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda checked, col=column: self._on_column_toggled(col, checked))
            self.columns_menu.addAction(action)
            self._column_actions.append(action)

        self.navigate_action = QAction(load_svg_icon("dashboard"), "Navigasjon", self)
        self.navigate_action.triggered.connect(lambda: self.navigation_list.setFocus())

        self.search_action = QAction(load_svg_icon("analytics"), "Søk", self)
        self.search_action.triggered.connect(self._focus_search)

        self.refresh_action = QAction(load_svg_icon("import"), "Oppdater", self)
        self.refresh_action.triggered.connect(self._refresh_model_data)

        self.fullscreen_action = QAction(load_svg_icon("layers"), "Fullskjerm", self)
        self.fullscreen_action.setCheckable(True)
        self.fullscreen_action.triggered.connect(lambda checked: self._toggle_fullscreen(checked))

        self.quick_toolbar.addAction(self.navigate_action)
        self.quick_toolbar.addAction(self.search_action)
        self.quick_toolbar.addAction(self.refresh_action)
        self.quick_toolbar.addAction(self.fullscreen_action)

        view_menu.addAction(self.fullscreen_action)
        view_menu.addSeparator()
        view_menu.addAction(self.refresh_action)

        self._update_column_actions()

    def _connect_shortcuts(self) -> None:
        """Definerer tastatursnarveier for vanlige handlinger."""

        def add_shortcut(sequence: str, callback) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

        add_shortcut("Ctrl+F", self._focus_search)
        add_shortcut("F5", self._refresh_model_data)
        add_shortcut("F11", lambda: self._toggle_fullscreen())
        add_shortcut("Ctrl+1", lambda: self.navigation_list.setFocus())
        add_shortcut("Ctrl+2", lambda: self.table_view.setFocus())
        add_shortcut("Ctrl+3", lambda: self.insight_dock.widget().setFocus())

    # endregion

    # region Qt overrides
    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if not self._is_fullscreen_table:
            self._apply_breakpoint()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: D401
        """Lagrer layout og brukerpreferanser før applikasjonen avsluttes."""

        self._save_mode_settings(self._current_mode)
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        self._settings.sync()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_Escape and self._is_fullscreen_table:
            self._toggle_fullscreen(False)
            event.accept()
            return
        super().keyPressEvent(event)

    # endregion

    # region Breakpoints
    def _apply_breakpoint(self, force: bool = False) -> None:
        width = self.width()
        if width < 1400:
            mode: BreakpointMode = "compact"
        elif width < 2200:
            mode = "standard"
        else:
            mode = "ultrawide"

        if self._current_mode == mode and not force:
            return

        if self._current_mode and self._current_mode != mode:
            self._save_mode_settings(self._current_mode)

        self._current_mode = mode
        print(f"Aktiv breakpoint: {mode}")

        if mode == "compact":
            self._set_compact_mode(True)
            self._set_ultrawide_extras(False)
            default_density: ColumnDensity = "compact"
        elif mode == "standard":
            self._set_compact_mode(False)
            self._set_ultrawide_extras(False)
            default_density = "comfortable"
        else:
            self._set_compact_mode(False)
            self._set_ultrawide_extras(True)
            default_density = "comfortable"

        self._load_mode_settings(mode, default_density)

    def _set_compact_mode(self, on: bool) -> None:
        if on:
            self.navigation_dock.hide()
            self.insight_dock.hide()
            self.detail_container.hide()
            self.quick_toolbar.show()
        else:
            self.navigation_dock.show()
            self.detail_container.show()
            self.quick_toolbar.hide()

    def _set_ultrawide_extras(self, on: bool) -> None:
        width = max(self.splitter.width(), 1)
        if on:
            self.insight_dock.show()
            primary = max(int(width * 0.6), 300)
            secondary = max(width - primary, 240)
            self.splitter.setSizes([primary, secondary])
        else:
            self.insight_dock.hide()
            primary = max(int(width * 0.7), 320)
            secondary = max(width - primary, 220)
            self.splitter.setSizes([primary, secondary])

    def _set_table_density(self, mode: ColumnDensity) -> None:
        self._density_mode = mode
        vertical_header = self.table_view.verticalHeader()
        if mode == "compact":
            vertical_header.setDefaultSectionSize(24)
            self.table_view.setStyleSheet("QTableView { font-size: 11px; }")
        else:
            vertical_header.setDefaultSectionSize(32)
            self.table_view.setStyleSheet("QTableView { font-size: 12px; }")
        self._apply_uniform_row_heights()
        
    def _apply_uniform_row_heights(self) -> None:
        """Aktiverer jevne radhøyder der API-et støttes av PySide-versjonen."""

        set_uniform = getattr(self.table_view, "setUniformRowHeights", None)
        if callable(set_uniform):
            set_uniform(True)

    # endregion

    # region Persistens
    def _restore_window_state(self) -> None:
        geometry = self._settings.value("window/geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        state = self._settings.value("window/state")
        if isinstance(state, QByteArray):
            self.restoreState(state)

    def _load_mode_settings(self, mode: BreakpointMode, default_density: ColumnDensity) -> None:
        prefix = f"modes/{mode}"

        density_value = self._settings.value(f"{prefix}/density", default_density)
        density = density_value if density_value in {"compact", "comfortable"} else default_density
        self._set_table_density(density)  # oppdaterer state og UI

        splitter_default = self.splitter.sizes()
        splitter_sizes = self._read_int_list(f"{prefix}/splitter", splitter_default)
        if splitter_sizes:
            self.splitter.setSizes(splitter_sizes)

        width_defaults = [self.table_view.columnWidth(i) for i in range(self._table_model.columnCount())]
        column_widths = self._read_int_list(f"{prefix}/columnWidths", width_defaults)
        for column, width in enumerate(column_widths):
            if width > 0:
                self.table_view.setColumnWidth(column, width)

        visibility_defaults = [1] * self._table_model.columnCount()
        visibility = self._read_int_list(f"{prefix}/columnVisibility", visibility_defaults)
        for column, visible in enumerate(visibility):
            self.table_view.setColumnHidden(column, not bool(visible))

        self._update_column_actions()

    def _save_mode_settings(self, mode: BreakpointMode | None) -> None:
        if not mode:
            return
        prefix = f"modes/{mode}"
        self._settings.setValue(f"{prefix}/density", self._density_mode)
        self._write_int_list(f"{prefix}/splitter", self.splitter.sizes())
        column_widths = [self.table_view.columnWidth(i) for i in range(self._table_model.columnCount())]
        self._write_int_list(f"{prefix}/columnWidths", column_widths)
        visibility = [int(not self.table_view.isColumnHidden(i)) for i in range(self._table_model.columnCount())]
        self._write_int_list(f"{prefix}/columnVisibility", visibility)

    def _read_int_list(self, key: str, default: Sequence[int]) -> List[int]:
        raw = self._settings.value(key, None)
        if raw is None:
            return list(default)
        if isinstance(raw, list):
            try:
                return [int(value) for value in raw]
            except (TypeError, ValueError):
                return list(default)
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return [int(value) for value in data]
            except json.JSONDecodeError:
                return list(default)
        return list(default)

    def _write_int_list(self, key: str, values: Sequence[int]) -> None:
        self._settings.setValue(key, json.dumps([int(value) for value in values]))

    # endregion

    # region Handlinger
    def _on_column_toggled(self, column: int, checked: bool) -> None:
        self.table_view.setColumnHidden(column, not checked)
        self._save_mode_settings(self._current_mode)

    def _update_column_actions(self) -> None:
        for column, action in enumerate(self._column_actions):
            action.blockSignals(True)
            action.setChecked(not self.table_view.isColumnHidden(column))
            action.blockSignals(False)

    def _focus_search(self) -> None:
        self.search_field.setFocus()
        self.search_field.selectAll()

    def _refresh_model_data(self) -> None:
        display_rows, sort_rows = self._generate_demo_rows()
        self._table_model.update_rows(display_rows, sort_rows)
        self._save_mode_settings(self._current_mode)

    def _toggle_fullscreen(self, enabled: Optional[bool] = None) -> None:
        if enabled is None:
            enabled = not self._is_fullscreen_table
        if enabled == self._is_fullscreen_table:
            return
        if enabled:
            self._save_mode_settings(self._current_mode)
            self._fullscreen_cache = {
                "navigation": self.navigation_dock.isVisible(),
                "insight": self.insight_dock.isVisible(),
                "detail": self.detail_container.isVisible(),
                "splitter": self.splitter.sizes(),
            }
            self.navigation_dock.hide()
            self.insight_dock.hide()
            self.detail_container.hide()
            self.quick_toolbar.hide()
            self.splitter.setSizes([self.splitter.width() or 1, 0])
            self._is_fullscreen_table = True
        else:
            cache = self._fullscreen_cache
            self._is_fullscreen_table = False
            self._apply_breakpoint(force=True)
            if self._current_mode != "compact":
                self.navigation_dock.setVisible(bool(cache.get("navigation", True)))
                self.detail_container.setVisible(bool(cache.get("detail", True)))
            if self._current_mode == "ultrawide":
                self.insight_dock.setVisible(True)
            elif self._current_mode == "standard":
                self.insight_dock.setVisible(bool(cache.get("insight", False)))
            sizes = cache.get("splitter")
            if isinstance(sizes, list) and sizes:
                self.splitter.setSizes([int(value) for value in sizes])
        self.fullscreen_action.blockSignals(True)
        self.fullscreen_action.setChecked(self._is_fullscreen_table)
        self.fullscreen_action.blockSignals(False)

    # endregion

    # region Demodata
    def _generate_demo_rows(self) -> Tuple[List[List[str]], List[List[object]]]:
        rng = random.Random(2024)
        today = date.today()
        display_rows: List[List[str]] = []
        sort_rows: List[List[object]] = []

        for index in range(2500):
            current_date = today - timedelta(days=index % 365)
            bilag = f"BL{index:05d}"
            konto = 3000 + (index % 120)
            tekst = f"Transaksjon {index:04d}"
            if index % 2 == 0:
                debet = round(rng.uniform(0.0, 5000.0), 2)
                kredit = 0.0
            else:
                kredit = round(rng.uniform(0.0, 5000.0), 2)
                debet = 0.0
            mva = round((debet - kredit) * 0.25, 2)
            prosjekt = f"PRJ-{index % 12:03d}"
            avdeling = f"AVD-{index % 8:03d}"
            belop_netto = round(debet - kredit - mva, 2)

            display_rows.append(
                [
                    current_date.strftime("%Y-%m-%d"),
                    bilag,
                    str(konto),
                    tekst,
                    self._format_amount(debet),
                    self._format_amount(kredit),
                    self._format_amount(mva),
                    prosjekt,
                    avdeling,
                    self._format_amount(belop_netto),
                ]
            )
            sort_rows.append(
                [
                    current_date,
                    index,
                    konto,
                    tekst,
                    debet,
                    kredit,
                    mva,
                    index % 12,
                    index % 8,
                    belop_netto,
                ]
            )

        return display_rows, sort_rows

    @staticmethod
    def _format_amount(value: float) -> str:
        return f"{value:,.2f}".replace(",", " ")

    # endregion
__all__ = ["AdaptiveMainWindow", "load_svg_icon", "LedgerTableModel"]
