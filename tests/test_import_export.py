import importlib
import types


def test_handle_load_finished_reports_apply_errors(dummy_pyside6: None) -> None:
    import nordlys.ui.import_export as import_export

    importlib.reload(import_export)
    controller_class = import_export.ImportExportController
    controller = controller_class.__new__(controller_class)

    messages = {"finalize": None, "error": None}

    controller._cast_results = lambda obj: [obj]  # type: ignore[assignment]

    def failing_apply(_: object) -> None:
        raise ValueError("Kunne ikke lagre\nMer info")

    controller._apply_results = failing_apply  # type: ignore[assignment]
    controller._finalize_loading = lambda message=None: messages.__setitem__(
        "finalize", message
    )  # type: ignore[assignment]
    controller._load_error_handler = lambda message: messages.__setitem__(
        "error", message
    )  # type: ignore[assignment]
    controller._format_task_error = controller_class._format_task_error.__get__(
        controller, controller_class
    )

    controller._handle_load_finished(object())

    assert messages["error"] == "Mer info"
    assert messages["finalize"] == "Mer info"


def test_prompt_export_path_adds_suffix_and_uses_dialog(dummy_pyside6: None) -> None:
    import nordlys.ui.import_export as import_export

    importlib.reload(import_export)
    controller_class = import_export.ImportExportController
    controller = controller_class.__new__(controller_class)
    controller._window = object()

    captured_calls: list[tuple[object, str, str, str]] = []

    def fake_dialog(
        parent: object, title: str, default: str, filter_str: str
    ) -> tuple[str, str]:
        captured_calls.append((parent, title, default, filter_str))
        return "rapport", ""

    path = controller_class._prompt_export_path(
        controller,
        "default_name",
        "Filter (*.pdf)",
        ensure_suffix=".pdf",
        dialog_func=fake_dialog,
    )

    assert path == "rapport.pdf"
    assert captured_calls == [
        (controller._window, "Eksporter rapport", "default_name", "Filter (*.pdf)"),
    ]


def test_require_dataset_loaded_warns_when_missing(dummy_pyside6: None) -> None:
    import nordlys.ui.import_export as import_export

    importlib.reload(import_export)
    controller_class = import_export.ImportExportController
    controller = controller_class.__new__(controller_class)
    controller._dataset_store = types.SimpleNamespace(saft_df=None)
    controller._window = object()

    warnings: list[tuple[object, str, str]] = []
    import_export.QMessageBox.warning = staticmethod(  # type: ignore[assignment]
        lambda parent, title, message: warnings.append((parent, title, message))
    )

    result = controller._require_dataset_loaded()

    assert result is False
    assert warnings == [
        (controller._window, "Ingenting å eksportere", "Last inn SAF-T først."),
    ]
