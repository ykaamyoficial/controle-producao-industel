from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import fitz

from app.services.proposal_import.compatibility import to_current_payload
from app.services.proposal_import.diagnostics import ImportStage
from app.services.proposal_import.proposal_ai_extractor import FakeProposalAIExtractor
from app.services.proposal_import.proposal_import_orchestrator import import_nomus_pdf
from app.services.proposal_import.source_selector import select_field_candidate
from app.services.proposal_import.provenance import FieldCandidate


def create_pipeline_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=700, height=900)
    lines = [
        (72, 70, "ORCAMENTO: ETCP 05288"),
        (72, 92, "Aparecida de Goiania, 20/06/2026"),
        (72, 116, "DADOS DO CLIENTE"),
        (72, 138, "MNS ENGENHARIA CNPJ: 00.000.000/0001-00"),
        (72, 162, "DADOS DA OBRA: SITE PIPELINE"),
        (72, 186, "PRAZO DE ENTREGA: 10 DIAS"),
        (20, 290, "ITEM"),
        (80, 290, "CODIGO"),
        (160, 290, "DESCRICAO DO PRODUTO"),
        (455, 290, "UNIDADE"),
        (505, 290, "QTDE"),
        (620, 290, "PESO"),
        (20, 315, "001"),
        (80, 315, "ABC-10"),
        (160, 315, "SUPORTE METALICO PARA ANTENA"),
        (160, 332, "COM FUROS OBLONGOS"),
        (455, 315, "UN"),
        (505, 315, "2"),
        (620, 315, "63 KG"),
        (20, 410, "TOTAL R$ 999,00"),
    ]
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=10)
    document.save(path)
    document.close()
    return path


class CountingAIExtractor(FakeProposalAIExtractor):
    def __init__(self):
        super().__init__({"site": "SITE NAO DEVE SOBRESCREVER", "total": "R$ 1.000,00"})
        self.calls = 0

    def extract(self, text: str):
        self.calls += 1
        self.last_text = text
        return super().extract(text)


class ProposalImportPipelinePhase6Tests(unittest.TestCase):
    def test_pipeline_exposes_safe_diagnostics_provenance_and_legacy_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = create_pipeline_pdf(Path(temp_dir) / "Caminho Com Empresa.pdf")
            result = import_nomus_pdf(pdf)

        standard = result.standard_result
        self.assertIsNotNone(standard)
        metadata = standard.metadata
        diagnostic = standard.build_diagnostic_summary()
        stages = [stage["stage"] for stage in metadata.pipeline_diagnostics["stages"]]
        expected_stages = {
            ImportStage.FILE_VALIDATION.value,
            ImportStage.PDF_STRUCTURE.value,
            ImportStage.TEMPLATE_DETECTION.value,
            ImportStage.HEADER_EXTRACTION.value,
            ImportStage.TEXT_EXTRACTION.value,
            ImportStage.TEXT_RULE_PARSER.value,
            ImportStage.TABLE_EXTRACTION.value,
            ImportStage.MERGE.value,
            ImportStage.NORMALIZATION.value,
            ImportStage.VALIDATION.value,
            ImportStage.CONFIDENCE.value,
            ImportStage.COMPATIBILITY.value,
        }
        self.assertTrue(expected_stages.issubset(set(stages)))
        self.assertEqual(diagnostic["template"], "nomus_current")
        self.assertTrue(metadata.field_provenance)
        self.assertTrue(metadata.item_field_provenance)
        payload = to_current_payload(standard)
        self.assertEqual(payload["proposal_number"]["value"], "CP05288")
        self.assertEqual(payload["client"]["value"], "MNS ENGENHARIA")
        serialized = json.dumps(
            {
                "payload": payload,
                "diagnostic": diagnostic,
                "pipeline": metadata.pipeline_diagnostics,
                "field_provenance": metadata.field_provenance,
            },
            ensure_ascii=False,
        ).upper()
        self.assertNotIn("R$", serialized)
        self.assertNotIn("999,00", serialized)
        self.assertNotIn(str(Path(temp_dir)).upper(), serialized)

    def test_pipeline_is_deterministic_ignoring_timings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = create_pipeline_pdf(Path(temp_dir) / "deterministic.pdf")
            first = import_nomus_pdf(pdf).standard_result
            second = import_nomus_pdf(pdf).standard_result
        self.assertEqual(first.proposal.to_dict(), second.proposal.to_dict())
        self.assertEqual([item.to_dict() for item in first.items], [item.to_dict() for item in second.items])
        self.assertEqual(first.metadata.field_provenance, second.metadata.field_provenance)
        self.assertEqual(first.metadata.item_field_provenance, second.metadata.item_field_provenance)

    def test_ai_and_rule_parser_are_not_executed_twice_inside_pdf_pipeline(self):
        ai = CountingAIExtractor()
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = create_pipeline_pdf(Path(temp_dir) / "single_flow.pdf")
            with patch("app.services.proposal_import.proposal_import_orchestrator.parse_nomus_text") as parse_mock:
                from app.services.proposal_import.nomus_rule_parser import parse_nomus_text

                parse_mock.side_effect = parse_nomus_text
                result = import_nomus_pdf(pdf, ai_extractor=ai)
        self.assertEqual(parse_mock.call_count, 1)
        self.assertEqual(ai.calls, 1)
        self.assertEqual(result.site.value, "SITE PIPELINE")
        self.assertNotIn("R$", ai.last_text)

    def test_table_failure_is_diagnostic_fallback_without_losing_parser_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = create_pipeline_pdf(Path(temp_dir) / "table_failure.pdf")
            with patch(
                "app.services.proposal_import.proposal_import_orchestrator.extract_and_merge_table_items",
                side_effect=RuntimeError(r"C:\\segredo\\falha R$ 10,00"),
            ):
                result = import_nomus_pdf(pdf)
        self.assertEqual(result.proposal_number.value, "CP05288")
        self.assertTrue(result.items)
        diagnostic = result.standard_result.metadata.pipeline_diagnostics
        table_stage = next(stage for stage in diagnostic["stages"] if stage["stage"] == ImportStage.TABLE_EXTRACTION.value)
        self.assertEqual(table_stage["status"], "failed")
        self.assertTrue(table_stage["fallback_used"])
        serialized = json.dumps(diagnostic, ensure_ascii=False).upper()
        self.assertNotIn("C:\\SEGREDO", serialized)
        self.assertNotIn("R$ 10,00", serialized)

    def test_source_selector_treats_spaced_proposal_numbers_as_equivalent(self):
        selected, provenance, message = select_field_candidate(
            "proposal_number",
            [
                FieldCandidate("proposal_number", "CP05288", "rule_parser", Decimal("0.86")),
                FieldCandidate("proposal_number", "CP 05288", "template:region", Decimal("0.94")),
            ],
            preferred_source="rule_parser",
        )
        self.assertEqual(selected.source, "rule_parser")
        self.assertTrue(provenance.agreement)
        self.assertIn("concordam", message)


if __name__ == "__main__":
    unittest.main()
