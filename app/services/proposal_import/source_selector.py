from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from .normalizers import NormalizationError, normalize_decimal, normalize_identifier, normalize_optional_text
from .provenance import FieldCandidate, FieldProvenance, ItemFieldProvenance
from .schemas import ProposalImportField, ProposalImportItem, ProposalImportResult, ProposalImportWarning
from .table_extraction.models import TableExtractionResult, TableMergeResult
from .templates.models import TemplateExtractionResult, TemplateFieldResult


MIN_REPLACEMENT_DELTA = Decimal("0.12")


def apply_header_source_selection(
    current_result: ProposalImportResult,
    template_result: TemplateExtractionResult | None,
) -> tuple[ProposalImportResult, list[str], list[FieldProvenance]]:
    if template_result is None:
        return current_result, [], [
            _single_source(field_name, getattr(current_result, result_attr), "rule_parser")
            for field_name, result_attr in _HEADER_MAPPING.items()
        ]
    replacements: dict[str, ProposalImportField] = {}
    warnings = list(current_result.warnings)
    messages: list[str] = []
    provenance: list[FieldProvenance] = []
    for template_field_name, result_attr in _HEADER_MAPPING.items():
        current_field: ProposalImportField = getattr(current_result, result_attr)
        template_field = template_result.fields.get(template_field_name)
        candidates = [_candidate_from_import_field(template_field_name, current_field)]
        if template_field:
            candidates.append(_candidate_from_template(template_field))
        selected, field_provenance, message = select_field_candidate(
            template_field_name,
            candidates,
            preferred_source=current_field.source or "rule_parser",
        )
        provenance.append(field_provenance)
        if selected.source.startswith("template") and not _same_value(selected.value, current_field.value):
            replacements[result_attr] = ProposalImportField(
                value=selected.value,
                confidence=float(selected.confidence),
                needs_confirmation=selected.needs_confirmation,
                source=selected.source,
            )
        elif field_provenance.agreement and current_field.value not in (None, ""):
            replacements[result_attr] = replace(
                current_field,
                confidence=max(float(current_field.confidence), float(selected.confidence)),
            )
        if message:
            messages.append(message)
        if field_provenance.conflict:
            warnings.append(
                ProposalImportWarning(
                    "HEADER_SOURCE_CONFLICT",
                    f"Conflito no campo {template_field_name}; valor do parser atual foi preservado para conferencia.",
                    "warning",
                )
            )
    if not replacements and not messages:
        return current_result, [], provenance
    return (
        replace(
            current_result,
            proposal_number=replacements.get("proposal_number", current_result.proposal_number),
            raw_budget_number=replacements.get("raw_budget_number", current_result.raw_budget_number),
            proposal_date=replacements.get("proposal_date", current_result.proposal_date),
            client=replacements.get("client", current_result.client),
            site=replacements.get("site", current_result.site),
            delivery_deadline_raw=replacements.get("delivery_deadline_raw", current_result.delivery_deadline_raw),
            warnings=warnings,
        ),
        messages,
        provenance,
    )


def select_field_candidate(
    field_name: str,
    candidates: list[FieldCandidate],
    *,
    preferred_source: str,
) -> tuple[FieldCandidate, FieldProvenance, str | None]:
    valid_candidates = [candidate for candidate in candidates if candidate.valid and candidate.value not in (None, "")]
    if not valid_candidates:
        selected = candidates[0] if candidates else FieldCandidate(field_name, None, preferred_source, Decimal("0"))
        return selected, FieldProvenance(field_name, selected.source, [c.source for c in candidates], selected.confidence, reason="sem candidato valido"), None
    preferred = next((candidate for candidate in valid_candidates if candidate.source == preferred_source), valid_candidates[0])
    equivalent = [candidate for candidate in valid_candidates if _same_value(candidate.value, preferred.value)]
    if len(equivalent) > 1:
        selected_confidence = min(Decimal("1.00"), max(candidate.confidence for candidate in equivalent) + Decimal("0.04"))
        selected = replace(preferred, confidence=selected_confidence)
        return (
            selected,
            FieldProvenance(
                field_name,
                selected.source,
                [candidate.source for candidate in equivalent],
                selected_confidence,
                agreement=True,
                reason="fontes concordam apos normalizacao",
            ),
            f"{field_name}: fontes concordam",
        )
    best = max(valid_candidates, key=lambda candidate: (_source_score(candidate), candidate.confidence))
    if not _same_value(best.value, preferred.value):
        if best.confidence - preferred.confidence >= MIN_REPLACEMENT_DELTA and _source_score(best) >= _source_score(preferred):
            return (
                best,
                FieldProvenance(
                    field_name,
                    best.source,
                    [candidate.source for candidate in valid_candidates],
                    best.confidence,
                    conflict=True,
                    reason="fonte secundaria venceu por validade e margem de confianca",
                ),
                f"{field_name}: {best.source} substituiu fonte preferida",
            )
        return (
            preferred,
            FieldProvenance(
                field_name,
                preferred.source,
                [candidate.source for candidate in valid_candidates],
                preferred.confidence,
                conflict=True,
                reason="conflito sem margem clara; comportamento atual preservado",
            ),
            f"{field_name}: conflito sem margem clara",
        )
    return (
        preferred,
        FieldProvenance(field_name, preferred.source, [candidate.source for candidate in valid_candidates], preferred.confidence, reason="fonte preferida preservada"),
        None,
    )


