from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from app.ui.process_form_dialog import ProcessFormDialog


class FakeService:
    def can_edit_process(self):
        return True


class FakeDisabledService:
    def can_edit_process(self):
        return False


class FakeStore:
    def __init__(self, *, enabled=True, configured=True):
        self.enabled = enabled
        self.configured = configured

    def load_settings(self):
        return type(
            "Settings",
            (),
            {
                "enabled": self.enabled,
                "base_url": "https://nomus.example/rest",
                "api_key_configured": self.configured,
            },
        )()


API_PAYLOAD = {
    "source": "nomus_api",
    "proposal_number": "CP05252",
    "client": "MNS ENGENHARIA",
    "site": "OBRA API",
    "proposal_date": "19/06/2026",
    "delivery_deadline_raw": "29/06/2026",
    "delivery_deadline_needs_confirmation": False,
    "purchase_order": "OC-123",
    "lot": "L01",
    "items": [
        {
            "item_number": 1,
            "product_code": "450.983",
            "description": "ITEM API",
            "unit": "UN",
            "quantity": 2,
            "weight_kg": 63.5,
            "weight_needs_confirmation": False,
        }
    ],
    "warnings": [],
}


class NomusApiFormIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _button_by_text(self, form, text):
        for button in form.findChildren(QPushButton):
            if button.text() == text:
                return button
        return None

    @patch("app.services.nomus_api_config.NomusApiConfigStore", return_value=FakeStore())
    def test_new_form_shows_enabled_nomus_api_button_when_configured(self, _store):
        form = ProcessFormDialog(FakeService())
        try:
            button = self._button_by_text(form, "Importar do Nomus")

            self.assertIsNotNone(button)
            self.assertTrue(button.isEnabled())
        finally:
            form.close()

    @patch("app.services.nomus_api_config.NomusApiConfigStore", return_value=FakeStore())
    def test_api_button_is_disabled_without_edit_permission(self, _store):
        form = ProcessFormDialog(FakeDisabledService())
        try:
            button = self._button_by_text(form, "Importar do Nomus")

            self.assertIsNotNone(button)
            self.assertFalse(button.isEnabled())
        finally:
            form.close()

    @patch("app.services.nomus_api_config.NomusApiConfigStore", return_value=FakeStore())
    def test_api_payload_fills_form_without_pdf_metadata(self, _store):
        form = ProcessFormDialog(FakeService())
        try:
            self.assertTrue(form.apply_import_data(API_PAYLOAD, confirm_overwrite=lambda _conflicts: True))

            self.assertEqual(form.fields["proposta"].text(), "CP05252")
            self.assertEqual(form.fields["cliente"].text(), "MNS ENGENHARIA")
            self.assertEqual(form.fields["obra_site"].text(), "OBRA API")
            self.assertEqual(form.items_table.rowCount(), 1)
            self.assertEqual(form.items_table.item(0, 1).text(), "450.983")
            self.assertIsNone(form.import_metadata)
        finally:
            form.close()


if __name__ == "__main__":
    unittest.main()
