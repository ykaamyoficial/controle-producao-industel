from __future__ import annotations

import unittest

from app.ui.proposal_import_viewmodel import (
    build_import_visual_model,
    confidence_level,
    friendly_source_name,
)


class ProposalImportPhase7ViewModelTests(unittest.TestCase):
    def test_confidence_levels_follow_approved_thresholds(self):
        self.assertEqual(confidence_level(0.96), "high")
        self.assertEqual(confidence_level(0.80), "attention")
        self.assertEqual(confidence_level(0.79), "low")
        self.assertEqual(confidence_level(0.99, conflict=True), "low")

    def test_source_names_are_friendly(self):
        self.assertEqual(friendly_source_name("template_header"), "Template do documento")
        self.assertEqual(friendly_source_name("table_pdfplumber"), "Tabela estruturada")
        self.assertEqual(friendly_source_name("nomus_rule_parser"), "Leitura textual")

    def test_visual_model_supports_metadata_and_hides_internal_names(self):
        payload = {
            "proposal_number": {"value": "CP05252", "confidence": 0.97, "needs_confirmation": False, "source": "nomus_rule_parser"},
            "client": {"value": "MNS ENGENHARIA", "confidence": 0.92, "needs_confirmation": False, "source": "template_header"},
            "site": {"value": "OBRA", "confidence": 0.65, "needs_confirmation": True, "source": "source_selector"},
            "proposal_date": {"value": "2026-06-20", "confidence": 0.98, "needs_confirmation": False, "source": "template_header"},
            "delivery_deadline_raw": {"value": "10 DIAS", "confidence": 0.83, "needs_confirmation": True, "source": "nomus_rule_parser"},
            "items": [
                {
                    "item_number": 1,
                    "product_code": "ABC",
                    "description": "ITEM TESTE",
                    "quantity": 1,
                    "weight_kg": None,
                    "confidence": 0.88,
                    "needs_confirmation": True,
                }
            ],
            "warnings": [{"message": "Prazo relativo precisa confirmacao."}],
        }
        metadata = {
            "template_id": "nomus_current",
            "extraction_method": "pymupdf_context_pdfplumber_text",
            "field_provenance": [
                {
                    "field_name": "site",
                    "selected_source": "source_selector",
                    "candidate_sources": ["template_header", "nomus_rule_parser"],
                    "selected_confidence": "0.65",
                    "conflict": True,
                    "reason": "conflito entre fontes",
                }
            ],
            "item_field_provenance": [
                {
                    "item_number": 1,
                    "field_name": "description",
                    "selected_source": "table_pdfplumber",
                    "candidate_sources": ["table_pdfplumber"],
                    "conflict": False,
                }
            ],
            "table_items_detected": 1,
        }
        visual = build_import_visual_model(payload, metadata=metadata)

        self.assertIn("1 item", visual.summary.lower())
        self.assertTrue(visual.fields["site"].conflict)
        self.assertIn("Conferencia entre leituras", visual.fields["site"].tooltip)
        self.assertIn("Peso pendente", visual.items[0].label)
        combined = "\n".join([visual.summary, visual.details, visual.fields["site"].tooltip, visual.items[0].tooltip])
        for internal in ("nomus_rule_parser", "pdfplumber", "source_selector", "pymupdf"):
            self.assertNotIn(internal, combined)

    def test_old_payload_without_metadata_remains_supported(self):
        payload = {
            "proposal_number": "CP00001",
            "client": "CLIENTE",
            "site": "OBRA",
            "proposal_date": "2026-06-20",
            "delivery_deadline_raw": "7 DIAS",
            "items": [],
            "warnings": [],
        }
        visual = build_import_visual_model(payload)

        self.assertIn("0 item", visual.summary)
        self.assertEqual(visual.warnings, [])


if __name__ == "__main__":
    unittest.main()
