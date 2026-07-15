from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


STAGE_CONFIGURATION = "configuration"
STAGE_CONNECTION = "connection"
STAGE_SEARCH = "search"
STAGE_ITEMS = "items"
STAGE_PRODUCTS = "products"
STAGE_VALIDATION = "validation"
STAGE_CONFERENCE = "conference"

PROGRESS_RANGES = {
    STAGE_CONFIGURATION: (0, 10),
    STAGE_CONNECTION: (10, 25),
    STAGE_SEARCH: (25, 35),
    STAGE_ITEMS: (35, 45),
    STAGE_PRODUCTS: (45, 85),
    STAGE_VALIDATION: (85, 95),
    STAGE_CONFERENCE: (95, 100),
}

STAGE_LABELS = {
    STAGE_CONFIGURATION: "Validando configuracao",
    STAGE_CONNECTION: "Conectando ao Nomus",
    STAGE_SEARCH: "Localizando a proposta",
    STAGE_ITEMS: "Carregando os itens",
    STAGE_PRODUCTS: "Consultando produtos e pesos",
    STAGE_VALIDATION: "Validando e organizando os dados",
    STAGE_CONFERENCE: "Preparando a conferencia",
}

ProgressCallback = Callable[["NomusImportProgressEvent"], None]


@dataclass(frozen=True)
class NomusImportProgressEvent:
    stage: str
    message: str
    percent: int | None = None
    detail: str = ""
    processed_products: int = 0
    total_products: int = 0
    indeterminate: bool = False
    warning: bool = False


def progress_percent_for_products(processed: int, total: int) -> int:
    start, end = PROGRESS_RANGES[STAGE_PRODUCTS]
    if total <= 0:
        return end
    processed = max(0, min(int(processed), int(total)))
    return start + int((processed / total) * (end - start))


def emit_progress(callback: ProgressCallback | None, event: NomusImportProgressEvent) -> None:
    if callback is None:
        return
    callback(event)
