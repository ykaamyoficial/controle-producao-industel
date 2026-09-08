from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from .confidence import calculate_field_confidences, calculate_overall_confidence
from .normalizers import (
    NormalizationError,
    normalize_date,
    normalize_decimal,
    normalize_description,
    normalize_identifier,
    normalize_integer,
    normalize_optional_text,
)
from .schemas import (
    ImportedProposalData,
    ImportedProposalItem,
    ProposalImportIssue,
    ProposalImportMetadata,
    ProposalImportResult,
    StandardProposalImportResult,
)
from .validators import validate_standard_result


def attach_standard_result(
    result: ProposalImportResult,
    *,
    extraction_method: str = "hybrid_rule_parser",
    used_fallback: bool = False,
    technical_metadata: dict[str, object] | None = None,
    fallback_reasons: list[str] | None = None,
    template_metadata: dict[str, object] | None = None,
    table_metadata: dict[str, object] | None = None,
    pipeline_diagnostics: dict[str, object] | None = None,
    diagnostic_summary: dict[str, object] | None = None,
    field_provenance: list[dict[str, object]] | None = None,
    item_field_provenance: list[dict[str, object]] | None = None,
) -> ProposalImportResult:
    return replace(
        result,
        standard_result=standardize_result(
            result,
            extraction_method=extraction_method,
            used_fallback=used_fallback,
            technical_metadata=technical_metadata,
            fallback_reasons=fallback_reasons,
            template_metadata=template_metadata,
            table_metadata=table_metadata,
            pipeline_diagnostics=pipeline_diagnostics,
            diagnostic_summary=diagnostic_summary,
            field_provenance=field_provenance,
            item_field_provenance=item_field_provenance,
        ),
    )


