from __future__ import annotations

import time
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.backend_adapter import COLOR_PALETTES, VersionConflictError
from app.ui.flow_review_dialog import FlowReviewDialog
from app.ui.flow_review_state import FlowRoute, ItemState, classify


def make_raw_item(item_id, numero, produzir, galvanizar, *, editavel=True, motivo_bloqueio=None, motivo="", quantidade="10.0000"):
    return {
        "id": item_id,
        "api_version": 1,
        "numero_item": numero,
        "codigo_produto": f"COD{numero}",
        "descricao": f"Item {numero}",
        "quantidade": quantidade,
        "produzir_internamente": produzir,
        "precisa_galvanizacao": galvanizar,
        "motivo_nao_produzir": motivo,
        "editavel": editavel,
        "motivo_bloqueio": motivo_bloqueio,
    }


class FakeService:
    palette = COLOR_PALETTES["aurora"]

    def __init__(self, data=None, *, fail_process_ids=None, start_fail_process_ids=None):
        self.data = data or {}
        self.fail_process_ids = set(fail_process_ids or ())
        self.start_fail_process_ids = set(start_fail_process_ids or ())
        self.saved_calls: list[tuple[int, list[dict], str]] = []
        self.start_calls: list[tuple[int, str, str, str]] = []
        self.load_calls: list[int] = []
        self.events: list[tuple[str, int]] = []

    def flow_review_data(self, process_id: int) -> dict:
        self.load_calls.append(process_id)
        return self.data[process_id]

    def item_no_production_reasons(self):
        return [("pronta_entrega", "Pronta entrega"), ("comprado_terceiro", "Comprado de terceiro")]

    def update_item_flow(self, process_id: int, definitions: list[dict], origin: str) -> int:
        if process_id in self.fail_process_ids:
            self.fail_process_ids.discard(process_id)
            raise VersionConflictError("Esta proposta foi alterada por outro usuario.")
        self.saved_calls.append((process_id, definitions, origin))
        self.events.append(("save", process_id))
        return len(definitions)

    def update_status(self, process_id: int, area: str, status: str, observation: str = ""):
        self.start_calls.append((process_id, area, status, observation))
        self.events.append(("start", process_id))
        if process_id in self.start_fail_process_ids:
            raise RuntimeError("Proposta nao esta pronta para iniciar.")
        return {}


class FlowReviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait_until(self, predicate, timeout_ticks=400):
        for _ in range(timeout_ticks):
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("condition never became true within the offscreen event-loop budget")

    def _build_and_load(self, data, process_ids, **kwargs):
        service = FakeService(data, **kwargs)
        dialog = FlowReviewDialog(service, process_ids)
        self._wait_until(lambda: dialog.stack.isEnabled())
        return service, dialog

    # ------------------------------------------------------------------ individual mode

    def test_individual_mode_applies_default_only_to_undefined_items_by_default(self):
        data = {
            1: {
                "proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5,
                "itens": [
                    make_raw_item(101, "1", "indefinido", "indefinido"),
                    make_raw_item(102, "2", "nao", "nao", motivo="pronta_entrega"),
                ],
            }
        }
        _service, dialog = self._build_and_load(data, [1])
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.PRODUZIR_GALVANIZAR))
        dialog._continue_to_review()

        item1 = next(i for _p, i, _t in dialog._rows if i.item_id == 101)
        item2 = next(i for _p, i, _t in dialog._rows if i.item_id == 102)
        self.assertEqual(item1.proposed_route, FlowRoute.PRODUZIR_GALVANIZAR)
        self.assertEqual(item2.proposed_route, FlowRoute.NAO_PRODUZIR)  # pre-existing exception preserved

    def test_individual_mode_save_sends_only_changed_items_and_accepts_dialog(self):
        data = {
            1: {
                "proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5,
                "itens": [
                    make_raw_item(101, "1", "indefinido", "indefinido"),
                    make_raw_item(102, "2", "sim", "sim"),
                ],
            }
        }
        service, dialog = self._build_and_load(data, [1])
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.PRODUZIR_GALVANIZAR))
        dialog._continue_to_review()

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        dialog._confirm_and_save()
        self._wait_until(lambda: bool(dialog.result()))

        self.assertEqual(len(service.saved_calls), 1)
        process_id, payload, origin = service.saved_calls[0]
        self.assertEqual(process_id, 1)
        self.assertEqual(origin, "Producao")
        self.assertEqual([row["id"] for row in payload], [101])  # item 102 was never touched
        self.assertEqual(dialog.result(), 1)
        self.assertTrue(dialog.changed)

    def test_manual_edit_creates_exception_and_can_be_restored(self):
        data = {1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "sim", "sim")]}}
        _service, dialog = self._build_and_load(data, [1])
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.PRODUZIR_GALVANIZAR))
        dialog._continue_to_review()

        proposal, item, tree_item = dialog._rows[0]
        key = (item.proposal_id, item.item_id)
        combo = dialog._route_combos[key]
        combo.setCurrentIndex(combo.findData(FlowRoute.NAO_PRODUZIR))
        dialog._reason_widgets[key].combo.setCurrentIndex(dialog._reason_widgets[key].combo.findData("pronta_entrega"))
        self.assertEqual(classify(item, proposal.default_route), ItemState.EXCECAO_CRIADA)

        tree_item.setSelected(True)
        dialog._restore_selected(default=False)
        self.assertEqual(item.proposed_route, FlowRoute.PRODUZIR_GALVANIZAR)
        self.assertEqual(classify(item, proposal.default_route), ItemState.PADRAO)

    def test_locked_item_is_never_defaulted_and_cannot_be_edited(self):
        data = {
            1: {
                "proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5,
                "itens": [make_raw_item(101, "1", "indefinido", "indefinido", editavel=False, motivo_bloqueio="Item ja possui producao registrada.")],
            }
        }
        _service, dialog = self._build_and_load(data, [1])
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.PRODUZIR_GALVANIZAR))
        dialog.scope_all_radio.setChecked(True)
        dialog._continue_to_review()

        proposal, item, _tree_item = dialog._rows[0]
        key = (item.proposal_id, item.item_id)
        self.assertEqual(item.proposed_route, FlowRoute.INDEFINIDO)  # never touched by the default
        self.assertFalse(dialog._route_combos[key].isEnabled())
        self.assertFalse(dialog._reason_widgets[key].isEnabled())
        self.assertEqual(classify(item, proposal.default_route), ItemState.BLOQUEADO)

    def test_save_button_disabled_until_required_reason_is_filled(self):
        data = {1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]}}
        service, dialog = self._build_and_load(data, [1])
        dialog.show()
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.PRODUZIR_GALVANIZAR))
        dialog._continue_to_review()
        _proposal, item, _tree_item = dialog._rows[0]
        key = (item.proposal_id, item.item_id)
        dialog._route_combos[key].setCurrentIndex(dialog._route_combos[key].findData(FlowRoute.NAO_PRODUZIR))
        self.app.processEvents()

        self.assertFalse(dialog.save_button.isEnabled())
        self.assertTrue(dialog.validation_button.isVisible())
        self.assertIn("1 item ainda exige motivo", dialog.validation_button.text())

        dialog._reason_widgets[key].combo.setCurrentIndex(dialog._reason_widgets[key].combo.findData("pronta_entrega"))
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertFalse(dialog.validation_button.isVisible())

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        dialog._confirm_and_save()
        self._wait_until(lambda: dialog.result() == 1)
        self.assertEqual(service.saved_calls[0][1][0]["motivo_nao_produzir"], "pronta_entrega")

    def test_setup_summary_and_conditional_global_reason_are_clear(self):
        data = {
            1: {
                "proposal_id": 1,
                "proposta": "CP001",
                "cliente": "Cliente A",
                "version": 5,
                "itens": [
                    make_raw_item(101, "1", "indefinido", "indefinido"),
                    make_raw_item(102, "2", "sim", "sim", editavel=False, motivo_bloqueio="Bloqueado"),
                ],
            }
        }
        _service, dialog = self._build_and_load(data, [1])

        self.assertEqual(dialog.setup_proposal_count.text(), "1")
        self.assertEqual(dialog.setup_item_count.text(), "2")
        self.assertEqual(dialog.setup_attention_count.text(), "2")
        self.assertTrue(dialog.global_reason_frame.isHidden())

        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.NAO_PRODUZIR))
        self.assertFalse(dialog.global_reason_frame.isHidden())

    def test_auto_start_option_is_only_available_for_producing_routes(self):
        data = {1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]}}
        _service, dialog = self._build_and_load(data, [1])

        self.assertFalse(dialog.auto_start_frame.isHidden())
        self.assertTrue(dialog.auto_start_checkbox.isEnabled())
        dialog.auto_start_checkbox.setChecked(True)

        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.NAO_PRODUZIR))

        self.assertTrue(dialog.auto_start_frame.isHidden())
        self.assertFalse(dialog.auto_start_frame.isEnabled())
        self.assertFalse(dialog.auto_start_checkbox.isEnabled())
        self.assertFalse(dialog.auto_start_checkbox.isChecked())

    def test_unchecked_auto_start_saves_flow_without_starting_production(self):
        data = {1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]}}
        service, dialog = self._build_and_load(data, [1])
        dialog._continue_to_review()

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        dialog._confirm_and_save()
        self._wait_until(lambda: dialog.result() == 1)

        self.assertEqual(len(service.saved_calls), 1)
        self.assertEqual(service.start_calls, [])

    def test_checked_auto_start_runs_only_after_every_flow_is_saved(self):
        data = {
            1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]},
            2: {"proposal_id": 2, "proposta": "CP002", "cliente": "Cliente B", "version": 3, "itens": [make_raw_item(201, "1", "indefinido", "indefinido")]},
        }
        service, dialog = self._build_and_load(data, [1, 2])
        dialog.auto_start_checkbox.setChecked(True)
        dialog._continue_to_review()

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        dialog._confirm_and_save()
        self._wait_until(lambda: dialog.result() == 1)

        self.assertEqual(service.events, [("save", 1), ("save", 2), ("start", 1), ("start", 2)])
        self.assertEqual(
            service.start_calls,
            [(1, "PRODUCAO", "INICIADO", ""), (2, "PRODUCAO", "INICIADO", "")],
        )

    def test_flow_save_failure_prevents_every_automatic_start(self):
        data = {
            1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]},
            2: {"proposal_id": 2, "proposta": "CP002", "cliente": "Cliente B", "version": 3, "itens": [make_raw_item(201, "1", "indefinido", "indefinido")]},
        }
        service, dialog = self._build_and_load(data, [1, 2], fail_process_ids={2})
        dialog.auto_start_checkbox.setChecked(True)
        dialog._continue_to_review()

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        dialog._confirm_and_save()
        self._wait_until(lambda: not dialog._saving)

        self.assertEqual(service.start_calls, [])

    def test_auto_start_failure_reports_partial_success_after_flow_save(self):
        data = {
            1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]},
            2: {"proposal_id": 2, "proposta": "CP002", "cliente": "Cliente B", "version": 3, "itens": [make_raw_item(201, "1", "indefinido", "indefinido")]},
        }
        service, dialog = self._build_and_load(data, [1, 2], start_fail_process_ids={2})
        dialog.auto_start_checkbox.setChecked(True)
        dialog._continue_to_review()
        messages: list[str] = []

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        QMessageBox.warning = staticmethod(lambda *a, **k: messages.append(a[2]))
        dialog._confirm_and_save()
        self._wait_until(lambda: dialog.result() == 1)

        self.assertEqual(len(service.saved_calls), 2)
        self.assertEqual(len(service.start_calls), 2)
        self.assertIn("Fluxo salvo com sucesso", messages[0])
        self.assertIn("1 de 2 proposta(s)", messages[0])
        self.assertIn("CP002", messages[0])

    def test_required_global_reason_blocks_continue_on_setup_step(self):
        data = {1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]}}
        _service, dialog = self._build_and_load(data, [1])
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.NAO_PRODUZIR))

        dialog._continue_to_review()

        self.assertEqual(dialog.stack.currentIndex(), 0)
        self.assertFalse(dialog.global_reason_validation.isHidden())
        self.assertEqual(dialog.global_reason_edit.property("validationState"), "error")

    def test_global_reason_prefills_review_and_preserves_individual_reason(self):
        data = {
            1: {
                "proposal_id": 1,
                "proposta": "CP001",
                "cliente": "Cliente A",
                "version": 5,
                "itens": [
                    make_raw_item(101, "1", "indefinido", "indefinido"),
                    make_raw_item(102, "2", "nao", "nao", motivo="pronta_entrega"),
                ],
            }
        }
        _service, dialog = self._build_and_load(data, [1])
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.NAO_PRODUZIR))
        dialog.scope_all_radio.setChecked(True)
        dialog.global_reason_edit.setPlainText("Motivo comum do lote")

        dialog._continue_to_review()

        rows = {item.item_id: item for _proposal, item, _tree_item in dialog._rows}
        self.assertEqual(rows[101].proposed_reason, "Motivo comum do lote")
        self.assertEqual(rows[102].proposed_reason, "pronta_entrega")
        self.assertEqual(dialog._reason_widgets[(1, 101)].reason(), "Motivo comum do lote")
        self.assertEqual(dialog._reason_widgets[(1, 101)].free_text.toolTip(), "Motivo comum do lote")
        self.assertEqual(dialog._reason_widgets[(1, 101)].free_text.cursorPosition(), 0)
        self.assertEqual(dialog.stack.currentIndex(), 1)

    def test_overwrite_option_replaces_existing_reason_with_global_reason(self):
        data = {
            1: {
                "proposal_id": 1,
                "proposta": "CP001",
                "cliente": "Cliente A",
                "version": 5,
                "itens": [make_raw_item(101, "1", "nao", "nao", motivo="pronta_entrega")],
            }
        }
        _service, dialog = self._build_and_load(data, [1])
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.NAO_PRODUZIR))
        dialog.scope_all_radio.setChecked(True)
        dialog.overwrite_checkbox.setChecked(True)
        dialog.global_reason_edit.setPlainText("Motivo substituto")

        dialog._continue_to_review()

        _proposal, item, _tree_item = dialog._rows[0]
        self.assertFalse(dialog.preserve_checkbox.isChecked())
        self.assertEqual(item.proposed_reason, "Motivo substituto")

    def test_new_route_column_has_readable_width_and_full_value_tooltip(self):
        data = {1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]}}
        _service, dialog = self._build_and_load(data, [1])
        dialog._continue_to_review()
        _proposal, item, _tree_item = dialog._rows[0]
        combo = dialog._route_combos[(item.proposal_id, item.item_id)]
        combo.setCurrentIndex(combo.findData(FlowRoute.NAO_PRODUZIR_GALVANIZAR))

        self.assertGreaterEqual(dialog.review_tree.columnWidth(5), 238)
        self.assertGreaterEqual(dialog.review_tree.columnWidth(7), 310)
        self.assertGreaterEqual(combo.minimumWidth(), 220)
        self.assertIn("Nao produzir, mas galvanizar", combo.toolTip())

    def test_overwrite_exceptions_requires_confirmation_with_count(self):
        data = {
            1: {
                "proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5,
                "itens": [
                    make_raw_item(101, "1", "nao", "nao", motivo="pronta_entrega"),
                    make_raw_item(102, "2", "nao", "sim", motivo="pronta_entrega"),
                ],
            }
        }
        _service, dialog = self._build_and_load(data, [1])
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.PRODUZIR_GALVANIZAR))
        dialog.scope_all_radio.setChecked(True)

        captured = []
        QMessageBox.question = staticmethod(lambda *a, **k: (captured.append(a[2] if len(a) > 2 else ""), QMessageBox.No)[1])
        dialog.overwrite_checkbox.setChecked(True)
        self.assertTrue(captured)
        self.assertIn("2 excecao", captured[0])
        self.assertFalse(dialog.overwrite_checkbox.isChecked())  # declining reverts the checkbox

    def test_closing_with_unsaved_changes_prompts_and_can_be_cancelled(self):
        data = {1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]}}
        _service, dialog = self._build_and_load(data, [1])
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.PRODUZIR_GALVANIZAR))
        dialog._continue_to_review()

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
        dialog.reject()
        self.assertEqual(dialog.result(), 0)  # stayed open

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        dialog.reject()
        self.assertEqual(dialog.result(), 0)  # QDialog.reject() without accept() keeps result 0, but dialog is now closed/hidden
        self.assertFalse(dialog.isVisible())

    # ------------------------------------------------------------------ batch mode

    def test_batch_mode_groups_items_by_proposal(self):
        data = {
            1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]},
            2: {"proposal_id": 2, "proposta": "CP002", "cliente": "Cliente B", "version": 2, "itens": [make_raw_item(201, "1", "indefinido", "indefinido"), make_raw_item(202, "2", "indefinido", "indefinido")]},
        }
        _service, dialog = self._build_and_load(data, [1, 2], )
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.PRODUZIR_GALVANIZAR))
        dialog._continue_to_review()

        self.assertEqual(len(dialog._group_items), 2)
        self.assertEqual(len(dialog._rows), 3)

    def test_batch_save_partial_success_keeps_conflicted_proposal_open_and_reloads_it(self):
        data = {
            1: {"proposal_id": 1, "proposta": "CP001", "cliente": "Cliente A", "version": 5, "itens": [make_raw_item(101, "1", "indefinido", "indefinido")]},
            2: {"proposal_id": 2, "proposta": "CP002", "cliente": "Cliente B", "version": 3, "itens": [make_raw_item(201, "1", "indefinido", "indefinido")]},
        }
        service, dialog = self._build_and_load(data, [1, 2], fail_process_ids={2})
        dialog.default_route_combo.setCurrentIndex(dialog.default_route_combo.findData(FlowRoute.PRODUZIR_GALVANIZAR))
        dialog._continue_to_review()

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        dialog._confirm_and_save()
        # A chamada do servico ocorre na thread de trabalho antes de o callback
        # atualizar ``dialog.proposals`` na thread da interface. Aguarde ambos.
        self._wait_until(lambda: len(service.saved_calls) >= 1 and not dialog._saving)

        # proposal 1 succeeded and was removed from the active review; the dialog stays open
        # because proposal 2 conflicted, and it must not be resubmitted automatically
        self.assertEqual(dialog.result(), 0)
        self.assertEqual([p.proposal_number for p in dialog.proposals], ["CP002"])
        self.assertEqual([call[0] for call in service.saved_calls], [1])

        # the conflict-reload worker refetches CP002 in the background
        self._wait_until(lambda: service.load_calls.count(2) >= 2)

        dialog._confirm_and_save()
        self._wait_until(lambda: dialog.result() == 1)
        self.assertEqual(sorted(call[0] for call in service.saved_calls), [1, 2])


if __name__ == "__main__":
    unittest.main()
