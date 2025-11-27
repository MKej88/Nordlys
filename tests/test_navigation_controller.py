from __future__ import annotations

import sys
import types
from typing import Callable, Optional
from unittest.mock import MagicMock


def stub_dependencies() -> None:
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.Qt = types.SimpleNamespace(UserRole=0)
    qtcore.Signal = lambda *args, **kwargs: None

    class _DummyIcon:
        def __init__(self, _path: str | None = None) -> None:
            self._path = _path

        def isNull(self) -> bool:
            return False

        def pixmap(self, _width: int, _height: int) -> _DummyIcon:
            return self

    qtgui = types.ModuleType("PySide6.QtGui")
    qtgui.QIcon = _DummyIcon

    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    qtwidgets.QTreeWidgetItem = object
    qtwidgets.QStatusBar = object
    qtwidgets.QWidget = object

    sys.modules.setdefault("PySide6", types.ModuleType("PySide6"))
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtWidgets"] = qtwidgets

    data_controller_module = types.ModuleType("nordlys.ui.data_controller")

    class SaftDataController:  # type: ignore[too-many-instance-attributes]
        def activate_dataset(self, key: str) -> None:  # pragma: no cover - stub
            return None

    data_controller_module.SaftDataController = SaftDataController
    sys.modules["nordlys.ui.data_controller"] = data_controller_module

    data_manager_module = types.ModuleType("nordlys.ui.data_manager")

    class SaftDatasetStore:  # pragma: no cover - stub
        def __init__(self) -> None:
            self.current_key: str | None = None

    data_manager_module.SaftDatasetStore = SaftDatasetStore
    sys.modules["nordlys.ui.data_manager"] = data_manager_module

    page_manager_module = types.ModuleType("nordlys.ui.page_manager")

    class PageManager:  # pragma: no cover - stub
        pass

    page_manager_module.PageManager = PageManager
    sys.modules["nordlys.ui.page_manager"] = page_manager_module

    responsive_module = types.ModuleType("nordlys.ui.responsive")

    class ResponsiveLayoutController:  # pragma: no cover - stub
        def schedule_update(self) -> None:
            return None

    responsive_module.ResponsiveLayoutController = ResponsiveLayoutController
    sys.modules["nordlys.ui.responsive"] = responsive_module


def clear_stubbed_modules() -> None:
    for module_name in [
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "nordlys.ui.data_controller",
        "nordlys.ui.data_manager",
        "nordlys.ui.page_manager",
        "nordlys.ui.responsive",
    ]:
        sys.modules.pop(module_name, None)


stub_dependencies()

from nordlys.ui.data_controller import SaftDataController
from nordlys.ui.data_manager import SaftDatasetStore
from nordlys.ui.navigation_controller import NavigationController


class FakeSignal:
    def __init__(self) -> None:
        self._callback: Optional[Callable[[str], None]] = None

    def connect(self, callback: Callable[[str], None]) -> None:
        self._callback = callback


class FakeHeaderBar:
    def __init__(self) -> None:
        self.dataset_changed = FakeSignal()


def test_on_dataset_changed_triggers_activation_for_new_key() -> None:
    header_bar = FakeHeaderBar()
    controller = NavigationController(
        header_bar=header_bar,
        stack=MagicMock(),
        responsive=MagicMock(),
        info_card=None,
    )
    dataset_store = SaftDatasetStore()
    dataset_store.current_key = "gammel"
    data_controller = MagicMock(spec=SaftDataController)

    controller.update_data_context(dataset_store, data_controller)

    controller._on_dataset_changed("ny")

    data_controller.activate_dataset.assert_called_once_with("ny")


def test_on_dataset_changed_skips_same_key() -> None:
    header_bar = FakeHeaderBar()
    controller = NavigationController(
        header_bar=header_bar,
        stack=MagicMock(),
        responsive=MagicMock(),
        info_card=None,
    )
    dataset_store = SaftDatasetStore()
    dataset_store.current_key = "eksisterende"
    data_controller = MagicMock(spec=SaftDataController)

    controller.update_data_context(dataset_store, data_controller)

    controller._on_dataset_changed("eksisterende")

    data_controller.activate_dataset.assert_not_called()


clear_stubbed_modules()
