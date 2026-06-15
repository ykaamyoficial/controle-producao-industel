from __future__ import annotations

import json
import hashlib
import os
import unittest
from pathlib import Path

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
        self.assertEqual(self.dialog.items_table.item(1, 4).text(), "Precisa confirmacao")

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
        self.dialog.items_table.item(1, 3).setText("125,5")
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


if __name__ == "__main__":
    unittest.main()
