from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from ..pymupdf_extractor import PdfExtractionContext, PdfTextBlock, PdfWord
from ..schemas import ProposalImportField, ProposalImportResult, ProposalImportWarning
from .base import PdfTemplate
from .models import (
    SCORE_CANDIDATE,
    TemplateColumnDefinition,
    TemplateExtractionResult,
    TemplateFieldResult,
    TemplateMarker,
    TemplateMatchResult,
    TemplateRegion,
    TemplateTableDefinition,
)


_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_BUDGET_RE = re.compile(r"\b(?:OR[ÇC]AMENTO|ORCAMENTO)\s*:?\s*(ETCP\s*\d+)\b", re.IGNORECASE)
_PROPOSAL_RE = re.compile(r"\bPROPOSTA\s*:?\s*(CP\s*\d+)\b", re.IGNORECASE)
_DEADLINE_RE = re.compile(r"\b(\d+)\s+DIAS?\b", re.IGNORECASE)
_PO_RE = re.compile(r"\b(?:PEDIDO(?:\s+DE\s+COMPRA)?|ORDEM\s+DE\s+COMPRA|OC)\s*[:#-]\s*([A-Z0-9./-]+)", re.IGNORECASE)


class NomusCurrentTemplate(PdfTemplate):
    template_id = "nomus_current"
    name = "Nomus proposta/orcamento atual"
    version = "1.0"
    priority = 100
    header_region = TemplateRegion(None, Decimal("0.00"), Decimal("0.00"), Decimal("1.00"), Decimal("0.45"))
    table_definition = TemplateTableDefinition(
        start_markers=("ITEM", "DESCRICAO DO PRODUTO", "QTDE", "QTD"),
        end_markers=("TOTAL", "CONDICAO DE PAGAMENTO", "OBSERVACOES"),
        columns=(
            TemplateColumnDefinition(
                "item",
                ("ITEM", "N", "Nº", "NRO"),
                True,
                Decimal("0.00"),
                Decimal("0.09"),
                "integer",
                confidence_weight=Decimal("1.20"),
            ),
            TemplateColumnDefinition(
                "product_code",
                ("PRODUTO", "COD PROD CLIENTE", "CODIGO", "COD.", "COD"),
                False,
                Decimal("0.09"),
                Decimal("0.22"),
                "text",
                confidence_weight=Decimal("0.70"),
            ),
            TemplateColumnDefinition(
                "description",
                ("DESCRICAO", "DESCRICAO DO PRODUTO", "PRODUTO", "ITEM/DESCRICAO"),
                True,
                Decimal("0.18"),
                Decimal("0.68"),
                "text",
                multiline=True,
                confidence_weight=Decimal("1.40"),
            ),
            TemplateColumnDefinition(
                "unit",
                ("UNIDADE", "UN", "UND"),
                False,
                Decimal("0.62"),
                Decimal("0.72"),
                "text",
            ),
            TemplateColumnDefinition(
                "quantity",
                ("QTDE", "QTD", "QUANTIDADE"),
                True,
                Decimal("0.68"),
                Decimal("0.80"),
                "decimal",
                confidence_weight=Decimal("1.30"),
            ),
            TemplateColumnDefinition(
                "unit_weight",
                ("PESO UNITARIO", "PESO UNIT.", "PESO UN", "KG/UN"),
                False,
                Decimal("0.78"),
                Decimal("0.89"),
                "decimal",
                confidence_weight=Decimal("0.80"),
            ),
            TemplateColumnDefinition(
                "total_weight",
                ("PESO TOTAL", "PESO", "KG"),
                False,
                Decimal("0.84"),
                Decimal("0.96"),
                "decimal",
                confidence_weight=Decimal("0.90"),
            ),
            TemplateColumnDefinition(
                "financial_value",
                ("VALOR", "PRECO", "PREÇO", "VALOR UNITARIO", "VALOR TOTAL", "SUBTOTAL", "DESCONTO", "ICMS", "IPI", "R$"),
                False,
                Decimal("0.86"),
                Decimal("1.00"),
                "money",
                ignored=True,
                confidence_weight=Decimal("0.00"),
            ),
        ),
        expected_region=TemplateRegion(None, Decimal("0.00"), Decimal("0.30"), Decimal("1.00"), Decimal("0.88")),
        can_span_pages=True,
    )
    required_markers = (
        TemplateMarker("ORCAMENTO", True, Decimal("0.28"), expected_region=header_region),
        TemplateMarker("PROPOSTA", True, Decimal("0.28"), expected_region=header_region),
        TemplateMarker("CLIENTE", True, Decimal("0.18"), expected_region=header_region),
        TemplateMarker("ITEM", True, Decimal("0.14")),
    )
    optional_markers = (
        TemplateMarker("DADOS DO CLIENTE", False, Decimal("0.05"), expected_region=header_region),
        TemplateMarker("DADOS DA OBRA", False, Decimal("0.08"), expected_region=header_region),
        TemplateMarker("OBRA/SITE", False, Decimal("0.08"), expected_region=header_region),
        TemplateMarker("PRAZO DE ENTREGA", False, Decimal("0.08")),
        TemplateMarker("DESCRICAO DO PRODUTO", False, Decimal("0.06")),
        TemplateMarker("QTDE", False, Decimal("0.04")),
        TemplateMarker("QTD", False, Decimal("0.04")),
        TemplateMarker("PESO", False, Decimal("0.03")),
    )

    def evaluate(self, context: PdfExtractionContext) -> TemplateMatchResult:
        start = time.perf_counter()
        normalized_text = _ascii_upper(context.full_text)
        matched_markers: list[str] = []
        missing_required: list[str] = []
        reasons: list[str] = []
        raw_score = Decimal("0.00")
        possible_score = Decimal("0.00")
        for marker in self.required_markers + self.optional_markers:
            alternatives = _marker_alternatives(marker.text)
            possible_score += marker.weight
            found = any(alt in normalized_text for alt in alternatives)
            if not found:
                if marker.required and not _required_marker_has_group_alternative(marker.text, normalized_text):
                    missing_required.append(marker.text)
                continue
            marker_score = marker.weight
            if marker.expected_region and _marker_in_region(marker, context):
                marker_score += marker.weight * Decimal("0.12")
                reasons.append(f"{marker.text}: marcador em regiao esperada")
            else:
                reasons.append(f"{marker.text}: marcador encontrado")
            raw_score += marker_score
            matched_markers.append(marker.text)
        if _BUDGET_RE.search(context.full_text) or _PROPOSAL_RE.search(context.full_text):
            raw_score += Decimal("0.18")
            possible_score += Decimal("0.18")
            reasons.append("assinatura de numero de proposta/orcamento encontrada")
        if _header_structure_score(context) > Decimal("0"):
            bonus = _header_structure_score(context)
            raw_score += bonus
            possible_score += Decimal("0.10")
            reasons.append("estrutura de cabecalho compativel")
        if not any(marker in matched_markers for marker in ("ORCAMENTO", "PROPOSTA")):
            raw_score -= Decimal("0.20")
            reasons.append("ausencia de assinatura ORCAMENTO/PROPOSTA penalizada")
        score = _clamp(raw_score / possible_score if possible_score else Decimal("0.00"))
        score = _round(score)
        return TemplateMatchResult(
            template_id=self.template_id,
            template_version=self.version,
            score=score,
            matched=score >= SCORE_CANDIDATE and not missing_required,
            matched_markers=matched_markers,
            missing_required_markers=missing_required,
            reasons=reasons,
            elapsed_seconds=round(time.perf_counter() - start, 6),
        )

    def extract_header(self, context: PdfExtractionContext) -> TemplateExtractionResult:
        start = time.perf_counter()
        fields = {
            "raw_budget_number": self._extract_budget(context),
            "proposal_number": self._extract_proposal_number(context),
            "proposal_date": self._extract_date(context),
            "client": self._extract_client(context),
            "site": self._extract_site(context),
            "delivery_deadline_raw": self._extract_deadline(context),
            "purchase_order": self._extract_purchase_order(context),
        }
        warnings = [f"{name} nao extraido pelo template" for name, field in fields.items() if field.normalized_value in (None, "")]
        return TemplateExtractionResult(
            template_id=self.template_id,
            template_version=self.version,
            fields=fields,
            table_region=self.table_definition.expected_region if self.table_definition else None,
            table_definition=self.table_definition,
            warnings=warnings,
            errors=[],
            elapsed_seconds=round(time.perf_counter() - start, 6),
        )

    def _extract_budget(self, context: PdfExtractionContext) -> TemplateFieldResult:
        match = _BUDGET_RE.search(context.full_text) or _PROPOSAL_RE.search(context.full_text)
        raw = match.group(1) if match else None
        return _field("raw_budget_number", raw, _normalize_raw_number(raw), "regex_header", context, match.group(0) if match else None, Decimal("0.96") if raw else Decimal("0.00"))

    def _extract_proposal_number(self, context: PdfExtractionContext) -> TemplateFieldResult:
        match = _BUDGET_RE.search(context.full_text) or _PROPOSAL_RE.search(context.full_text)
        raw = match.group(1) if match else None
        return _field("proposal_number", raw, _proposal_number(raw), "regex_header", context, match.group(0) if match else None, Decimal("0.96") if raw else Decimal("0.00"))

    def _extract_date(self, context: PdfExtractionContext) -> TemplateFieldResult:
        match = _DATE_RE.search("\n".join(context.full_text.splitlines()[:15]))
        raw = match.group(1) if match else None
        normalized = _iso_date(raw)
        confidence = Decimal("0.90") if normalized else Decimal("0.00")
        return _field("proposal_date", raw, normalized, "regex_header", context, raw, confidence)

    def _extract_client(self, context: PdfExtractionContext) -> TemplateFieldResult:
        lines = _clean_lines(context.full_text)
        value = _client_from_lines(lines)
        confidence = Decimal("0.88") if value else Decimal("0.00")
        return _field("client", value, value, "marker_between_blocks", context, value, confidence)

    def _extract_site(self, context: PdfExtractionContext) -> TemplateFieldResult:
        lines = _clean_lines(context.full_text)
        value = _site_from_lines(lines)
        confidence = Decimal("0.92") if value else Decimal("0.00")
        return _field("site", value, value, "label_same_or_next_block", context, value, confidence)

    def _extract_deadline(self, context: PdfExtractionContext) -> TemplateFieldResult:
        lines = _clean_lines(context.full_text)
        raw = None
        for index, line in enumerate(lines):
            if "PRAZO DE ENTREGA" not in _ascii_upper(line):
                continue
            candidates = [line] + lines[index + 1 : index + 4]
            for candidate in candidates:
                date_match = _DATE_RE.search(candidate)
                deadline_match = _DEADLINE_RE.search(candidate)
                if deadline_match:
                    raw = deadline_match.group(0).upper()
                    break
                if date_match:
                    raw = date_match.group(1)
                    break
            break
        confidence = Decimal("0.90") if raw else Decimal("0.00")
        return _field("delivery_deadline_raw", raw, raw, "label_nearby_block", context, raw, confidence, warnings=["prazo relativo precisa confirmacao"] if raw and _DEADLINE_RE.search(raw) else [])

    def _extract_purchase_order(self, context: PdfExtractionContext) -> TemplateFieldResult:
        match = _PO_RE.search(context.full_text)
        raw = match.group(1).upper() if match else None
        confidence = Decimal("0.75") if raw else Decimal("0.50")
        return _field("purchase_order", raw, raw, "regex_optional_header", context, raw, confidence)


