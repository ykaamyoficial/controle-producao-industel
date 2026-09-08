from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from app.services.performance_metrics import measure_operation
from app.services.app_logging import get_logger


log = get_logger("background_worker")


class Worker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, operation: Callable[[], Any], *, operation_name: str, screen: str):
        super().__init__()
        self.operation = operation
        self.operation_name = operation_name
        self.screen = screen

    def run(self):
        try:
            with measure_operation(
                self.operation_name,
                screen=self.screen,
                action=self.operation_name,
                execution_thread="background",
            ):
                result = self.operation()
            self.succeeded.emit(result)
        except Exception as exc:
            log.exception("worker_failed | operation=%s | error_type=%s", self.operation_name, type(exc).__name__)
            self.failed.emit(exc)
        finally:
            self.finished.emit()


class _CallbackBridge(QObject):
    """Garante que callbacks de UI nunca sejam executados no worker thread."""

    success_received = Signal(object)
    error_received = Signal(object)

    def __init__(self, on_success, on_error, parent=None):
        super().__init__(parent)
        self._on_success = on_success
        self._on_error = on_error
        self.success_received.connect(self._dispatch_success, Qt.ConnectionType.QueuedConnection)
        self.error_received.connect(self._dispatch_error, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _dispatch_success(self, result):
        self._on_success(result)

    @Slot(object)
    def _dispatch_error(self, exc):
        self._on_error(exc)


def start_worker(
    owner: QObject,
    operation: Callable[[], Any],
    on_success,
    on_error,
    *,
    operation_name: str | None = None,
) -> QThread:
    screen = owner.objectName() or owner.__class__.__name__ or "unknown"
    module = getattr(operation, "__module__", "unknown")
    callable_name = getattr(operation, "__name__", operation.__class__.__name__)
    name = operation_name or f"worker:{module}.{callable_name}"
    thread = QThread(owner)
    worker = Worker(operation, operation_name=name, screen=screen)
    bridge = _CallbackBridge(on_success, on_error, parent=owner)
    worker.moveToThread(thread)
    thread.worker = worker
    thread.bridge = bridge
    thread.started.connect(worker.run)
    worker.succeeded.connect(bridge.success_received.emit)
    worker.failed.connect(bridge.error_received.emit)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(bridge.deleteLater)
    thread.start()
    return thread