def build_item_field_provenance(
    original_items: list[ProposalImportItem],
    merged_items: list[ProposalImportItem],
    table_result: TableExtractionResult | None,
    table_merge: TableMergeResult | None,
) -> list[ItemFieldProvenance]:
    original_by_number = {item.item_number: item for item in original_items}
    table_by_number = {item.item_number: item for item in (table_result.items if table_result else [])}
    conflict_count = int((table_merge.comparison_summary.get("conflicts") if table_merge else 0) or 0)
    provenance: list[ItemFieldProvenance] = []
    fields = ("item_number", "product_code", "description", "quantity", "weight_kg")
    for item in merged_items:
        original = original_by_number.get(item.item_number)
        table_item = table_by_number.get(item.item_number)
        for field_name in fields:
            selected_source = "rule_parser"
            sources = ["rule_parser"] if original else []
            conflict = False
            reason = "valor preservado do parser atual" if original else "item adicionado"
            if table_item:
                sources.append(table_result.method if table_result else "structured_table")
                original_value = getattr(original, field_name, None) if original else None
                selected_value = getattr(item, field_name, None)
                table_value = getattr(table_item, field_name, None)
                if original_value in (None, "", 0) and table_value not in (None, "", 0):
                    selected_source = table_result.method if table_result else "structured_table"
                    reason = "campo complementado pela tabela estruturada"
                elif original_value is None and selected_value == table_value:
                    selected_source = table_result.method if table_result else "structured_table"
                    reason = "campo veio da tabela estruturada"
                elif table_value not in (None, "") and not _same_value(original_value, table_value):
                    conflict = conflict_count > 0
                    reason = "conflito preservado para conferencia" if conflict else "fontes divergentes sem impacto"
            provenance.append(
                ItemFieldProvenance(
                    item_number=item.item_number,
                    field_name=field_name,
                    selected_source=selected_source,
                    candidate_sources=sources,
                    conflict=conflict,
                    reason=reason,
                )
            )
    return provenance


_HEADER_MAPPING = {
    "proposal_number": "proposal_number",
    "raw_budget_number": "raw_budget_number",
    "proposal_date": "proposal_date",
    "client": "client",
    "site": "site",
    "delivery_deadline_raw": "delivery_deadline_raw",
}


def _candidate_from_import_field(field_name: str, field: ProposalImportField) -> FieldCandidate:
    return FieldCandidate(
        field_name=field_name,
        value=field.value,
        source=field.source or "rule_parser",
        confidence=Decimal(str(field.confidence)),
        valid=field.value not in (None, ""),
        deterministic=not str(field.source).startswith("ai"),
        needs_confirmation=field.needs_confirmation,
        reason="resultado do parser atual",
    )


def _candidate_from_template(field: TemplateFieldResult) -> FieldCandidate:
    return FieldCandidate(
        field_name=field.field_name,
        value=field.normalized_value,
        source=f"template:{field.extraction_strategy}",
        confidence=field.confidence,
        valid=field.normalized_value not in (None, ""),
        deterministic=True,
        needs_confirmation=bool(field.warnings) or field.confidence < Decimal("0.90"),
        reason=field.reason,
    )


def _single_source(field_name: str, field: ProposalImportField, source: str) -> FieldProvenance:
    return FieldProvenance(
        field_name=field_name,
        selected_source=field.source or source,
        candidate_sources=[field.source or source],
        selected_confidence=Decimal(str(field.confidence)),
        reason="fonte unica",
    )


def _source_score(candidate: FieldCandidate) -> tuple[int, int]:
    deterministic = 1 if candidate.deterministic else 0
    preferred_method = 1 if candidate.source.startswith(("template", "rule", "table")) else 0
    return deterministic, preferred_method


def _same_value(first: object, second: object) -> bool:
    if first in (None, "") or second in (None, ""):
        return first == second
    first_norm = _normalize_for_compare(first)
    second_norm = _normalize_for_compare(second)
    return first_norm == second_norm


def _normalize_for_compare(value: object) -> str:
    try:
        decimal = normalize_decimal(value)
    except NormalizationError:
        decimal = None
    if decimal is not None:
        return f"decimal:{decimal.normalize()}"
    text = normalize_optional_text(value) or ""
    identifier = normalize_identifier(text)
    if identifier:
        return re_identifier(identifier)
    return re_identifier(" ".join(text.upper().split()))


def re_identifier(value: str) -> str:
    normalized = value.upper().strip()
    normalized = " ".join(normalized.split())
    compact = normalized.replace(" ", "")
    if compact.startswith(("CP", "ETCP")) and compact[2:].isdigit():
        return compact
    return normalized
