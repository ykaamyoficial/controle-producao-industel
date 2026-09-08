from __future__ import annotations

import os
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.batch_status_dialog import BatchStatusDialog
from app.ui.batch_selection_review_dialog import BatchSelectionReviewDialog
from app.ui.components.batch_selection import BatchSelectionController
from app.ui.process_page import ProcessPage


ROWS = [
    {
        "id": 10,
        "proposta": "CP05266",
        "cliente": "MNS Engenharia",
        "obra_site": "Site A",
        "lote": "L1",
        "status_producao": "INICIADO",
        "prazo_entrega": "10/08/2026",
        "prazo_bucket": "VENCIDOS",
    },
    {
        "id": 27,
        "proposta": "CP06120",
        "cliente": "Cliente B",
        "obra_site": "Site B",
        "lote": "L2",
        "status_producao": "PARADO",
        "prazo_entrega": "15/08/2026",
        "prazo_bucket": "PROXIMOS_7_DIAS",
    },
    {
        "id": 38,
        "proposta": "CP07415",
        "cliente": "Cliente ABC",
        "obra_site": "Site C",
        "lote": "L3",
        "status_producao": "INICIADO",
        "prazo_entrega": "30/08/2026",
        "prazo_bucket": "",
    },
]


class FakeProductionService:
    def __init__(self, *, theme: str = "claro"):
        self.palette = OFFICIAL_COLOR_PALETTES[theme]
        self.rows = deepcopy(ROWS)
        self.reads = 0
        self.writes = 0
        self.validation_result = None
        self.last_validation = None

    def can_edit_area(self, _area):
        return True

    def can_access_area(self, _area):
        return True

    def can_edit_process(self):
        return True

    def visible_areas(self):
        return ["PRODUCAO"]

    def list_status(self, _area=None):
        return ["INICIADO", "PARADO"]

    def status_label(self, status):
        return {"INICIADO": "Em produção", "PARADO": "Produção pausada"}.get(status, status)

    def area_status_label(self, _area, status):
        return self.status_label(status)

    def current_location(self, row):
        return "PRODUCAO", "Produção", row.get("status_producao") or ""

    def display_cell(self, _key, value, _row=None):
        return "" if value is None else str(value)

    def process_rows(self, _area, filters):
        self.reads += 1
        rows = deepcopy(self.rows)
        needle = str(filters.get("text") or "").casefold()
        status = filters.get("status") or ""
        prazo = filters.get("prazo") or ""
        if needle:
            rows = [
                row
                for row in rows
                if needle
                in " ".join(str(row.get(key) or "") for key in ("proposta", "cliente", "obra_site", "lote")).casefold()
            ]
        if status:
            rows = [row for row in rows if row.get("status_producao") == status]
        if prazo:
            rows = [row for row in rows if row.get("prazo_bucket") == prazo]
        return rows

    def validate_batch_selection(self, area, process_ids, action_id):
        self.reads += len(process_ids)
        self.last_validation = (area, list(process_ids), action_id)
        if self.validation_result is not None:
            return deepcopy(self.validation_result)
        return {
            "valid_ids": list(process_ids),
            "incompatible": [],
            "common_statuses": ["INICIADO"],
            "global_reason": "",
        }


class FakeBatchDialogService(FakeProductionService):
    def batch_status_candidates(self, _area, _text="", exclude_ids=None):
        excluded = exclude_ids or set()
        return [deepcopy(row) for row in self.rows if row["id"] not in excluded]

    def sort_process_rows(self, _area, rows):
        return rows

    def status_for_area(self, row, _area):
        return row.get("status_producao") or ""

    def get_process_dict(self, process_id):
        self.reads += 1
        row = next((row for row in self.rows if row["id"] == process_id), None)
        if row is None:
            raise RuntimeError("proposta removida")
        return deepcopy(row)

    def process_visible_in_area(self, _process, _area):
        return True

    def common_next_statuses(self, _area, process_ids):
        return ["INICIADO"] if process_ids else []

    def action_label(self, _area, status):
        return self.status_label(status)

    def validate_batch_selection(self, area, process_ids, action_id):
        self.last_validation = (area, list(process_ids), action_id)
        if self.validation_result is not None:
            return deepcopy(self.validation_result)
        return {
            "valid_ids": list(process_ids),
            "incompatible": [],
            "common_statuses": ["INICIADO"],
            "global_reason": "",
        }


def _run_synchronously(_owner, operation, on_success, on_error, **_kwargs):
    try:
        on_success(operation())
    except Exception as exc:
        on_error(exc)
    return None


