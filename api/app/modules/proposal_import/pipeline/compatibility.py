from __future__ import annotations

from decimal import Decimal
from typing import Any

from .schemas import StandardProposalImportResult


def to_current_payload(result: StandardProposalImportResult) -> dict[str, Any]:
    proposal = result.proposal
    confidences = result.field_confidences

    def field(name: str, value: Any, needs_confirmation: bool = False) -> dict[str, Any]:
        confidence = confidences.get(name)
        return {
            "value": _legacy_value(value),
            "confidence": float(confidence.score) if confidence else 0.5,
            "needs_confirmation": needs_confirmation,
            "source": confidence.source_method if confidence and confidence.source_method else "standardized",
        }

    return {
        "source": result.metadata.source if result.metadata else "nomus_pdf",
        "proposal_number": field("proposal_number", proposal.proposal_number),
        "raw_budget_number": field("proposal_number", proposal.raw_budget_number),
        "proposal_date": field("proposal_date", proposal.proposal_date),
        "client": field("client", proposal.client),
        "client_document": field("client_document", None),
        "buyer_name": field("buyer_name", None),
        "buyer_email": field("buyer_email", None),
        "buyer_phone": field("buyer_phone", None),
        "site": field("site", proposal.site, proposal.site is None),
        "delivery_deadline_days": field("deadline", proposal.deadline_days, proposal.deadline_raw is not None),
        "delivery_deadline_raw": field("deadline", proposal.deadline_raw, proposal.deadline_raw is not None),
        "budget_validity": field("budget_validity", None),
        "operational_notes": field("operational_notes", proposal.operational_notes),
        "items": [
            {
                "item_number": item.item_number,
                "product_code": item.product_code,
                "description": item.description,
                "unit": item.unit,
                "quantity": int(item.quantity) if item.quantity is not None and item.quantity == item.quantity.to_integral_value() else _legacy_value(item.quantity),
                "ncm": item.ncm,
                "weight_kg": _legacy_value(item.total_weight),
                "weight_extracted_from_text": item.total_weight is not None,
                "weight_needs_confirmation": item.weight_needs_confirmation,
                "raw_text": item.description,
                "confidence": 0.75,
                "weight_confidence": 0.95 if item.total_weight is not None else 0.0,
                "needs_confirmation": item.weight_needs_confirmation,
            }
            for item in result.items
        ],
        "warnings": [warning.to_dict() for warning in result.warnings],
        "requires_human_review": result.metadata.requires_human_review if result.metadata else True,
    }


def _legacy_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