def merge_template_fields(
    current_result: ProposalImportResult,
    template_result: TemplateExtractionResult | None,
    *,
    min_confidence_delta: Decimal = Decimal("0.12"),
) -> tuple[ProposalImportResult, list[str]]:
    if template_result is None:
        return current_result, []
    replacements: dict[str, ProposalImportField] = {}
    warnings = list(current_result.warnings)
    merge_warnings: list[str] = []
    mapping = {
        "proposal_number": "proposal_number",
        "raw_budget_number": "raw_budget_number",
        "proposal_date": "proposal_date",
        "client": "client",
        "site": "site",
        "delivery_deadline_raw": "delivery_deadline_raw",
    }
    for template_field_name, result_attr in mapping.items():
        template_field = template_result.fields.get(template_field_name)
        if not template_field or template_field.normalized_value in (None, ""):
            continue
        current_field: ProposalImportField = getattr(current_result, result_attr)
        current_value = current_field.value
        template_value = template_field.normalized_value
        template_confidence = template_field.confidence
        current_confidence = Decimal(str(current_field.confidence))
        if current_value in (None, ""):
            replacements[result_attr] = _to_import_field(template_field)
            merge_warnings.append(f"{template_field_name}: template complementou campo ausente")
            continue
        if _same_value(current_value, template_value):
            replacements[result_attr] = ProposalImportField(
                value=current_field.value,
                confidence=max(float(current_confidence), float(template_confidence)),
                needs_confirmation=current_field.needs_confirmation,
                source=current_field.source,
            )
            continue
        if template_confidence - current_confidence >= min_confidence_delta:
            replacements[result_attr] = _to_import_field(template_field)
            merge_warnings.append(f"{template_field_name}: template substituiu campo com maior confianca")
        else:
            merge_warnings.append(f"{template_field_name}: conflito entre parser atual e template")
            warnings.append(
                ProposalImportWarning(
                    "template_conflict",
                    f"Conflito no campo {template_field_name}; valor do parser atual foi preservado.",
                    "warning",
                )
            )
    if not replacements and not merge_warnings:
        return current_result, []
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
        merge_warnings,
    )


