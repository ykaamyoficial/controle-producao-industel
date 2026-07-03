from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal


class Worker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, operation: Callable[[], Any]):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation())
        except Exception as exc:
            self.failed.emit(exc)
        finally:
            self.finished.emit()


def start_worker(owner: QObject, operation: Callable[[], Any], on_success, on_error) -> QThread:
    thread = QThread(owner)
    worker = Worker(operation)
    worker.moveToThread(thread)
    thread.worker = worker
    thread.started.connect(worker.run)
    worker.succeeded.connect(on_success)
    worker.failed.connect(on_error)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
