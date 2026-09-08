from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from app.ui.proposal_import_dialog import ProposalImportDialog


FORBIDDEN_TEXT = (
    "R$",
    "PRECO",
    "VALOR UNITARIO",
    "SUBTOTAL",
    "IMPOSTO",
    "PAGAMENTO",
    "FRETE",
    "ICMS",
    "DESCONTO",
)


def _fake_result(payload: dict, metadata: dict | None = None, confidence: str = "0.88"):
    standard = SimpleNamespace(
        metadata=SimpleNamespace(to_dict=lambda: metadata or {}),
        overall_confidence=confidence,
        build_diagnostic_summary=lambda: (metadata or {}).get("diagnostic_summary", {}),
    )
    return SimpleNamespace(to_dict=lambda: payload, standard_result=standard)


class ProposalImportDialogPhase7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf_path = Path(self.temp_dir.name) / "proposta.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 fake")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _payload(self):
        return {
            "proposal_number": {"value": "CP05252", "confidence": 0.97, "needs_confirmation": False, "source": "nomus_rule_parser"},
            "raw_budget_number": {"value": "ETCP 05252", "confidence": 0.97, "needs_confirmation": False, "source": "nomus_rule_parser"},
            "client": {"value": "MNS ENGENHARIA", "confidence": 0.93, "needs_confirmation": False, "source": "template_header"},
            "site": {"value": "MTCMX001", "confidence": 0.64, "needs_confirmation": True, "source": "source_selector"},
            "proposal_date": {"value": "2026-06-20", "confidence": 0.98, "needs_confirmation": False, "source": "template_header"},
            "delivery_deadline_raw": {"value": "10 DIAS", "confidence": 0.86, "needs_confirmation": True, "source": "nomus_rule_parser"},
            "items": [
                {
                    "item_number": 1,
                    "product_code": "450.983",
                    "description": "VIGA METALICA",
                    "unit": "UN",
                    "quantity": 1,
                    "weight_kg": None,
                    "confidence": 0.88,
                    "needs_confirmation": True,
                }
            ],
            "warnings": [{"message": "Prazo relativo precisa confirmacao."}],
        }

    def _metadata(self):
        return {
            "template_id": "nomus_current",
            "extraction_method": "pymupdf_context_pdfplumber_text",
            "field_provenance": [
                {
                    "field_name": "site",
                    "selected_source": "source_selector",
                    "candidate_sources": ["template_header", "nomus_rule_parser"],
                    "selected_confidence": "0.64",
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

    def test_dialog_renders_confidence_source_and_review_warnings(self):
        with patch(
            "app.ui.proposal_import_dialog.import_nomus_pdf_hybrid",
            return_value=_fake_result(self._payload(), self._metadata()),
        ):
            dialog = ProposalImportDialog(pdf_path=self.pdf_path)
        try:
            self.assertIn("confianca geral", dialog.import_summary_label.text().lower())
            self.assertEqual(dialog.fields["site"].property("validationState"), "warning")
            self.assertIn("Conferencia entre leituras", dialog.fields["site"].toolTip())
            self.assertEqual(dialog.items_table.item(0, 6).text(), "Peso pendente")
            self.assertIn("Tabela estruturada", dialog.items_table.item(0, 2).toolTip())
            self.assertIn("sem peso", dialog.alerts_label.text().lower())
        finally:
            dialog.close()

    def test_dialog_does_not_expose_internal_sources_or_financial_content(self):
        payload = self._payload()
        payload["warnings"] = [
            {"message": "Linha com R$ e valor unitario descartada."},
            {"message": "Campo operacional precisa revisao."},
        ]
        with patch(
            "app.ui.proposal_import_dialog.import_nomus_pdf_hybrid",
            return_value=_fake_result(payload, self._metadata()),
        ):
            dialog = ProposalImportDialog(pdf_path=self.pdf_path)
        try:
            visible = " ".join(label.text() for label in dialog.findChildren(QLabel)).upper()
            tooltips = " ".join(
                [
                    dialog.fields["site"].toolTip(),
                    dialog.items_table.item(0, 2).toolTip(),
                    dialog.items_table.item(0, 6).toolTip(),
                ]
            )
            prepared = json.dumps(dialog.collect_data(), ensure_ascii=False).upper()
            for forbidden in FORBIDDEN_TEXT:
                self.assertNotIn(forbidden, visible)
                self.assertNotIn(forbidden, prepared)
            for internal in ("nomus_rule_parser", "pdfplumber", "source_selector", "pymupdf"):
                self.assertNotIn(internal, tooltips)
        finally:
            dialog.close()

    def test_manual_field_edit_is_marked_only_in_memory(self):
        with patch(
            "app.ui.proposal_import_dialog.import_nomus_pdf_hybrid",
            return_value=_fake_result(self._payload(), self._metadata()),
        ):
            dialog = ProposalImportDialog(pdf_path=self.pdf_path)
        try:
            dialog.fields["client"].setText("CLIENTE REVISADO")
            dialog._mark_field_reviewed("client")
            self.assertIn("ajustado manualmente", dialog.fields["client"].toolTip().lower())
            data = dialog.collect_data()
            self.assertEqual(data["client"], "CLIENTE REVISADO")
            self.assertNotIn("metadata", data)
        finally:
            dialog.close()

    def test_legacy_payload_still_loads_without_metadata(self):
        legacy_payload = {
            "proposal_number": "CP00001",
            "client": "CLIENTE",
            "site": "OBRA",
            "proposal_date": "2026-06-20",
            "delivery_deadline_raw": "7 DIAS",
            "delivery_deadline_needs_confirmation": True,
            "items": [
                {"item_number": 1, "description": "ITEM", "quantity": 1, "weight_kg": None}
            ],
            "warnings": [],
        }
        with patch(
            "app.ui.proposal_import_dialog.import_nomus_pdf_hybrid",
            return_value=SimpleNamespace(to_dict=lambda: legacy_payload),
        ):
            dialog = ProposalImportDialog(pdf_path=self.pdf_path)
        try:
            self.assertEqual(dialog.fields["proposal_number"].text(), "CP00001")
            self.assertEqual(dialog.items_table.item(0, 6).text(), "Peso pendente")
            self.assertTrue(dialog.collect_data()["items"][0]["weight_needs_confirmation"])
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
