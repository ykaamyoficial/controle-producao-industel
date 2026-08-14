from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from app.ui.production_registration_dialog import ProductionRegistrationDialog, ProductionReviewDialog


class FakeProductionRegistrationService:
    def __init__(self):
        self.writes = []

    def get_process_area_dict(self, process_id, _area):
        return {"proposta": f"CP{process_id}", "cliente": f"Cliente {process_id}"}

    def proposal_items(self, process_id, pending_production=False, pending_delivery=False):
        rows = [
            {
                "id": process_id * 10 + 1,
                "api_id": process_id * 10 + 1,
                "processo_atual_id": process_id,
                "numero_item": "1",
                "codigo_produto": "COD-1",
                "descricao": "Base",
                "quantidade": "10",
                "peso": "2",
                "produzido": False,
                "produzir_internamente": "sim",
            },
            {
                "id": process_id * 10 + 2,
                "api_id": process_id * 10 + 2,
                "processo_atual_id": process_id,
                "numero_item": "2",
                "codigo_produto": "COD-2",
                "descricao": "Acabado",
                "quantidade": "4",
                "peso": "",
                "produzido": True,
                "produzir_internamente": "sim",
            },
        ]
        if pending_production:
            return [row for row in rows if not row["produzido"]]
        return rows

    def next_status_options(self, _area, _process_id):
        return ["FINALIZADO", "FINALIZADO_PARCIAL"]

    def update_status(self, *args, **kwargs):
        self.writes.append((args, kwargs))


class ProductionRegistrationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_groups_proposals_and_preserves_selection_when_filtered(self):
        dialog = ProductionRegistrationDialog(FakeProductionRegistrationService(), [1, 2])

        self.assertEqual(dialog.tree.topLevelItemCount(), 2)
        self.assertEqual(len(dialog._items_by_id), 4)
        dialog._set_all(True)
        self.assertEqual(dialog.selected_item_ids, {11, 21})

        dialog.search.setText("CP1")
        self.assertEqual(dialog.selected_item_ids, {11, 21})
        self.assertFalse(dialog.tree.topLevelItem(0).isHidden())
        self.assertTrue(dialog.tree.topLevelItem(1).isHidden())
        dialog.reject()

    def test_proposal_checkbox_is_tri_state_and_excludes_produced_items(self):
        dialog = ProductionRegistrationDialog(FakeProductionRegistrationService(), [1])
        dialog._set_all(True)
        group = dialog.tree.topLevelItem(0)
        self.assertEqual(group.checkState(0).value, 2)
        dialog.selected_item_ids.clear()
        dialog._render()
        group = dialog.tree.topLevelItem(0)
        item = group.child(0)
        item.setCheckState(0, Qt.Checked)
        self.assertIn(11, dialog.selected_item_ids)
        self.assertNotIn(12, dialog.selected_item_ids)
        dialog._set_all(False)
        self.assertEqual(dialog.footer_summary.text().split(" |")[0], "0 item(ns)")
        dialog.reject()

    def test_review_and_revalidation_do_not_write_before_final_confirmation(self):
        service = FakeProductionRegistrationService()
        dialog = ProductionRegistrationDialog(service, [1])
        dialog._set_all(True)
        group = {**dialog._groups[0], "selected": list(dialog._groups[0]["available"])}
        valid, message = dialog._revalidate([group])
        self.assertTrue(valid, message)
        self.assertEqual(service.writes, [])
        dialog.reject()

    def test_clicking_item_row_toggles_without_touching_the_checkbox(self):
        dialog = ProductionRegistrationDialog(FakeProductionRegistrationService(), [1])
        item = dialog.tree.topLevelItem(0).child(0)
        dialog._item_clicked(item, 2)
        self.assertIn(11, dialog.selected_item_ids)
        dialog._item_clicked(item, 2)
        self.assertNotIn(11, dialog.selected_item_ids)
        dialog.reject()

    def test_clicking_empty_tree_area_is_ignored(self):
        dialog = ProductionRegistrationDialog(FakeProductionRegistrationService(), [1])
        dialog._item_clicked(None, 1)
        self.assertEqual(dialog.selected_item_ids, set())
        dialog.reject()

    def test_review_button_is_labeled_confirmar_producao(self):
        dialog = ProductionRegistrationDialog(FakeProductionRegistrationService(), [1])
        self.assertEqual(dialog.review_button.text(), "Confirmar producao")
        dialog.reject()

    def test_review_dialog_constructs_without_crashing_on_the_real_weight_field(self):
        # Regressao: ProductionReviewDialog lia row["weight"], mas o campo
        # calculado em ProductionRegistrationDialog._load() e row["_weight"] -
        # isso levantava um KeyError assim que a tela de revisao era
        # construida. Como o botao e conectado via `.clicked.connect()`, essa
        # excecao era capturada silenciosamente pelo excepthook global da
        # aplicacao (app/main.py) em vez de propagar - clicar em "Confirmar
        # producao" na mesa principal parecia nao fazer nada.
        service = FakeProductionRegistrationService()
        dialog = ProductionRegistrationDialog(service, [1])
        dialog._set_all(True)
        group = dialog._groups[0]
        selected = [
            row for row in group["available"]
            if int(row.get("api_id") or row.get("id")) in dialog.selected_item_ids
        ]
        review = ProductionReviewDialog([{**group, "selected": selected}], "", dialog)
        review.reject()
        dialog.reject()

    def test_confirming_the_review_dialog_registers_production(self):
        service = FakeProductionRegistrationService()
        dialog = ProductionRegistrationDialog(service, [1])
        dialog._set_all(True)

        def fake_exec(self):
            self.confirmed = True
            return QDialog.Accepted

        with patch("app.ui.production_registration_dialog.ProductionReviewDialog.exec", fake_exec), patch(
            "app.ui.production_registration_dialog.QMessageBox.information"
        ) as info:
            dialog._review()

        info.assert_called_once()
        self.assertEqual(len(service.writes), 1)
        self.assertTrue(dialog.result())

    def test_declining_the_review_dialog_does_not_register_production(self):
        service = FakeProductionRegistrationService()
        dialog = ProductionRegistrationDialog(service, [1])
        dialog._set_all(True)

        with patch("app.ui.production_registration_dialog.ProductionReviewDialog.exec", return_value=QDialog.Rejected):
            dialog._review()

        self.assertEqual(service.writes, [])
        self.assertFalse(dialog.result())
        dialog.reject()


if __name__ == "__main__":
    unittest.main()
