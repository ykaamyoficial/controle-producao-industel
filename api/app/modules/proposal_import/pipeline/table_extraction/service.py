from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..pymupdf_extractor import PdfExtractionContext
from ..schemas import ProposalImportItem
from ..templates.models import TemplateExtractionResult
from .coordinate_extractor import extract_with_coordinates
from .merger import merge_table_items
from .models import TableExtractionResult, TableMergeResult, empty_table_result
from .pdfplumber_extractor import extract_with_pdfplumber


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableProcessingResult:
    extraction: TableExtractionResult
    merge: TableMergeResult
    strategy_results: list[TableExtractionResult]

    def metadata(self) -> dict[str, object]:
        return {
            "table_extraction_method": self.extraction.method,
            "table_extraction_confidence": str(self.extraction.confidence),
            "table_pages_processed": list(self.extraction.pages_processed),
            "table_rows_detected": len(self.extraction.rows),
            "table_items_detected": self.extraction.item_count,
            "table_warnings": list(self.extraction.warnings) + list(self.merge.warnings),
            "table_fallback_reasons": list(self.merge.fallback_reasons),
            "table_comparison_summary": dict(self.merge.comparison_summary),
        }


def extract_and_merge_table_items(
    pdf_path: str | Path,
    context: PdfExtractionContext | None,
    template_extraction: TemplateExtractionResult | None,
    current_items: list[ProposalImportItem],
) -> TableProcessingResult:
    if not template_extraction or not template_extraction.table_definition:
        extraction = empty_table_result("structured_table", warning="template sem definicao de tabela")
        return TableProcessingResult(extraction, merge_table_items(current_items, extraction), [extraction])

    table_definition = template_extraction.table_definition
    strategy_results = [
        extract_with_pdfplumber(pdf_path, table_definition),
        extract_with_coordinates(context, table_definition),
    ]
    selected = max(strategy_results, key=_score_result)
    logger.info(
        "Extracao de tabela Nomus: metodo=%s confianca=%s itens=%s avisos=%s erros=%s",
        selected.method,
        selected.confidence,
        selected.item_count,
        len(selected.warnings),
        len(selected.errors),
    )
    merge = merge_table_items(current_items, selected)
    return TableProcessingResult(selected, merge, strategy_results)


def _score_result(result: TableExtractionResult) -> tuple[Decimal, int, int]:
    penalty = Decimal("0.08") * Decimal(len(result.errors))
    return (max(Decimal("0.00"), result.confidence - penalty), result.item_count, -len(result.warnings))