def standardize_result(
    result: ProposalImportResult,
    *,
    extraction_method: str = "hybrid_rule_parser",
    used_fallback: bool = False,
    technical_metadata: dict[str, object] | None = None,
    fallback_reasons: list[str] | None = None,
    template_metadata: dict[str, object] | None = None,
    table_metadata: dict[str, object] | None = None,
    pipeline_diagnostics: dict[str, object] | None = None,
    diagnostic_summary: dict[str, object] | None = None,
    field_provenance: list[dict[str, object]] | None = None,
    item_field_provenance: list[dict[str, object]] | None = None,
) -> StandardProposalImportResult:
    normalization_issues: list[ProposalImportIssue] = []
    proposal = ImportedProposalData(
        proposal_number=normalize_identifier(result.proposal_number.value),
        raw_budget_number=normalize_optional_text(result.raw_budget_number.value),
        proposal_date=_safe_date("proposal_date", result.proposal_date.value, normalization_issues),
        client=normalize_optional_text(result.client.value),
        site=normalize_optional_text(result.site.value),
        deadline_days=_safe_int("delivery_deadline_days", result.delivery_deadline_days.value, normalization_issues),
        deadline_raw=normalize_optional_text(result.delivery_deadline_raw.value),
        purchase_order=None,
        lot=None,
        operational_notes=normalize_optional_text(result.operational_notes.value),
    )
    items = [
        ImportedProposalItem(
            item_number=_safe_int("item_number", item.item_number, normalization_issues, index=index),
            product_code=normalize_optional_text(item.product_code),
            description=normalize_description(item.description),
            quantity=_safe_decimal("quantity", item.quantity, normalization_issues, index=index),
            unit=normalize_optional_text(item.unit),
            ncm=normalize_optional_text(item.ncm),
            unit_weight=None,
            total_weight=_safe_decimal("weight_kg", item.weight_kg, normalization_issues, index=index),
            weight_needs_confirmation=item.weight_needs_confirmation,
            source_method="legacy_rule_item",
        )
        for index, item in enumerate(result.items)
    ]
    metadata = ProposalImportMetadata(
        source=result.source,
        extraction_method=extraction_method,
        template_id=str(template_metadata.get("template_id")) if template_metadata and template_metadata.get("template_id") else None,
        template_version=str(template_metadata.get("template_version")) if template_metadata and template_metadata.get("template_version") else None,
        template_detection_score=str(template_metadata.get("template_detection_score")) if template_metadata and template_metadata.get("template_detection_score") is not None else None,
        template_detection_status=str(template_metadata.get("template_detection_status")) if template_metadata and template_metadata.get("template_detection_status") else None,
        template_candidates=list(template_metadata.get("template_candidates") or []) if template_metadata else [],
        template_warnings=list(template_metadata.get("template_warnings") or []) if template_metadata else [],
        table_extraction_method=str(table_metadata.get("table_extraction_method")) if table_metadata and table_metadata.get("table_extraction_method") else None,
        table_extraction_confidence=str(table_metadata.get("table_extraction_confidence")) if table_metadata and table_metadata.get("table_extraction_confidence") is not None else None,
        table_pages_processed=list(table_metadata.get("table_pages_processed") or []) if table_metadata else [],
        table_rows_detected=int(table_metadata.get("table_rows_detected") or 0) if table_metadata else 0,
        table_items_detected=int(table_metadata.get("table_items_detected") or 0) if table_metadata else 0,
        table_warnings=list(table_metadata.get("table_warnings") or []) if table_metadata else [],
        table_fallback_reasons=list(table_metadata.get("table_fallback_reasons") or []) if table_metadata else [],
        table_comparison_summary=dict(table_metadata.get("table_comparison_summary") or {}) if table_metadata else {},
        pipeline_diagnostics=dict(pipeline_diagnostics or {}),
        diagnostic_summary=dict(diagnostic_summary or {}),
        field_provenance=list(field_provenance or []),
        item_field_provenance=list(item_field_provenance or []),
        requires_human_review=result.requires_human_review,
        technical_metadata=dict(technical_metadata or {}),
        fallback_reasons=list(fallback_reasons or []),
    )
    warning_issues = [
        ProposalImportIssue(
            field_name="import",
            code=warning.code,
            message=warning.message,
            severity=warning.severity,
        )
        for warning in result.warnings
    ]
    placeholder = StandardProposalImportResult(
        proposal=proposal,
        items=items,
        field_confidences={},
        overall_confidence=Decimal("0.00"),
        warnings=[],
        errors=[],
        metadata=metadata,
    )
    validation_warnings, validation_errors = validate_standard_result(placeholder)
    all_warnings = warning_issues + normalization_issues + validation_warnings
    all_errors = validation_errors
    with_confidences = replace(
        placeholder,
        warnings=all_warnings,
        errors=all_errors,
    )
    confidences = calculate_field_confidences(result, with_confidences, used_fallback=used_fallback)
    with_scores = replace(with_confidences, field_confidences=confidences)
    overall = calculate_overall_confidence(with_scores, all_warnings + all_errors)
    return replace(with_scores, overall_confidence=overall)


def _safe_decimal(
    field_name: str,
    value: object,
    issues: list[ProposalImportIssue],
    *,
    index: int | None = None,
) -> Decimal | None:
    try:
        return normalize_decimal(value)
    except NormalizationError as exc:
        issues.append(ProposalImportIssue(field_name, "normalization_error", str(exc), "warning", index))
        return None


def _safe_int(
    field_name: str,
    value: object,
    issues: list[ProposalImportIssue],
    *,
    index: int | None = None,
) -> int | None:
    try:
        return normalize_integer(value)
    except NormalizationError as exc:
        issues.append(ProposalImportIssue(field_name, "normalization_error", str(exc), "warning", index))
        return None


def _safe_date(
    field_name: str,
    value: object,
    issues: list[ProposalImportIssue],
) -> object:
    try:
        return normalize_date(value)
    except NormalizationError as exc:
        issues.append(ProposalImportIssue(field_name, "normalization_error", str(exc), "warning"))
        return None
