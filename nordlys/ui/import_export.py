"""Kontroller for import/eksport-operasjoner i Nordlys GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, cast

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QProgressBar, QWidget

from ..core.task_runner import TaskRunner
from ..helpers.lazy_imports import lazy_import
from .data_manager import SaftDatasetStore
from .excel_export import export_dataset_to_excel
from .progress_display import ImportProgressDisplay

if TYPE_CHECKING:
    from ..saft.loader import SaftLoadResult


saft_loader = lazy_import("nordlys.saft.loader")


@dataclass
class ImportTaskState:
    """Holder styr på pågående importoppgaver."""

    loading_files: List[str] = field(default_factory=list)
    current_task_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def is_current(self, task_id: str) -> bool:
        return task_id == self.current_task_id

    def start(self, task_id: str, files: Sequence[str], description: str) -> None:
        self.current_task_id = task_id
        self.loading_files = list(files)
        self.meta = {
            "type": "saft_import",
            "files": list(files),
            "description": description,
        }

    def description(self) -> str:
        description = self.meta.get("description")
        return description if isinstance(description, str) else "Arbeid pågår …"

    def clear(self) -> None:
        self.loading_files.clear()
        self.current_task_id = None
        self.meta.clear()


class ImportExportController(QObject):
    """Håndterer import og eksport av SAF-T-data i bakgrunnen."""

    def __init__(
        self,
        parent: QWidget,
        data_manager: SaftDatasetStore,
        task_runner: TaskRunner,
        apply_results: Callable[[Sequence[SaftLoadResult]], None],
        set_loading_state: Callable[[bool, Optional[str]], None],
        status_callback: Callable[[str], None],
        log_import_event: Callable[..., None],
        load_error_handler: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._window = parent
        self._dataset_store = data_manager
        self._task_runner = task_runner
        self._apply_results = apply_results
        self._set_loading_state = set_loading_state
        self._status_callback = status_callback
        self._log_import_event = log_import_event
        self._load_error_handler = load_error_handler

        self._progress_display = ImportProgressDisplay(parent)
        self._task_state = ImportTaskState()

        self._task_runner.sig_started.connect(self._on_task_started)
        self._task_runner.sig_progress.connect(self._on_task_progress)
        self._task_runner.sig_done.connect(self._on_task_done)
        self._task_runner.sig_error.connect(self._on_task_error)

    # region Initialisering
    def register_status_widgets(
        self, label: QLabel, progress_bar: QProgressBar
    ) -> None:
        self._progress_display.register_widgets(label, progress_bar)

    # endregion

    # region Handlinger
    def handle_open(self) -> None:
        if self._task_state.current_task_id is not None:
            QMessageBox.information(
                self._window,
                "Laster allerede",
                (
                    "En SAF-T-jobb kjører allerede i bakgrunnen. Vent til prosessen er "
                    "ferdig."
                ),
            )
            return
        file_names, _ = QFileDialog.getOpenFileNames(
            self._window,
            "Åpne SAF-T XML",
            str(Path.home()),
            "SAF-T XML (*.xml);;Alle filer (*)",
        )
        if not file_names:
            return
        summary = (
            "Starter import av 1 SAF-T-fil"
            if len(file_names) == 1
            else f"Starter import av {len(file_names)} SAF-T-filer"
        )
        self._log_import_event(summary, reset=True)
        for name in file_names:
            self._log_import_event(f"Forbereder: {Path(name).name}")
        description = "Importer SAF-T"
        task_id = self._task_runner.run(
            saft_loader.load_saft_files,
            file_names,
            description=description,
        )
        self._task_state.start(task_id, file_names, description)
        self._progress_display.set_files(self._task_state.loading_files)

    def handle_export(self) -> None:
        if self._dataset_store.saft_df is None:
            QMessageBox.warning(
                self._window,
                "Ingenting å eksportere",
                "Last inn SAF-T først.",
            )
            return
        file_name, _ = QFileDialog.getSaveFileName(
            self._window,
            "Eksporter rapport",
            str(Path.home() / "SAFT_rapport.xlsx"),
            "Excel (*.xlsx)",
        )
        if not file_name:
            return
        try:
            export_dataset_to_excel(self._dataset_store, file_name)
            self._status_callback(f"Eksportert: {file_name}")
            self._log_import_event(f"Rapport eksportert: {Path(file_name).name}")
        except Exception as exc:  # pragma: no cover - vises i GUI
            self._log_import_event(f"Feil ved eksport: {exc}")
            QMessageBox.critical(self._window, "Feil ved eksport", str(exc))

    # endregion

    # region TaskRunner håndtering
    @Slot(str)
    def _on_task_started(self, task_id: str) -> None:
        if not self._task_state.is_current(task_id):
            return
        file_count = len(self._task_state.loading_files)
        if file_count == 1:
            message = f"Laster SAF-T: {Path(self._task_state.loading_files[0]).name} …"
        elif file_count > 1:
            message = f"Laster {file_count} SAF-T-filer …"
        else:
            message = "Laster SAF-T …"
        self._set_loading_state(True, message)
        self._progress_display.set_files(self._task_state.loading_files)
        self._progress_display.show_progress(message, 0)

    @Slot(str, int, str)
    def _on_task_progress(self, task_id: str, percent: int, message: str) -> None:
        if not self._task_state.is_current(task_id):
            return
        clean_message = message.strip() if message else ""
        if not clean_message:
            clean_message = self._task_state.description()
        self._progress_display.show_progress(clean_message, percent)
        self._status_callback(clean_message)

    @Slot(str, object)
    def _on_task_done(self, task_id: str, result: object) -> None:
        if not self._task_state.is_current(task_id):
            return
        task_type = self._task_state.meta.get("type")
        if task_type == "saft_import":
            self._handle_load_finished(result)
        else:
            self._finalize_loading()

    @Slot(str, str)
    def _on_task_error(self, task_id: str, exc_str: str) -> None:
        if not self._task_state.is_current(task_id):
            return
        message = self._format_task_error(exc_str)
        self._finalize_loading(message)
        self._load_error_handler(message)

    def _handle_load_finished(self, result_obj: object) -> None:
        casted_results = self._cast_results(result_obj)
        self._apply_results(casted_results)
        self._finalize_loading()

    # endregion

    # region Statusvisning
    def _finalize_loading(self, status_message: Optional[str] = None) -> None:
        self._progress_display.hide()
        self._set_loading_state(False)
        self._status_callback(status_message or "Klar.")
        self._task_state.clear()

    # endregion

    # region Hjelpere
    def _cast_results(self, result_obj: object) -> List["SaftLoadResult"]:
        result_type = saft_loader.SaftLoadResult
        if isinstance(result_obj, list):
            return [cast(result_type, item) for item in result_obj]
        return [cast(result_type, result_obj)]

    def _format_task_error(self, exc_str: str) -> str:
        text = exc_str.strip()
        if not text:
            return "Ukjent feil"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "Ukjent feil"
        return lines[-1]

    # endregion
