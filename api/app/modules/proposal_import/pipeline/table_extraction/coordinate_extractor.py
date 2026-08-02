from __future__ import annotations

import time
from decimal import Decimal

from ..pymupdf_extractor import PdfExtractionContext, PdfWord
from ..templates.models import TemplateColumnDefinition, TemplateTableDefinition
from .models import ExtractedCell, ExtractedTableRow, TableExtractionResult, empty_table_result
from .row_reconstructor import physical_rows_to_table_result
from .utils import clean_text


def extract_with_coordinates(
    context: PdfExtractionContext | None,
    table_definition: TemplateTableDefinition,
) -> TableExtractionResult:
    start = time.perf_counter()
    if context is None:
        return empty_table_result("pymupdf_coordinates", warning="contexto PyMuPDF indisponivel")
    physical_rows: list[ExtractedTableRow] = []
    try:
        for page_number in range(1, context.page_count + 1):
            page_size = context.page_size(page_number)
            page_words = [word for word in context.words if word.page_number == page_number]
            if table_definition.expected_region and page_size:
                if (
                    table_definition.expected_region.page_number is not None
                    and table_definition.expected_region.page_number != page_number
                ):
                    continue
                region = table_definition.expected_region.to_absolute(*page_size)
                page_words = [word for word in page_words if region.contains(word)]
            grouped_rows = _group_words_by_line(page_words)
            for row_index, words in enumerate(grouped_rows):
                row = _words_to_row(row_index, page_number, page_size, words, table_definition)
                if row and row.raw_text:
                    physical_rows.append(row)
    except Exception as exc:
        return empty_table_result("pymupdf_coordinates", error=f"extracao por coordenadas falhou: {exc}")
    result = physical_rows_to_table_result(physical_rows, table_definition, method="pymupdf_coordinates")
    result.elapsed_seconds = time.perf_counter() - start
    return result


def _group_words_by_line(words: list[PdfWord]) -> list[list[PdfWord]]:
    if not words:
        return []
    sorted_words = sorted(words, key=lambda word: (word.y0, word.x0))
    heights = [max(1.0, word.y1 - word.y0) for word in sorted_words]
    tolerance = max(3.5, sum(heights) / len(heights) * 0.55)
    rows: list[list[PdfWord]] = []
    current: list[PdfWord] = []
    current_y: float | None = None
    for word in sorted_words:
        if current_y is None or abs(word.y0 - current_y) <= tolerance:
            current.append(word)
            current_y = word.y0 if current_y is None else (current_y + word.y0) / 2
            continue
        rows.append(sorted(current, key=lambda item: item.x0))
        current = [word]
        current_y = word.y0
    if current:
        rows.append(sorted(current, key=lambda item: item.x0))
    return rows


def _words_to_row(
    row_index: int,
    page_number: int,
    page_size: tuple[float, float] | None,
    words: list[PdfWord],
    table_definition: TemplateTableDefinition,
) -> ExtractedTableRow | None:
    if not words:
        return None
    page_width = page_size[0] if page_size else max(word.x1 for word in words)
    cells: dict[str, ExtractedCell] = {}
    for column in table_definition.columns:
        if column.ignored:
            continue
        column_words = _words_for_column(words, column, page_width)
        raw = clean_text(" ".join(word.text for word in column_words))
        if not raw:
            continue
        bbox = (
            min(word.x0 for word in column_words),
            min(word.y0 for word in column_words),
            max(word.x1 for word in column_words),
            max(word.y1 for word in column_words),
        )
        cells[column.name] = ExtractedCell(
            column_name=column.name,
            raw_text=raw,
            page_number=page_number,
            bbox=bbox,
            extraction_method="pymupdf_coordinates",
            confidence=Decimal("0.80"),
        )
    raw_text = clean_text(" ".join(word.text for word in words))
    return ExtractedTableRow(
        row_index=row_index,
        page_number=page_number,
        cells=cells,
        raw_text=raw_text,
        confidence=Decimal("0.80"),
    )


def _words_for_column(words: list[PdfWord], column: TemplateColumnDefinition, page_width: float) -> list[PdfWord]:
    if column.x0_ratio is None or column.x1_ratio is None:
        return []
    x0 = float(column.x0_ratio) * page_width
    x1 = float(column.x1_ratio) * page_width
    return [word for word in words if x0 <= word.center_x <= x1]
