from __future__ import annotations

import json
import hashlib
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from app.ui.process_form_dialog import ProcessFormDialog
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


def model_pdf_path() -> Path | None:
    configured = os.environ.get("NOMUS_PDF_TEST_FILE")
    if configured and Path(configured).is_file():
        return Path(configured)
    matches = sorted((Path.home() / "Downloads").glob("CP 05228*.pdf"))
    return matches[0] if matches else None


class ProposalImportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.pdf_path = model_pdf_path()
        if not cls.pdf_path:
            raise unittest.SkipTest("PDF modelo ausente para teste visual isolado.")

    def setUp(self):
        self.dialog = ProposalImportDialog(pdf_path=self.pdf_path)

    def tearDown(self):
        self.dialog.close()

    def test_loads_editable_operational_preview(self):
        self.assertEqual(self.dialog.fields["proposal_number"].text(), "CP05228")
        self.assertEqual(self.dialog.fields["client"].text(), "MNS ENGENHARIA")
        self.assertEqual(self.dialog.items_table.rowCount(), 2)
        self.assertFalse(self.dialog.fields["client"].isReadOnly())
        self.assertEqual(self.dialog.items_table.item(0, 1).text(), "450.983")
        self.assertEqual(self.dialog.items_table.item(1, 6).text(), "Peso pendente")

    def test_validates_in_memory_without_service_or_database(self):
        self.assertTrue(self.dialog.validate_import())
        prepared = self.dialog.prepared_data
        self.assertIsNotNone(prepared)
        self.assertEqual(prepared["proposal_number"], "CP05228")
        self.assertEqual(prepared["items"][0]["weight_kg"], 69.5)
        self.assertIsNone(prepared["items"][1]["weight_kg"])
        self.assertEqual(
            prepared["source_file_sha256"],
            hashlib.sha256(self.pdf_path.read_bytes()).hexdigest(),
        )
        self.assertNotIn("service", self.dialog.__dict__)

    def test_manual_correction_is_reflected_in_prepared_data(self):
        self.dialog.fields["client"].setText("CLIENTE CONFERIDO")
        self.dialog.items_table.item(1, 5).setText("125,5")
        self.assertTrue(self.dialog.validate_import())
        self.assertEqual(self.dialog.prepared_data["client"], "CLIENTE CONFERIDO")
        self.assertEqual(self.dialog.prepared_data["items"][1]["weight_kg"], 125.5)
        self.assertFalse(self.dialog.prepared_data["items"][1]["weight_needs_confirmation"])

    def test_missing_required_field_is_rejected(self):
        self.dialog.fields["client"].clear()
        self.assertFalse(self.dialog.validate_import())
        self.assertIsNone(self.dialog.prepared_data)
        self.assertEqual(self.dialog.fields["client"].property("validationState"), "error")

    def test_interface_and_prepared_result_have_no_financial_content(self):
        visible_labels = " ".join(
            label.text() for label in self.dialog.findChildren(QLabel)
        ).upper()
        prepared = json.dumps(self.dialog.collect_data(), ensure_ascii=False).upper()
        for forbidden in FORBIDDEN_TEXT:
            self.assertNotIn(forbidden, visible_labels)
            self.assertNotIn(forbidden, prepared)

    def test_new_process_form_only_exposes_preview_entry_point(self):
        form = ProcessFormDialog(object())
        try:
            buttons = [button.text() for button in form.findChildren(QPushButton)]
            self.assertIn("Conferir PDF Nomus", buttons)
        finally:
            form.close()

    def test_use_button_accepts_only_validated_data(self):
        self.dialog.fields["client"].clear()
        self.dialog.use_data_in_registration()
        self.assertNotEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
        self.dialog.fields["client"].setText("MNS ENGENHARIA")
        self.dialog.use_data_in_registration()
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)

    def test_fallback_to_legacy_parser_keeps_dialog_usable(self):
        legacy_payload = {
            "proposal_number": "CP99999",
            "client": "CLIENTE LEGADO",
            "site": "OBRA LEGADA",
            "proposal_date": "2026-06-20",
            "delivery_deadline_raw": "7 DIAS",
            "delivery_deadline_needs_confirmation": True,
            "purchase_order": None,
            "lot": None,
            "items": [
                {
                    "item_number": 1,
                    "description": "ITEM LEGADO",
                    "quantity": 1,
                    "weight_kg": None,
                    "weight_needs_confirmation": True,
                }
            ],
            "warnings": [],
        }
        with patch(
            "app.ui.proposal_import_dialog.import_nomus_pdf_hybrid",
            side_effect=ValueError("falha hibrida"),
        ), patch(
            "app.ui.proposal_import_dialog.parse_nomus_pdf_legacy",
            return_value=SimpleNamespace(to_dict=lambda: legacy_payload),
        ):
            dialog = ProposalImportDialog(pdf_path=self.pdf_path)
        try:
            self.assertTrue(dialog.loaded_with_fallback)
            self.assertEqual(dialog.fields["proposal_number"].text(), "CP99999")
            self.assertIn("fallback", dialog.alerts_label.text().lower())
        finally:
            dialog.close()

    def test_low_confidence_field_is_marked_for_review(self):
        payload = {
            "proposal_number": {"value": "CP99998", "confidence": 0.96, "needs_confirmation": False},
            "raw_budget_number": {"value": "ETCP 99998", "confidence": 0.96, "needs_confirmation": False},
            "client": {"value": "CLIENTE INCERTO", "confidence": 0.45, "needs_confirmation": True},
            "site": {"value": "OBRA", "confidence": 0.95, "needs_confirmation": False},
            "proposal_date": {"value": "2026-06-20", "confidence": 0.9, "needs_confirmation": False},
            "delivery_deadline_raw": {"value": "7 DIAS", "confidence": 0.93, "needs_confirmation": True},
            "items": [],
            "warnings": [{"message": "Cliente identificado com baixa confianca."}],
        }
        with patch(
            "app.ui.proposal_import_dialog.import_nomus_pdf_hybrid",
            return_value=SimpleNamespace(to_dict=lambda: payload),
        ):
            dialog = ProposalImportDialog(pdf_path=self.pdf_path)
        try:
            self.assertEqual(dialog.fields["client"].property("validationState"), "warning")
            self.assertIn("baixa confianca", dialog.alerts_label.text().lower())
        finally:
            dialog.close()

    def test_real_nomus_pdfs_load_expected_operational_fields(self):
        expected = {
            "CP 05252.pdf": ("CP05252", "MNS ENGENHARIA", "MTCMX001 - MTCZN13 - WINITY - CLARO", "10 DIAS", "63"),
            "CP 05242.pdf": ("CP05242", "MNS ENGENHARIA", "SITE - 66010031 - SN - NVUMI", "7 DIAS", ""),
            "CP 05234.pdf": ("CP05234", "MNS ENGENHARIA", "6105001101 - 5G - BSA025", "10 DIAS", ""),
        }
        missing = [name for name in expected if not (Path.home() / "Downloads" / name).is_file()]
        if missing:
            self.skipTest(f"PDFs reais ausentes: {', '.join(missing)}")
        for name, (proposal, client, site, deadline, first_weight) in expected.items():
            dialog = ProposalImportDialog(pdf_path=Path.home() / "Downloads" / name)
            try:
                self.assertEqual(dialog.fields["proposal_number"].text(), proposal)
                self.assertEqual(dialog.fields["client"].text(), client)
                self.assertEqual(dialog.fields["site"].text(), site)
                self.assertEqual(dialog.fields["delivery_deadline_raw"].text(), deadline)
                self.assertEqual(dialog.items_table.item(0, 4).text(), first_weight)
                prepared = json.dumps(dialog.collect_data(), ensure_ascii=False).upper()
                for forbidden in FORBIDDEN_TEXT:
                    self.assertNotIn(forbidden, prepared)
            finally:
                dialog.close()


if __name__ == "__main__":
    unittest.main()
