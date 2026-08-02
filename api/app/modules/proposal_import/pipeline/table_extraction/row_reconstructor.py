from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Iterable

from ..schemas import ProposalImportItem
from ..templates.models import TemplateColumnDefinition, TemplateTableDefinition
from .models import ExtractedCell, ExtractedTableRow, TableExtractionResult, TableHeaderDetection, empty_table_result
from .utils import (
    ascii_upper,
    clean_text,
    contains_financial_text,
    decimal_to_float,
    decimal_to_int_if_integral,
    header_is_financial,
    join_description_fragments,
    normalize_description_safe,
    normalize_item_number,
    normalize_quantity,
    normalize_weight,
    safe_optional_text,
)


_FOOTER_TERMS = (
    "TOTAL",
    "CONDICAO DE PAGAMENTO",
    "CONDIÇÃO DE PAGAMENTO",
    "OBSERVACOES",
    "OBSERVAÇÕES",
    "ASSINATURA",
)


def detect_header_from_rows(
    rows: list[list[str]],
    table_definition: TemplateTableDefinition,
    *,
    page_number: int = 1,
) -> tuple[int | None, TableHeaderDetection]:
    best_index: int | None = None
    best_score = Decimal("0.00")
    best_columns: dict[str, str] = {}
    for index, row in enumerate(rows[:12]):
        recognized = _recognized_columns(row, table_definition)
        required_count = sum(1 for column in table_definition.columns if column.required and column.name in recognized)
        score = Decimal(len(recognized)) / Decimal(max(1, len([c for c in table_definition.columns if not c.ignored])))
        if required_count >= 2:
            score += Decimal("0.25")
        if score > best_score:
            best_score = min(score, Decimal("1.00"))
            best_index = index
            best_columns = recognized
    missing = [
        column.name
        for column in table_definition.columns
        if column.required and column.name not in best_columns
    ]
    if not best_columns or len(best_columns) < 2:
        best_index = None
    return best_index, TableHeaderDetection(
        page_number=page_number if best_index is not None else None,
        bbox=None,
        recognized_columns=best_columns,
        missing_required=missing,
        confidence=best_score if best_index is not None else Decimal("0.00"),
        warnings=["cabecalho de tabela nao localizado"] if best_index is None else [],
    )


def rows_to_table_result(
    rows: list[list[str]],
    table_definition: TemplateTableDefinition,
    *,
    method: str,
    page_number: int = 1,
) -> TableExtractionResult:
    if not rows:
        return empty_table_result(method, warning="nenhuma linha bruta extraida da tabela")
    header_index, header = detect_header_from_rows(rows, table_definition, page_number=page_number)
    if header_index is None:
        return empty_table_result(method, warning="cabecalho da tabela nao reconhecido")
    body_rows = rows[header_index + 1 :]
    header_mapping = _column_positions(rows[header_index], table_definition)
    mapped_rows = [_map_row_by_header(row, header_mapping, table_definition) for row in body_rows]
    return _body_rows_to_items(mapped_rows, table_definition, header, method=method, default_page=page_number)


def physical_rows_to_table_result(
    physical_rows: list[ExtractedTableRow],
    table_definition: TemplateTableDefinition,
    *,
    method: str,
) -> TableExtractionResult:
    if not physical_rows:
        return empty_table_result(method, warning="nenhuma linha por coordenada extraida")
    logical_rows = [
        [
            _cells_by_template_columns(row, table_definition).get(column.name, "")
            for column in table_definition.columns
            if not column.ignored
        ]
        for row in physical_rows
    ]
    header_index, header = detect_header_from_rows(
        logical_rows,
        table_definition,
        page_number=physical_rows[0].page_number,
    )
    if header_index is None:
        return empty_table_result(method, warning="cabecalho da tabela nao reconhecido por coordenadas")
    body = physical_rows[header_index + 1 :]
    return _body_rows_to_items(
        [_cells_by_template_columns(row, table_definition) for row in body],
        table_definition,
        header,
        method=method,
        default_page=physical_rows[0].page_number,
    )


