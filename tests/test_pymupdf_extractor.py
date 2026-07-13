from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from app.services.proposal_import.proposal_import_orchestrator import import_nomus_pdf
from app.services.proposal_import.pymupdf_extractor import (
    InvalidPdfError,
    PdfDocumentContext,
    PdfOpenError,
    PdfRegion,
    PdfTextExtractionError,
    PdfWithoutExtractableTextError,
    extract_pdf_context,
    horizontally_close,
    vertically_close,
    words_in_region,
)


def create_pdf(path: Path, pages: list[list[tuple[float, float, str]]]) -> Path:
    document = fitz.open()
    for page_lines in pages:
        page = document.new_page()
        for x, y, text in page_lines:
            page.insert_text((x, y), text)
    document.save(path)
    document.close()
    return path


class PyMuPdfExtractorTests(unittest.TestCase):
    def test_valid_pdf_extracts_text_blocks_words_and_coordinates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = create_pdf(
                Path(temp_dir) / "proposal.pdf",
                [[
                    (72, 72, "Orcamento ETCP 05228"),
                    (72, 92, "Cliente MNS ENGENHARIA"),
                    (72, 112, "Quantidade 1"),
                    (72, 132, "Peso 69,50"),
                ]],
            )
            context = extract_pdf_context(pdf_path)
        self.assertEqual(context.page_count, 1)
        self.assertIn("Orcamento ETCP 05228", context.full_text)
        self.assertTrue(context.has_extractable_text)
        self.assertGreater(len(context.words), 4)
        self.assertGreater(len(context.blocks), 0)
        first_word = context.words[0]
        self.assertGreaterEqual(first_word.x1, first_word.x0)
        self.assertGreaterEqual(first_word.y1, first_word.y0)
        self.assertIn("PyMuPDF", context.metadata["engine"])
        self.assertEqual(context.metadata["has_extractable_text"], True)

    def test_multiple_pages_preserve_page_separator_and_numbers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = create_pdf(
                Path(temp_dir) / "multi.pdf",
                [
                    [(72, 72, "Primeira pagina cliente MNS ENGENHARIA")],
                    [(72, 72, "Segunda pagina item 001 quantidade 1")],
                ],
            )
            context = extract_pdf_context(pdf_path)
        self.assertEqual(context.page_count, 2)
        self.assertIn("--- PAGE 1 ---", context.full_text)
        self.assertIn("--- PAGE 2 ---", context.full_text)
        self.assertTrue(any(word.page_number == 2 for word in context.words))
        self.assertTrue(any(block.page_number == 2 for block in context.blocks))

    def test_empty_pdf_reports_controlled_without_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = create_pdf(Path(temp_dir) / "empty.pdf", [[]])
            context = extract_pdf_context(pdf_path, require_text=False)
            self.assertFalse(context.has_extractable_text)
            self.assertTrue(context.text_detection.reason)
            with self.assertRaises(PdfWithoutExtractableTextError):
                extract_pdf_context(pdf_path)

    def test_invalid_and_missing_files_raise_specific_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid = Path(temp_dir) / "invalid.pdf"
            invalid.write_text("not a pdf", encoding="utf-8")
            with self.assertRaises(InvalidPdfError):
                extract_pdf_context(invalid)
            with self.assertRaises(PdfOpenError):
                extract_pdf_context(Path(temp_dir) / "missing.pdf")

    def test_context_manager_closes_document_even_after_exception(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = create_pdf(Path(temp_dir) / "ctx.pdf", [[(72, 72, "Texto suficiente para abrir o contexto")]])
            context = PdfDocumentContext(pdf_path)
            with self.assertRaises(RuntimeError):
                with context:
                    self.assertFalse(context.is_closed)
                    raise RuntimeError("falha simulada")
            self.assertTrue(context.is_closed)
            with self.assertRaises(PdfTextExtractionError):
                context.get_full_text()

    def test_coordinate_helpers(self):
        word = PdfRegion(10, 20, 30, 40)
        region = PdfRegion(0, 0, 50, 60)
        self.assertEqual(word.width, 20)
        self.assertEqual(word.height, 20)
        self.assertEqual(word.center_x, 20)
        self.assertEqual(word.center_y, 30)
        self.assertTrue(region.contains(word))
        self.assertTrue(horizontally_close(PdfRegion(0, 0, 10, 10), PdfRegion(12, 0, 20, 10), 3))
        self.assertTrue(vertically_close(PdfRegion(0, 0, 10, 10), PdfRegion(0, 2, 10, 12), 3))

    def test_words_in_region_filters_by_coordinates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = create_pdf(Path(temp_dir) / "coords.pdf", [[(72, 72, "Cliente MNS Engenharia"), (300, 300, "Fora da regiao operacional")]])
            context = extract_pdf_context(pdf_path)
        region = PdfRegion(50, 50, 200, 100)
        selected = words_in_region(context.words, region)
        self.assertTrue(any(word.text.startswith("Cliente") for word in selected))
        self.assertFalse(any(word.text.startswith("Fora") for word in selected))

    def test_orchestrator_falls_back_to_current_extractor_when_pymupdf_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = create_pdf(
                Path(temp_dir) / "fallback.pdf",
                [[
                    (72, 72, "ORCAMENTO: ETCP 05228"),
                    (72, 92, "MNS ENGENHARIA"),
                    (72, 112, "DADOS DA OBRA: OBRA TESTE"),
                    (72, 132, "PRAZO DE ENTREGA: 7 DIAS"),
                    (72, 152, "ITEM COD PROD CLIENTE DESCRICAO DO PRODUTO NCM QTD IPI ICMS PRECO UNITARIO SUB-TOTAL"),
                    (72, 172, "001 N/A ITEM TESTE 73089010 1 0 0 R$ 1,00 R$ 1,00"),
                ]],
            )
            with patch(
                "app.services.proposal_import.proposal_import_orchestrator.extract_pdf_context",
                side_effect=PdfWithoutExtractableTextError("falha simulada"),
            ):
                result = import_nomus_pdf(pdf_path)
        self.assertEqual(result.proposal_number.value, "CP05228")
        self.assertEqual(result.standard_result.metadata.extraction_method, "pdfplumber_text")
        self.assertTrue(result.standard_result.metadata.fallback_reasons)


if __name__ == "__main__":
    unittest.main()
