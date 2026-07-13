from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class ProposalImportField:
    value: Any
    confidence: float
    needs_confirmation: bool = False
    source: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(float(self.confidence), 3),
            "needs_confirmation": bool(self.needs_confirmation),
            "source": self.source,
        }


@dataclass(frozen=True)
class ProposalImportWarning:
    code: str
    message: str
    severity: str = "warning"
    field_name: str | None = None
    item_index: int | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "field_name": self.field_name,
            "item_index": self.item_index,
            "source": self.source,
        }


@dataclass(frozen=True)
class ProposalImportIssue:
    field_name: str
    code: str
    message: str
    severity: str = "warning"
    item_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "item_index": self.item_index,
        }


@dataclass(frozen=True)
class FieldConfidence:
    field_name: str
    score: Decimal
    reason: str
    source_method: str | None = None
    used_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "score": _json_safe(self.score),
            "reason": self.reason,
            "source_method": self.source_method,
            "used_fallback": self.used_fallback,
        }


@dataclass(frozen=True)
class ImportedProposalData:
    proposal_number: str | None
    raw_budget_number: str | None = None
    proposal_date: date | None = None
    client: str | None = None
    site: str | None = None
    deadline_days: int | None = None
    deadline_raw: str | None = None
    purchase_order: str | None = None
    lot: str | None = None
    operational_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_number": self.proposal_number,
            "raw_budget_number": self.raw_budget_number,
            "proposal_date": _json_safe(self.proposal_date),
            "client": self.client,
            "site": self.site,
            "deadline_days": self.deadline_days,
            "deadline_raw": self.deadline_raw,
            "purchase_order": self.purchase_order,
            "lot": self.lot,
            "operational_notes": self.operational_notes,
        }


@dataclass(frozen=True)
class ImportedProposalItem:
    item_number: int | None
    product_code: str | None
    description: str
    quantity: Decimal | None
    unit: str | None = None
    ncm: str | None = None
    unit_weight: Decimal | None = None
    total_weight: Decimal | None = None
    weight_needs_confirmation: bool = False
    source_method: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_number": self.item_number,
            "product_code": self.product_code,
            "description": self.description,
            "quantity": _json_safe(self.quantity),
            "unit": self.unit,
            "ncm": self.ncm,
            "unit_weight": _json_safe(self.unit_weight),
            "total_weight": _json_safe(self.total_weight),
            "weight_needs_confirmation": self.weight_needs_confirmation,
            "source_method": self.source_method,
        }


@dataclass(frozen=True)
class ProposalImportMetadata:
    source: str
    extraction_method: str
    template_id: str | None = None
    template_version: str | None = None
    template_detection_score: str | None = None
    template_detection_status: str | None = None
    template_candidates: list[dict[str, Any]] = field(default_factory=list)
    template_warnings: list[str] = field(default_factory=list)
    table_extraction_method: str | None = None
    table_extraction_confidence: str | None = None
    table_pages_processed: list[int] = field(default_factory=list)
    table_rows_detected: int = 0
    table_items_detected: int = 0
    table_warnings: list[str] = field(default_factory=list)
    table_fallback_reasons: list[str] = field(default_factory=list)
    table_comparison_summary: dict[str, Any] = field(default_factory=dict)
    pipeline_diagnostics: dict[str, Any] = field(default_factory=dict)
    diagnostic_summary: dict[str, Any] = field(default_factory=dict)
    field_provenance: list[dict[str, Any]] = field(default_factory=list)
    item_field_provenance: list[dict[str, Any]] = field(default_factory=list)
    parser_version: str = "phase2-standardized"
    requires_human_review: bool = True
    technical_metadata: dict[str, Any] = field(default_factory=dict)
    fallback_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "extraction_method": self.extraction_method,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_detection_score": self.template_detection_score,
            "template_detection_status": self.template_detection_status,
            "template_candidates": _json_safe(self.template_candidates),
            "template_warnings": list(self.template_warnings),
            "table_extraction_method": self.table_extraction_method,
            "table_extraction_confidence": self.table_extraction_confidence,
            "table_pages_processed": list(self.table_pages_processed),
            "table_rows_detected": self.table_rows_detected,
            "table_items_detected": self.table_items_detected,
            "table_warnings": list(self.table_warnings),
            "table_fallback_reasons": list(self.table_fallback_reasons),
            "table_comparison_summary": _json_safe(self.table_comparison_summary),
            "pipeline_diagnostics": _json_safe(self.pipeline_diagnostics),
            "diagnostic_summary": _json_safe(self.diagnostic_summary),
            "field_provenance": _json_safe(self.field_provenance),
            "item_field_provenance": _json_safe(self.item_field_provenance),
            "parser_version": self.parser_version,
            "requires_human_review": self.requires_human_review,
            "technical_metadata": _json_safe(self.technical_metadata),
            "fallback_reasons": list(self.fallback_reasons),
        }