def _field(
    name: str,
    raw: str | None,
    normalized: object | None,
    strategy: str,
    context: PdfExtractionContext,
    marker: str | None,
    confidence: Decimal,
    warnings: list[str] | None = None,
) -> TemplateFieldResult:
    bbox, page_number = _bbox_for_text(context, marker or raw)
    reason = "valor extraido pelo template" if normalized not in (None, "") else "campo nao encontrado pelo template"
    return TemplateFieldResult(
        field_name=name,
        raw_value=raw,
        normalized_value=normalized,
        confidence=_round(confidence),
        extraction_strategy=strategy,
        source_page=page_number,
        source_bbox=bbox,
        warnings=list(warnings or []),
        reason=reason,
    )


def _to_import_field(template_field: TemplateFieldResult) -> ProposalImportField:
    return ProposalImportField(
        value=template_field.normalized_value,
        confidence=float(template_field.confidence),
        needs_confirmation=bool(template_field.warnings) or template_field.confidence < Decimal("0.90"),
        source=f"template:{template_field.extraction_strategy}",
    )


def _bbox_for_text(context: PdfExtractionContext, text: str | None) -> tuple[tuple[float, float, float, float] | None, int | None]:
    if not text:
        return None, None
    normalized = _ascii_upper(text)
    words = [word for word in context.words if _ascii_upper(word.text) and _ascii_upper(word.text) in normalized]
    if not words:
        block = _block_containing(context.blocks, text)
        if not block:
            return None, None
        return (block.x0, block.y0, block.x1, block.y1), block.page_number
    page = words[0].page_number
    same_page = [word for word in words if word.page_number == page]
    return (
        min(word.x0 for word in same_page),
        min(word.y0 for word in same_page),
        max(word.x1 for word in same_page),
        max(word.y1 for word in same_page),
    ), page


