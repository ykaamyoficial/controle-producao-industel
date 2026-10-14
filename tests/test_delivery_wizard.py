from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from app.ui.delivery_wizard import DeliveryWizardDialog


class FakeDeliveryService:
    palette = None

    def __init__(self, pending=None):
        # proposta -> itens pendentes de retirada
        self.pending = pending if pending is not None else {
            1: [
                {"id": 101, "numero_item": "1", "codigo_produto": "450.1", "descricao": "Quadro", "quantidade": "2", "peso": "10"},
                {"id": 102, "numero_item": "2", "codigo_produto": "450.2", "descricao": "Poste", "quantidade": "1", "peso": ""},
            ],
            2: [],
        }
        self.calls = []

    def get_process_dict(self, process_id):
        return {"proposta": f"CP{process_id}", "cliente": f"Cliente {process_id}"}

    def proposal_items(self, process_id, pending_production=False, pending_delivery=False):
        return [dict(row) for row in self.pending.get(process_id, [])]

    def update_status(self, process_id, area, status, observation="", item_ids=None, **kwargs):
        self.calls.append(("update_status", process_id, area, status, observation, item_ids))


class DeliveryWizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wizard(self, ids=(1,), service=None, parent=None):
        service = service or FakeDeliveryService()
        return DeliveryWizardDialog(service, list(ids), parent), service

    def test_one_window_with_three_steps_and_the_size_of_the_other_wizards(self):
        parent = QWidget()
        parent.resize(1600, 960)
        parent.show()
        wizard, _ = self._wizard(parent=parent)
        self.assertEqual(wizard.stepper.steps(), ["Itens", "Revisão", "Concluído"])
        self.assertEqual(wizard.width(), int(parent.width() * 0.94))
        self.assertEqual(wizard.height(), max(690, int(parent.height() * 0.94)))

    def test_next_needs_a_marked_item(self):
        wizard, _ = self._wizard()
        self.assertFalse(wizard.next_button.isEnabled())
        wizard.items_page._set_all(True)
        self.assertTrue(wizard.next_button.isEnabled())
        self.assertEqual(wizard.next_button.text(), "Revisar")

    def test_partial_selection_registers_partial_delivery_and_shows_the_result_in_the_window(self):
        wizard, service = self._wizard()
        item = wizard.items_page.tree.topLevelItem(0).child(0)
        item.setCheckState(0, Qt.Checked)
        wizard._next()
        self.assertIs(wizard.current_page(), wizard.review_page)
        self.assertEqual(service.calls, [])
        wizard.review_page.observation_input.setText("retirou 14h")
        wizard._next()
        self.assertEqual(service.calls, [("update_status", 1, "EXPEDICAO", "ENTREGUE_PARCIAL", "retirou 14h", [101])])
        self.assertIs(wizard.current_page(), wizard.done_page)
        self.assertTrue(wizard.registered)
        wizard._next()
        self.assertEqual(wizard.result(), QDialog.Accepted)

    def test_all_items_selected_registers_total_delivery(self):
        wizard, service = self._wizard()
        wizard.items_page._set_all(True)
        wizard._next()
        wizard._next()
        self.assertEqual(service.calls, [("update_status", 1, "EXPEDICAO", "ENTREGUE", "", [101, 102])])

    def test_proposal_without_pending_items_is_delivered_directly(self):
        wizard, service = self._wizard(ids=(2,))
        self.assertTrue(wizard.next_button.isEnabled())
        wizard._next()
        wizard._next()
        self.assertEqual(service.calls, [("update_status", 2, "EXPEDICAO", "ENTREGUE", "", None)])

    def test_batch_mixes_a_partial_delivery_and_a_direct_one(self):
        wizard, service = self._wizard(ids=(1, 2))
        wizard.items_page.tree.topLevelItem(0).child(1).setCheckState(0, Qt.Checked)
        wizard._next()
        wizard._next()
        self.assertEqual(
            service.calls,
            [("update_status", 1, "EXPEDICAO", "ENTREGUE_PARCIAL", "", [102]), ("update_status", 2, "EXPEDICAO", "ENTREGUE", "", None)],
        )

    def test_review_blocks_when_the_items_changed_meanwhile(self):
        wizard, service = self._wizard()
        wizard.items_page._set_all(True)
        wizard._next()
        service.pending[1] = [row for row in service.pending[1] if row["id"] != 101]  # outra pessoa registrou o 101
        wizard._next()
        self.assertEqual(service.calls, [])
        self.assertIs(wizard.current_page(), wizard.review_page)
        self.assertIn("atualizada por outro usuário", wizard.review_page.notice.text())

    def test_partial_failure_keeps_done_proposals_out_of_a_retry(self):
        service = FakeDeliveryService()
        original = service.update_status

        def flaky(process_id, *args, **kwargs):
            if process_id == 1:
                raise RuntimeError("API fora")
            return original(process_id, *args, **kwargs)

        service.update_status = flaky
        wizard, _ = self._wizard(ids=(2, 1), service=service)
        wizard.items_page._set_all(True)
        wizard._next()
        wizard._next()
        self.assertIs(wizard.current_page(), wizard.review_page)
        self.assertIn("API fora", wizard.review_page.notice.text())
        self.assertEqual([call[1] for call in service.calls], [2])
        self.assertEqual([entry["process_id"] for entry in wizard.state.entries()], [1])


if __name__ == "__main__":
    unittest.main()