@dataclass(frozen=True)
class StandardProposalImportResult:
    proposal: ImportedProposalData
    items: list[ImportedProposalItem]
    field_confidences: dict[str, FieldConfidence]
    overall_confidence: Decimal
    warnings: list[ProposalImportIssue] = field(default_factory=list)
    errors: list[ProposalImportIssue] = field(default_factory=list)
    metadata: ProposalImportMetadata | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "field_confidences": {
                key: confidence.to_dict()
                for key, confidence in self.field_confidences.items()
            },
            "overall_confidence": _json_safe(self.overall_confidence),
            "warnings": [warning.to_dict() for warning in self.warnings],
            "errors": [error.to_dict() for error in self.errors],
            "metadata": self.metadata.to_dict() if self.metadata else {},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def build_diagnostic_summary(self) -> dict[str, Any]:
        if not self.metadata:
            return {}
        return _json_safe(self.metadata.diagnostic_summary or self.metadata.pipeline_diagnostics)


@dataclass(frozen=True)
class ProposalImportItem:
    item_number: int
    product_code: str | None
    description: str
    unit: str | None
    quantity: int | None
    ncm: str | None
    weight_kg: float | None
    weight_extracted_from_text: bool
    weight_needs_confirmation: bool
    raw_text: str
    confidence: float = 0.75
    weight_confidence: float = 0.0
    needs_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_number": self.item_number,
            "product_code": self.product_code,
            "description": self.description,
            "unit": self.unit,
            "quantity": self.quantity,
            "ncm": self.ncm,
            "weight_kg": self.weight_kg,
            "weight_extracted_from_text": self.weight_extracted_from_text,
            "weight_needs_confirmation": self.weight_needs_confirmation,
            "raw_text": self.raw_text,
            "confidence": round(float(self.confidence), 3),
            "weight_confidence": round(float(self.weight_confidence), 3),
            "needs_confirmation": bool(self.needs_confirmation),
        }


@dataclass(frozen=True)
class ProposalImportResult:
    source: str
    proposal_number: ProposalImportField
    raw_budget_number: ProposalImportField
    proposal_date: ProposalImportField
    client: ProposalImportField
    client_document: ProposalImportField
    buyer_name: ProposalImportField
    buyer_email: ProposalImportField
    buyer_phone: ProposalImportField
    site: ProposalImportField
    delivery_deadline_days: ProposalImportField
    delivery_deadline_raw: ProposalImportField
    budget_validity: ProposalImportField
    operational_notes: ProposalImportField
    items: list[ProposalImportItem] = field(default_factory=list)
    warnings: list[ProposalImportWarning] = field(default_factory=list)
    requires_human_review: bool = True
    standard_result: StandardProposalImportResult | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "proposal_number": self.proposal_number.to_dict(),
            "raw_budget_number": self.raw_budget_number.to_dict(),
            "proposal_date": self.proposal_date.to_dict(),
            "client": self.client.to_dict(),
            "client_document": self.client_document.to_dict(),
            "buyer_name": self.buyer_name.to_dict(),
            "buyer_email": self.buyer_email.to_dict(),
            "buyer_phone": self.buyer_phone.to_dict(),
            "site": self.site.to_dict(),
            "delivery_deadline_days": self.delivery_deadline_days.to_dict(),
            "delivery_deadline_raw": self.delivery_deadline_raw.to_dict(),
            "budget_validity": self.budget_validity.to_dict(),
            "operational_notes": self.operational_notes.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "requires_human_review": self.requires_human_review,
        }