def _block_containing(blocks: list[PdfTextBlock], text: str) -> PdfTextBlock | None:
    target = _ascii_upper(text)
    return next((block for block in blocks if target in _ascii_upper(block.text)), None)


def _marker_in_region(marker: TemplateMarker, context: PdfExtractionContext) -> bool:
    if marker.expected_region is None:
        return False
    alternatives = _marker_alternatives(marker.text)
    for word in context.words:
        if _ascii_upper(word.text) not in alternatives:
            continue
        page_size = context.page_size(word.page_number)
        if marker.expected_region.contains_word(word, page_size):
            return True
    return False


def _marker_alternatives(text: str) -> tuple[str, ...]:
    normalized = _ascii_upper(text)
    alternatives = {normalized}
    if "ORCAMENTO" in normalized:
        alternatives.update({"ORCAMENTO", "ORÇAMENTO"})
    if "DESCRICAO" in normalized:
        alternatives.update({"DESCRICAO", "DESCRIÇÃO"})
    return tuple(alternatives)


def _required_marker_has_group_alternative(marker: str, normalized_text: str) -> bool:
    if marker == "ORCAMENTO":
        return "PROPOSTA" in normalized_text
    if marker == "PROPOSTA":
        return "ORCAMENTO" in normalized_text
    if marker == "CLIENTE":
        return "DADOS DO CLIENTE" in normalized_text
    return False


