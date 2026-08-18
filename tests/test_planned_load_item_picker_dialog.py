from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.planned_load_item_picker_dialog import PlannedLoadItemPickerDialog


class FakeItemPickerService:
    """Reaproveita os mesmos metodos genericos e agnosticos de etapa que a
    aba "Controle Geral" ja usa (`process_rows`/`proposal_items`) -- nao
    existe endpoint dedicado de busca para o picker de Carga Planejada."""

    def __init__(self):
        self.proposals = [
            {"id": 10, "api_id": 10, "proposta": "CP00101", "cliente": "MNS"},
            {"id": 20, "api_id": 20, "proposta": "CP00202", "cliente": "ABC"},
        ]
        self.items_by_proposal = {
            10: [
                {"id": 9001, "api_id": 9001, "numero_item": "1", "codigo_produto": "COD-A", "descricao": "Item A", "quantidade": "10"},
                {"id": 9002, "api_id": 9002, "numero_item": "2", "codigo_produto": "COD-B", "descricao": "Item B", "quantidade": "5"},
            ],
            20: [
                {"id": 9101, "api_id": 9101, "numero_item": "1", "codigo_produto": "COD-C", "descricao": "Item C", "quantidade": "8"},
            ],
        }
        self.process_rows_calls = []
        self.proposal_items_calls = []

    def process_rows(self, area, filters):
        self.process_rows_calls.append((area, filters))
        text = (filters or {}).get("text", "").strip().upper()
        if not text:
            return list(self.proposals)
        return [
            row
            for row in self.proposals
            if text in row["proposta"].upper() or text in row["cliente"].upper()
        ]

    def proposal_items(self, proposal_id):
        self.proposal_items_calls.append(proposal_id)
        return list(self.items_by_proposal.get(int(proposal_id), []))


class PlannedLoadItemPickerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = FakeItemPickerService()

    def test_construction_lists_all_proposals(self):
        dialog = PlannedLoadItemPickerDialog(self.service)
        self.assertEqual(dialog.proposals_table.rowCount(), 2)
        self.assertEqual(dialog.proposals_table.item(0, 0).text(), "CP00101")
        self.assertEqual(dialog.proposals_table.item(1, 0).text(), "CP00202")

    def test_search_filters_proposals_by_text(self):
        dialog = PlannedLoadItemPickerDialog(self.service)
        dialog.search_field.setText("ABC")
        dialog.search_proposals()
        self.assertEqual(dialog.proposals_table.rowCount(), 1)
        self.assertEqual(dialog.proposals_table.item(0, 0).text(), "CP00202")

    def test_selecting_proposal_loads_its_items(self):
        dialog = PlannedLoadItemPickerDialog(self.service)
        dialog.proposals_table.selectRow(0)
        self.assertEqual(self.service.proposal_items_calls, [10])
        self.assertEqual(dialog.items_table.rowCount(), 2)
        self.assertEqual(dialog.items_table.item(0, 0).text(), "1")
        self.assertEqual(dialog.items_table.item(0, 1).text(), "Item A")

    def test_add_to_cart_without_item_selection_shows_warning(self):
        dialog = PlannedLoadItemPickerDialog(self.service)
        dialog.proposals_table.selectRow(0)
        with patch("app.ui.planned_load_item_picker_dialog.QMessageBox.warning") as warning:
            dialog.add_selected_item_to_cart()
        warning.assert_called_once()

    def test_add_to_cart_appends_entry_with_display_fields(self):
        dialog = PlannedLoadItemPickerDialog(self.service)
        dialog.proposals_table.selectRow(0)
        dialog.items_table.selectRow(1)
        dialog.quantity_field.setValue(3.5)
        dialog.notes_field.setText("observacao")
        dialog.add_selected_item_to_cart()

        self.assertIn(9002, dialog.cart)
        entry = dialog.cart[9002]
        self.assertEqual(entry["proposal_item_id"], 9002)
        self.assertEqual(entry["planned_quantity"], 3.5)
        self.assertEqual(entry["notes"], "observacao")
        self.assertEqual(entry["proposal_number"], "CP00101")
        self.assertEqual(entry["customer_name"], "MNS")
        self.assertEqual(entry["item_number"], "2")
        self.assertEqual(entry["description"], "Item B")
        self.assertEqual(dialog.cart_table.rowCount(), 1)
        self.assertEqual(dialog.cart_table.item(0, 1).text(), "2")

    def test_add_to_cart_rejects_zero_quantity(self):
        dialog = PlannedLoadItemPickerDialog(self.service)
        dialog.proposals_table.selectRow(0)
        dialog.items_table.selectRow(0)
        dialog.quantity_field.setValue(0.0001)
        # Forca o campo para zero (o spin box normalmente ja bloqueia isso
        # pelo minimo configurado, mas o metodo tambem valida por conta
        # propria caso o minimo mude no futuro).
        dialog.quantity_field.setMinimum(0.0)
        dialog.quantity_field.setValue(0.0)
        with patch("app.ui.planned_load_item_picker_dialog.QMessageBox.warning") as warning:
            dialog.add_selected_item_to_cart()
        warning.assert_called_once()
        self.assertEqual(dialog.cart, {})

    def test_remove_from_cart(self):
        dialog = PlannedLoadItemPickerDialog(self.service)
        dialog.proposals_table.selectRow(0)
        dialog.items_table.selectRow(0)
        dialog.quantity_field.setValue(2.0)
        dialog.add_selected_item_to_cart()
        self.assertEqual(dialog.cart_table.rowCount(), 1)

        dialog.cart_table.selectRow(0)
        dialog.remove_selected_from_cart()
        self.assertEqual(dialog.cart, {})
        self.assertEqual(dialog.cart_table.rowCount(), 0)

    def test_confirm_without_cart_shows_warning_and_does_not_accept(self):
        dialog = PlannedLoadItemPickerDialog(self.service)
        with patch("app.ui.planned_load_item_picker_dialog.QMessageBox.warning") as warning:
            dialog._confirm()
        warning.assert_called_once()
        self.assertFalse(dialog.result())

    def test_confirm_with_cart_accepts_and_returns_selected_items(self):
        dialog = PlannedLoadItemPickerDialog(self.service)
        dialog.proposals_table.selectRow(1)
        dialog.items_table.selectRow(0)
        dialog.quantity_field.setValue(4.0)
        dialog.add_selected_item_to_cart()

        dialog._confirm()

        self.assertTrue(dialog.result())
        selected = dialog.get_selected_items()
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["proposal_item_id"], 9101)
        self.assertEqual(selected[0]["planned_quantity"], 4.0)
        self.assertEqual(selected[0]["proposal_number"], "CP00202")

    def test_search_error_shows_critical_message(self):
        def failing_process_rows(area, filters):
            raise RuntimeError("falha ao buscar propostas")

        self.service.process_rows = failing_process_rows
        with patch("app.ui.planned_load_item_picker_dialog.QMessageBox.critical") as critical:
            PlannedLoadItemPickerDialog(self.service)
        critical.assert_called_once()


if __name__ == "__main__":
    unittest.main()