def _body_rows_to_items(
    rows: list[list[str] | dict[str, str]],
    table_definition: TemplateTableDefinition,
    header: TableHeaderDetection,
    *,
    method: str,
    default_page: int,
) -> TableExtractionResult:
    warnings: list[str] = list(header.warnings)
    extracted_rows: list[ExtractedTableRow] = []
    items: list[ProposalImportItem] = []
    current: dict[str, str] | None = None
    current_page = default_page
    for row_index, row in enumerate(rows):
        cells = row if isinstance(row, dict) else _map_row_by_order(row, table_definition)
        raw_text = clean_text(" ".join(str(value or "") for value in cells.values()))
        if not raw_text:
            continue
        if _is_footer(raw_text):
            warnings.append("rodape/fim de tabela ignorado")
            break
        if _is_repeated_header(raw_text, table_definition):
            warnings.append("cabecalho repetido ignorado")
            continue
        if _row_is_financial(cells):
            warnings.append("linha financeira ignorada")
            continue
        if _is_confirmed_new_item(cells):
            if current:
                item = _item_from_cells(current, method)
                if item:
                    items.append(item)
                    extracted_rows.append(_row_record(len(extracted_rows), current_page, current, method))
                else:
                    warnings.append("linha de item descartada por campos obrigatorios invalidos")
            current = {key: _clean_cell(value, key) for key, value in cells.items()}
            current_page = default_page
        elif current and _continuation_description(cells):
            current["description"] = join_description_fragments(
                [current.get("description", ""), _continuation_description(cells)]
            )
            if cells.get("quantity") and not current.get("quantity"):
                current["quantity"] = clean_text(cells.get("quantity"))
            if cells.get("total_weight") and not current.get("total_weight"):
                current["total_weight"] = clean_text(cells.get("total_weight"))
            warnings.append("descricao multilinha reconstruida")
        elif raw_text:
            if contains_financial_text(raw_text):
                warnings.append("linha financeira/orfa ignorada")
            else:
                warnings.append(f"linha orfa ignorada: {raw_text[:40]}")
    if current:
        item = _item_from_cells(current, method)
        if item:
            items.append(item)
            extracted_rows.append(_row_record(len(extracted_rows), current_page, current, method))
        else:
            warnings.append("linha final descartada por campos obrigatorios invalidos")
    errors = _validate_items(items)
    confidence = _table_confidence(items, extracted_rows, header, errors)
    return TableExtractionResult(
        items=items,
        method=method,
        confidence=confidence,
        rows=extracted_rows,
        warnings=warnings,
        errors=errors,
        pages_processed=sorted({row.page_number for row in extracted_rows}) or [default_page],
        header=header,
    )


def _recognized_columns(row: Iterable[str], table_definition: TemplateTableDefinition) -> dict[str, str]:
    text = [ascii_upper(cell) for cell in row]
    recognized: dict[str, str] = {}
    for cell in text:
        if header_is_financial(cell):
            recognized.setdefault("financial_value", cell)
            continue
        match = _best_header_match(cell, table_definition)
        if match:
            recognized.setdefault(match.name, cell)
    return recognized


def _column_positions(row: Iterable[str], table_definition: TemplateTableDefinition) -> dict[int, str]:
    positions: dict[int, str] = {}
    for index, cell in enumerate(row):
        upper = ascii_upper(cell)
        if header_is_financial(upper):
            positions[index] = "financial_value"
            continue
        match = _best_header_match(upper, table_definition)
        if match:
            positions[index] = match.name
    return positions


def _best_header_match(
    upper_cell: str,
    table_definition: TemplateTableDefinition,
) -> TemplateColumnDefinition | None:
    if "DESCRICAO" in upper_cell:
        for column in table_definition.columns:
            if column.name == "description":
                return column
    matches: list[tuple[int, TemplateColumnDefinition]] = []
    for column in table_definition.columns:
        if column.ignored:
            continue
        for alias in column.aliases:
            normalized = ascii_upper(alias)
            if normalized and normalized in upper_cell:
                matches.append((len(normalized), column))
    if not matches:
        return None
    return sorted(matches, key=lambda item: item[0], reverse=True)[0][1]