def _header_structure_score(context: PdfExtractionContext) -> Decimal:
    first_page_blocks = [block for block in context.blocks if block.page_number == 1]
    header_blocks = [block for block in first_page_blocks if block.y0 < 280]
    header_text = _ascii_upper(" ".join(block.text for block in header_blocks))
    score = Decimal("0.00")
    if "CLIENTE" in header_text or "CNPJ" in header_text:
        score += Decimal("0.04")
    if "OBRA" in header_text or "SITE" in header_text:
        score += Decimal("0.03")
    if "PRAZO" in _ascii_upper(context.full_text):
        score += Decimal("0.03")
    return score


def _client_from_lines(lines: list[str]) -> str | None:
    issuer_terms = ("INDUSTEL", "ENERTEL INDUSTRIA", "ORCAMENTO", "PROPOSTA", "APARECIDA DE GOIANIA")
    for index, line in enumerate(lines):
        upper = _ascii_upper(line)
        if "DADOS DO CLIENTE" in upper:
            candidates = lines[index + 1 : index + 7]
            for candidate in candidates:
                candidate_upper = _ascii_upper(candidate)
                if any(stop in candidate_upper for stop in ("DADOS DA OBRA", "OBRA/SITE", "PRAZO DE ENTREGA")):
                    break
                value = _clean_client(candidate)
                if value:
                    return value
        if "CNPJ/CPF" in upper and index > 0:
            for candidate in reversed(lines[max(0, index - 3) : index]):
                value = _clean_client(candidate)
                if value:
                    return value
    for line in lines[:12]:
        value = _clean_client(line)
        if value and not any(term in _ascii_upper(value) for term in issuer_terms):
            return value
    return None


def _clean_client(value: str) -> str | None:
    cleaned = re.sub(r"\s+(?:CNPJ|CPF|CNPJ/CPF)\s*:.*$", "", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}.*$", "", cleaned)
    cleaned = re.sub(r"\s+(?:DANIELE|PEDRO|LUANA|ISADORA|SILVIO|PATRICIA)\b.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = _clean_space(cleaned).upper()
    if not cleaned:
        return None
    upper = _ascii_upper(cleaned)
    if any(term in upper for term in ("INDUSTEL", "ENERTEL INDUSTRIA", "APARECIDA DE GOIANIA", "CNPJ", "EMAIL")):
        return None
    if any(term in upper for term in ("DADOS DA OBRA", "OBRA/SITE", "PRAZO", "COMPRADOR")):
        return None
    return cleaned


def _site_from_lines(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        upper = _ascii_upper(line)
        if "DADOS DA OBRA" in upper or "OBRA/SITE" in upper:
            if ":" in line:
                candidate = _clean_space(line.split(":", 1)[1])
                if candidate and "NULL" not in _ascii_upper(candidate):
                    return candidate.upper()
            for candidate in lines[index + 1 : index + 4]:
                if candidate and "NULL" not in _ascii_upper(candidate):
                    return _clean_space(candidate).upper()
    return None


def _clean_lines(text: str) -> list[str]:
    return [_clean_space(line) for line in text.splitlines() if _clean_space(line) and not line.startswith("--- PAGE")]


def _clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" -|\t")


def _ascii_upper(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char)).upper()


def _normalize_raw_number(raw: str | None) -> str | None:
    if not raw:
        return None
    upper = _clean_space(raw).upper()
    prefix = "ETCP" if "ETCP" in upper else "CP"
    digits = re.sub(r"\D", "", upper)
    return f"{prefix} {int(digits):05d}" if digits else None


def _proposal_number(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return f"CP{int(digits):05d}" if digits else None


def _iso_date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _same_value(first: object, second: object) -> bool:
    return _ascii_upper(str(first)) == _ascii_upper(str(second))


def _clamp(value: Decimal) -> Decimal:
    return max(Decimal("0.00"), min(Decimal("1.00"), value))


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
