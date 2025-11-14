"""Tabellmodell med vindusinnlasting for store datasett."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Iterable, Iterator, Mapping, Optional, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush

try:  # pragma: no cover - valgfri avhengighet
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - pandas er valgfritt
    pd = None  # type: ignore


@dataclass
class SaftTableCell:
    """Representerer én celle i tabellen."""

    value: Any
    display: Optional[str] = None
    sort_value: Any = None
    editable: bool = False
    alignment: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter
    user_value: Any = None
    background: Optional[QBrush] = None


@dataclass
class SaftTableSource:
    """Enkel wrapper for sekvensielle rader med eksplisitte kolonnenavn."""

    columns: Sequence[str]
    rows: Iterable[Sequence[Any]]

    def __iter__(self) -> Iterator[Sequence[Any]]:
        return iter(self.rows)


class SaftTableModel(QAbstractTableModel):
    """QAbstractTableModel som kun henter et vindu av rader om gangen."""

    def __init__(self, parent: Optional[object] = None) -> None:
        super().__init__(parent)
        self._columns: list[str] = []
        self._rows: list[list[SaftTableCell]] = []
        self._buffer: Deque[list[SaftTableCell]] = deque()
        self._window_size = 200
        self._prefetch_size = 100
        self._source_iter: Optional[Iterator[Any]] = None
        self._has_more = False
        self._edit_callback: Optional[Callable[[int, int, SaftTableCell], None]] = None

    # region Offentlig API
    def set_window_size(self, size: int) -> None:
        """Angir hvor mange rader som lastes per "vindus"-operasjon."""

        if size <= 0:
            raise ValueError("Vindusstørrelse må være større enn null")
        self._window_size = size
        self._prefetch_size = max(1, size // 2)

    def set_edit_callback(
        self, callback: Optional[Callable[[int, int, SaftTableCell], None]]
    ) -> None:
        """Registrerer en funksjon som kalles når en celle endres."""

        self._edit_callback = callback

    def set_source(self, source: Optional[Iterable[Any]]) -> None:
        """Setter datastrømmen som modellen skal lese fra."""

        self.beginResetModel()
        self._clear_internal()

        if source is None:
            self.endResetModel()
            return

        iterator, columns_hint = self._prepare_iterator(source)
        first_raw = self._consume_first_row(iterator)
        if first_raw is None:
            self._columns = list(columns_hint)
            self.endResetModel()
            return

        cells, columns = self._normalize_row(first_raw, columns_hint)
        self._columns = list(columns)
        self._buffer.append(cells)
        self._source_iter = iterator
        self._has_more = True

        self._fill_prefetch_buffer(initial=True)
        self._rows = self._take_from_buffer(self._window_size)
        self.endResetModel()

    def fetch_more(self, count: Optional[int] = None) -> int:
        """Henter flere rader og returnerer hvor mange som faktisk ble lagt til."""

        chunk = count or self._window_size
        return self._fetch_next_chunk(chunk)

    def get_cell(self, row: int, column: int) -> Optional[SaftTableCell]:
        """Returnerer celleobjektet dersom indeksen er gyldig."""

        if 0 <= row < len(self._rows) and 0 <= column < len(self._columns):
            return self._rows[row][column]
        return None

    def set_cell_background(
        self, row: int, column: int, brush: Optional[QBrush]
    ) -> None:
        """Setter bakgrunnsfarge for en celle og emitterer oppdatering."""

        cell = self.get_cell(row, column)
        if cell is None:
            return
        if (cell.background is None and brush is None) or cell.background == brush:
            return
        cell.background = brush
        top_left = self.index(row, column)
        self.dataChanged.emit(top_left, top_left, [Qt.BackgroundRole])

    # endregion

    # region QAbstractTableModel-implementasjon
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = index.row()
        column = index.column()
        if not (0 <= row < len(self._rows) and 0 <= column < len(self._columns)):
            return None

        cell = self._rows[row][column]
        if role == Qt.DisplayRole:
            if cell.display is not None:
                return cell.display
            return "" if cell.value is None else str(cell.value)
        if role == Qt.EditRole:
            return cell.value
        if role == Qt.UserRole:
            return cell.sort_value if cell.sort_value is not None else cell.value
        if role == Qt.TextAlignmentRole:
            return int(cell.alignment)
        if role == Qt.BackgroundRole:
            return cell.background
        if role == Qt.ToolTipRole and isinstance(cell.value, str) and "\n" in cell.value:
            return cell.value
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self._columns):
                return self._columns[section]
            return None
        return section + 1

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:  # type: ignore[override]
        base_flags = super().flags(index)
        if not index.isValid():
            return base_flags
        cell = self.get_cell(index.row(), index.column())
        if cell and cell.editable:
            return base_flags | Qt.ItemIsEditable
        return base_flags

    def setData(
        self, index: QModelIndex, value: Any, role: int = Qt.EditRole
    ) -> bool:  # type: ignore[override]
        if role not in (Qt.EditRole, Qt.DisplayRole):
            return False
        cell = self.get_cell(index.row(), index.column())
        if cell is None or not cell.editable:
            return False
        cell.value = value
        cell.display = "" if value is None else str(value)
        cell.sort_value = value
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole, Qt.UserRole])
        if self._edit_callback is not None:
            self._edit_callback(index.row(), index.column(), cell)
        return True

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:  # type: ignore[override]
        if parent.isValid():
            return False
        return self._has_more or bool(self._buffer)

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:  # type: ignore[override]
        if parent.isValid():
            return
        self._fetch_next_chunk(self._window_size)

    # endregion

    # region Interne hjelpere
    def _clear_internal(self) -> None:
        self._rows.clear()
        self._buffer.clear()
        self._columns.clear()
        self._source_iter = None
        self._has_more = False

    def _prepare_iterator(
        self, source: Iterable[Any]
    ) -> tuple[Iterator[Any], Sequence[str]]:
        columns_hint: Sequence[str] = []

        if pd is not None and isinstance(source, pd.DataFrame):  # type: ignore[arg-type]
            columns_hint = [str(col) for col in source.columns]
            iterator = (tuple(row) for row in source.itertuples(index=False, name=None))
        elif isinstance(source, SaftTableSource):
            columns_hint = [str(col) for col in source.columns]
            iterator = iter(source.rows)
        elif hasattr(source, "columns"):
            try:
                columns_hint = [str(col) for col in list(getattr(source, "columns"))]
            except Exception:  # pragma: no cover - beste innsats
                columns_hint = []
            iterator = iter(source)
        else:
            iterator = iter(source)
        return iterator, columns_hint

    def _consume_first_row(self, iterator: Iterator[Any]) -> Optional[Any]:
        try:
            return next(iterator)
        except StopIteration:
            return None

    def _normalize_row(
        self, raw_row: Any, columns_hint: Sequence[str]
    ) -> tuple[list[SaftTableCell], list[str]]:
        from collections.abc import Sequence as SeqABC

        if isinstance(raw_row, list) and raw_row and isinstance(raw_row[0], SaftTableCell):
            cells = [cell if isinstance(cell, SaftTableCell) else self._coerce_cell(cell) for cell in raw_row]
            columns = list(columns_hint) or [f"Kolonne {idx + 1}" for idx in range(len(cells))]
            return cells, columns

        if isinstance(raw_row, SaftTableCell):
            cell = raw_row
            columns = list(columns_hint) or ["Kolonne 1"]
            return [cell], columns

        if isinstance(raw_row, Mapping):
            if columns_hint:
                columns = [str(col) for col in columns_hint]
            else:
                columns = [str(key) for key in raw_row.keys()]
            cells = [self._coerce_cell(raw_row.get(col)) for col in columns]
            return cells, columns

        if isinstance(raw_row, SeqABC) and not isinstance(
            raw_row, (str, bytes, bytearray)
        ):
            values = list(raw_row)
            columns = list(columns_hint) or [
                f"Kolonne {idx + 1}" for idx in range(len(values))
            ]
            cells = [self._coerce_cell(value) for value in values]
            if len(columns) < len(cells):
                extra = [f"Kolonne {len(columns) + idx + 1}" for idx in range(len(cells) - len(columns))]
                columns.extend(extra)
            elif len(columns) > len(cells):
                columns = columns[: len(cells)]
            return cells, columns

        cell = self._coerce_cell(raw_row)
        columns = list(columns_hint) or ["Kolonne 1"]
        return [cell], columns

    def _coerce_cell(self, value: Any) -> SaftTableCell:
        if isinstance(value, SaftTableCell):
            return value
        display = "" if value is None else str(value)
        alignment = Qt.AlignLeft | Qt.AlignVCenter
        if isinstance(value, (int, float)):
            alignment = Qt.AlignRight | Qt.AlignVCenter
        sort_value = value
        return SaftTableCell(
            value=value,
            display=display,
            sort_value=sort_value,
            editable=False,
            alignment=alignment,
        )

    def _fill_prefetch_buffer(self, *, initial: bool = False) -> None:
        target = self._window_size + self._prefetch_size if initial else self._prefetch_size
        while len(self._buffer) < target and self._has_more:
            next_row = self._get_next_row()
            if next_row is None:
                break
            self._buffer.append(next_row)

    def _get_next_row(self) -> Optional[list[SaftTableCell]]:
        if self._source_iter is None:
            self._has_more = False
            return None
        try:
            raw_row = next(self._source_iter)
        except StopIteration:
            self._has_more = False
            return None
        cells, columns = self._normalize_row(raw_row, self._columns)
        if not self._columns:
            self._columns = list(columns)
        elif len(cells) != len(self._columns):
            cells = self._adjust_cell_length(cells)
        return cells

    def _adjust_cell_length(self, cells: list[SaftTableCell]) -> list[SaftTableCell]:
        if not self._columns:
            return cells
        desired = len(self._columns)
        if len(cells) >= desired:
            return cells[:desired]
        padded = list(cells)
        for _ in range(desired - len(cells)):
            padded.append(self._coerce_cell(None))
        return padded

    def _take_from_buffer(self, count: int) -> list[list[SaftTableCell]]:
        taken: list[list[SaftTableCell]] = []
        while len(taken) < count:
            if self._buffer:
                taken.append(self._buffer.popleft())
                continue
            if not self._has_more:
                break
            next_row = self._get_next_row()
            if next_row is None:
                break
            taken.append(next_row)
        return taken

    def _fetch_next_chunk(self, count: int) -> int:
        if count <= 0:
            return 0
        new_rows = self._take_from_buffer(count)
        if not new_rows:
            return 0
        first = len(self._rows)
        last = first + len(new_rows) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._rows.extend(new_rows)
        self.endInsertRows()
        self._fill_prefetch_buffer()
        return len(new_rows)

    # endregion


__all__ = ["SaftTableCell", "SaftTableModel", "SaftTableSource"]
