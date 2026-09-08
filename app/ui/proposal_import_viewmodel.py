from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CONFIDENCE_HIGH = 0.95
CONFIDENCE_ATTENTION = 0.80


@dataclass(frozen=True)
class ImportFieldVisual:
    field_name: str
    level: str
    label: str
    message: str
    tooltip: str
    needs_review: bool = False
    conflict: bool = False


@dataclass(frozen=True)
class ImportItemVisual:
    row: int
    item_number: str
    level: str
    label: str
    tooltip: str
    needs_review: bool = False


@dataclass(frozen=True)
class ImportVisualModel:
    summary: str
    details: str
    fields: dict[str, ImportFieldVisual] = field(default_factory=dict)
    items: dict[int, ImportItemVisual] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def friendly_source_name(source: str | None) -> str:
    value = (source or "").strip().lower()
    if not value:
        return "Leitura do documento"
    if "template" in value or "region" in value or "header" in value:
        return "Template do documento"
    if "table" in value or "pdfplumber" in value or "structured" in value:
        return "Tabela estruturada"
    if "legacy" in value:
        return "Leitor de compatibilidade"
    if "ai" in value:
        return "Sugestao auxiliar"
    if "source_selector" in value or "merge" in value:
        return "Conferencia entre leituras"
    if "rule" in value or "nomus" in value or "text" in value:
        return "Leitura textual"
    if "safety" in value:
        return "Camada de seguranca"
    return "Leitura do documento"


def confidence_level(score: Any, *, needs_confirmation: bool = False, conflict: bool = False, missing: bool = False) -> str:
    if missing or conflict:
        return "low"
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        numeric = 0.0 if needs_confirmation else 1.0
    if needs_confirmation:
        return "attention" if numeric >= CONFIDENCE_ATTENTION else "low"
    if numeric >= CONFIDENCE_HIGH:
        return "high"
    if numeric >= CONFIDENCE_ATTENTION:
        return "attention"
    return "low"


def build_import_visual_model(
    payload: dict[str, Any],
    *,
    standard_result: Any | None = None,
    metadata: dict[str, Any] | None = None,
    used_fallback: bool = False,
) -> ImportVisualModel:
    metadata = metadata or _metadata_from_standard(standard_result)
    field_provenance = _field_provenance_by_name(metadata)
    item_provenance = _item_provenance_by_number(metadata)
    field_visuals: dict[str, ImportFieldVisual] = {}

    for field_name in ("proposal_number", "client", "site", "proposal_date", "delivery_deadline_raw", "purchase_order"):
        visual = _build_field_visual(field_name, payload, field_provenance.get(field_name))
        if visual:
            field_visuals[field_name] = visual

    item_visuals: dict[int, ImportItemVisual] = {}
    for row, item in enumerate(payload.get("items") or []):
        item_visuals[row] = _build_item_visual(row, item, item_provenance)

    warning_messages = _group_warnings(payload, field_visuals, item_visuals, metadata, used_fallback)
    summary, details = _summary_text(payload, standard_result, metadata, warning_messages, used_fallback)
    return ImportVisualModel(
        summary=summary,
        details=details,
        fields=field_visuals,
        items=item_visuals,
        warnings=warning_messages,
    )


def _metadata_from_standard(standard_result: Any | None) -> dict[str, Any]:
    if standard_result is None:
        return {}
    metadata = getattr(standard_result, "metadata", None)
    if hasattr(metadata, "to_dict"):
        return metadata.to_dict()
    if isinstance(metadata, dict):
        return metadata
    return {}


