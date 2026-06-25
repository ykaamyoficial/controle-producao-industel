from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


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
