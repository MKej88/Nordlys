"""Kontroller for import/eksport-operasjoner i Nordlys GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, cast

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QProgressBar, QWidget

from ..core.task_runner import TaskRunner
from ..saft.loader import SaftLoadResult, load_saft_files
from ..utils import lazy_pandas
from .data_manager import SaftDatasetStore
from .widgets import TaskProgressDialog

pd = lazy_pandas()


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

        self._loading_files: List[str] = []
        self._current_task_id: Optional[str] = None
        self._current_task_meta: Dict[str, Any] = {}
        self._status_progress_label: Optional[QLabel] = None
        self._status_progress_bar: Optional[QProgressBar] = None
        self._progress_dialog: Optional[TaskProgressDialog] = None

        self._task_runner.sig_started.connect(self._on_task_started)
        self._task_runner.sig_progress.connect(self._on_task_progress)
        self._task_runner.sig_done.connect(self._on_task_done)
        self._task_runner.sig_error.connect(self._on_task_error)

    # region Initialisering
    def register_status_widgets(
        self, label: QLabel, progress_bar: QProgressBar
    ) -> None:
        self._status_progress_label = label
        self._status_progress_bar = progress_bar

    # endregion

    # region Handlinger
    def handle_open(self) -> None:
        if self._current_task_id is not None:
            QMessageBox.information(
                self._window,
                "Laster allerede",
                "En SAF-T-jobb kjører allerede i bakgrunnen. Vent til prosessen er ferdig.",
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
        self._loading_files = list(file_names)
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
            load_saft_files,
            file_names,
            description=description,
        )
        self._current_task_id = task_id
        self._current_task_meta = {
            "type": "saft_import",
            "files": list(file_names),
            "description": description,
        }

    def handle_export(self) -> None:
        saft_df = self._dataset_store.saft_df
        if saft_df is None:
            QMessageBox.warning(self._window, "Ingenting å eksportere", "Last inn SAF-T først.")
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
            with pd.ExcelWriter(file_name, engine="xlsxwriter") as writer:
                saft_df.to_excel(writer, sheet_name="Saldobalanse", index=False)
                summary = self._dataset_store.saft_summary
                if summary:
                    summary_df = pd.DataFrame([summary]).T.reset_index()
                    summary_df.columns = ["Nøkkel", "Beløp"]
                    summary_df.to_excel(writer, sheet_name="NS4102_Sammendrag", index=False)
                customer_sales = self._dataset_store.customer_sales
                if customer_sales is not None:
                    customer_sales.to_excel(
                        writer, sheet_name="Sales_by_customer", index=False
                    )
                brreg_json = self._dataset_store.brreg_json
                if brreg_json:
                    pd.json_normalize(brreg_json).to_excel(
                        writer, sheet_name="Brreg_JSON", index=False
                    )
                brreg_map = self._dataset_store.brreg_map
                if brreg_map:
                    map_df = pd.DataFrame(list(brreg_map.items()), columns=["Felt", "Verdi"])
                    map_df.to_excel(writer, sheet_name="Brreg_Mapping", index=False)
            self._status_callback(f"Eksportert: {file_name}")
            self._log_import_event(f"Rapport eksportert: {Path(file_name).name}")
        except Exception as exc:  # pragma: no cover - vises i GUI
            self._log_import_event(f"Feil ved eksport: {exc}")
            QMessageBox.critical(self._window, "Feil ved eksport", str(exc))

    # endregion

    # region TaskRunner håndtering
    @Slot(str)
    def _on_task_started(self, task_id: str) -> None:
        if task_id != self._current_task_id:
            return
        if len(self._loading_files) == 1:
            message = f"Laster SAF-T: {Path(self._loading_files[0]).name} …"
        elif len(self._loading_files) > 1:
            message = f"Laster {len(self._loading_files)} SAF-T-filer …"
        else:
            message = "Laster SAF-T …"
        self._set_loading_state(True, message)
        self._show_status_progress(message, 0)

    @Slot(str, int, str)
    def _on_task_progress(self, task_id: str, percent: int, message: str) -> None:
        if task_id != self._current_task_id:
            return
        clean_message = message.strip() if message else ""
        if not clean_message:
            clean_message = self._current_task_meta.get("description", "Arbeid pågår …")
        self._show_status_progress(clean_message, percent)
        self._status_callback(clean_message)

    @Slot(str, object)
    def _on_task_done(self, task_id: str, result: object) -> None:
        if task_id != self._current_task_id:
            return
        task_type = self._current_task_meta.get("type")
        if task_type == "saft_import":
            self._handle_load_finished(result)
        else:
            self._finalize_loading()

    @Slot(str, str)
    def _on_task_error(self, task_id: str, exc_str: str) -> None:
        if task_id != self._current_task_id:
            return
        message = self._format_task_error(exc_str)
        self._finalize_loading(message)
        self._load_error_handler(message)

    def _handle_load_finished(self, result_obj: object) -> None:
        if isinstance(result_obj, list):
            casted = [cast(SaftLoadResult, item) for item in result_obj]
        else:
            casted = [cast(SaftLoadResult, result_obj)]
        self._apply_results(casted)
        self._finalize_loading()

    # endregion

    # region Statusvisning
    def _show_status_progress(self, message: str, value: int) -> None:
        if self._status_progress_label is not None:
            self._status_progress_label.setText(message)
            self._status_progress_label.setVisible(True)
        if self._status_progress_bar is not None:
            clamped = max(0, min(100, int(value)))
            self._status_progress_bar.setValue(clamped)
            self._status_progress_bar.setVisible(True)
        self._update_progress_dialog(message, value)

    def _hide_status_progress(self) -> None:
        if self._status_progress_label is not None:
            self._status_progress_label.clear()
            self._status_progress_label.setVisible(False)
        if self._status_progress_bar is not None:
            self._status_progress_bar.setValue(0)
            self._status_progress_bar.setVisible(False)
        self._close_progress_dialog()

    def _ensure_progress_dialog(self) -> TaskProgressDialog:
        if self._progress_dialog is None:
            self._progress_dialog = TaskProgressDialog(self._window)
        return self._progress_dialog

    def _update_progress_dialog(self, message: str, value: int) -> None:
        dialog = self._ensure_progress_dialog()
        dialog.set_files(self._loading_files)
        dialog.update_status(message, value)
        if not dialog.isVisible():
            dialog.show()
        dialog.raise_()

    def _close_progress_dialog(self) -> None:
        if self._progress_dialog is None:
            return
        dialog = self._progress_dialog
        self._progress_dialog = None
        dialog.hide()
        dialog.deleteLater()

    def _finalize_loading(self, status_message: Optional[str] = None) -> None:
        self._hide_status_progress()
        self._set_loading_state(False)
        self._status_callback(status_message or "Klar.")
        self._loading_files = []
        self._current_task_id = None
        self._current_task_meta = {}

    # endregion

    # region Hjelpere
    def _format_task_error(self, exc_str: str) -> str:
        text = exc_str.strip()
        if not text:
            return "Ukjent feil"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "Ukjent feil"
        return lines[-1]

    # endregion