def _map_row_by_header(
    row: list[str],
    positions: dict[int, str],
    table_definition: TemplateTableDefinition,
) -> dict[str, str]:
    if not positions:
        return _map_row_by_order(row, table_definition)
    mapped = {column.name: "" for column in table_definition.columns if not column.ignored}
    mapped["financial_value"] = ""
    last_column: str | None = None
    for index, value in enumerate(row):
        cleaned = _clean_cell(value, positions.get(index))
        column_name = positions.get(index)
        if column_name:
            last_column = column_name
        elif last_column == "description":
            column_name = "description"
        if not column_name:
            continue
        if column_name == "description":
            mapped[column_name] = join_description_fragments([mapped.get(column_name, ""), cleaned])
        else:
            mapped[column_name] = _clean_cell(f"{mapped.get(column_name, '')} {cleaned}", column_name)
    return mapped


def _map_row_by_order(row: list[str], table_definition: TemplateTableDefinition) -> dict[str, str]:
    usable_columns = [column for column in table_definition.columns if not column.ignored]
    values = [clean_text(value) for value in row]
    mapped: dict[str, str] = {}
    for index, column in enumerate(usable_columns):
        mapped[column.name] = _clean_cell(row[index], column.name) if index < len(row) else ""
    if len(values) > len(usable_columns):
        mapped["description"] = join_description_fragments(
            [mapped.get("description", ""), " ".join(values[len(usable_columns):])]
        )
    return mapped


def _cells_by_template_columns(row: ExtractedTableRow, table_definition: TemplateTableDefinition) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for column in table_definition.columns:
        if column.ignored:
            continue
        cell = row.cells.get(column.name)
        mapped[column.name] = cell.raw_text if cell else ""
    return mapped


def _item_from_cells(cells: dict[str, str], method: str) -> ProposalImportItem | None:
    description = normalize_description_safe(_description_from_cells(cells))
    if not description or contains_financial_text(description):
        return None
    product_code = safe_optional_text(cells.get("product_code"))
    description = _strip_product_code_prefix(description, product_code)
    quantity = normalize_quantity(cells.get("quantity"))
    if quantity is None:
        return None
    total_weight = normalize_weight(cells.get("total_weight") or cells.get("weight"))
    unit_weight = normalize_weight(cells.get("unit_weight"))
    weight = total_weight if total_weight is not None else unit_weight
    item_number = normalize_item_number(cells.get("item")) or 0
    raw_text = " ".join(
        value for key, value in cells.items()
        if key not in {"financial_value"} and not contains_financial_text(value)
    )
    confidence = _item_confidence(cells, has_weight=weight is not None, method=method)
    return ProposalImportItem(
        item_number=item_number,
        product_code=product_code,
        description=description,
        unit=safe_optional_text(cells.get("unit")),
        quantity=decimal_to_int_if_integral(quantity),
        ncm=None,
        weight_kg=decimal_to_float(weight),
        weight_extracted_from_text=weight is not None,
        weight_needs_confirmation=weight is None,
        raw_text=raw_text,
        confidence=float(confidence),
        weight_confidence=0.92 if weight is not None else 0.0,
        needs_confirmation=weight is None or confidence < Decimal("0.85"),
    )


def _row_record(row_index: int, page_number: int, cells: dict[str, str], method: str) -> ExtractedTableRow:
    safe_values = [
        value
        for key, value in cells.items()
        if key != "financial_value" and not contains_financial_text(value)
    ]
    return ExtractedTableRow(
        row_index=row_index,
        page_number=page_number,
        cells={
            key: ExtractedCell(key, value, page_number, None, method, Decimal("0.84"))
            for key, value in cells.items()
            if key != "financial_value"
        },
        raw_text=clean_text(" ".join(safe_values)),
        confidence=Decimal("0.84"),
    )


def _item_confidence(cells: dict[str, str], *, has_weight: bool, method: str) -> Decimal:
    score = Decimal("0.60")
    if normalize_item_number(cells.get("item")) is not None:
        score += Decimal("0.10")
    if cells.get("description"):
        score += Decimal("0.12")
    if normalize_quantity(cells.get("quantity")) is not None:
        score += Decimal("0.12")
    if has_weight:
        score += Decimal("0.06")
    if method.startswith("pdfplumber"):
        score += Decimal("0.03")
    return min(score, Decimal("0.98"))


