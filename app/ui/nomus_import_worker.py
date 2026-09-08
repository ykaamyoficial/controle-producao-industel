from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from app.services.nomus_api_client import NomusApiClientError
from app.services.nomus_api_config import NomusApiSecretError
from app.services.nomus_api_importer import (
    NomusApiAmbiguousOrderError,
    NomusApiImportError,
    NomusApiItemsNotFoundError,
    NomusApiOrderNotFoundError,
)
from app.services.nomus_import_progress import NomusImportProgressEvent


class NomusImportWorker(QObject):
    progress_event = Signal(object)
    progress_changed = Signal(int)
    stage_changed = Signal(str)
    detail_changed = Signal(str)
    product_progress_changed = Signal(int, int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, importer: Any, identifier: str):
        super().__init__()
        self.importer = importer
        self.identifier = identifier
        self._last_percent = 0

    def run(self):
        try:
            result = self._fetch_with_progress()
            self._emit_progress(
                NomusImportProgressEvent(
                    stage="conference",
                    message="Importacao concluida.",
                    percent=100,
                    detail="Abrindo a conferencia para revisao.",
                )
            )
            self.completed.emit(result)
        except Exception as exc:  # pragma: no cover - covered by UI/worker tests
            self.failed.emit(_friendly_nomus_error(exc))

    def _fetch_with_progress(self):
        try:
            return self.importer.fetch_proposal(
                self.identifier,
                progress_callback=self._emit_progress,
            )
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                raise
            return self.importer.fetch_proposal(self.identifier)

    def _emit_progress(self, event: NomusImportProgressEvent):
        if event.percent is not None:
            percent = max(self._last_percent, min(100, max(0, int(event.percent))))
            self._last_percent = percent
            if percent != event.percent:
                event = NomusImportProgressEvent(
                    stage=event.stage,
                    message=event.message,
                    percent=percent,
                    detail=event.detail,
                    processed_products=event.processed_products,
                    total_products=event.total_products,
                    indeterminate=event.indeterminate,
                    warning=event.warning,
                )
            self.progress_changed.emit(percent)
        self.stage_changed.emit(event.message)
        self.detail_changed.emit(event.detail)
        self.product_progress_changed.emit(event.processed_products, event.total_products)
        self.progress_event.emit(event)


def _friendly_nomus_error(exc: Exception) -> str:
    if isinstance(exc, NomusApiOrderNotFoundError):
        return "Nenhuma proposta foi encontrada no Nomus para o identificador informado."
    if isinstance(exc, NomusApiAmbiguousOrderError):
        return "Mais de uma proposta foi encontrada. Informe o ID interno do pedido Nomus."
    if isinstance(exc, NomusApiItemsNotFoundError):
        return "A proposta foi encontrada, mas nao retornou itens operacionais para conferencia."
    if isinstance(exc, (NomusApiClientError, NomusApiImportError, NomusApiSecretError)):
        return str(exc)
    return "Nao foi possivel consultar o Nomus agora. Verifique a configuracao, internet ou tente novamente."