class BatchSelectionControllerTests(unittest.TestCase):
    def test_controller_uses_stable_ids_and_preserves_hidden_entities(self):
        controller = BatchSelectionController()
        controller.activate()
        controller.select(10, ROWS[0])
        controller.select(27, ROWS[1])
        controller.deselect(10)
        controller.select(10, ROWS[0])

        self.assertEqual(controller.selected_ids, {10, 27})
        self.assertEqual(controller.ordered_selected_ids, [27, 10])
        self.assertEqual(controller.selected_entities()[0]["proposta"], "CP06120")

    def test_header_state_and_visible_bulk_operations_do_not_replace_hidden_selection(self):
        controller = BatchSelectionController()
        controller.activate()
        controller.select(10, ROWS[0])
        self.assertEqual(controller.header_state([27, 38]), Qt.Unchecked)
        controller.select_many([ROWS[1], ROWS[2]])
        self.assertEqual(controller.header_state([27, 38]), Qt.Checked)
        controller.deselect_many([27, 38])
        self.assertEqual(controller.selected_ids, {10})
        self.assertEqual(controller.header_state([10, 27]), Qt.PartiallyChecked)

    def test_clear_keeps_mode_active_and_deactivate_clears_everything(self):
        controller = BatchSelectionController()
        controller.activate()
        controller.select(10, ROWS[0])
        controller.clear()
        self.assertTrue(controller.active)
        self.assertEqual(controller.count, 0)
        controller.select(27, ROWS[1])
        controller.deactivate(clear=True)
        self.assertFalse(controller.active)
        self.assertEqual(controller.selected_ids, set())


class ProcessBatchSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _page(self, *, theme="claro"):
        service = FakeProductionService(theme=theme)
        page = ProcessPage(service, "PRODUCAO", "Produção")
        page._refresh_success((deepcopy(service.rows), {}))
        return page, service

    @staticmethod
    def _select_visible_row(page: ProcessPage, row: int = 0):
        page._handle_table_click(page.proxy.index(row, 1))

    def test_empty_state_uses_content_region_without_card_identity(self):
        page, _service = self._page()
        page.model.set_rows([])
        page._update_empty_state()

        self.assertIs(page.table_stack.currentWidget(), page.empty_state)
        self.assertEqual(page.empty_state.objectName(), "OperationalEmptyState")
        self.assertNotEqual(page.empty_state.objectName(), "Panel")
        self.assertNotEqual(page.empty_state.objectName(), "Card")

    def test_filter_without_results_uses_specific_empty_message(self):
        page, _service = self._page()
        page.search.setText("sem-correspondencia")

        self.assertIs(page.table_stack.currentWidget(), page.empty_state)
        labels = [label.text() for label in page.empty_state.findChildren(QLabel)]
        self.assertIn("Nenhum resultado para os filtros aplicados", labels)

    def test_normal_mode_has_no_checkbox_and_activation_adds_temporary_column(self):
        page, _service = self._page()
        self.assertEqual(page.model.columns[0][0], "status_icon")
        self.assertFalse(page.batch_selection.active)

        page.activate_batch_selection()

        self.assertEqual(page.model.columns[0][0], "batch_select")
        self.assertTrue(page.batch_selection.active)
        self.assertFalse(page.batch_mode_label.isHidden())
        self.assertTrue(page.normal_action_buttons[0].isHidden())

    def test_row_and_checkbox_toggle_exact_proposal_id(self):
        page, _service = self._page()
        page.activate_batch_selection()
        self._select_visible_row(page, 1)
        self.assertEqual(page.batch_selection.selected_ids, {27})
        self.assertEqual(page.model.data(page.model.index(1, 0), Qt.CheckStateRole), Qt.Checked)

        page.model.setData(page.model.index(1, 0), Qt.Unchecked, Qt.CheckStateRole)
        self.assertEqual(page.batch_selection.selected_ids, set())

    def test_real_mouse_clicks_toggle_row_checkbox_and_header(self):
        page, _service = self._page()
        page.resize(1200, 700)
        page.activate_batch_selection()
        page.show()
        self.app.processEvents()

        row_rect = page.table.visualRect(page.proxy.index(0, 2))
        QTest.mouseClick(page.table.viewport(), Qt.LeftButton, Qt.NoModifier, row_rect.center())
        checkbox_rect = page.table.visualRect(page.proxy.index(1, 0))
        QTest.mouseClick(page.table.viewport(), Qt.LeftButton, Qt.NoModifier, checkbox_rect.center())
        self.assertEqual(page.batch_selection.selected_ids, {10, 27})

        x = page.batch_header.sectionViewportPosition(0) + page.batch_header.sectionSize(0) // 2
        QTest.mouseClick(
            page.batch_header.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(x, page.batch_header.height() // 2),
        )
        self.assertEqual(page.batch_selection.selected_ids, {10, 27, 38})
        self.assertEqual(page.batch_header.check_state, Qt.Checked)

    def test_selection_accumulates_across_searches_and_reappears_checked(self):
        page, _service = self._page()
        page.activate_batch_selection()
        page.search.setText("CP05266")
        self._select_visible_row(page)
        page.search.setText("CP06120")
        self._select_visible_row(page)
        page.search.setText("CP07415")
        self._select_visible_row(page)

        self.assertEqual(page.batch_selection.selected_ids, {10, 27, 38})
        self.assertEqual(page.batch_count_label.text(), "3 propostas selecionadas")
        page.search.setText("CP05266")
        self.assertEqual(page.proxy.data(page.proxy.index(0, 0), Qt.CheckStateRole), Qt.Checked)

    def test_status_deadline_apply_and_clear_filters_preserve_selection(self):
        page, service = self._page()
        page.activate_batch_selection()
        self._select_visible_row(page)
        page.status.addItem("Em produção", "INICIADO")
        page.status.setCurrentIndex(page.status.findData("INICIADO"))
        page.prazo.setCurrentText("VENCIDOS")
        with patch("app.ui.process_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        self.assertEqual(page.batch_selection.selected_ids, {10})
        self.assertEqual(page.proxy.rowCount(), 1)

        with patch("app.ui.process_page.start_worker", side_effect=_run_synchronously):
            page.clear()
        self.assertEqual(page.batch_selection.selected_ids, {10})
        self.assertGreaterEqual(service.reads, 2)

    def test_header_selects_and_unselects_only_current_visible_rows(self):
        page, _service = self._page()
        page.activate_batch_selection()
        page.search.setText("CP05266")
        page._toggle_visible_batch_rows(True)
        page.search.setText("Cliente")
        page._toggle_visible_batch_rows(True)
        self.assertEqual(page.batch_selection.selected_ids, {10, 27, 38})
        self.assertEqual(page.batch_header.check_state, Qt.Checked)

        page._toggle_visible_batch_rows(False)
        self.assertEqual(page.batch_selection.selected_ids, {10})
        page.search.clear()
        self.assertEqual(page.batch_header.check_state, Qt.PartiallyChecked)

    def test_view_selected_includes_hidden_rows_and_individual_remove_updates_main_table(self):
        page, _service = self._page()
        page.activate_batch_selection()
        page.batch_selection.select(10, ROWS[0])
        page.batch_selection.select(27, ROWS[1])
        page.search.setText("CP06120")
        dialog = BatchSelectionReviewDialog(page.batch_selection, page)
        self.assertEqual(dialog.table.rowCount(), 2)

        dialog.table.cellWidget(0, 3).click()

        self.assertEqual(page.batch_selection.selected_ids, {27})
        self.assertEqual(page.batch_count_label.text(), "1 proposta selecionada")

    def test_clear_selection_keeps_mode_and_cancel_restores_normal_mode_without_writes(self):
        page, service = self._page()
        page.activate_batch_selection()
        page.batch_selection.select_many(ROWS)
        page.clear_selection_button.click()
        self.assertTrue(page.batch_selection.active)
        self.assertEqual(page.batch_selection.count, 0)
        self.assertEqual(page.model.columns[0][0], "batch_select")

        page.batch_selection.select(10, ROWS[0])
        page.cancel_selection_button.click()
        self.assertFalse(page.batch_selection.active)
        self.assertEqual(page.batch_selection.selected_ids, set())
        self.assertEqual(page.model.columns[0][0], "status_icon")
        self.assertEqual(service.writes, 0)

    def test_action_button_tracks_total_selection_not_visible_count(self):
        page, _service = self._page()
        page.activate_batch_selection()
        self.assertFalse(page.batch_actions_button.isEnabled())
        page.batch_selection.select(10, ROWS[0])
        page.search.setText("CP06120")
        self.assertTrue(page.batch_actions_button.isEnabled())
        self.assertEqual(page.batch_count_label.text(), "1 proposta selecionada")

    def test_refresh_preserves_selection_and_sorting_keeps_checkbox_with_id(self):
        page, _service = self._page()
        page.activate_batch_selection()
        page.batch_selection.select(27, ROWS[1])
        page._refresh_success((list(reversed(deepcopy(ROWS))), {}))
        proposal_column = next(index for index, (key, _label) in enumerate(page.model.columns) if key == "proposta")
        page.proxy.sort(proposal_column, Qt.DescendingOrder)

        checked_ids = set()
        for proxy_row in range(page.proxy.rowCount()):
            if page.proxy.data(page.proxy.index(proxy_row, 0), Qt.CheckStateRole) == Qt.Checked:
                source = page.proxy.mapToSource(page.proxy.index(proxy_row, 0))
                checked_ids.add(page.model.process_id_at(source.row()))
        self.assertEqual(checked_ids, {27})

    def test_search_and_selection_are_local_and_never_write(self):
        page, service = self._page(theme="escuro")
        page.activate_batch_selection()
        page.search.setText("Cliente")
        page._toggle_visible_batch_rows(True)
        page.search.clear()
        page.batch_selection.deselect(27)
        self.assertEqual(service.writes, 0)
        self.assertIsNotNone(page.model.data(page.model.index(2, 0), Qt.BackgroundRole))

    def test_batch_action_center_receives_exact_ids_area_and_labels_then_clears_and_refreshes(self):
        # "Acoes" (lote) agora abre BatchProposalActionCenter direto - sem
        # menu intermediario e sem o BatchStatusDialog antigo. A revalidacao
        # (validate_batch_selection) passou a acontecer dentro da propria
        # Central, no momento de cada card, nao mais aqui em ProcessPage -
        # ver tests/test_batch_action_center.py.
        page, service = self._page()
        page.activate_batch_selection()
        page.batch_selection.select(27, ROWS[1])
        page.batch_selection.select(10, ROWS[0])
        captured = {}

        class FakeCenter:
            changed = True

            def __init__(_self, _service, process_ids, area, _parent, **kwargs):
                captured["ids"] = list(process_ids)
                captured["area"] = area
                captured["labels"] = kwargs.get("proposal_labels")

            def exec(_self):
                return True

        refreshes = []
        page.refresh = lambda: refreshes.append(True)
        with patch("app.ui.process_page.BatchProposalActionCenter", FakeCenter):
            page.open_batch_action_center()

        self.assertEqual(captured["ids"], [27, 10])
        self.assertEqual(captured["area"], "PRODUCAO")
        self.assertEqual(captured["labels"], {27: "CP06120", 10: "CP05266"})
        self.assertEqual(service.last_validation, None)
        self.assertFalse(page.batch_selection.active)
        self.assertEqual(page.batch_selection.selected_ids, set())
        self.assertEqual(refreshes, [True])

    def test_no_selection_shows_toast_and_does_not_open_center(self):
        page, _service = self._page()
        page.activate_batch_selection()
        with patch("app.ui.process_page.BatchProposalActionCenter") as center, patch(
            "app.ui.process_page.ToastNotification"
        ) as toast:
            page.open_batch_action_center()
        center.assert_not_called()
        toast.assert_called_once()

    def test_strict_executor_locks_preselection_and_blocks_disappeared_proposal(self):
        service = FakeBatchDialogService()
        dialog = BatchStatusDialog(
            service,
            [10, 999],
            "PRODUCAO",
            strict_preselection=True,
            lock_area=True,
        )
        self.assertEqual(dialog.selected_ids, [10])
        self.assertEqual(dialog.invalid_preselected_ids, [999])
        self.assertFalse(dialog.area_combo.isEnabled())
        self.assertFalse(dialog.add_btn.isEnabled())
        self.assertIn("CP05266", dialog._confirmation_text("Iniciar produção"))

        with patch("app.ui.batch_status_dialog.QMessageBox.warning") as warning:
            dialog.apply_batch()
        warning.assert_called_once()
        self.assertEqual(service.writes, 0)

    def test_strict_executor_revalidates_again_immediately_before_confirmation(self):
        service = FakeBatchDialogService()
        dialog = BatchStatusDialog(
            service,
            [10],
            "PRODUCAO",
            strict_preselection=True,
            lock_area=True,
        )
        service.validation_result = {
            "valid_ids": [],
            "incompatible": [{"id": 10, "proposta": "CP05266", "reason": "estado alterado"}],
            "common_statuses": [],
            "global_reason": "",
        }
        with (
            patch("app.ui.batch_status_dialog.QMessageBox.warning") as warning,
            patch("app.ui.batch_status_dialog.QMessageBox.question") as confirmation,
        ):
            dialog.apply_batch()

        warning.assert_called_once()
        confirmation.assert_not_called()
        self.assertEqual(service.last_validation, ("PRODUCAO", [10], "STATUS"))
        self.assertEqual(service.writes, 0)


class CheckboxBatchAllAreasTests(unittest.TestCase):
    """As 5 areas migradas (Controle Geral, Producao, Expedicao,
    Almoxarifado, Galvanizacao) usam a mesma selecao por checkbox e o mesmo
    ponto de abertura, `open_batch_action_center()` -> `BatchProposalActionCenter`
    - nao ha mais menu intermediario nem `BatchStatusDialog` na entrada de
    "Acoes em lote" para nenhuma delas. `BatchStatusDialog` continua
    existindo/testado (test_strict_executor_* acima) e ainda e o fallback
    para areas fora de `_CHECKBOX_BATCH_AREAS`."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    _AREAS = ("CONTROLE GERAL", "PRODUCAO", "EXPEDICAO", "ALMOXARIFADO", "GALVANIZACAO")

    def _page(self, area: str):
        service = FakeProductionService()
        page = ProcessPage(service, area, area.title())
        page._refresh_success((deepcopy(service.rows), {}))
        return page, service

    def test_all_five_areas_enter_checkbox_mode_via_the_batch_button(self):
        for area in self._AREAS:
            with self.subTest(area=area):
                page, _service = self._page(area)
                with patch("app.ui.process_page.BatchStatusDialog") as dialog, patch(
                    "app.ui.process_page.BatchProposalActionCenter"
                ) as center:
                    page.activate_batch_selection()
                dialog.assert_not_called()
                center.assert_not_called()  # so abre ao clicar em "Acoes", nao ao ativar o modo
                self.assertTrue(page.batch_selection.active)
                self.assertEqual(page.model.columns[0][0], "batch_select")

    def test_context_menu_batch_entry_enters_checkbox_mode_for_every_area(self):
        # "Acoes em lote..." do menu contextual chama change_status_batch() -
        # deve convergir para o mesmo modo de checkbox do botao "Acoes".
        for area in self._AREAS:
            with self.subTest(area=area):
                page, _service = self._page(area)
                with patch("app.ui.process_page.BatchStatusDialog") as dialog:
                    page.change_status_batch()
                dialog.assert_not_called()
                self.assertTrue(page.batch_selection.active)

    def test_area_outside_the_checkbox_set_still_opens_the_old_dialog_directly(self):
        # PARCIAIS nunca teve "Acoes em lote" funcional e continua fora do
        # conjunto de checkbox - guarda de que o fallback ainda existe.
        service = FakeProductionService()
        page = ProcessPage(service, "PARCIAIS", "Parciais")
        page._refresh_success((deepcopy(service.rows), {}))
        with patch("app.ui.process_page.BatchStatusDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            page.activate_batch_selection()
        dialog.assert_called_once()
        self.assertFalse(page.batch_selection.active)

    def test_batch_button_click_opens_the_center_directly_with_no_menu(self):
        # O botao "Acoes" nao tem mais QMenu associado - clicar chama
        # open_batch_action_center() direto.
        page, _service = self._page("CONTROLE GERAL")
        page.activate_batch_selection()
        self.assertIsNone(page.batch_actions_button.menu())
        page.batch_selection.select(10, ROWS[0])
        with patch("app.ui.process_page.BatchProposalActionCenter") as center:
            center.return_value.exec.return_value = 0
            center.return_value.changed = False
            page.batch_actions_button.click()
        center.assert_called_once()

    def test_open_batch_action_center_receives_correct_area_and_ids_for_every_area(self):
        for area in self._AREAS:
            with self.subTest(area=area):
                page, _service = self._page(area)
                page.activate_batch_selection()
                page.batch_selection.select(27, ROWS[1])
                page.batch_selection.select(10, ROWS[0])
                captured = {}

                class FakeCenter:
                    changed = False

                    def __init__(_self, _service, process_ids, dlg_area, _parent, **kwargs):
                        captured["ids"] = list(process_ids)
                        captured["area"] = dlg_area

                    def exec(_self):
                        return False

                with patch("app.ui.process_page.BatchProposalActionCenter", FakeCenter):
                    page.open_batch_action_center()

                self.assertEqual(captured, {"ids": [27, 10], "area": area})
                # cancelar (exec()=False, changed=False) mantem o modo de lote aberto
                self.assertTrue(page.batch_selection.active)

    def test_permission_denied_blocks_opening_for_every_area(self):
        for area in self._AREAS:
            with self.subTest(area=area):
                page, service = self._page(area)
                page.activate_batch_selection()
                page.batch_selection.select(10, ROWS[0])
                service.can_edit_area = lambda _area: False
                with patch("app.ui.process_page.BatchProposalActionCenter") as center:
                    page.open_batch_action_center()
                center.assert_not_called()


if __name__ == "__main__":
    unittest.main()
