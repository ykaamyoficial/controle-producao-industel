from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from app.ui.production_wizard import ProductionWizardDialog
from app.ui.production_wizard import dialog as dialog_module
from app.ui.production_wizard.state import flow_is_undefined, is_production_eligible


def _row(process_id, number, **overrides):
    row = {
        "id": process_id * 10 + number, "api_id": process_id * 10 + number, "processo_atual_id": process_id,
        "numero_item": str(number), "codigo_produto": f"COD-{number}", "descricao": "Base", "quantidade": "10",
        "peso": "2", "produzido": False, "produzir_internamente": "sim", "precisa_galvanizacao": "sim",
    }
    row.update(overrides)
    return row


class FakeProductionService:
    """Servico de mentira: itens de cada proposta, fluxo e gravacao de producao."""

    palette = None

    def __init__(self, undefined_flow=False):
        self.writes = []
        self.flow_writes = []
        self.rows = {}
        for process_id in (1, 2):
            first = _row(process_id, 1)
            if undefined_flow:
                first.update(produzir_internamente="indefinido", precisa_galvanizacao="indefinido")
            self.rows[process_id] = [first, _row(process_id, 2, produzido=True, peso="", quantidade="4")]

    def get_process_area_dict(self, process_id, _area):
        return {"proposta": f"CP{process_id}", "cliente": f"Cliente {process_id}"}

    def proposal_items(self, process_id, pending_production=False, pending_delivery=False):
        rows = self.rows[process_id]
        # como a API real: o item nem sempre traz a proposta a que pertence
        return [{**row, "processo_atual_id": None} for row in rows if not (pending_production and row["produzido"])]

    def next_status_options(self, _area, _process_id):
        return ["FINALIZADO", "FINALIZADO_PARCIAL"]

    def update_status(self, *args, **kwargs):
        self.writes.append((args, kwargs))

    def item_no_production_reasons(self):
        return [("pronta_entrega", "Pronta entrega")]

    def flow_review_data(self, process_id):
        return {
            "proposal_id": process_id, "proposta": f"CP{process_id}", "cliente": "", "version": 1,
            "itens": [
                {
                    "id": row["id"], "api_version": 1, "numero_item": row["numero_item"], "codigo_produto": row["codigo_produto"],
                    "descricao": row["descricao"], "quantidade": row["quantidade"], "produzir_internamente": row["produzir_internamente"],
                    "precisa_galvanizacao": row["precisa_galvanizacao"], "motivo_nao_produzir": "", "editavel": True, "motivo_bloqueio": None,
                }
                for row in self.rows[process_id]
            ],
        }

    def update_item_flow(self, process_id, payload, origin="Producao"):
        self.flow_writes.append((process_id, payload, origin))
        by_id = {entry["id"]: entry for entry in payload}
        for row in self.rows[process_id]:
            entry = by_id.get(row["id"])
            if entry:
                row["produzir_internamente"] = entry["produzir_internamente"]
                row["precisa_galvanizacao"] = entry["precisa_galvanizacao"]
        return len(payload)


class ProductionWizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wizard(self, service=None, ids=(1, 2), **kwargs):
        service = service or FakeProductionService()
        return ProductionWizardDialog(service, list(ids), **kwargs), service

    # -- uma janela, no tamanho do remanejamento --------------------------------------------------------
    def test_one_window_with_the_steps_and_the_size_of_the_remanagement_wizard(self):
        wizard, _ = self._wizard()
        self.assertEqual(wizard.stepper.steps(), ["Itens", "Revisão", "Concluído"])
        self.assertEqual(wizard.stack.count(), 4)  # as paginas vivem na mesma janela
        self.assertGreaterEqual(wizard.width(), 1180)
        self.assertGreaterEqual(wizard.height(), 690)

    def test_opens_at_the_size_of_the_parent_window(self):
        parent = QWidget()
        parent.resize(1600, 960)
        parent.show()
        wizard, _ = self._wizard(parent=parent)
        self.assertEqual(wizard.width(), int(parent.width() * 0.94))
        self.assertEqual(wizard.height(), max(690, int(parent.height() * 0.94)))

    # -- passo 1: itens ---------------------------------------------------------------------------------
    def test_groups_proposals_and_preserves_selection_when_filtered(self):
        wizard, _ = self._wizard()
        page = wizard.items_page
        self.assertEqual(page.tree.topLevelItemCount(), 2)
        self.assertEqual(len(wizard.state.items_by_id), 4)
        page._set_all(True)
        self.assertEqual(wizard.state.selected_item_ids, {11, 21})
        page.search.setText("CP1")
        self.assertEqual(wizard.state.selected_item_ids, {11, 21})
        self.assertFalse(page.tree.topLevelItem(0).isHidden())
        self.assertTrue(page.tree.topLevelItem(1).isHidden())

    def test_proposal_checkbox_is_tri_state_and_excludes_produced_items(self):
        wizard, _ = self._wizard(ids=(1,))
        page = wizard.items_page
        page._set_all(True)
        self.assertEqual(page.tree.topLevelItem(0).checkState(0).value, 2)
        wizard.state.selected_item_ids.clear()
        page._render()
        item = page.tree.topLevelItem(0).child(0)
        item.setCheckState(0, Qt.Checked)
        self.assertIn(11, wizard.state.selected_item_ids)
        self.assertNotIn(12, wizard.state.selected_item_ids)
        page._set_all(False)
        self.assertTrue(page.summary().startswith("Nenhum item"))

    def test_clicking_an_item_row_toggles_it_and_empty_area_is_ignored(self):
        wizard, _ = self._wizard(ids=(1,))
        page = wizard.items_page
        item = page.tree.topLevelItem(0).child(0)
        page._item_clicked(item, 2)
        self.assertIn(11, wizard.state.selected_item_ids)
        page._item_clicked(item, 2)
        self.assertNotIn(11, wizard.state.selected_item_ids)
        page._item_clicked(None, 1)
        self.assertEqual(wizard.state.selected_item_ids, set())

    def test_preselected_items_open_marked_and_next_needs_a_selection(self):
        wizard, _ = self._wizard(ids=(1,), preselected_item_ids={11})
        self.assertEqual(wizard.state.selected_item_ids, {11})
        self.assertTrue(wizard.next_button.isEnabled())
        self.assertEqual(wizard.next_button.text(), "Revisar")
        wizard.items_page._set_all(False)
        self.assertFalse(wizard.next_button.isEnabled())

    # -- passo de fluxo: so quando falta ------------------------------------------------------------------
    def test_no_flow_step_when_every_marked_item_has_a_flow(self):
        wizard, _ = self._wizard(ids=(1,), preselected_item_ids={11})
        wizard._next()
        self.assertIs(wizard.current_page(), wizard.review_page)
        self.assertEqual(wizard.stepper.steps(), ["Itens", "Revisão", "Concluído"])

    def test_flow_step_appears_before_the_review_when_a_marked_item_has_no_flow(self):
        service = FakeProductionService(undefined_flow=True)
        wizard, _ = self._wizard(service, ids=(1,), preselected_item_ids={11})
        wizard._next()
        self.assertIs(wizard.current_page(), wizard.flow_page)
        self.assertEqual(wizard.stepper.steps(), ["Itens", "Fluxo", "Revisão", "Concluído"])
        self.assertFalse(wizard.next_button.isEnabled())  # falta escolher o fluxo
        combo = wizard.flow_page._route_combos[11]
        combo.setCurrentIndex(1)
        self.assertTrue(wizard.next_button.isEnabled())
        wizard._next()
        self.assertEqual(len(service.flow_writes), 1)
        self.assertEqual(service.flow_writes[0][0], 1)
        self.assertIs(wizard.current_page(), wizard.review_page)
        self.assertEqual(service.writes, [])  # producao ainda nao foi gravada
        self.assertTrue(wizard.registered)

    def test_not_producing_needs_a_reason_and_drops_the_item_from_the_registration(self):
        service = FakeProductionService(undefined_flow=True)
        wizard, _ = self._wizard(service, ids=(1,), preselected_item_ids={11})
        wizard._next()
        page = wizard.flow_page
        from app.ui.flow_review_state import FlowRoute

        page._route_combos[11].setCurrentIndex(page._route_combos[11].findData(FlowRoute.NAO_PRODUZIR))
        self.assertFalse(wizard.next_button.isEnabled())  # falta o motivo
        reason = page._reasons[11]
        reason.combo.setCurrentIndex(reason.combo.findData("pronta_entrega"))
        self.assertTrue(wizard.next_button.isEnabled())
        wizard._next()
        # o unico item marcado virou "nao produzir": volta para escolher outros
        self.assertIs(wizard.current_page(), wizard.items_page)
        self.assertEqual(wizard.state.selected_item_ids, set())
        self.assertTrue(wizard.items_page.notice.isVisibleTo(wizard.items_page) or wizard.items_page.notice.text())

    def test_a_failed_flow_save_keeps_the_user_on_the_step(self):
        service = FakeProductionService(undefined_flow=True)
        service.update_item_flow = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("API fora"))
        wizard, _ = self._wizard(service, ids=(1,), preselected_item_ids={11})
        wizard._next()
        wizard.flow_page._route_combos[11].setCurrentIndex(1)
        wizard._next()
        self.assertIs(wizard.current_page(), wizard.flow_page)
        self.assertIn("API fora", wizard.flow_page.notice.text())

    # -- revisao e conclusao --------------------------------------------------------------------------------
    def test_review_does_not_write_and_confirm_registers_then_shows_the_result_in_the_same_window(self):
        wizard, service = self._wizard(ids=(1,), preselected_item_ids={11})
        wizard._next()
        self.assertIs(wizard.current_page(), wizard.review_page)
        self.assertEqual(wizard.next_button.text(), "Confirmar produção")
        self.assertEqual(service.writes, [])
        wizard.review_page.observation_input.setText("turno 2")
        wizard._next()
        self.assertEqual(len(service.writes), 1)
        args, kwargs = service.writes[0]
        self.assertEqual(args, (1, "PRODUCAO", "FINALIZADO", "turno 2"))
        self.assertEqual(kwargs["item_ids"], [11])
        self.assertIs(wizard.current_page(), wizard.done_page)
        self.assertEqual(wizard.next_button.text(), "Fechar")
        self.assertEqual(wizard.done_page.items_stat.itemAt(0).widget().text(), "1")
        self.assertTrue(wizard.registered)
        wizard._next()  # "Fechar"
        self.assertEqual(wizard.result(), QDialog.Accepted)

    def test_partial_registration_uses_the_partial_status(self):
        service = FakeProductionService()
        service.rows[1].append(_row(1, 3))
        wizard, _ = self._wizard(service, ids=(1,), preselected_item_ids={11})
        wizard._next()
        wizard._next()
        self.assertEqual(service.writes[0][0][2], "FINALIZADO_PARCIAL")

    def test_review_blocks_when_the_proposal_changed_meanwhile(self):
        wizard, service = self._wizard(ids=(1,), preselected_item_ids={11})
        wizard._next()
        service.rows[1][0]["produzido"] = True  # outro usuario registrou antes
        wizard._next()
        self.assertEqual(service.writes, [])
        self.assertIs(wizard.current_page(), wizard.review_page)
        self.assertIn("atualizada por outro usuário", wizard.review_page.notice.text())

    def test_back_keeps_the_selection_and_closing_a_started_registration_asks_first(self):
        wizard, _ = self._wizard(ids=(1,), preselected_item_ids={11})
        wizard._next()
        wizard._back()
        self.assertIs(wizard.current_page(), wizard.items_page)
        self.assertEqual(wizard.state.selected_item_ids, {11})
        wizard._next()
        closed = []
        wizard.rejected.connect(lambda: closed.append(True))
        with patch.object(dialog_module.QMessageBox, "question", return_value=dialog_module.QMessageBox.No) as ask:
            wizard.reject()
        ask.assert_called_once()
        self.assertEqual(closed, [])  # disse "nao": continua na janela
        with patch.object(dialog_module.QMessageBox, "question", return_value=dialog_module.QMessageBox.Yes):
            wizard.reject()
        self.assertEqual(closed, [True])
        self.assertFalse(wizard.registered)


class StateRulesTests(unittest.TestCase):
    def test_eligibility(self):
        self.assertTrue(is_production_eligible(_row(1, 1)))
        self.assertFalse(is_production_eligible(_row(1, 1, produzido=True)))
        self.assertFalse(is_production_eligible(_row(1, 1, produzir_internamente="nao")))
        self.assertFalse(is_production_eligible(_row(1, 1, motivo_bloqueio="Item ja entregue")))

    def test_flow_is_undefined_when_either_flag_is_missing(self):
        self.assertFalse(flow_is_undefined(_row(1, 1)))
        self.assertTrue(flow_is_undefined(_row(1, 1, produzir_internamente="indefinido")))
        self.assertTrue(flow_is_undefined(_row(1, 1, precisa_galvanizacao="indefinido")))


if __name__ == "__main__":
    unittest.main()
