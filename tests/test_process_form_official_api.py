from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.process_form_dialog import ProcessFormDialog


class OfficialServiceSpy:
    def __init__(self, *, fail: Exception | None = None):
        self.fail = fail
        self.save_calls = []

    def official_proposals_enabled(self):
        return True

    def can_edit_process(self):
        return True

    def item_no_production_reasons(self):
        return [("pronta_entrega", "Pronta entrega")]

    def save_process(self, data, process_id=None, import_metadata=None):
        self.save_calls.append((data, process_id, import_metadata))
        if self.fail:
            raise self.fail
        return 123

    def get_process_dict(self, _process_id):
        return {
            "id": 10,
            "api_version": 4,
            "proposta": "CP00010",
            "cliente": "Cliente",
            "status_localizacao": "AGUARDANDO_LIBERACAO",
            "localizacao_atual": "CONTROLE_GERAL",
        }

    def proposal_items(self, _process_id):
        return [
            {
                "api_id": 50,
                "api_version": 2,
                "numero_item": "1",
                "codigo_produto": "COD",
                "descricao": "Item oficial",
                "quantidade": "2",
                "peso": "3.5",
                "processo_atual_id": 10,
            }
        ]


class ProcessFormOfficialApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_official_save_uses_service_payload_without_financial_fields(self):
        service = OfficialServiceSpy()
        form = ProcessFormDialog(service)
        try:
            form.fields["proposta"].setText("CP00001")
            form.fields["cliente"].setText("Cliente")
            form.fields["data_entrada"].setText("21/07/2026")
            form.add_item("1", "COD", "Descricao", "2", "3.5")
            form.save()

            self.assertEqual(len(service.save_calls), 1)
            data, process_id, metadata = service.save_calls[0]
            self.assertIsNone(process_id)
            self.assertIsNone(metadata)
            self.assertEqual(data["proposta"], "CP00001")
            self.assertEqual(data["itens"][0]["descricao"], "Descricao")
            self.assertNotIn("valor_total", data)
            self.assertNotIn("price", data)
        finally:
            form.close()

    def test_failure_keeps_form_open_and_data_available(self):
        service = OfficialServiceSpy(fail=RuntimeError("servidor indisponivel"))
        form = ProcessFormDialog(service)
        try:
            form.fields["proposta"].setText("CP00002")
            form.fields["cliente"].setText("Cliente")
            form.add_item("1", "COD", "Descricao", "1", "1")
            with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok):
                form.save()
            self.assertNotEqual(form.result(), form.DialogCode.Accepted)
            self.assertEqual(form.fields["proposta"].text(), "CP00002")
            self.assertEqual(len(service.save_calls), 1)
        finally:
            form.close()

    def test_edit_load_preserves_official_item_identity(self):
        service = OfficialServiceSpy()
        form = ProcessFormDialog(service, process_id=10)
        try:
            number = form.items_table.item(0, 0)
            self.assertEqual(number.data(Qt.UserRole), 50)
            self.assertEqual(number.data(Qt.UserRole + 1), 2)
            form.save()
            data, process_id, _metadata = service.save_calls[0]
            self.assertEqual(process_id, 10)
            self.assertEqual(data["itens"][0]["api_id"], 50)
            self.assertEqual(data["itens"][0]["api_version"], 2)
        finally:
            form.close()


if __name__ == "__main__":
    unittest.main()