def _table_confidence(
    items: list[ProposalImportItem],
    rows: list[ExtractedTableRow],
    header: TableHeaderDetection,
    errors: list[str],
) -> Decimal:
    if not items or errors:
        return Decimal("0.00") if not items else Decimal("0.55")
    avg_item = sum(Decimal(str(item.confidence)) for item in items) / Decimal(len(items))
    score = (avg_item * Decimal("0.70")) + (header.confidence * Decimal("0.30"))
    if len(items) != len(rows):
        score -= Decimal("0.08")
    return max(Decimal("0.00"), min(score, Decimal("1.00")))


def _validate_items(items: list[ProposalImportItem]) -> list[str]:
    errors: list[str] = []
    if not items:
        return ["nenhum item valido reconstruido"]
    seen: set[int] = set()
    for item in items:
        if item.item_number in seen:
            errors.append(f"numero de item duplicado: {item.item_number}")
        seen.add(item.item_number)
        if not item.description:
            errors.append(f"item {item.item_number}: descricao ausente")
        if item.quantity is None or item.quantity <= 0:
            errors.append(f"item {item.item_number}: quantidade invalida")
        if item.weight_kg is not None and item.weight_kg < 0:
            errors.append(f"item {item.item_number}: peso negativo")
    return errors


def _is_footer(text: str) -> bool:
    upper = ascii_upper(text)
    return any(term in upper for term in _FOOTER_TERMS)


def _is_repeated_header(text: str, table_definition: TemplateTableDefinition) -> bool:
    recognized = _recognized_columns([text], table_definition)
    return len(recognized) >= 2 and "item" in recognized


def _row_is_financial(cells: dict[str, str]) -> bool:
    raw = " ".join(cells.values())
    has_operational_data = bool(cells.get("item") or cells.get("description") or cells.get("quantity"))
    return contains_financial_text(raw) and not has_operational_data


def _is_confirmed_new_item(cells: dict[str, str]) -> bool:
    if normalize_item_number(cells.get("item")) is not None:
        return True
    product_code = safe_optional_text(cells.get("product_code"))
    has_quantity = normalize_quantity(cells.get("quantity")) is not None
    has_description = bool(clean_text(cells.get("description")))
    return bool(product_code and has_quantity and has_description)


def _continuation_description(cells: dict[str, str]) -> str:
    return _description_from_cells(cells)


def _strip_product_code_prefix(description: str, product_code: str | None) -> str:
    if not product_code:
        return description
    upper_description = ascii_upper(description)
    upper_code = ascii_upper(product_code)
    if upper_description == upper_code:
        return description
    if upper_description.startswith(upper_code):
        stripped = description[len(product_code):].lstrip(" -:")
        return stripped or description
    return description


def _clean_cell(value: object, column_name: str | None) -> str:
    text = str(value or "").replace("\xa0", " ")
    return " ".join(text.split()).strip(" \t|")


def _description_from_cells(cells: dict[str, str]) -> str:
    fragments = [_clean_cell(cells.get("description"), "description")]
    for key, raw_value in cells.items():
        if key in {"item", "description"}:
            continue
        value = _clean_cell(raw_value, "description")
        if _is_description_fragment_candidate(key, value):
            fragments.append(value)
    return join_description_fragments(fragments)


def _is_description_fragment_candidate(key: str, value: str) -> bool:
    if not value:
        return False
    if contains_financial_text(value):
        return bool(join_description_fragments([value]))
    upper = ascii_upper(value)
    if key == "unit" and upper in {"UN", "UND", "UNIDADE", "PC", "PCA", "PECA", "PEÇA"}:
        return False
    if key == "quantity" and normalize_quantity(value) is not None:
        return False
    if key in {"unit_weight", "total_weight", "weight"} and normalize_weight(value) is not None:
        return False
    return any(char.isalpha() for char in value)
