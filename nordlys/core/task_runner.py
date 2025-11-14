"""Generisk kjøring av tunge oppgaver i bakgrunnen."""
from __future__ import annotations

import inspect
import traceback
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True)
class _TaskSpec:
    """Metadata om en planlagt oppgave."""

    description: Optional[str]


class TaskRunner(QObject):
    """Kjører Python-funksjoner i en QThreadPool med praktiske signaler."""

    sig_started: Signal = Signal(str)
    sig_progress: Signal = Signal(str, int, str)
    sig_done: Signal = Signal(str, object)
    sig_error: Signal = Signal(str, str)

    def __init__(self, parent: Optional[QObject] = None, *, max_threads: Optional[int] = None) -> None:
        super().__init__(parent)
        if max_threads is None:
            self._pool = QThreadPool.globalInstance()
        else:
            self._pool = QThreadPool()
            self._pool.setMaxThreadCount(max_threads)
        self._tasks: Dict[str, _TaskSpec] = {}

    def run(
        self,
        func: Callable[..., Any],
        *args: Any,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Starter funksjonen i bakgrunnen og returnerer oppgavens id."""

        task_id = uuid.uuid4().hex
        self._tasks[task_id] = _TaskSpec(description=description)
        runnable = _TaskRunnable(task_id, func, args, kwargs, self)
        self._pool.start(runnable)
        return task_id

    def description_for(self, task_id: str) -> Optional[str]:
        """Returnerer oppgavens beskrivelse hvis registrert."""

        spec = self._tasks.get(task_id)
        return spec.description if spec else None

    def _emit_started(self, task_id: str) -> None:
        self.sig_started.emit(task_id)

    def _emit_progress(self, task_id: str, percent: int, message: str) -> None:
        clamped = max(0, min(100, int(percent)))
        self.sig_progress.emit(task_id, clamped, message)

    def _emit_done(self, task_id: str, result: Any) -> None:
        self.sig_done.emit(task_id, result)
        self._tasks.pop(task_id, None)

    def _emit_error(self, task_id: str, exc_str: str) -> None:
        self.sig_error.emit(task_id, exc_str)
        self._tasks.pop(task_id, None)


class _TaskRunnable(QRunnable):
    """Innpakning som kjører en funksjon og sender signaler tilbake."""

    def __init__(
        self,
        task_id: str,
        func: Callable[..., Any],
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
        runner: TaskRunner,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._task_id = task_id
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self._runner = runner

    def run(self) -> None:  # type: ignore[override]
        self._runner._emit_started(self._task_id)
        progress_callback = self._build_progress_callback()
        try:
            result = self._invoke_with_progress(progress_callback)
        except Exception:
            exc_str = traceback.format_exc()
            self._runner._emit_error(self._task_id, exc_str)
            return
        self._runner._emit_done(self._task_id, result)

    def _invoke_with_progress(self, progress_callback: ProgressCallback) -> Any:
        if self._should_inject_progress():
            kwargs = dict(self._kwargs)
            kwargs.setdefault("progress_callback", progress_callback)
            return self._func(*self._args, **kwargs)
        return self._func(*self._args, **self._kwargs)

    def _should_inject_progress(self) -> bool:
        if "progress_callback" in self._kwargs:
            return False
        try:
            signature = inspect.signature(self._func)
        except (TypeError, ValueError):
            return False
        parameters = signature.parameters
        if "progress_callback" in parameters:
            return True
        return any(param.kind == param.VAR_KEYWORD for param in parameters.values())

    def _build_progress_callback(self) -> ProgressCallback:
        description = self._runner.description_for(self._task_id)

        def _callback(percent: int, message: str = "") -> None:
            text = message or description or "Arbeid pågår …"
            self._runner._emit_progress(self._task_id, percent, text)

        return _callback
