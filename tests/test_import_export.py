import importlib
import sys
import types
from collections.abc import Iterator

import pytest


def _create_dummy_pyside6() -> dict[str, types.ModuleType | None]:
    original_modules: dict[str, types.ModuleType | None] = {
        name: sys.modules.get(name)
        for name in [
            "PySide6",
            "PySide6.QtCore",
            "PySide6.QtGui",
            "PySide6.QtWidgets",
        ]
    }

    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _DummyQObject:
        def __init__(self, *_: object, **__: object) -> None:
            return

    def _slot(*_: object, **__: object):
        def wrapper(func):
            return func

        return wrapper

    qtcore.QObject = _DummyQObject
    qtcore.Slot = _slot
    qtcore.QRunnable = type("QRunnable", (), {"setAutoDelete": lambda self, flag: None})

    class _DummyQt:
        def __getattr__(self, name: str) -> int:
            return 0

    qtcore.Qt = _DummyQt()

    class _DummyThreadPool:
        @staticmethod
        def globalInstance():  # noqa: N802 - etterligner Qt
            return _DummyThreadPool()

        def start(self, *_: object, **__: object) -> None:
            return None

        def setMaxThreadCount(self, *_: object, **__: object) -> None:
            return None

    class _DummySignal:
        def __init__(self, *_: object, **__: object) -> None:
            return

        def connect(self, *_: object, **__: object) -> None:
            return None

        def emit(self, *_: object, **__: object) -> None:
            return None

    qtcore.QThreadPool = _DummyThreadPool
    qtcore.Signal = _DummySignal

    class _DummyTimer:
        def __init__(self, *_: object, **__: object) -> None:
            self.timeout = _DummySignal()

        def setInterval(self, *_: object, **__: object) -> None:
            return None

        def start(self, *_: object, **__: object) -> None:
            return None

        def stop(self, *_: object, **__: object) -> None:
            return None

    qtcore.QTimer = _DummyTimer

    class _DummyColor:
        def __init__(self, *_: object, **__: object) -> None:
            return

    qtgui.QColor = _DummyColor

    class _DummyWidget:
        def __init__(self, *_: object, **__: object) -> None:
            return

    for name in ["QFileDialog", "QLabel", "QMessageBox", "QProgressBar", "QWidget"]:
        setattr(qtwidgets, name, type(name, (_DummyWidget,), {}))

    for name in [
        "QDialog",
        "QFrame",
        "QGraphicsDropShadowEffect",
        "QGridLayout",
        "QHBoxLayout",
        "QLayout",
        "QSizePolicy",
        "QVBoxLayout",
    ]:
        setattr(qtwidgets, name, type(name, (_DummyWidget,), {}))

    pyside6 = sys.modules.get("PySide6") or types.ModuleType("PySide6")
    pyside6.QtCore = qtcore
    pyside6.QtGui = qtgui
    pyside6.QtWidgets = qtwidgets

    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtWidgets"] = qtwidgets

    return original_modules


def _restore_modules(original_modules: dict[str, types.ModuleType | None]) -> None:
    for name, module in original_modules.items():
        if module is None and name in sys.modules:
            del sys.modules[name]
        elif module is not None:
            sys.modules[name] = module


@pytest.fixture
def dummy_pyside6() -> Iterator[None]:
    original_modules = _create_dummy_pyside6()
    try:
        yield
    finally:
        _restore_modules(original_modules)


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