def _field_provenance_by_name(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in metadata.get("field_provenance") or []:
        if isinstance(entry, dict) and entry.get("field_name"):
            result[str(entry["field_name"])] = entry
    return result


def _item_provenance_by_number(metadata: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in metadata.get("item_field_provenance") or []:
        if not isinstance(entry, dict):
            continue
        item_number = entry.get("item_number")
        field_name = entry.get("field_name")
        if item_number is not None and field_name:
            result[(str(item_number), str(field_name))] = entry
    return result


def _field_meta(payload: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = payload.get(field_name)
    return value if isinstance(value, dict) else {}


def _field_raw_value(payload: dict[str, Any], field_name: str) -> Any:
    value = payload.get(field_name)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _build_field_visual(field_name: str, payload: dict[str, Any], provenance: dict[str, Any] | None) -> ImportFieldVisual | None:
    meta = _field_meta(payload, field_name)
    raw_value = _field_raw_value(payload, field_name)
    if meta:
        score = meta.get("confidence")
        needs_confirmation = bool(meta.get("needs_confirmation"))
        source = meta.get("source")
    else:
        score = provenance.get("selected_confidence") if provenance else None
        needs_confirmation = False
        source = provenance.get("selected_source") if provenance else None

    conflict = bool(provenance and provenance.get("conflict"))
    missing = raw_value in (None, "")
    if missing and field_name in {"purchase_order"} and not meta and not provenance:
        return None
    level = confidence_level(score, needs_confirmation=needs_confirmation, conflict=conflict, missing=missing)
    if not meta and not provenance and not missing:
        return None
    source_label = friendly_source_name(source)
    score_text = _format_score(score)
    if missing:
        label = "Revisar"
        message = "Campo nao identificado; revise antes de continuar."
    elif conflict:
        label = "Revisar"
        message = "Leituras divergentes; valor escolhido para conferencia."
    elif needs_confirmation or level in {"attention", "low"}:
        label = "Revisar"
        message = "Precisa confirmacao humana."
    else:
        label = "OK"
        message = ""
    tooltip_parts = [f"Fonte: {source_label}"]
    if score_text:
        tooltip_parts.append(f"Confianca: {score_text}")
    if conflict:
        tooltip_parts.append("Ha divergencia entre leituras; confira o valor.")
    elif needs_confirmation or level in {"attention", "low"}:
        tooltip_parts.append("Confira este campo antes de usar no cadastro.")
    else:
        tooltip_parts.append("Campo identificado com boa confianca.")
    return ImportFieldVisual(
        field_name=field_name,
        level=level,
        label=label,
        message=message,
        tooltip="\n".join(tooltip_parts),
        needs_review=bool(missing or conflict or needs_confirmation or level in {"attention", "low"}),
        conflict=conflict,
    )


def _build_item_visual(
    row: int,
    item: dict[str, Any],
    item_provenance: dict[tuple[str, str], dict[str, Any]],
) -> ImportItemVisual:
    item_number = str(item.get("item_number") or row + 1)
    weight_missing = item.get("weight_kg") is None
    needs_confirmation = bool(item.get("needs_confirmation") or item.get("weight_needs_confirmation"))
    score = item.get("confidence")
    related_provenance = [
        provenance
        for (number, _field), provenance in item_provenance.items()
        if number == item_number
    ]
    conflict = any(bool(entry.get("conflict")) for entry in related_provenance)
    level = confidence_level(score, needs_confirmation=needs_confirmation, conflict=conflict, missing=False)
    if conflict:
        label = "Revisar"
        tooltip = "Ha divergencia entre leituras deste item; confira os dados."
    elif weight_missing:
        label = "Peso pendente"
        tooltip = "O documento nao informou peso em kg para este item."
        level = "attention"
    elif needs_confirmation or level in {"attention", "low"}:
        label = "Revisar"
        tooltip = "Item precisa confirmacao humana antes do cadastro."
    else:
        label = "OK"
        tooltip = "Item identificado com boa confianca."
    sources = sorted({friendly_source_name(entry.get("selected_source")) for entry in related_provenance if entry.get("selected_source")})
    if sources:
        tooltip = f"{tooltip}\nFonte: {', '.join(sources)}"
    return ImportItemVisual(
        row=row,
        item_number=item_number,
        level=level,
        label=label,
        tooltip=tooltip,
        needs_review=bool(conflict or weight_missing or needs_confirmation or level in {"attention", "low"}),
    )


def _group_warnings(
    payload: dict[str, Any],
    fields: dict[str, ImportFieldVisual],
    items: dict[int, ImportItemVisual],
    metadata: dict[str, Any],
    used_fallback: bool,
) -> list[str]:
    messages: list[str] = []
    if used_fallback:
        messages.append("Leitor de compatibilidade usado como fallback; revise os dados antes de continuar.")
    missing_weights = sum(1 for item in payload.get("items") or [] if item.get("weight_kg") is None)
    if missing_weights:
        messages.append(f"{missing_weights} item(ns) sem peso informado.")
    review_fields = [visual for visual in fields.values() if visual.needs_review]
    if review_fields:
        messages.append(f"{len(review_fields)} campo(s) do cabecalho precisam conferencia.")
    review_items = [visual for visual in items.values() if visual.needs_review]
    if review_items and missing_weights != len(review_items):
        messages.append(f"{len(review_items)} item(ns) precisam conferencia.")
    conflicts = sum(1 for visual in fields.values() if visual.conflict)
    conflicts += sum(1 for visual in items.values() if "divergencia" in visual.tooltip.lower())
    if conflicts:
        messages.append(f"{conflicts} divergencia(s) entre leituras foram mantidas para revisao.")
    for warning in payload.get("warnings") or []:
        if isinstance(warning, dict):
            text = warning.get("message")
        else:
            text = str(warning)
        text = _safe_warning_text(text)
        if text:
            messages.append(text)
    for text in metadata.get("template_warnings") or []:
        text = _safe_warning_text(text)
        if text:
            messages.append(text)
    return _unique(messages)


def _summary_text(
    payload: dict[str, Any],
    standard_result: Any | None,
    metadata: dict[str, Any],
    warnings: list[str],
    used_fallback: bool,
) -> tuple[str, str]:
    item_count = len(payload.get("items") or [])
    confidence = getattr(standard_result, "overall_confidence", None)
    confidence_text = _format_score(confidence)
    if confidence_text:
        summary = f"Importacao preparada para conferencia: {item_count} item(ns), confianca geral {confidence_text}."
    else:
        summary = f"Importacao preparada para conferencia: {item_count} item(ns)."
    if used_fallback:
        summary += " Leitor de compatibilidade usado."
    if warnings:
        summary += f" {len(warnings)} aviso(s) para revisar."

    details_parts = []
    template_id = metadata.get("template_id")
    if template_id:
        details_parts.append("Modelo reconhecido: proposta Nomus.")
    method = friendly_source_name(metadata.get("extraction_method"))
    details_parts.append(f"Base da leitura: {method}.")
    if metadata.get("table_items_detected"):
        details_parts.append(f"Itens estruturados detectados: {metadata.get('table_items_detected')}.")
    return summary, " ".join(details_parts)


def _format_score(score: Any) -> str:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return ""
    if numeric <= 1:
        numeric *= 100
    return f"{numeric:.0f}%"


def _safe_warning_text(text: Any) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    blocked = ("R$", "PRECO", "PREÇO", "VALOR UNITARIO", "VALOR UNITÁRIO", "SUBTOTAL", "ICMS", "IPI", "DIFAL", "FRETE")
    upper = value.upper()
    if any(term in upper for term in blocked):
        return "Conteudo comercial descartado pela camada de seguranca."
    return value


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result
