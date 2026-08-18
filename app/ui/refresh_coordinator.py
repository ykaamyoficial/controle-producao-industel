from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from app.ui.background_worker import start_worker


class RefreshCoordinator(QObject):
    """Serializa refreshes, descarta respostas antigas e aplica debounce."""

    def __init__(self, owner: QObject, *, debounce_ms: int = 280, start_worker: Callable = start_worker):
        super().__init__(owner)
        self.owner = owner
        self.debounce_ms = debounce_ms
        self._generation = 0
        self._running = False
        self._pending = None
        self._start_worker = start_worker
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_pending)
        self.thread = None

    @property
    def running(self) -> bool:
        return self._running

    def request(self, loader: Callable, on_success: Callable, on_error: Callable,
                *, operation_name: str, immediate: bool = False) -> None:
        self._generation += 1
        self._pending = (loader, on_success, on_error, operation_name, self._generation)
        if self._running:
            return
        if immediate:
            # Uma chamada imediata deve surtir efeito de fato "agora" (sem
            # esperar o loop de eventos processar um QTimer de 0ms) para que
            # quem chama `refresh(...)`/`request(..., immediate=True)` possa
            # contar com o resultado ja refletido ao retornar do metodo, tal
            # como acontecia antes de existir o RefreshCoordinator.
            self._timer.stop()
            self._start_pending()
        else:
            self._timer.start(self.debounce_ms)

    def invalidate(self) -> None:
        self._generation += 1
        self._pending = None
        self._timer.stop()

    def _start_pending(self):
        if self._running or not self._pending:
            return
        loader, on_success, on_error, operation_name, generation = self._pending
        self._pending = None
        self._running = True

        def success(result):
            current = generation == self._generation
            if current:
                on_success(result)
            self._complete()

        def error(exc):
            current = generation == self._generation
            if current:
                on_error(exc)
            self._complete()

        self.thread = self._start_worker(
            self.owner, loader, success, error, operation_name=operation_name
        )

    def _complete(self):
        self._running = False
        if self._pending:
            self._timer.start(0)
