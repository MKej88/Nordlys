import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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
            self._callbacks: dict[int, list[object]] = {}

        def __get__(
            self, instance: object | None, owner: type[object] | None = None
        ) -> "_BoundDummySignal | _DummySignal":
            if instance is None:
                return self
            return _BoundDummySignal(self, instance)

        def _callbacks_for(self, emitter: object) -> list[object]:
            return self._callbacks.setdefault(id(emitter), [])

        def connect(self, callback, *_: object, **__: object) -> None:
            callbacks = self._callbacks_for(self)
            callbacks.append(callback)

        def emit(self, *args: object, **kwargs: object) -> None:
            callbacks = self._callbacks_for(self)
            for callback in list(callbacks):
                callback(*args, **kwargs)

    class _BoundDummySignal:
        def __init__(self, signal: _DummySignal, instance: object) -> None:
            self._signal = signal
            self._instance = instance

        def connect(self, callback, *_: object, **__: object) -> None:
            callbacks = self._signal._callbacks_for(self._instance)
            callbacks.append(callback)

        def emit(self, *args: object, **kwargs: object) -> None:
            callbacks = self._signal._callbacks.get(id(self._instance), [])
            for callback in list(callbacks):
                callback(*args, **kwargs)

    qtcore.QThreadPool = _DummyThreadPool
    qtcore.Signal = _DummySignal

    class _DummyTimer:
        def __init__(self, *_: object, **__: object) -> None:
            self.timeout = _DummySignal()
            self._active = False

        def setInterval(self, *_: object, **__: object) -> None:
            return None

        def start(self, *_: object, **__: object) -> None:
            self._active = True
            return None

        def stop(self, *_: object, **__: object) -> None:
            self._active = False
            return None

        def isActive(self) -> bool:
            return self._active

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
