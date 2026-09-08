from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


@dataclass(frozen=True)
class FieldCandidate:
    field_name: str
    value: Any
    source: str
    confidence: Decimal
    valid: bool = True
    deterministic: bool = True
    needs_confirmation: bool = False
    reason: str = ""


@dataclass(frozen=True)
class FieldProvenance:
    field_name: str
    selected_source: str
    candidate_sources: list[str]
    selected_confidence: Decimal
    conflict: bool = False
    agreement: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "selected_source": self.selected_source,
            "candidate_sources": list(self.candidate_sources),
            "selected_confidence": _json_decimal(self.selected_confidence),
            "conflict": self.conflict,
            "agreement": self.agreement,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ItemFieldProvenance:
    item_number: int | None
    field_name: str
    selected_source: str
    candidate_sources: list[str] = field(default_factory=list)
    conflict: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_number": self.item_number,
            "field_name": self.field_name,
            "selected_source": self.selected_source,
            "candidate_sources": list(self.candidate_sources),
            "conflict": self.conflict,
            "reason": self.reason,
        }


def _json_decimal(value: Decimal) -> str:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP).to_eng_string()
