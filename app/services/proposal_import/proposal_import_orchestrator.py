from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .nomus_rule_parser import FORBIDDEN_FINANCIAL_TERMS, _money_free, parse_nomus_text
from .pdf_text_extractor import extract_pdf_text
from .proposal_ai_extractor import ProposalAIExtractor
from .schemas import ProposalImportField, ProposalImportResult, ProposalImportWarning


_FORBIDDEN_KEY_RE = re.compile(
    r"price|preco|preço|value|valor|amount|subtotal|total|tax|imposto|icms|ipi|difal|discount|payment|frete|currency",
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
            )
        )
    if _contains_financial_content(result.to_dict()):
        warnings.append(
            ProposalImportWarning(
                "financial_content_blocked",
                "Conteudo financeiro detectado e bloqueado antes da conferencia.",
                "critical",
            )
        )
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
        items=result.items,
        warnings=warnings,
        requires_human_review=True,
    )


def import_nomus_from_text(text: str, ai_extractor: ProposalAIExtractor | None = None) -> ProposalImportResult:
    rule_result = parse_nomus_text(text)
    ai_data: dict[str, Any] = {}
    if ai_extractor is not None:
        ai_data = ai_extractor.extract(_sanitize_text_for_ai(text)) or {}
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
    return _add_safety_warnings(merged, ai_data)


def import_nomus_pdf(path: str | Path, ai_extractor: ProposalAIExtractor | None = None) -> ProposalImportResult:
    extraction = extract_pdf_text(path)
    return import_nomus_from_text(extraction.text, ai_extractor=ai_extractor)
