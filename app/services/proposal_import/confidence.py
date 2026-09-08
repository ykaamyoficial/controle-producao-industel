from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .schemas import FieldConfidence, ProposalImportField, ProposalImportIssue, ProposalImportResult, StandardProposalImportResult


_ZERO = Decimal("0.00")
_ONE = Decimal("1.00")


def confidence_from_field(
    field_name: str,
    field: ProposalImportField,
    *,
    required: bool = False,
    used_fallback: bool = False,
) -> FieldConfidence:
    if field.value in (None, ""):
        score = Decimal("0.00") if required else Decimal("0.50")
        reason = "campo ausente" if required else "campo opcional ausente"
    else:
        score = _clamp(Decimal(str(field.confidence)))
        reason = f"extraido por {field.source}"
    if field.needs_confirmation:
        score = min(score, Decimal("0.60"))
        reason = f"{reason}; precisa confirmacao"
    if used_fallback:
        score = min(score, Decimal("0.75"))
        reason = f"{reason}; fallback usado"
    return FieldConfidence(
        field_name=field_name,
        score=_round(score),
        reason=reason,
        source_method=field.source,
        used_fallback=used_fallback,
    )


def calculate_field_confidences(
    legacy_result: ProposalImportResult,
    standard: StandardProposalImportResult,
    *,
    used_fallback: bool = False,
) -> dict[str, FieldConfidence]:
    confidences = {
        "proposal_number": confidence_from_field("proposal_number", legacy_result.proposal_number, required=True, used_fallback=used_fallback),
        "client": confidence_from_field("client", legacy_result.client, required=True, used_fallback=used_fallback),
        "site": confidence_from_field("site", legacy_result.site, used_fallback=used_fallback),
        "proposal_date": confidence_from_field("proposal_date", legacy_result.proposal_date, used_fallback=used_fallback),
        "deadline": confidence_from_field("deadline", legacy_result.delivery_deadline_raw, used_fallback=used_fallback),
        "items": _items_confidence(standard, used_fallback=used_fallback),
        "weights": _weights_confidence(standard, used_fallback=used_fallback),
    }
    return confidences


def calculate_overall_confidence(
    standard: StandardProposalImportResult,
    issues: list[ProposalImportIssue],
) -> Decimal:
    weights = {
        "proposal_number": Decimal("4"),
        "client": Decimal("4"),
        "site": Decimal("2"),
        "proposal_date": Decimal("2"),
        "deadline": Decimal("2"),
        "items": Decimal("4"),
        "weights": Decimal("1"),
    }
    total_weight = sum(weights.values(), Decimal("0"))
    weighted = Decimal("0")
    for field_name, weight in weights.items():
        confidence = standard.field_confidences.get(field_name)
        weighted += (confidence.score if confidence else Decimal("0.50")) * weight
    score = weighted / total_weight if total_weight else Decimal("0")
    if any(issue.severity == "error" for issue in issues):
        score -= Decimal("0.25")
    warning_count = sum(1 for issue in issues if issue.severity != "error")
    score -= min(Decimal("0.15"), Decimal(warning_count) * Decimal("0.01"))
    return _round(_clamp(score))


def _items_confidence(standard: StandardProposalImportResult, *, used_fallback: bool) -> FieldConfidence:
    if not standard.items:
        score = Decimal("0.00")
        reason = "nenhum item extraido"
    else:
        valid = sum(1 for item in standard.items if item.description and item.quantity and item.quantity > 0)
        score = Decimal(valid) / Decimal(len(standard.items))
        reason = "itens extraidos e normalizados"
    if used_fallback:
        score = min(score, Decimal("0.75"))
        reason = f"{reason}; fallback usado"
    return FieldConfidence("items", _round(score), reason, source_method="standardizer", used_fallback=used_fallback)


def _weights_confidence(standard: StandardProposalImportResult, *, used_fallback: bool) -> FieldConfidence:
    if not standard.items:
        score = Decimal("0.00")
        reason = "sem itens para avaliar peso"
    else:
        with_weight = sum(1 for item in standard.items if item.total_weight is not None or item.unit_weight is not None)
        score = Decimal("0.95") if with_weight == len(standard.items) else Decimal("0.55")
        reason = "pesos identificados" if with_weight else "pesos ausentes permitidos"
    if used_fallback:
        score = min(score, Decimal("0.75"))
        reason = f"{reason}; fallback usado"
    return FieldConfidence("weights", _round(score), reason, source_method="standardizer", used_fallback=used_fallback)


def _clamp(value: Decimal) -> Decimal:
    return max(_ZERO, min(_ONE, value))


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
