"""Icone na coluna 0 (Central de Acoes) e menu de contexto nas listas de Inspecao e Logistica."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import test_inspection_entry_desktop as insp
import test_logistics_desktop as logi
from PySide6.QtWidgets import QMenu

from app.ui import inspection_page as insp_page_module
from app.ui import logistics_dialogs as dialogs_module
from app.ui import logistics_page as logi_page_module
from app.ui.components import row_actions as row_actions_module
from app.ui.components.row_actions import RowActionIconDelegate
from app.ui.inspection_page import InspectionPage
from app.ui.logistics_dialogs import LoadDetailDialog, LogDetailDialog
from app.ui.logistics_page import LogisticsPage


class _CenterSpy:
    calls: list[tuple[str, list[str]]] = []

    def __init__(self, palette, title, actions, parent=None):
        _CenterSpy.calls.append((title, [a.label for a in actions]))

    def exec(self):
        return 0


def context_menu_labels(table, row: int) -> list[str]:
    """Dispara o botao direito na linha e devolve os rotulos do QMenu (sem abrir o menu real)."""
    captured: list[list[str]] = []

    class SpyMenu(QMenu):
        def exec(self, *_args):
            captured.append([action.text() for action in self.actions() if action.isEnabled()])

    position = table.visualRect(table.model().index(row, 1)).center()
    with patch.object(row_actions_module, "QMenu", SpyMenu):
        table.customContextMenuRequested.emit(position)
    return captured[0] if captured else []


class _SpyMixin:
    def setUp(self):
        super().setUp()
        _CenterSpy.calls = []
        for module in (insp_page_module, logi_page_module):
            patcher = patch.object(module, "RowActionCenter", _CenterSpy)
            patcher.start()
            self.addCleanup(patcher.stop)


class InspectionRowActionsTests(_SpyMixin, insp.QtCase):
    def _page(self):
        api = insp.FakeApi()
        api.items = [{"id": 1, "pd_code": "PD-1", "proposal_numbers": ["CP 1"], "stage": "solicitada", "attempt": 1, "days_in_stage": 2}]
        api.to_request = [
            {"row_type": "to_request", "pd_code": None, "proposal_id": 7, "proposal_numbers": ["CP 700"], "customer_name": "Cliente A", "proposals": []}
        ]
        page = InspectionPage(insp.FakeService(api))
        page.refresh()
        return page

    def test_icon_column_uses_delegate_and_click_opens_center_on_that_row(self):
        page = self._page()
        self.assertIsInstance(page.table.itemDelegateForColumn(0), RowActionIconDelegate)
        page.table.cellClicked.emit(1, 0)
        self.assertEqual(_CenterSpy.calls, [("PD PD-1", ["Detalhes", "Registrar andamento", "Nova inspeção"])])
        self.assertEqual(page.table.currentRow(), 1)

    def test_click_outside_icon_column_does_not_open_center(self):
        page = self._page()
        page.table.cellClicked.emit(1, 1)
        self.assertEqual(_CenterSpy.calls, [])

    def test_context_menu_depends_on_row_type(self):
        page = self._page()
        self.assertEqual(context_menu_labels(page.table, 0), ["Iniciar inspeção", "Nova inspeção"])
        self.assertEqual(context_menu_labels(page.table, 1), ["Detalhes", "Registrar andamento", "Nova inspeção"])
        self.assertEqual(page.table.currentRow(), 1)  # botao direito seleciona a linha

    def test_view_only_user_gets_only_details(self):
        page = self._page()
        page.can_edit = False
        self.assertEqual(context_menu_labels(page.table, 1), ["Detalhes"])
        self.assertEqual(context_menu_labels(page.table, 0), [])


class LogisticsRowActionsTests(_SpyMixin, logi.QtCase):
    def _page(self, logs=None, loads=None, can_edit=True, tab="logs"):
        api = logi.FakeLogisticsApi(logs, loads if loads is not None else [logi._load()])
        page = LogisticsPage(logi.FakeService(api, can_edit))
        page.refresh()
        if tab == "loads":
            page.tabs.set_current_key("loads")
        return page

    def test_logs_click_opens_center_with_progress_for_open_log(self):
        page = self._page()
        page.logs_table.cellClicked.emit(0, 0)
        self.assertEqual(_CenterSpy.calls, [("LOG101", ["Detalhes", "Editar datas", "Registrar andamento"])])

    def test_logs_menu_for_delivered_log_offers_delivery_correction(self):
        page = self._page(logs=[logi._log(stage="aprovada", display_stage="entregue", delivered_on="2026-11-11")])
        self.assertEqual(context_menu_labels(page.logs_table, 0), ["Detalhes", "Editar datas", "Corrigir entrega"])

    def test_logs_view_only_gets_only_details(self):
        page = self._page(can_edit=False)
        self.assertEqual(context_menu_labels(page.logs_table, 0), ["Detalhes"])

    def test_loads_menu_and_click(self):
        page = self._page(tab="loads")
        self.assertEqual(context_menu_labels(page.loads_table, 0), ["Detalhes", "Saiu em", "Desfazer carga"])
        page.loads_table.cellClicked.emit(0, 0)
        self.assertEqual(_CenterSpy.calls, [("CE-01", ["Detalhes", "Saiu em", "Desfazer carga"])])

    def test_loads_view_only_gets_only_details(self):
        page = self._page(can_edit=False, tab="loads")
        self.assertEqual(context_menu_labels(page.loads_table, 0), ["Detalhes"])

    def test_action_opens_detail_with_start_action(self):
        page = self._page()
        page.logs_table.selectRow(0)
        opened = []

        class FakeDialog:
            changed = False

            def __init__(self, service, item, parent, can_edit, start_action=None):
                opened.append(start_action)

            def exec(self):
                return 0

        with patch.object(logi_page_module, "LogDetailDialog", FakeDialog):
            for action in page._log_actions(0):
                action.callback()
        self.assertEqual(opened, [None, "open_edit_dates", "open_progress"])


class StartActionTests(logi.QtCase):
    def test_log_dialog_runs_start_action_once_after_loading(self):
        api = logi.FakeLogisticsApi()
        api.result = logi._log()
        with patch.object(LogDetailDialog, "open_edit_dates") as action:
            dialog = LogDetailDialog(logi.FakeService(api), logi._log(), can_edit=True, start_action="open_edit_dates")
            dialog._apply(logi._log())
        action.assert_called_once()

    def test_load_dialog_start_action(self):
        api = logi.FakeLogisticsApi()
        api.result = logi._load()
        with patch.object(LoadDetailDialog, "open_departed") as action:
            LoadDetailDialog(logi.FakeService(api), logi._load(), can_edit=True, start_action="open_departed")
        action.assert_called_once()


if __name__ == "__main__":
    unittest.main()
