from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..pymupdf_extractor import PdfRegion, PdfWord


SCORE_CONFIRMATION = Decimal("0.90")
SCORE_CANDIDATE = Decimal("0.75")
SCORE_AMBIGUITY_DELTA = Decimal("0.07")


class TemplateDetectionError(ValueError):
    pass


class TemplateNotFoundError(TemplateDetectionError):
    pass


class AmbiguousTemplateError(TemplateDetectionError):
    pass


class TemplateExtractionError(ValueError):
    pass


class InvalidTemplateConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class TemplateMarker:
    text: str
    required: bool
    weight: Decimal
    case_sensitive: bool = False
    page_number: int | None = None
    expected_region: "TemplateRegion | None" = None


@dataclass(frozen=True)
class TemplateRegion:
    page_number: int | None
    x0_ratio: Decimal
    y0_ratio: Decimal
    x1_ratio: Decimal
    y1_ratio: Decimal

    def __post_init__(self) -> None:
        values = (self.x0_ratio, self.y0_ratio, self.x1_ratio, self.y1_ratio)
        if any(value < Decimal("0") or value > Decimal("1") for value in values):
            raise InvalidTemplateConfigurationError("Regiao relativa deve estar entre 0 e 1.")
        if self.x1_ratio < self.x0_ratio or self.y1_ratio < self.y0_ratio:
            raise InvalidTemplateConfigurationError("Regiao relativa invalida.")

    def to_absolute(self, page_width: float, page_height: float) -> PdfRegion:
        return PdfRegion(
            float(self.x0_ratio) * page_width,
            float(self.y0_ratio) * page_height,
            float(self.x1_ratio) * page_width,
            float(self.y1_ratio) * page_height,
        )

    def contains_word(self, word: PdfWord, page_size: tuple[float, float] | None) -> bool:
        if self.page_number is not None and word.page_number != self.page_number:
            return False
        if not page_size:
            return True
        return self.to_absolute(*page_size).contains(word)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "x0_ratio": str(self.x0_ratio),
            "y0_ratio": str(self.y0_ratio),
            "x1_ratio": str(self.x1_ratio),
            "y1_ratio": str(self.y1_ratio),
        }


@dataclass(frozen=True)
class TemplateColumnDefinition:
    name: str
    aliases: tuple[str, ...] = ()
    required: bool = False
    x0_ratio: Decimal | None = None
    x1_ratio: Decimal | None = None
    data_type: str = "text"
    multiline: bool = False
    ignored: bool = False
    confidence_weight: Decimal = Decimal("1.00")


@dataclass(frozen=True)
class TemplateTableDefinition:
    start_markers: tuple[str, ...]
    end_markers: tuple[str, ...]
    columns: tuple[TemplateColumnDefinition, ...]
    expected_region: TemplateRegion | None = None
    can_span_pages: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_markers": list(self.start_markers),
            "end_markers": list(self.end_markers),
            "columns": [
                {"name": column.name, "aliases": list(column.aliases), "required": column.required}
                for column in self.columns
            ],
            "expected_region": self.expected_region.to_dict() if self.expected_region else None,
            "can_span_pages": self.can_span_pages,
        }


@dataclass(frozen=True)
class TemplateMatchResult:
    template_id: str
    template_version: str
    score: Decimal
    matched: bool
    matched_markers: list[str] = field(default_factory=list)
    missing_required_markers: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "template_version": self.template_version,
            "score": str(self.score),
            "matched": self.matched,
            "matched_markers": list(self.matched_markers),
            "missing_required_markers": list(self.missing_required_markers),
            "reasons": list(self.reasons),
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass(frozen=True)
class TemplateDetectionResult:
    selected_template_id: str | None
    selected_template_version: str | None
    confidence: Decimal
    ambiguous: bool
    candidates: list[TemplateMatchResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def status(self) -> str:
        if self.ambiguous:
            return "ambiguous"
        if self.selected_template_id and self.confidence >= SCORE_CONFIRMATION:
            return "confirmed"
        if self.selected_template_id and self.confidence >= SCORE_CANDIDATE:
            return "probable"
        return "not_found"

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_template_id": self.selected_template_id,
            "selected_template_version": self.selected_template_version,
            "confidence": str(self.confidence),
            "ambiguous": self.ambiguous,
            "status": self.status,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "reasons": list(self.reasons),
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass(frozen=True)
class TemplateFieldResult:
    field_name: str
    raw_value: str | None
    normalized_value: Any | None
    confidence: Decimal
    extraction_strategy: str
    source_page: int | None
    source_bbox: tuple[float, float, float, float] | None
    warnings: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value.isoformat() if hasattr(self.normalized_value, "isoformat") else self.normalized_value,
            "confidence": str(_round(self.confidence)),
            "extraction_strategy": self.extraction_strategy,
            "source_page": self.source_page,
            "source_bbox": list(self.source_bbox) if self.source_bbox else None,
            "warnings": list(self.warnings),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TemplateExtractionResult:
    template_id: str
    template_version: str
    fields: dict[str, TemplateFieldResult]
    table_region: TemplateRegion | None
    table_definition: TemplateTableDefinition | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "template_version": self.template_version,
            "fields": {key: value.to_dict() for key, value in self.fields.items()},
            "table_region": self.table_region.to_dict() if self.table_region else None,
            "table_definition": self.table_definition.to_dict() if self.table_definition else None,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "elapsed_seconds": self.elapsed_seconds,
        }


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
