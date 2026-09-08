from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from ..schemas import ProposalImportItem
from .models import TABLE_CONFIDENCE_GOOD, TABLE_CONFIDENCE_HIGH, TableExtractionResult, TableMergeResult
from .utils import contains_financial_text


def merge_table_items(
    current_items: list[ProposalImportItem],
    table_result: TableExtractionResult | None,
) -> TableMergeResult:
    if table_result is None or not table_result.items:
        return TableMergeResult(
            items=list(current_items),
            warnings=["tabela estruturada indisponivel"],
            comparison_summary={"preserved": len(current_items), "added": 0, "completed": 0, "conflicts": 0},
            selected_method=table_result.method if table_result else "none",
            selected_confidence=table_result.confidence if table_result else Decimal("0.00"),
            fallback_reasons=["sem itens extraidos por tabela"],
        )
    warnings: list[str] = list(table_result.warnings)
    if table_result.errors:
        warnings.extend(f"erro na tabela: {error}" for error in table_result.errors)
    if not current_items and table_result.confidence >= TABLE_CONFIDENCE_GOOD:
        return TableMergeResult(
            items=list(table_result.items),
            warnings=warnings + ["itens vieram da tabela estruturada porque o parser atual nao retornou itens"],
            comparison_summary={
                "preserved": 0,
                "added": len(table_result.items),
                "completed": 0,
                "conflicts": 0,
                "source": "structured_table",
            },
            selected_method=table_result.method,
            selected_confidence=table_result.confidence,
        )

    table_by_number = {item.item_number: item for item in table_result.items if item.item_number}
    merged: list[ProposalImportItem] = []
    added = 0
    completed = 0
    conflicts = 0
    for current in current_items:
        table_item = table_by_number.get(current.item_number)
        if not table_item:
            merged.append(current)
            continue
        item, item_completed, item_conflicts = _merge_one(current, table_item)
        completed += 1 if item_completed else 0
        conflicts += item_conflicts
        if item_conflicts:
            warnings.append(f"conflito preservado no item {current.item_number}; revisar manualmente")
        merged.append(item)

    current_numbers = {item.item_number for item in current_items if item.item_number}
    if table_result.confidence >= TABLE_CONFIDENCE_HIGH:
        for table_item in table_result.items:
            if table_item.item_number and table_item.item_number not in current_numbers:
                merged.append(table_item)
                added += 1
                warnings.append(f"item {table_item.item_number} adicionado a partir da tabela estruturada")

    return TableMergeResult(
        items=merged,
        warnings=warnings,
        comparison_summary={
            "preserved": len(current_items),
            "added": added,
            "completed": completed,
            "conflicts": conflicts,
            "source": "merged_parser_table",
        },
        selected_method=table_result.method,
        selected_confidence=table_result.confidence,
        fallback_reasons=[] if table_result.confidence >= TABLE_CONFIDENCE_GOOD else ["confianca de tabela abaixo do ideal"],
    )


def _merge_one(current: ProposalImportItem, table_item: ProposalImportItem) -> tuple[ProposalImportItem, bool, int]:
    completed = False
    conflicts = 0
    product_code = current.product_code
    unit = current.unit
    quantity = current.quantity
    description = current.description
    weight = current.weight_kg
    weight_extracted = current.weight_extracted_from_text
    weight_needs_confirmation = current.weight_needs_confirmation
    weight_confidence = current.weight_confidence

    if not product_code and table_item.product_code:
        product_code = table_item.product_code
        completed = True
    elif product_code and table_item.product_code and product_code.strip().upper() != table_item.product_code.strip().upper():
        conflicts += 1

    if not unit and table_item.unit:
        unit = table_item.unit
        completed = True
    elif unit and table_item.unit and unit.strip().upper() != table_item.unit.strip().upper():
        conflicts += 1

    if quantity in (None, 0) and table_item.quantity:
        quantity = table_item.quantity
        completed = True
    elif quantity and table_item.quantity and int(quantity) != int(table_item.quantity):
        conflicts += 1

    if table_item.description and not contains_financial_text(table_item.description):
        preferred_description, changed, conflict = _merge_description(description, table_item.description)
        if changed:
            description = preferred_description
            completed = True
        if conflict:
            conflicts += 1

    if weight is None and table_item.weight_kg is not None:
        weight = table_item.weight_kg
        weight_extracted = True
        weight_needs_confirmation = False
        weight_confidence = max(weight_confidence, table_item.weight_confidence)
        completed = True
    elif weight is not None and table_item.weight_kg is not None:
        if abs(float(weight) - float(table_item.weight_kg)) > 0.01:
            conflicts += 1

    return (
        replace(
            current,
            product_code=product_code,
            description=description,
            unit=unit,
            quantity=quantity,
            weight_kg=weight,
            weight_extracted_from_text=weight_extracted,
            weight_needs_confirmation=weight_needs_confirmation,
            weight_confidence=weight_confidence,
            confidence=max(current.confidence, min(0.96, table_item.confidence)),
            needs_confirmation=current.needs_confirmation or conflicts > 0 or weight is None,
        ),
        completed,
        conflicts,
    )


def _normalized(value: str) -> str:
    return " ".join((value or "").upper().split())


def _normalized_compact(value: str) -> str:
    return "".join(char for char in _normalized(value) if char.isalnum())


def _merge_description(current: str, table_description: str) -> tuple[str, bool, bool]:
    if not current or len(current) < 8:
        return table_description, True, False
    current_normalized = _normalized(current)
    table_normalized = _normalized(table_description)
    if current_normalized == table_normalized:
        return current, False, False

    current_compact = _normalized_compact(current)
    table_compact = _normalized_compact(table_description)
    if current_compact and current_compact in table_compact:
        if len(table_description) > len(current):
            return table_description, True, False
        return current, False, False
    if table_compact and table_compact in current_compact:
        return current, False, False
    return current, False, True
