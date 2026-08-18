from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import QObject, Signal

from app.services.nomus_batch_import import CancellationToken, NomusBatchEvent, NomusBatchEventType


class NomusBatchImportWorker(QObject):
    batch_started = Signal(int)
    proposal_state_changed = Signal(str, str, str)
    batch_progress = Signal(int, int)
    proposal_ready = Signal(str, object)
    batch_finished = Signal(object)
    batch_cancelled = Signal(object)
    failed = Signal(object)

    def __init__(self, service: Any, raw_input: str | Iterable[Any], *, cancellation_token: CancellationToken | None = None):
        super().__init__()
        self.service = service
        self.raw_input = raw_input
        self.cancellation_token = cancellation_token or CancellationToken()

    def cancel(self) -> None:
        self.cancellation_token.cancel()

    def run(self) -> None:
        try:
            result = self.service.prepare_batch(
                self.raw_input,
                cancellation_token=self.cancellation_token,
                event_callback=self._handle_event,
            )
            if any(target.state.value == "CANCELLED" for target in result.targets):
                self.batch_cancelled.emit(result)
            else:
                self.batch_finished.emit(result)
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.failed.emit(exc)

    def _handle_event(self, event: NomusBatchEvent) -> None:
        if event.event_type == NomusBatchEventType.BATCH_STARTED:
            self.batch_started.emit(event.total)
        elif event.event_type == NomusBatchEventType.PROPOSAL_STATE_CHANGED:
            self.proposal_state_changed.emit(event.proposal_number or "", event.state.value if event.state else "", event.message)
        elif event.event_type == NomusBatchEventType.BATCH_PROGRESS:
            self.batch_progress.emit(event.completed, event.total)
        elif event.event_type == NomusBatchEventType.PROPOSAL_READY:
            self.proposal_ready.emit(event.proposal_number or "", event.result)
