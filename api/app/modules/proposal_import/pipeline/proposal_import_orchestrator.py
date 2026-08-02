from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from .diagnostics import ImportPipelineDiagnostics, ImportStage, ImportStageStatus, now_ms_since, sanitize_mapping, timed_call
from .nomus_rule_parser import FORBIDDEN_FINANCIAL_TERMS, _money_free, parse_nomus_text
from .pdf_text_extractor import PdfTextExtraction, extract_pdf_text
from .proposal_ai_extractor import ProposalAIExtractor
from .pymupdf_extractor import PdfExtractionError as PyMuPdfExtractionError
from .pymupdf_extractor import extract_pdf_context
from .schemas import ProposalImportField, ProposalImportResult, ProposalImportWarning
from .source_selector import apply_header_source_selection, build_item_field_provenance
from .standardizer import attach_standard_result
from .table_extraction.service import TableProcessingResult, extract_and_merge_table_items
from .templates.models import TemplateDetectionResult, TemplateExtractionResult
from .templates.registry import default_template_registry


logger = logging.getLogger(__name__)


_FORBIDDEN_KEY_RE = re.compile(
    r"price|preco|preÃ§o|value|valor|amount|subtotal|total|tax|imposto|icms|ipi|difal|discount|payment|frete|currency",
    re.IGNORECASE,
)


def _contains_financial_content(value: Any) -> bool:
    serialized = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    upper = serialized.upper()
    return any(term.upper() in upper for term in FORBIDDEN_FINANCIAL_TERMS) or "R$" in upper


