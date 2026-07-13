from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import fitz

from app.services.proposal_import.proposal_import_orchestrator import import_nomus_pdf
from app.services.proposal_import.pymupdf_extractor import PdfRegion, extract_pdf_context, words_in_region
from app.services.proposal_import.templates.detector import TemplateDetector
from app.services.proposal_import.templates.models import (
    AmbiguousTemplateError,
    InvalidTemplateConfigurationError,
    SCORE_CANDIDATE,
    TemplateMarker,
    TemplateRegion,
)
from app.services.proposal_import.templates.nomus_current import NomusCurrentTemplate
from app.services.proposal_import.templates.registry import TemplateRegistry, default_template_registry


def create_pdf(path: Path, pages: list[list[tuple[float, float, str]]], *, size: tuple[float, float] | None = None) -> Path:
    document = fitz.open()
    for page_lines in pages:
        page = document.new_page(width=size[0], height=size[1]) if size else document.new_page()
        for x, y, text in page_lines:
            page.insert_text((x, y), text)
    document.save(path)
    document.close()
    return path


def create_nomus_pdf(path: Path, *, shifted: bool = False, missing_order: bool = False, size: tuple[float, float] | None = None) -> Path:
    x = 96 if shifted else 72
    y = 80 if shifted else 72
    lines = [
        (x, y, "ORCAMENTO: ETCP 05228"),
        (x, y + 20, "Aparecida de Goiania, 08/06/2026"),
        (x, y + 40, "DADOS DO CLIENTE"),
        (x, y + 60, "MNS ENGENHARIA CNPJ: 00.000.000/0001-00"),
        (x, y + 80, "DADOS DA OBRA: 1101013505 - SP1FJ"),
        (x, y + 100, "PRAZO DE ENTREGA: 7 DIAS"),
    ]
    if not missing_order:
        lines.append((x, y + 120, "PEDIDO DE COMPRA: OC123"))
    lines.extend(
        [
            (x, y + 150, "ITEM COD PROD CLIENTE DESCRICAO DO PRODUTO NCM QTD PESO"),
            (x, y + 170, "001 N/A VIGA METALICA W200X15 73089010 1 PESO: 69,50 KG"),
        ]
    )
    return create_pdf(path, [lines], size=size)


class TemplateRegistryTests(unittest.TestCase):
    def test_registry_registers_orders_and_rejects_duplicates(self):
        registry = TemplateRegistry()
        template = NomusCurrentTemplate()
        registry.register(template)
        self.assertEqual(registry.get(template.template_id, template.version), template)
        self.assertEqual(registry.get_all()[0].template_id, "nomus_current")
        with self.assertRaises(InvalidTemplateConfigurationError):
            registry.register(template)

    def test_registry_empty_returns_not_found_detection(self):
        registry = TemplateRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = create_nomus_pdf(Path(temp_dir) / "nomus.pdf")
            context = extract_pdf_context(pdf)
        detection = registry.detect(context)
        self.assertEqual(detection.status, "not_found")
        self.assertIsNone(detection.selected_template_id)

    def test_default_registry_contains_nomus_template(self):
        registry = default_template_registry()
        self.assertIsNotNone(registry.get("nomus_current", "1.0"))


class NomusTemplateDetectionTests(unittest.TestCase):
    def test_detects_nomus_template_without_using_file_name_or_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = create_nomus_pdf(Path(temp_dir) / "arquivo_generico.pdf")
            context = extract_pdf_context(pdf)
            detection = default_template_registry().detect(context)
        self.assertEqual(detection.selected_template_id, "nomus_current")
        self.assertGreaterEqual(detection.confidence, SCORE_CANDIDATE)
        self.assertIn(detection.status, {"confirmed", "probable"})

    def test_incompatible_document_is_not_selected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = create_pdf(Path(temp_dir) / "other.pdf", [[(72, 72, "Documento comum sem assinatura Nomus suficiente")]])
            context = extract_pdf_context(pdf)
            detection = default_template_registry().detect(context)
        self.assertEqual(detection.status, "not_found")
        self.assertIsNone(detection.selected_template_id)

    def test_optional_markers_raise_score_but_missing_order_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with_order = extract_pdf_context(create_nomus_pdf(Path(temp_dir) / "with.pdf"))
            without_order = extract_pdf_context(create_nomus_pdf(Path(temp_dir) / "without.pdf", missing_order=True))
            template = NomusCurrentTemplate()
            first = template.evaluate(with_order)
            second = template.evaluate(without_order)
        self.assertGreaterEqual(first.score, second.score)
        self.assertTrue(second.score >= SCORE_CANDIDATE)

    def test_ambiguous_candidates_are_not_silently_selected(self):
        class AliasNomusTemplate(NomusCurrentTemplate):
            template_id = "nomus_alias"
            priority = 99

        with tempfile.TemporaryDirectory() as temp_dir:
            context = extract_pdf_context(create_nomus_pdf(Path(temp_dir) / "ambiguous.pdf"))
            registry = TemplateRegistry()
            registry.register(NomusCurrentTemplate())
            registry.register(AliasNomusTemplate())
            detection = TemplateDetector(registry).detect(context)
        self.assertTrue(detection.ambiguous)
        self.assertIsNone(detection.selected_template_id)
        self.assertEqual(AmbiguousTemplateError.__name__, "AmbiguousTemplateError")


