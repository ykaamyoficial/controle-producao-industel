from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

import pdfplumber

from ..templates.models import TemplateTableDefinition
from .models import TableExtractionResult, empty_table_result
from .row_reconstructor import rows_to_table_result


_PDFPLUMBER_SETTINGS = (
    {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "intersection_tolerance": 5,
        "text_tolerance": 2,
    },
    {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "snap_tolerance": 4,
        "join_tolerance": 4,
        "intersection_tolerance": 5,
        "text_tolerance": 2,
    },
)


def extract_with_pdfplumber(
    pdf_path: str | Path,
    table_definition: TemplateTableDefinition,
) -> TableExtractionResult:
    start = time.perf_counter()
    candidates: list[TableExtractionResult] = []
    try:
        with pdfplumber.open(Path(pdf_path)) as pdf:
            for strategy_index, settings in enumerate(_PDFPLUMBER_SETTINGS, start=1):
                all_rows: list[list[str]] = []
                pages_processed: set[int] = set()
                for page_number, page in enumerate(pdf.pages, start=1):
                    working_page = page
                    if table_definition.expected_region:
                        size = (float(page.width), float(page.height))
                        if (
                            table_definition.expected_region.page_number is None
                            or table_definition.expected_region.page_number == page_number
                        ):
                            region = table_definition.expected_region.to_absolute(*size)
                            working_page = page.crop((region.x0, region.y0, region.x1, region.y1))
                    for table in working_page.extract_tables(table_settings=settings) or []:
                        normalized = [
                            [str(cell or "").strip() for cell in row]
                            for row in table
                            if any(str(cell or "").strip() for cell in row)
                        ]
                        if normalized:
                            all_rows.extend(normalized)
                            pages_processed.add(page_number)
                result = rows_to_table_result(
                    all_rows,
                    table_definition,
                    method=f"pdfplumber_table_strategy_{strategy_index}",
                    page_number=min(pages_processed) if pages_processed else 1,
                )
                result.elapsed_seconds = time.perf_counter() - start
                if pages_processed:
                    result.pages_processed = sorted(pages_processed)
                candidates.append(result)
    except Exception as exc:
        return empty_table_result("pdfplumber_table", error=f"pdfplumber falhou: {exc}")
    if not candidates:
        return empty_table_result("pdfplumber_table", warning="pdfplumber nao retornou tabelas")
    return max(candidates, key=_score_result)


def _score_result(result: TableExtractionResult) -> tuple[Decimal, int, int]:
    penalty = Decimal("0.08") * Decimal(len(result.errors))
    return (max(Decimal("0.00"), result.confidence - penalty), result.item_count, -len(result.warnings))