def _sanitize_text_for_ai(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in (text or "").splitlines():
        upper = line.upper()
        if any(term.upper() in upper for term in FORBIDDEN_FINANCIAL_TERMS):
            continue
        cleaned = _money_free(line)
        if cleaned:
            cleaned_lines.append(cleaned)
    return "\n".join(cleaned_lines)


def _safe_ai_value(ai_data: dict[str, Any], key: str) -> Any:
    if any(_FORBIDDEN_KEY_RE.search(part) for part in key.split(".")):
        return None
    value = ai_data.get(key)
    if value is None or _contains_financial_content(value):
        return None
    return value


def _merge_field(rule_field: ProposalImportField, ai_data: dict[str, Any], ai_key: str) -> ProposalImportField:
    if rule_field.value not in (None, "") and not _contains_financial_content(rule_field.value):
        return rule_field
    ai_value = _safe_ai_value(ai_data, ai_key)
    if ai_value in (None, ""):
        return rule_field
    return ProposalImportField(value=ai_value, confidence=0.45, needs_confirmation=True, source="ai_fake")


def _add_safety_warnings(result: ProposalImportResult, ai_data: dict[str, Any] | None) -> ProposalImportResult:
    warnings = list(result.warnings)
    if ai_data and any(_FORBIDDEN_KEY_RE.search(str(key)) or _contains_financial_content(value) for key, value in ai_data.items()):
        warnings.append(
            ProposalImportWarning(
                "ai_financial_discarded",
                "Sugestoes com conteudo financeiro foram descartadas pela camada de seguranca.",
                "info",
                source="ai_fake",
            )
        )
    if _contains_financial_content(result.to_dict()):
        warnings.append(
            ProposalImportWarning(
                "financial_content_blocked",
                "Conteudo financeiro detectado e bloqueado antes da conferencia.",
                "critical",
                source="safety",
            )
        )
    return _clone_result(result, warnings=warnings)


def import_nomus_from_text(
    text: str,
    ai_extractor: ProposalAIExtractor | None = None,
    *,
    extraction_method: str = "plain_text",
    technical_metadata: dict[str, Any] | None = None,
    fallback_reasons: list[str] | None = None,
    template_detection: TemplateDetectionResult | None = None,
    template_extraction: TemplateExtractionResult | None = None,
    table_processing: TableProcessingResult | None = None,
    pipeline_diagnostics: ImportPipelineDiagnostics | None = None,
) -> ProposalImportResult:
    diagnostics = pipeline_diagnostics or ImportPipelineDiagnostics()
    rule_result, duration = timed_call(lambda: parse_nomus_text(text))
    diagnostics.add(
        ImportStage.TEXT_RULE_PARSER,
        status=ImportStageStatus.SUCCESS,
        method="nomus_rule_parser",
        duration_ms=duration,
        metadata={"items": len(rule_result.items), "warnings": len(rule_result.warnings)},
    )
    ai_data = ai_extractor.extract(_sanitize_text_for_ai(text)) or {} if ai_extractor else {}
    return _build_import_result(
        rule_result,
        ai_data,
        extraction_method=extraction_method,
        technical_metadata=technical_metadata,
        fallback_reasons=fallback_reasons,
        template_detection=template_detection,
        template_extraction=template_extraction,
        table_processing=table_processing,
        diagnostics=diagnostics,
    )


def import_nomus_pdf(path: str | Path, ai_extractor: ProposalAIExtractor | None = None) -> ProposalImportResult:
    total_start = time.perf_counter()
    diagnostics = ImportPipelineDiagnostics()
    fallback_reasons: list[str] = []
    technical_metadata: dict[str, Any] = {}
    extraction_method = "pdfplumber_text"
    template_detection: TemplateDetectionResult | None = None
    template_extraction: TemplateExtractionResult | None = None
    table_processing: TableProcessingResult | None = None
    context = None
    pdf_path = Path(path)

    validation_start = time.perf_counter()
    if not pdf_path.is_file():
        diagnostics.add(
            ImportStage.FILE_VALIDATION,
            status=ImportStageStatus.FAILED,
            method="pathlib",
            duration_ms=now_ms_since(validation_start),
            errors=[f"Arquivo PDF nao encontrado: {pdf_path.name}"],
        )
        raise ValueError(f"Arquivo PDF nao encontrado: {pdf_path.name}")
    diagnostics.add(
        ImportStage.FILE_VALIDATION,
        status=ImportStageStatus.SUCCESS,
        method="pathlib",
        duration_ms=now_ms_since(validation_start),
        metadata={"file_name": pdf_path.name, "file_size": pdf_path.stat().st_size},
    )

    try:
        context, duration = timed_call(lambda: extract_pdf_context(pdf_path))
        technical_metadata.update(context.metadata)
        extraction_method = "pymupdf_context_pdfplumber_text"
        diagnostics.add(
            ImportStage.PDF_STRUCTURE,
            status=ImportStageStatus.SUCCESS,
            method="PyMuPDF",
            duration_ms=duration,
            metadata={
                "page_count": context.page_count,
                "has_extractable_text": context.has_extractable_text,
                "text_detection_reason": context.text_detection.reason,
            },
        )
        template_detection, duration = timed_call(lambda: default_template_registry().detect(context))
        diagnostics.add(
            ImportStage.TEMPLATE_DETECTION,
            status=ImportStageStatus.SUCCESS if template_detection.selected_template_id else ImportStageStatus.WARNING,
            method="template_registry",
            duration_ms=duration,
            warnings=template_detection.reasons,
            metadata={
                "status": template_detection.status,
                "selected_template_id": template_detection.selected_template_id,
                "confidence": template_detection.confidence,
            },
        )
        template_extraction, duration = timed_call(lambda: _extract_template_header(context, template_detection))
        diagnostics.add(
            ImportStage.HEADER_EXTRACTION,
            status=ImportStageStatus.SUCCESS if template_extraction else ImportStageStatus.SKIPPED,
            method="template_header" if template_extraction else None,
            duration_ms=duration,
            warnings=template_extraction.warnings if template_extraction else [],
            errors=template_extraction.errors if template_extraction else [],
            metadata={"fields": len(template_extraction.fields) if template_extraction else 0},
        )
    except PyMuPdfExtractionError as exc:
        fallback_reasons.append(f"pymupdf: {exc}")
        diagnostics.add(
            ImportStage.PDF_STRUCTURE,
            status=ImportStageStatus.FAILED,
            method="PyMuPDF",
            errors=[str(exc)],
            fallback_used=True,
        )

    extraction = _extract_text_with_fallback(pdf_path, context, fallback_reasons, diagnostics)
    technical_metadata.update(
        {
            "parser_text_engine": "pdfplumber" if extraction.tables else "pdfplumber_or_pymupdf_text",
            "line_count": len(extraction.lines),
            "table_count": len(extraction.tables),
        }
    )

    rule_result, duration = timed_call(lambda: parse_nomus_text(extraction.text))
    diagnostics.add(
        ImportStage.TEXT_RULE_PARSER,
        status=ImportStageStatus.SUCCESS,
        method="nomus_rule_parser",
        duration_ms=duration,
        metadata={"items": len(rule_result.items), "warnings": len(rule_result.warnings)},
    )
    ai_data = ai_extractor.extract(_sanitize_text_for_ai(extraction.text)) or {} if ai_extractor else {}

    if template_extraction and template_extraction.table_definition:
        try:
            table_processing, duration = timed_call(
                lambda: extract_and_merge_table_items(pdf_path, context, template_extraction, rule_result.items)
            )
            metadata = table_processing.metadata()
            diagnostics.add(
                ImportStage.TABLE_EXTRACTION,
                status=ImportStageStatus.SUCCESS if not table_processing.extraction.errors else ImportStageStatus.WARNING,
                method=table_processing.extraction.method,
                duration_ms=duration,
                warnings=list(metadata.get("table_warnings", [])),
                errors=table_processing.extraction.errors,
                metadata=metadata,
                fallback_used=bool(table_processing.merge.fallback_reasons),
            )
        except Exception as exc:
            fallback_reasons.append(f"table_extraction: {exc}")
            diagnostics.add(
                ImportStage.TABLE_EXTRACTION,
                status=ImportStageStatus.FAILED,
                method="structured_table",
                errors=[str(exc)],
                fallback_used=True,
            )
    else:
        diagnostics.add(
            ImportStage.TABLE_EXTRACTION,
            status=ImportStageStatus.SKIPPED,
            warnings=["template sem definicao de tabela"] if template_extraction else ["template nao disponivel"],
        )

    diagnostics.total_duration_ms = now_ms_since(total_start)
    return _build_import_result(
        rule_result,
        ai_data,
        extraction_method=extraction_method,
        fallback_reasons=fallback_reasons,
        technical_metadata=technical_metadata,
        template_detection=template_detection,
        template_extraction=template_extraction,
        table_processing=table_processing,
        diagnostics=diagnostics,
    )


def _build_import_result(
    rule_result: ProposalImportResult,
    ai_data: dict[str, Any],
    *,
    extraction_method: str,
    technical_metadata: dict[str, Any] | None,
    fallback_reasons: list[str] | None,
    template_detection: TemplateDetectionResult | None,
    template_extraction: TemplateExtractionResult | None,
    table_processing: TableProcessingResult | None,
    diagnostics: ImportPipelineDiagnostics,
) -> ProposalImportResult:
    merge_start = time.perf_counter()
    merged = ProposalImportResult(
        source=rule_result.source,
        proposal_number=_merge_field(rule_result.proposal_number, ai_data, "proposal_number"),
        raw_budget_number=_merge_field(rule_result.raw_budget_number, ai_data, "raw_budget_number"),
        proposal_date=_merge_field(rule_result.proposal_date, ai_data, "proposal_date"),
        client=_merge_field(rule_result.client, ai_data, "client"),
        client_document=_merge_field(rule_result.client_document, ai_data, "client_document"),
        buyer_name=_merge_field(rule_result.buyer_name, ai_data, "buyer_name"),
        buyer_email=_merge_field(rule_result.buyer_email, ai_data, "buyer_email"),
        buyer_phone=_merge_field(rule_result.buyer_phone, ai_data, "buyer_phone"),
        site=_merge_field(rule_result.site, ai_data, "site"),
        delivery_deadline_days=rule_result.delivery_deadline_days,
        delivery_deadline_raw=rule_result.delivery_deadline_raw,
        budget_validity=_merge_field(rule_result.budget_validity, ai_data, "budget_validity"),
        operational_notes=_merge_field(rule_result.operational_notes, ai_data, "operational_notes"),
        items=rule_result.items,
        warnings=rule_result.warnings,
        requires_human_review=True,
    )
    header_merged, header_messages, header_provenance = apply_header_source_selection(merged, template_extraction)
    table_metadata: dict[str, Any] = {}
    item_provenance = build_item_field_provenance(header_merged.items, header_merged.items, None, None)
    final_result = header_merged
    if table_processing is not None:
        table_metadata = table_processing.metadata()
        item_provenance = build_item_field_provenance(
            header_merged.items,
            table_processing.merge.items,
            table_processing.extraction,
            table_processing.merge,
        )
        if table_processing.merge.items != header_merged.items or table_processing.merge.warnings:
            final_result = _clone_result(
                header_merged,
                items=table_processing.merge.items,
                warnings=list(header_merged.warnings)
                + [
                    ProposalImportWarning("table_extraction", warning, "info", source=table_processing.extraction.method)
                    for warning in table_processing.merge.warnings
                ],
            )
    if header_messages:
        logger.info("Selecao de fontes do cabecalho: %s", "; ".join(header_messages))
        final_result = _clone_result(
            final_result,
            warnings=list(final_result.warnings)
            + [
                ProposalImportWarning(
                    "HEADER_SOURCE_AGREEMENT" if "concordam" in warning else "HEADER_SOURCE_CONFLICT",
                    warning,
                    "info" if "concordam" in warning else "warning",
                    source="source_selector",
                )
                for warning in header_messages
                if "conflito" not in warning.lower() or "sem margem clara" not in warning.lower()
            ],
        )
    diagnostics.selected_template = template_detection.selected_template_id if template_detection else None
    diagnostics.selected_header_source = _dominant_source([item.to_dict() for item in header_provenance])
    diagnostics.selected_table_source = table_processing.extraction.method if table_processing else None
    diagnostics.fallback_used = bool(fallback_reasons)
    diagnostics.fallback_reasons = list(fallback_reasons or [])
    diagnostics.add(
        ImportStage.MERGE,
        status=ImportStageStatus.WARNING if header_messages or (table_processing and table_processing.merge.warnings) else ImportStageStatus.SUCCESS,
        method="source_selector",
        duration_ms=now_ms_since(merge_start),
        warnings=header_messages + (table_processing.merge.warnings if table_processing else []),
        metadata={
            "header_provenance_count": len(header_provenance),
            "item_provenance_count": len(item_provenance),
            "final_items": len(final_result.items),
        },
    )
    safe_result = _add_safety_warnings(final_result, ai_data)
    return _attach_standard_with_diagnostics(
        safe_result,
        extraction_method=extraction_method,
        fallback_reasons=fallback_reasons,
        technical_metadata=technical_metadata,
        template_detection=template_detection,
        template_extraction=template_extraction,
        table_metadata=table_metadata,
        diagnostics=diagnostics,
        header_provenance=[item.to_dict() for item in header_provenance],
        item_provenance=[item.to_dict() for item in item_provenance],
    )


def _attach_standard_with_diagnostics(
    result: ProposalImportResult,
    *,
    extraction_method: str,
    fallback_reasons: list[str] | None,
    technical_metadata: dict[str, Any] | None,
    template_detection: TemplateDetectionResult | None,
    template_extraction: TemplateExtractionResult | None,
    table_metadata: dict[str, Any],
    diagnostics: ImportPipelineDiagnostics,
    header_provenance: list[dict[str, Any]],
    item_provenance: list[dict[str, Any]],
) -> ProposalImportResult:
    start = time.perf_counter()
    first = attach_standard_result(
        result,
        extraction_method=extraction_method,
        used_fallback=bool(fallback_reasons),
        technical_metadata=sanitize_mapping(technical_metadata or {}),
        fallback_reasons=fallback_reasons,
        template_metadata=sanitize_mapping(_template_metadata(template_detection, template_extraction)),
        table_metadata=sanitize_mapping(table_metadata),
        pipeline_diagnostics=diagnostics.to_safe_dict(),
        diagnostic_summary=diagnostics.build_diagnostic_summary(),
        field_provenance=header_provenance,
        item_field_provenance=item_provenance,
    )
    standard = first.standard_result
    diagnostics.add(
        ImportStage.NORMALIZATION,
        status=ImportStageStatus.SUCCESS,
        method="standardizer",
        duration_ms=now_ms_since(start),
        metadata={"items": len(standard.items) if standard else 0},
    )
    diagnostics.add(
        ImportStage.VALIDATION,
        status=ImportStageStatus.FAILED if standard and standard.errors else ImportStageStatus.WARNING if standard and standard.warnings else ImportStageStatus.SUCCESS,
        method="validators",
        warnings=[issue.message for issue in (standard.warnings if standard else [])],
        errors=[issue.message for issue in (standard.errors if standard else [])],
        metadata={"warnings": len(standard.warnings) if standard else 0, "errors": len(standard.errors) if standard else 0},
    )
    diagnostics.add(
        ImportStage.CONFIDENCE,
        status=ImportStageStatus.SUCCESS,
        method="confidence",
        metadata={"overall_confidence": standard.overall_confidence if standard else None},
    )
    diagnostics.add(
        ImportStage.COMPATIBILITY,
        status=ImportStageStatus.SUCCESS,
        method="legacy_payload_contract",
        metadata={"legacy_keys": sorted(result.to_dict().keys())},
    )
    return attach_standard_result(
        result,
        extraction_method=extraction_method,
        used_fallback=bool(fallback_reasons),
        technical_metadata=sanitize_mapping(technical_metadata or {}),
        fallback_reasons=fallback_reasons,
        template_metadata=sanitize_mapping(_template_metadata(template_detection, template_extraction)),
        table_metadata=sanitize_mapping(table_metadata),
        pipeline_diagnostics=diagnostics.to_safe_dict(),
        diagnostic_summary=diagnostics.build_diagnostic_summary(),
        field_provenance=header_provenance,
        item_field_provenance=item_provenance,
    )


def _extract_text_with_fallback(
    pdf_path: Path,
    context,
    fallback_reasons: list[str],
    diagnostics: ImportPipelineDiagnostics,
) -> PdfTextExtraction:
    try:
        extraction, duration = timed_call(lambda: extract_pdf_text(pdf_path))
        diagnostics.add(
            ImportStage.TEXT_EXTRACTION,
            status=ImportStageStatus.SUCCESS,
            method="pdfplumber",
            duration_ms=duration,
            metadata={"line_count": len(extraction.lines), "table_count": len(extraction.tables)},
        )
        return extraction
    except Exception as exc:
        if context and context.full_text:
            fallback_reasons.append(f"pdfplumber_text: {exc}")
            lines = [" ".join(line.split()).strip() for line in context.full_text.splitlines() if line.strip()]
            diagnostics.add(
                ImportStage.TEXT_EXTRACTION,
                status=ImportStageStatus.WARNING,
                method="pymupdf_text_fallback",
                warnings=[str(exc)],
                metadata={"line_count": len(lines), "table_count": 0},
                fallback_used=True,
            )
            return PdfTextExtraction(text=context.full_text, lines=lines, tables=[])
        diagnostics.add(
            ImportStage.TEXT_EXTRACTION,
            status=ImportStageStatus.FAILED,
            method="pdfplumber",
            errors=[str(exc)],
        )
        raise


def _extract_template_header(context, detection: TemplateDetectionResult | None) -> TemplateExtractionResult | None:
    if not detection or not detection.selected_template_id or detection.ambiguous:
        return None
    template = default_template_registry().get(detection.selected_template_id, detection.selected_template_version)
    if template is None:
        return None
    return template.extract_header(context)


def _detect_and_extract_template(context) -> tuple[TemplateDetectionResult | None, TemplateExtractionResult | None]:
    registry = default_template_registry()
    detection = registry.detect(context)
    logger.info("Template detection status=%s score=%s", detection.status, detection.confidence)
    return detection, _extract_template_header(context, detection)


def _template_metadata(
    detection: TemplateDetectionResult | None,
    extraction: TemplateExtractionResult | None,
) -> dict[str, Any]:
    if detection is None:
        return {}
    warnings: list[str] = []
    if extraction:
        warnings.extend(extraction.warnings)
    warnings.extend(detection.reasons)
    return {
        "template_id": detection.selected_template_id,
        "template_version": detection.selected_template_version,
        "template_detection_score": str(detection.confidence),
        "template_detection_status": detection.status,
        "template_candidates": [candidate.to_dict() for candidate in detection.candidates],
        "template_warnings": warnings,
    }


def _clone_result(
    result: ProposalImportResult,
    *,
    items=None,
    warnings=None,
) -> ProposalImportResult:
    return ProposalImportResult(
        source=result.source,
        proposal_number=result.proposal_number,
        raw_budget_number=result.raw_budget_number,
        proposal_date=result.proposal_date,
        client=result.client,
        client_document=result.client_document,
        buyer_name=result.buyer_name,
        buyer_email=result.buyer_email,
        buyer_phone=result.buyer_phone,
        site=result.site,
        delivery_deadline_days=result.delivery_deadline_days,
        delivery_deadline_raw=result.delivery_deadline_raw,
        budget_validity=result.budget_validity,
        operational_notes=result.operational_notes,
        items=list(items if items is not None else result.items),
        warnings=list(warnings if warnings is not None else result.warnings),
        requires_human_review=result.requires_human_review,
    )


def _dominant_source(provenance: list[dict[str, Any]]) -> str | None:
    counts: dict[str, int] = {}
    for item in provenance:
        source = item.get("selected_source")
        if source:
            counts[str(source)] = counts.get(str(source), 0) + 1
    return max(counts.items(), key=lambda pair: pair[1])[0] if counts else None
