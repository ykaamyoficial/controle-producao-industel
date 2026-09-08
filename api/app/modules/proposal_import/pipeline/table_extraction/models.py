from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..schemas import ProposalImportItem


TABLE_CONFIDENCE_HIGH = Decimal("0.90")
TABLE_CONFIDENCE_GOOD = Decimal("0.82")
TABLE_CONFIDENCE_USABLE = Decimal("0.72")
TABLE_CONFIDENCE_LOW = Decimal("0.60")

FINANCIAL_HEADER_TERMS = (
    "VALOR",
    "PRECO",
    "PREÇO",
    "UNITARIO",
    "UNITÁRIO",
    "TOTAL FINANCEIRO",
    "DESCONTO",
    "SUBTOTAL",
    "TRIBUTO",
    "IMPOSTO",
    "ICMS",
    "IPI",
    "R$",
)

FINANCIAL_TEXT_TERMS = (
    "R$",
    "VALOR UNITARIO",
    "VALOR UNITÁRIO",
    "VALOR TOTAL",
    "PRECO UNITARIO",
    "PREÇO UNITÁRIO",
    "DESCONTO",
    "SUBTOTAL",
    "CONDICAO DE PAGAMENTO",
    "CONDIÇÃO DE PAGAMENTO",
    "ICMS",
    "IPI",
)


class TableExtractionError(ValueError):
    pass


class TableHeaderNotFoundError(TableExtractionError):
    pass


class TableRegionNotFoundError(TableExtractionError):
    pass


class TableColumnMappingError(TableExtractionError):
    pass


class TableRowReconstructionError(TableExtractionError):
    pass


class AmbiguousTableResultError(TableExtractionError):
    pass


@dataclass(frozen=True)
class ExtractedCell:
    column_name: str
    raw_text: str
    page_number: int
    bbox: tuple[float, float, float, float] | None
    extraction_method: str
    confidence: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "column_name": self.column_name,
            "raw_text": self.raw_text,
            "page_number": self.page_number,
            "bbox": list(self.bbox) if self.bbox else None,
            "extraction_method": self.extraction_method,
            "confidence": str(_round(self.confidence)),
        }


@dataclass
class ExtractedTableRow:
    row_index: int
    page_number: int
    cells: dict[str, ExtractedCell]
    raw_text: str
    confidence: Decimal
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_index": self.row_index,
            "page_number": self.page_number,
            "cells": {key: value.to_dict() for key, value in self.cells.items()},
            "raw_text": self.raw_text,
            "confidence": str(_round(self.confidence)),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class TableHeaderDetection:
    page_number: int | None
    bbox: tuple[float, float, float, float] | None
    recognized_columns: dict[str, str]
    missing_required: list[str]
    confidence: Decimal
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "bbox": list(self.bbox) if self.bbox else None,
            "recognized_columns": dict(self.recognized_columns),
            "missing_required": list(self.missing_required),
            "confidence": str(_round(self.confidence)),
            "warnings": list(self.warnings),
        }


@dataclass
class TableExtractionResult:
    items: list[ProposalImportItem]
    method: str
    confidence: Decimal
    rows: list[ExtractedTableRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pages_processed: list[int] = field(default_factory=list)
    header: TableHeaderDetection | None = None
    elapsed_seconds: float = 0.0

    @property
    def item_count(self) -> int:
        return len(self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "confidence": str(_round(self.confidence)),
            "items": [item.to_dict() for item in self.items],
            "rows": [row.to_dict() for row in self.rows],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "pages_processed": list(self.pages_processed),
            "header": self.header.to_dict() if self.header else None,
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass(frozen=True)
class TableComparisonItem:
    item_number: int | None
    status: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_number": self.item_number,
            "status": self.status,
            "details": list(self.details),
        }


@dataclass(frozen=True)
class TableMergeResult:
    items: list[ProposalImportItem]
    warnings: list[str]
    comparison_summary: dict[str, Any]
    selected_method: str
    selected_confidence: Decimal
    fallback_reasons: list[str] = field(default_factory=list)


def empty_table_result(method: str, warning: str | None = None, error: str | None = None) -> TableExtractionResult:
    return TableExtractionResult(
        items=[],
        method=method,
        confidence=Decimal("0.00"),
        warnings=[warning] if warning else [],
        errors=[error] if error else [],
    )


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
