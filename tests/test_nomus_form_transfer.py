from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.process_form_dialog import ProcessFormDialog


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "app" / "data" / "controle_producao.db"


class ServiceSpy:
    def __init__(self):
        self.save_calls = []

    def save_process(self, *args, **kwargs):
        self.save_calls.append((args, kwargs))
        return 1


def reviewed_data() -> dict:
    return {
        "source": "nomus_pdf",
        "source_file_name": "proposta.pdf",
        "source_file_sha256": "a" * 64,
        "proposal_number": "CP05228",
        "client": "MNS ENGENHARIA",
        "site": "1101013505 - SP1FJ",
        "proposal_date": "2026-06-08",
        "delivery_deadline_raw": "7 DIAS",
        "delivery_deadline_needs_confirmation": True,
        "purchase_order": None,
        "lot": None,
        "items": [
            {
                "item_number": 1,
                "description": "VIGA METALICA I W200x15",
                "quantity": 1,
                "weight_kg": 69.5,
                "weight_needs_confirmation": False,
            },
            {
                "item_number": 2,
                "description": "TUBO 76 X 3,75 X 3000MM",
                "quantity": 6,
                "weight_kg": None,
                "weight_needs_confirmation": True,
            },
        ],
        "warnings": [],
    }


class NomusFormTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = ServiceSpy()
        self.form = ProcessFormDialog(self.service)
        self.db_hash_before = self._db_hash()
        self.db_time_before = DATABASE.stat().st_mtime_ns

    def tearDown(self):
        self.form.close()

    @staticmethod
    def _db_hash():
        return hashlib.sha256(DATABASE.read_bytes()).hexdigest()

    def assert_database_unchanged(self):
        self.assertEqual(self._db_hash(), self.db_hash_before)
        self.assertEqual(DATABASE.stat().st_mtime_ns, self.db_time_before)

    def test_transfers_operational_fields_and_items(self):
        self.assertTrue(self.form.apply_import_data(reviewed_data()))
        self.assertEqual(self.form.fields["proposta"].text(), "CP05228")
        self.assertEqual(self.form.fields["cliente"].text(), "MNS ENGENHARIA")
        self.assertEqual(self.form.fields["obra_site"].text(), "1101013505 - SP1FJ")
        self.assertEqual(self.form.fields["data_entrada"].text(), "2026-06-08")
        self.assertEqual(self.form.items_table.rowCount(), 2)
        self.assertEqual(self.form.items_table.item(0, 2).text(), "1")
        self.assertEqual(self.form.items_table.item(1, 2).text(), "6")
        self.assertEqual(self.form.items_table.item(0, 3).text(), "69.5")
        self.assertEqual(self.form.items_table.item(1, 3).text(), "")
        self.assertEqual(self.service.save_calls, [])
        self.assertEqual(self.form.import_metadata["hash_sha256"], "a" * 64)
        self.assert_database_unchanged()

    def test_relative_deadline_is_not_transferred(self):
        self.assertTrue(self.form.apply_import_data(reviewed_data()))
        self.assertEqual(self.form.fields["prazo_entrega"].text(), "")
        self.assertIn("7 DIAS", self.form.import_notice.text())

    def test_confirmed_deadline_is_transferred(self):
        data = reviewed_data()
        data["delivery_deadline_raw"] = "2026-06-15"
        data["delivery_deadline_needs_confirmation"] = False
        self.assertTrue(self.form.apply_import_data(data))
        self.assertEqual(self.form.fields["prazo_entrega"].text(), "2026-06-15")

    def test_missing_required_data_prevents_transfer(self):
        data = reviewed_data()
        data["client"] = ""
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok):
            self.assertFalse(self.form.apply_import_data(data))
        self.assertEqual(self.form.fields["proposta"].text(), "")
        self.assertEqual(self.service.save_calls, [])

    def test_existing_manual_data_requires_confirmation(self):
        self.form.fields["cliente"].setText("CLIENTE MANUAL")
        decisions = []
        result = self.form.apply_import_data(
            reviewed_data(),
            confirm_overwrite=lambda conflicts: decisions.append(conflicts) or False,
        )
        self.assertFalse(result)
        self.assertEqual(self.form.fields["cliente"].text(), "CLIENTE MANUAL")
        self.assertTrue(any("Cliente" in conflict for conflict in decisions[0]))

    def test_manual_total_weight_is_not_cleared_without_confirmation(self):
        self.form.fields["peso"].setText("999")
        captured = []
        self.assertFalse(
            self.form.apply_import_data(
                reviewed_data(),
                confirm_overwrite=lambda conflicts: captured.extend(conflicts) or False,
            )
        )
        self.assertEqual(self.form.fields["peso"].text(), "999")
        self.assertTrue(any("Peso total" in conflict for conflict in captured))

    def test_same_proposal_already_typed_generates_warning(self):
        self.form.fields["proposta"].setText("CP05228")
        captured = []
        self.assertFalse(
            self.form.apply_import_data(
                reviewed_data(),
                confirm_overwrite=lambda conflicts: captured.extend(conflicts) or False,
            )
        )
        self.assertTrue(any("mesmo numero" in conflict for conflict in captured))

    def test_financial_fields_are_never_transferred(self):
        data = reviewed_data()
        data.update(
            {
                "price": 1920,
                "subtotal": 5220,
                "tax": "19%",
                "payment": "30 dias",
                "currency": "BRL",
            }
        )
        self.assertTrue(self.form.apply_import_data(data))
        serialized = json.dumps(
            {
                key: field.text()
                for key, field in self.form.fields.items()
                if hasattr(field, "text")
            },
            ensure_ascii=False,
        ).upper()
        for forbidden in ("1920", "5220", "19%", "30 DIAS", "BRL"):
            self.assertNotIn(forbidden, serialized)

    def test_save_service_is_called_only_after_explicit_save(self):
        self.assertTrue(self.form.apply_import_data(reviewed_data()))
        self.assertEqual(self.service.save_calls, [])
        self.form.save()
        self.assertEqual(len(self.service.save_calls), 1)


if __name__ == "__main__":
    unittest.main()
