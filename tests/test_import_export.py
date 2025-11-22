import sys
import types


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

sys.modules.setdefault("PySide6", types.ModuleType("PySide6"))
sys.modules["PySide6.QtCore"] = qtcore
sys.modules["PySide6.QtGui"] = qtgui
sys.modules["PySide6.QtWidgets"] = qtwidgets

from nordlys.ui.import_export import ImportExportController


def test_handle_load_finished_reports_apply_errors() -> None:
    controller = ImportExportController.__new__(ImportExportController)

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
    controller._format_task_error = ImportExportController._format_task_error.__get__(
        controller, ImportExportController
    )

    controller._handle_load_finished(object())

    assert messages["error"] == "Mer info"
    assert messages["finalize"] == "Mer info"