class TemplateRegionAndFieldTests(unittest.TestCase):
    def test_relative_region_converts_to_absolute_and_filters_words(self):
        region = TemplateRegion(None, Decimal("0.10"), Decimal("0.20"), Decimal("0.50"), Decimal("0.60"))
        absolute = region.to_absolute(1000, 500)
        self.assertEqual((absolute.x0, absolute.y0, absolute.x1, absolute.y1), (100.0, 100.0, 500.0, 300.0))
        with tempfile.TemporaryDirectory() as temp_dir:
            context = extract_pdf_context(create_nomus_pdf(Path(temp_dir) / "region.pdf"))
            selected = words_in_region(context.words, PdfRegion(60, 50, 260, 180))
        self.assertTrue(any(word.text.startswith("ORCAMENTO") for word in selected))

    def test_extracts_header_fields_with_bbox_page_and_confidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            context = extract_pdf_context(create_nomus_pdf(Path(temp_dir) / "nomus.pdf"))
            result = NomusCurrentTemplate().extract_header(context)
        self.assertEqual(result.template_id, "nomus_current")
        self.assertEqual(result.fields["proposal_number"].normalized_value, "CP05228")
        self.assertEqual(result.fields["raw_budget_number"].normalized_value, "ETCP 05228")
        self.assertEqual(result.fields["proposal_date"].normalized_value, "2026-06-08")
        self.assertEqual(result.fields["client"].normalized_value, "MNS ENGENHARIA")
        self.assertEqual(result.fields["site"].normalized_value, "1101013505 - SP1FJ")
        self.assertEqual(result.fields["delivery_deadline_raw"].normalized_value, "7 DIAS")
        self.assertEqual(result.fields["purchase_order"].normalized_value, "OC123")
        self.assertIsNotNone(result.fields["proposal_number"].source_bbox)
        self.assertEqual(result.fields["proposal_number"].source_page, 1)
        self.assertGreaterEqual(result.fields["proposal_number"].confidence, Decimal("0.90"))
        self.assertIsNotNone(result.table_region)
        self.assertIsNotNone(result.table_definition)

    def test_variation_with_shifted_label_and_different_page_size_still_extracts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            context = extract_pdf_context(
                create_nomus_pdf(Path(temp_dir) / "variation.pdf", shifted=True, missing_order=True, size=(700, 900))
            )
            result = NomusCurrentTemplate().extract_header(context)
        self.assertEqual(result.fields["proposal_number"].normalized_value, "CP05228")
        self.assertEqual(result.fields["site"].normalized_value, "1101013505 - SP1FJ")
        self.assertIsNone(result.fields["purchase_order"].normalized_value)


class TemplateOrchestratorIntegrationTests(unittest.TestCase):
    def test_template_metadata_is_attached_without_changing_current_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = create_nomus_pdf(Path(temp_dir) / "nomus.pdf")
            result = import_nomus_pdf(pdf)
            current_payload = result.to_dict()
            metadata = result.standard_result.metadata
        self.assertEqual(current_payload["proposal_number"]["value"], "CP05228")
        self.assertNotIn("template_id", current_payload)
        self.assertEqual(metadata.template_id, "nomus_current")
        self.assertEqual(metadata.template_version, "1.0")
        self.assertIn(metadata.template_detection_status, {"confirmed", "probable"})
        self.assertTrue(metadata.template_candidates)
        self.assertFalse(any("R$" in str(candidate) for candidate in metadata.template_candidates))

    def test_template_complements_missing_field_without_database_or_ui(self):
        text_only_pdf_lines = [[
            (72, 72, "ORCAMENTO: ETCP 05228"),
            (72, 92, "Aparecida de Goiania, 08/06/2026"),
            (72, 112, "DADOS DO CLIENTE"),
            (72, 132, "MNS ENGENHARIA CNPJ: 00.000.000/0001-00"),
            (72, 152, "DADOS DA OBRA: OBRA TESTE"),
            (72, 172, "PRAZO DE ENTREGA: 7 DIAS"),
            (72, 192, "ITEM DESCRICAO DO PRODUTO QTD"),
            (72, 212, "001 ITEM OPERACIONAL 1"),
        ]]
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = create_pdf(Path(temp_dir) / "simple.pdf", text_only_pdf_lines)
            result = import_nomus_pdf(pdf)
        self.assertEqual(result.standard_result.metadata.template_id, "nomus_current")
        self.assertEqual(result.standard_result.metadata.extraction_method, "pymupdf_context_pdfplumber_text")


if __name__ == "__main__":
    unittest.main()
