from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import QObject, Signal, Slot

from app.services.nomus_batch_import import CancellationToken
from app.services.nomus_batch_persistence import (
    NomusBatchPersistenceResult,
    NomusPersistenceEvent,
    NomusPersistenceEventType,
    ProposalImportPersistenceService,
)


class NomusBatchPersistenceWorker(QObject):
    batch_started = Signal(int)
    proposal_state_changed = Signal(str, str, str)
    batch_progress = Signal(int, int)
    proposal_finished = Signal(object)
    batch_finished = Signal(object)
    batch_cancelled = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        service: ProposalImportPersistenceService,
        prepared_results: Iterable[Any],
        *,
        cancellation_token: CancellationToken | None = None,
        batch_id: str | None = None,
    ):
        super().__init__()
        self.service = service
        self.prepared_results = list(prepared_results)
        self.cancellation_token = cancellation_token or CancellationToken()
        self.batch_id = batch_id

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.persist_batch(
                self.prepared_results,
                cancellation_token=self.cancellation_token,
                event_callback=self._handle_event,
                batch_id=self.batch_id,
            )
        except Exception as exc:
            self.failed.emit(exc)
            return
        if result.cancelled:
            self.batch_cancelled.emit(result)
        else:
            self.batch_finished.emit(result)

    @Slot()
    def cancel(self) -> None:
        self.cancellation_token.cancel()

    def _handle_event(self, event: NomusPersistenceEvent) -> None:
        if event.event_type == NomusPersistenceEventType.BATCH_STARTED:
            self.batch_started.emit(event.total)
        elif event.event_type == NomusPersistenceEventType.PROPOSAL_STATE_CHANGED:
            self.proposal_state_changed.emit(
                event.proposal_number or "",
                event.status.value if event.status else "",
                event.message,
            )
        elif event.event_type == NomusPersistenceEventType.BATCH_PROGRESS:
            self.batch_progress.emit(event.completed, event.total)
        elif event.event_type == NomusPersistenceEventType.PROPOSAL_FINISHED and event.result is not None:
            self.proposal_finished.emit(event.result)
