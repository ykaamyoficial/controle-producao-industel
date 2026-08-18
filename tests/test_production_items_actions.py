from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.action_center.batch_action_center import BatchProposalActionCenter
from app.ui.production_items_page import ProductionItemsPage


def make_item(
    item_id: int,
    *,
    proposal_id: int = 10,
    produced: bool = False,
    flow_defined: bool = True,
    galvanize: str = "sim",
    status: str = "INICIADO",
) -> dict:
    return {
        "id": item_id,
        "api_id": item_id,
        "api_proposal_id": proposal_id,
        "processo_atual_id": proposal_id,
        "proposta": f"CP{proposal_id}",
        "cliente": "Cliente",
        "numero_item": str(item_id),
        "codigo_produto": f"COD-{item_id}",
        "descricao": f"Item {item_id}",
        "quantidade": "1.0000",
        "peso_total": "1.0000",
        "produzir_internamente": "sim",
        "precisa_galvanizacao": galvanize,
        "fluxo_definido": flow_defined,
        "produzido": produced,
        "status_producao": status,
        "status_producao_item": status,
        "obra_site": "Site",
        "lote": "L1",
    }


class FakeProductionItemsService:
    palette = OFFICIAL_COLOR_PALETTES["claro"]

    def __init__(self, eligible_load_ids=None):
        self.eligible_load_ids = set(eligible_load_ids or ())
        self.calls: list[tuple] = []

    def can_edit(self, _area):
        return True

    def can_mount_galvanization_load(self):
        return True

    def display_cell(self, _key, value, _row):
        return str(value or "")

    def area_status_label(self, _area, status):
        return str(status or "").replace("_", " ").title()

    def common_next_statuses(self, _area, _process_ids):
        return ["INICIADO", "FINALIZADO"]

    def action_label(self, _area, status):
        return "Iniciar ou retomar producao" if status == "INICIADO" else status.title()

    def item_flow_summary(self, _process_id):
        return {"total": 2, "undefined_count": 0}

    def galvanization_item_eligibility(self, item_ids):
        eligible = [item_id for item_id in item_ids if item_id in self.eligible_load_ids]
        rejected = [
            {"item_id": item_id, "reason": "sem saldo"}
            for item_id in item_ids
            if item_id not in self.eligible_load_ids
        ]
        return {"eligible_item_ids": eligible, "rejected_items": rejected}

    def update_status(self, proposal_id, area, status, observation, item_ids=None):
        self.calls.append(("update_status", proposal_id, area, status, observation, item_ids))

    def add_items_to_galvanization_load(self, load_id, *, item_ids=None, proposal_ids=None):
        self.calls.append(("add_items_to_galvanization_load", load_id, item_ids, proposal_ids))
        return {"added_item_ids": list(item_ids or []), "rejected_items": [], "proposals": []}


class ProductionItemsSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _page(self, rows):
        page = ProductionItemsPage(FakeProductionItemsService(eligible_load_ids={row["id"] for row in rows}))
        page.group_by_product.setChecked(False)
        page._flat_rows = list(rows)
        page._apply_grouping()
        page.resize(1100, 500)
        page.show()
        self.app.processEvents()
        return page

    def _click(self, page, row: int, column: int):
        index = page.model.index(row, column)
        page.table.scrollTo(index)
        self.app.processEvents()
        QTest.mouseClick(page.table.viewport(), Qt.LeftButton, pos=page.table.visualRect(index).center())
        self.app.processEvents()

    def test_row_click_toggles_checkbox_highlight_ids_and_count(self):
        page = self._page([make_item(101), make_item(102)])
        page.activate_batch_selection()

        self._click(page, 0, 1)

        self.assertEqual(page.get_selected_item_ids(), [101])
        self.assertEqual(page.model.index(0, 0).data(Qt.CheckStateRole), Qt.Checked)
        self.assertTrue(page.table.selectionModel().isRowSelected(0, QModelIndex()))
        self.assertEqual(page.batch_count_label.text(), "1 item(ns) selecionado(s)")

        self._click(page, 0, 1)

        self.assertEqual(page.get_selected_item_ids(), [])
        self.assertEqual(page.model.index(0, 0).data(Qt.CheckStateRole), Qt.Unchecked)
        self.assertFalse(page.table.selectionModel().isRowSelected(0, QModelIndex()))
        page.close()

    def test_checkbox_click_updates_operational_selection_and_row_highlight(self):
        page = self._page([make_item(101)])
        page.activate_batch_selection()

        self._click(page, 0, 0)

        self.assertEqual(page.get_selected_item_ids(), [101])
        self.assertTrue(page.table.selectionModel().isRowSelected(0, QModelIndex()))
        self._click(page, 0, 0)
        self.assertEqual(page.get_selected_item_ids(), [])
        self.assertFalse(page.table.selectionModel().isRowSelected(0, QModelIndex()))
        page.close()

    def test_multiple_plain_row_clicks_accumulate_and_cancel_clears_every_state(self):
        page = self._page([make_item(101), make_item(102)])
        page.activate_batch_selection()

        self._click(page, 0, 1)
        self._click(page, 1, 1)
        self.assertEqual(page.get_selected_item_ids(), [101, 102])

        page.cancel_batch_selection()

        self.assertEqual(page.get_selected_item_ids(), [])
        self.assertFalse(page.batch_selection.active)
        self.assertFalse(page.table.selectionModel().hasSelection())
        page.close()

    def test_ctrl_and_shift_selection_keep_checkbox_ids_in_sync(self):
        page = self._page([make_item(101), make_item(102), make_item(103)])
        page.activate_batch_selection()

        self._click(page, 0, 1)
        index = page.model.index(1, 1)
        QTest.mouseClick(
            page.table.viewport(),
            Qt.LeftButton,
            Qt.ControlModifier,
            page.table.visualRect(index).center(),
        )
        self.app.processEvents()

        self.assertEqual(page.get_selected_item_ids(), [101, 102])
        self.assertEqual(page.model.index(0, 0).data(Qt.CheckStateRole), Qt.Checked)
        self.assertEqual(page.model.index(1, 0).data(Qt.CheckStateRole), Qt.Checked)

        index = page.model.index(2, 1)
        QTest.mouseClick(
            page.table.viewport(),
            Qt.LeftButton,
            Qt.ShiftModifier,
            page.table.visualRect(index).center(),
        )
        self.app.processEvents()

        self.assertEqual(set(page.get_selected_item_ids()), {101, 102, 103})
        self.assertEqual(page.model.index(2, 0).data(Qt.CheckStateRole), Qt.Checked)
        page.close()

    def test_actions_button_opens_standard_batch_center_with_exact_item_context(self):
        rows = [make_item(101), make_item(102, proposal_id=20)]
        page = self._page(rows)
        page.activate_batch_selection()
        page.batch_selection.select_many(rows)
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        fake_dialog.changed = False

        with patch("app.ui.production_items_page.BatchProposalActionCenter", return_value=fake_dialog) as ctor:
            page.open_action_center()

        ctor.assert_called_once_with(
            page.service,
            [10, 20],
            "PRODUCAO",
            page,
            proposal_labels={10: "CP10", 20: "CP20"},
            item_rows=rows,
            item_action_host=page,
        )
        page.close()

    def test_batch_actions_button_reopens_standard_dialog_once_selection_mode_is_active(self):
        """Cenario 2: com o modo de selecao por checkbox ja ativo (rotulo do
        botao passou de "Acoes em lote" para "Acoes"), o mesmo clique
        precisa abrir a central padrao de acoes, e nao apenas reentrar em
        activate_batch_selection (que retornaria sem efeito)."""
        rows = [make_item(101), make_item(102, proposal_id=20)]
        page = self._page(rows)
        page.batch_actions_button.click()
        self.assertTrue(page._batch_mode)
        self.assertEqual(page.batch_actions_button.text(), "Acoes")
        page.batch_selection.select_many(rows)
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        fake_dialog.changed = False

        with patch("app.ui.production_items_page.BatchProposalActionCenter", return_value=fake_dialog) as ctor:
            page.batch_actions_button.click()

        ctor.assert_called_once_with(
            page.service,
            [10, 20],
            "PRODUCAO",
            page,
            proposal_labels={10: "CP10", 20: "CP20"},
            item_rows=rows,
            item_action_host=page,
        )
        page.close()

    def test_add_single_pending_item_to_existing_load_registers_production_first(self):
        """Cenario 6 + 7: um unico item ainda pendente de producao, ao ser
        encaminhado para "Adicionar a uma carga existente", primeiro
        registra a producao automaticamente (mesmo passo que "Criar nova
        carga" ja fazia) e so entao inclui o item na carga escolhida."""
        rows = [make_item(101)]
        page = self._page(rows)
        page.refresh = MagicMock()

        def _run_synchronously(_owner, operation, on_success, on_error, **_kwargs):
            try:
                result = operation()
            except Exception as exc:
                on_error(exc)
            else:
                on_success(result)
            return None

        with patch("app.ui.production_items_page.start_worker", side_effect=_run_synchronously), \
             patch("app.ui.production_items_page.QMessageBox.information"):
            page.open_assemble_load(rows, load_id=55)

        update_calls = [call for call in page.service.calls if call[0] == "update_status"]
        self.assertEqual(
            update_calls,
            [("update_status", 10, "PRODUCAO", "FINALIZADO", "Producao registrada automaticamente ao montar carga", [101])],
        )
        load_calls = [call for call in page.service.calls if call[0] == "add_items_to_galvanization_load"]
        self.assertEqual(load_calls, [("add_items_to_galvanization_load", 55, [101], None)])
        page.close()

    def test_mixed_load_result_is_consolidated_in_one_message(self):
        page = self._page([make_item(101)])
        detail = {
            "added_item_ids": [101],
            "rejected_items": [{"item_id": 102, "message": "Item 102: ja pertence a esta carga."}],
            "proposals": [],
        }

        with patch("app.ui.production_items_page.QMessageBox.information") as information:
            page._show_load_addition_summary(detail)

        message = information.call_args.args[2]
        self.assertIn("1 item(ns) adicionado(s)", message)
        self.assertIn("1 item(ns) ignorado(s)", message)
        self.assertIn("ja pertence a esta carga", message)
        information.assert_called_once()
        page.close()


class ProductionItemsStandardActionCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_item_context_uses_standard_header_and_reports_mixed_coverage(self):
        # Item 101 esta pendente de producao mas ja tem fluxo definido e
        # precisa de galvanizacao: "Adicionar a uma carga existente" usa a
        # MESMA elegibilidade de "Criar nova carga" (producao pendente e
        # registrada automaticamente ao montar a carga - ver
        # ProductionItemsPage.open_assemble_load), entao nao exige mais que
        # o item ja esteja "produzido" para aparecer.
        rows = [make_item(101), make_item(102, galvanize="nao")]
        service = FakeProductionItemsService()
        dialog = BatchProposalActionCenter(service, [10], "PRODUCAO", item_rows=rows, item_action_host=MagicMock())

        self.assertEqual(dialog.item_ids, [101, 102])
        self.assertEqual(dialog._title_label.text(), "2 itens selecionados")
        load_action = next(action for action in dialog.actions if action.id == "MANAGE_LOAD_EXISTING")
        self.assertIn("Disponivel para 1 de 2 itens", load_action.description)

    def test_single_pending_item_is_eligible_for_existing_load(self):
        """Cenario 7: selecionar somente 1 item, ainda pendente de producao,
        precisa continuar oferecendo "Adicionar a uma carga existente"."""
        rows = [make_item(101)]
        service = FakeProductionItemsService()
        dialog = BatchProposalActionCenter(service, [10], "PRODUCAO", item_rows=rows, item_action_host=MagicMock())

        self.assertEqual(dialog._title_label.text(), "1 item selecionado")
        load_action = next(action for action in dialog.actions if action.id == "MANAGE_LOAD_EXISTING")
        self.assertNotIn("Disponivel para", load_action.description)

    def test_existing_load_action_forwards_only_contextually_eligible_items(self):
        rows = [make_item(101), make_item(102, galvanize="nao")]
        service = FakeProductionItemsService()
        host = MagicMock()
        dialog = BatchProposalActionCenter(service, [10], "PRODUCAO", item_rows=rows, item_action_host=host)
        action = next(value for value in dialog.actions if value.id == "MANAGE_LOAD_EXISTING")

        with patch("app.ui.action_center.batch_action_center.choose_existing_load_for_addition", return_value=7):
            dialog.run_action(action)

        host.open_assemble_load.assert_called_once_with([rows[0]], load_id=7)
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    def test_new_load_action_forwards_only_contextually_eligible_items(self):
        rows = [make_item(101), make_item(102, galvanize="nao")]
        service = FakeProductionItemsService(eligible_load_ids=set())
        host = MagicMock()
        dialog = BatchProposalActionCenter(service, [10], "PRODUCAO", item_rows=rows, item_action_host=host)
        action = next(value for value in dialog.actions if value.id == "MANAGE_LOAD_NEW")

        dialog.run_action(action)

        host.open_assemble_load.assert_called_once_with([rows[0]])


if __name__ == "__main__":
    unittest.main()
