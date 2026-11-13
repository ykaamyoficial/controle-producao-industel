"""Icone na coluna 0 (Central de Acoes) e menu de contexto nas listas de Inspecao e Logistica."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import test_inspection_entry_desktop as insp
import test_logistics_desktop as logi
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMenu

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui import inspection_page as insp_page_module
from app.ui import logistics_dialogs as dialogs_module
from app.ui import logistics_page as logi_page_module
from app.ui.components import row_actions as row_actions_module
from app.ui.action_center.row_action_center import RowActionCenter
from app.ui.components.row_actions import RowAction, RowActionIconDelegate
from app.ui.inspection_page import InspectionPage
from app.ui.logistics_dialogs import LoadDetailDialog, LogDetailDialog
from app.ui.logistics_page import LogisticsPage


class _CenterSpy:
    calls: list[tuple[str, list[str]]] = []

    def __init__(self, palette, title, actions, parent=None):
        _CenterSpy.calls.append((title, [a.label for a in actions]))

    def exec(self):
        return 0

    def deleteLater(self):
        pass


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


def trigger_menu_action(table, row: int, label: str) -> None:
    """Botao direito na linha e aciona (QAction.triggered) a entrada com esse rotulo."""

    class TriggerMenu(QMenu):
        def exec(self, *_args):
            next(a for a in self.actions() if a.text() == label).trigger()

    position = table.visualRect(table.model().index(row, 1)).center()
    with patch.object(row_actions_module, "QMenu", TriggerMenu):
        table.customContextMenuRequested.emit(position)


class _SpyMixin:
    def setUp(self):
        super().setUp()
        _CenterSpy.calls = []
        for module in (insp_page_module, logi_page_module):
            patcher = patch.object(module, "RowActionCenter", _CenterSpy)
            patcher.start()
            self.addCleanup(patcher.stop)


class RowActionCenterTests(insp.QtCase):
    def test_callback_runs_after_exec_with_center_closed(self):
        seen = []
        center = None

        def callback():
            seen.append(center.isVisible())

        actions = [RowAction("Fazer", "info", True, callback), RowAction("Apagar", "close", True, lambda: None, destructive=True)]
        center = RowActionCenter(OFFICIAL_COLOR_PALETTES["claro"], "T", actions)
        QTimer.singleShot(0, center.cards[0].click)
        center.exec()
        self.assertEqual(seen, [False])

    def test_destructive_action_uses_destructive_card(self):
        actions = [RowAction("Fazer", "info", True, lambda: None), RowAction("Apagar", "close", True, lambda: None, destructive=True)]
        center = RowActionCenter(OFFICIAL_COLOR_PALETTES["claro"], "T", actions)
        plain = RowActionCenter(OFFICIAL_COLOR_PALETTES["claro"], "T", [RowAction("Apagar", "close", True, lambda: None)])
        self.assertNotEqual(center.cards[1].styleSheet(), plain.cards[0].styleSheet())


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

    def test_to_request_row_center_and_menu_trigger(self):
        page = self._page()
        page.table.cellClicked.emit(0, 0)
        self.assertEqual(_CenterSpy.calls, [("Inspeção", ["Iniciar inspeção", "Nova inspeção"])])
        with patch.object(page, "open_new") as opened:
            trigger_menu_action(page.table, 0, "Nova inspeção")
        opened.assert_called_once()

    def test_double_click_on_icon_column_does_not_open_details(self):
        page = self._page()
        with patch.object(page, "open_selected") as opened:
            page.table.doubleClicked.emit(page.table.model().index(1, 0))
            opened.assert_not_called()
            page.table.doubleClicked.emit(page.table.model().index(1, 1))
            opened.assert_called_once()

    def test_view_only_user_cannot_start_inspection(self):
        page = self._page()
        page.can_edit = False
        page.table.selectRow(0)
        with patch.object(insp_page_module, "start_inspection_for_proposal") as start:
            page.start_selected()
        start.assert_not_called()

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
        self.assertEqual(_CenterSpy.calls, [("LOG101", ["Detalhes", "Imprimir relatório", "Editar datas", "Registrar andamento"])])

    def test_logs_menu_for_delivered_log_offers_delivery_correction(self):
        page = self._page(logs=[logi._log(stage="aprovada", display_stage="entregue", delivered_on="2026-11-11")])
        self.assertEqual(context_menu_labels(page.logs_table, 0), ["Detalhes", "Imprimir relatório", "Editar datas", "Corrigir entrega"])

    def test_logs_view_only_gets_only_details(self):
        page = self._page(can_edit=False)
        self.assertEqual(context_menu_labels(page.logs_table, 0), ["Detalhes", "Imprimir relatório"])

    def test_loads_menu_and_click(self):
        page = self._page(tab="loads")
        self.assertEqual(context_menu_labels(page.loads_table, 0), ["Detalhes", "Imprimir relatório", "Saiu em", "Desfazer carga"])
        page.loads_table.cellClicked.emit(0, 0)
        self.assertEqual(_CenterSpy.calls, [("CE-01", ["Detalhes", "Imprimir relatório", "Saiu em", "Desfazer carga"])])

    def test_undo_load_is_destructive(self):
        page = self._page(tab="loads")
        by_label = {a.label: a for a in page._load_actions(0)}
        self.assertTrue(by_label["Desfazer carga"].destructive)
        self.assertFalse(by_label["Saiu em"].destructive)

    def test_print_report_action_is_plain(self):
        for tab, actions in (("logs", lambda p: p._log_actions(0)), ("loads", lambda p: p._load_actions(0))):
            by_label = {a.label: a for a in actions(self._page(tab=tab))}
            self.assertFalse(by_label["Imprimir relatório"].primary)
            self.assertFalse(by_label["Imprimir relatório"].destructive)

    def test_print_report_fetches_detail_and_calls_report_actions(self):
        page = self._page()
        page.logs_table.selectRow(0)
        with patch.object(logi_page_module.report_actions, "save_log_report") as save:
            trigger_menu_action(page.logs_table, 0, "Imprimir relatório")
        parent, detail, service = save.call_args.args
        self.assertEqual(detail["code"], "LOG101")
        self.assertIs(service, page.service)
        self.assertIn(("get_log", 1), page.service.api.calls)

    def test_print_report_on_loads_tab(self):
        page = self._page(tab="loads")
        page.loads_table.selectRow(0)
        page.service.api.get_load = lambda load_id: logi._load(id=load_id)
        with patch.object(logi_page_module.report_actions, "save_load_report") as save:
            trigger_menu_action(page.loads_table, 0, "Imprimir relatório")
        self.assertEqual(save.call_args.args[1]["code"], "CE-01")

    def test_print_report_fetch_error_warns_without_report(self):
        page = self._page()
        page.logs_table.selectRow(0)
        page.service.api.error = OSError("sem rede")
        with patch.object(logi_page_module.report_actions, "save_log_report") as save,                 patch.object(logi_page_module.QMessageBox, "warning") as warning:
            page._print_report()
        save.assert_not_called()
        warning.assert_called_once()

    def test_double_click_on_icon_column_does_not_open_details(self):
        page = self._page()
        with patch.object(page, "open_selected") as opened:
            page.logs_table.doubleClicked.emit(page.logs_table.model().index(0, 0))
            opened.assert_not_called()

    def test_loads_view_only_gets_only_details(self):
        page = self._page(can_edit=False, tab="loads")
        self.assertEqual(context_menu_labels(page.loads_table, 0), ["Detalhes", "Imprimir relatório"])

    def test_menu_triggered_runs_callback(self):
        page = self._page()
        opened = []
        with patch.object(page, "_open_detail", lambda start_action=None: opened.append(start_action)):
            trigger_menu_action(page.logs_table, 0, "Editar datas")
        self.assertEqual(opened, ["open_edit_dates"])

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

        with patch.object(logi_page_module, "LogDetailDialog", FakeDialog),                 patch.object(logi_page_module.report_actions, "save_log_report"):
            for action in page._log_actions(0):
                action.callback()
        self.assertEqual(opened, [None, "open_edit_dates", "open_progress"])


class StartActionTests(logi.QtCase):
    def test_start_action_blocked_when_updated_state_does_not_offer_button(self):
        api = logi.FakeLogisticsApi()
        delivered = logi._log(stage="aprovada", display_stage="entregue", delivered_on="2026-11-11")
        api.result = delivered
        with patch.object(LogDetailDialog, "open_progress") as action:
            dialog = LogDetailDialog(logi.FakeService(api), logi._log(), can_edit=True, start_action="open_progress")
            dialog._apply(delivered)
        action.assert_not_called()

    def test_start_action_blocked_without_edit_permission(self):
        api = logi.FakeLogisticsApi()
        with patch.object(LogDetailDialog, "open_edit_dates") as action:
            dialog = LogDetailDialog(logi.FakeService(api, False), logi._log(), can_edit=False, start_action="open_edit_dates")
            dialog._apply(logi._log())
        action.assert_not_called()

    def test_start_action_cleared_on_error(self):
        with patch.object(LogDetailDialog, "open_edit_dates"):
            dialog = LogDetailDialog(logi.FakeService(logi.FakeLogisticsApi()), logi._log(), can_edit=True, start_action="open_edit_dates")
        dialog._start_action = "open_edit_dates"
        dialog._show_error(RuntimeError("falhou"))
        self.assertIsNone(dialog._start_action)

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
