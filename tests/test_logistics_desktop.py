from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox

from app.integrations.api.exceptions import ApiBusinessError
from app.integrations.api.logistics_client import LogisticsApiClient
from app.services.api_proposal_storage import api_permission_level, legacy_permissions_to_api_codes
from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES, AppError
from app.services.logistics_service import ERROR_MESSAGES, LogisticsService
from app.ui import date_edit_dialog as date_edit_module
from app.ui import logistics_dialogs as dialogs_module
from app.ui import logistics_page as page_module
from app.ui.logistics_dialogs import (
    LoadDetailDialog,
    LogDetailDialog,
    NewLoadDialog,
    NewLogDialog,
    check_links,
    parse_date,
)
from app.ui.logistics_page import LogisticsPage
from app.ui.sidebar import NAV_LABELS, Sidebar


def _sync_worker(owner, operation, on_success, on_error, *, operation_name=None):
    try:
        result = operation()
    except Exception as exc:  # noqa: BLE001 - igual ao worker real
        on_error(exc)
    else:
        on_success(result)


def _log(**changes) -> dict:
    base = {
        "id": 1, "code": "LOG101", "state": "EQT-MA", "requested_date": "2026-11-10", "reserved_date": "2026-11-10",
        "loading_date": "2026-11-09", "delivery_date": "2026-11-10", "stage": "reservada", "stage_since": "2026-10-15T10:00:00Z",
        "days_in_stage": 4, "business_days_in_stage": 2, "delivered_on": None, "delivery_proof_link": None, "nf_link": None, "xml_link": None, "bim_link": None, "load_id": None, "load_code": None,
        "proposal_count": 2, "created_at": "2026-10-15T10:00:00Z", "updated_at": "2026-10-15T10:00:00Z",
        "items": [
            {"id": 10, "proposal_id": 1, "proposal_number": "10480/B", "customer_name": "Torres Norte", "project_name": "X", "pd_code": "PD-1180",
             "status": "ok", "added_at": "2026-10-15T10:00:00Z"},
            {"id": 11, "proposal_id": 2, "proposal_number": "10483/A", "customer_name": "Serra Azul", "project_name": "Y", "pd_code": "PD-1180",
             "status": "pendente", "added_at": "2026-10-16T10:00:00Z"},
        ],
        "removed_items": [], "events": [],
    }
    return {**base, **changes}


def _load(**changes) -> dict:
    base = {
        "id": 5, "code": "CE-01", "departure_date": "2026-11-08", "departed_on": None, "logs_total": 2, "logs_delivered": 0, "log_count": 2, "proposal_count": 3, "log_codes": ["LOG101", "LOG102"],
        "states": ["EQT-MA", "EQT-PA"], "created_at": "2026-10-15T10:00:00Z", "updated_at": "2026-10-15T10:00:00Z",
        "logs": [_log(stage="aprovada"), _log(id=2, code="LOG102", state="EQT-PA", stage="aprovada")], "events": [],
    }
    return {**base, **changes}


class FakeHttp:
    def __init__(self):
        self.calls = []

    def _ok(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return type("Resp", (), {"data": {"ok": True}})()

    def get(self, path, access_token=None):
        return self._ok("GET", path)

    def post(self, path, json_payload=None, access_token=None):
        return self._ok("POST", path, json_payload)

    def patch(self, path, json_payload=None, access_token=None):
        return self._ok("PATCH", path, json_payload)

    def delete(self, path, json_payload=None, access_token=None):
        return self._ok("DELETE", path)


class FakeLogisticsApi:
    """Servico de logistica falso: cada chamada vai para `calls`; `error` e levantado se definido."""

    def __init__(self, logs=None, loads=None, eligible=None):
        self.logs = logs if logs is not None else [_log()]
        self.loads = loads if loads is not None else []
        self.eligible = eligible if eligible is not None else [
            {"id": 7, "proposal_number": "10489/C", "customer_name": "Rede Sul", "project_name": "Z", "pd_code": "PD-1195", "nqt_code": "NQT-1"}
        ]
        self.calls: list[tuple] = []
        self.error: Exception | None = None
        self.result: dict | None = None
        self.remove_result: dict = {"log_deleted": False, "log": _log()}

    def _respond(self, name, *args, default=None):
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error
        return self.result if self.result is not None else (default if default is not None else _log())

    def list_logs(self, **kwargs):
        self.calls.append(("list_logs", kwargs))
        if self.error is not None:
            raise self.error
        return {"items": self.logs, "total": len(self.logs)}

    def eligible_proposals(self, **kwargs):
        self.calls.append(("eligible", kwargs))
        return {"items": self.eligible, "total": len(self.eligible)}

    def get_log(self, log_id):
        return self._respond("get_log", log_id)

    def create_log(self, payload):
        return self._respond("create_log", dict(payload))

    def send_docs(self, log_id, nf, xml, bim):
        return self._respond("send_docs", log_id, nf, xml, bim)

    def approve_log(self, log_id):
        return self._respond("approve_log", log_id)

    def add_proposals(self, log_id, ids):
        return self._respond("add_proposals", log_id, ids)

    def resolve_item(self, log_id, item_id, result):
        return self._respond("resolve_item", log_id, item_id, result)

    def remove_item(self, log_id, item_id, reason):
        self.calls.append(("remove_item", log_id, item_id, reason))
        if self.error is not None:
            raise self.error
        return self.remove_result

    def list_loads(self, **kwargs):
        self.calls.append(("list_loads", kwargs))
        if self.error is not None:
            raise self.error
        return {"items": self.loads, "total": len(self.loads)}

    def get_load(self, load_id):
        return self._respond("get_load", load_id, default=_load())

    def create_load(self, departure_date, log_ids, confirm_dates=False):
        extra = (True,) if confirm_dates else ()
        return self._respond("create_load", departure_date, log_ids, *extra, default=_load())

    def update_log_dates(self, log_id, dates, reason, confirm_dates=False):
        extra = (True,) if confirm_dates else ()
        return self._respond("update_log_dates", log_id, dict(dates), reason, *extra)

    def log_delivery(self, log_id, delivered_on, proof_link=None, reason=None):
        return self._respond("log_delivery", log_id, delivered_on, proof_link, reason)

    def load_departed(self, load_id, departed_on, reason=None):
        return self._respond("load_departed", load_id, departed_on, reason, default=_load())

    def update_load(self, load_id, departure_date, reason, confirm_dates=False):
        extra = (True,) if confirm_dates else ()
        return self._respond("update_load", load_id, departure_date, reason, *extra, default=_load())

    def remove_log_from_load(self, load_id, log_id):
        return self._respond("remove_log_from_load", load_id, log_id, default=_load())

    def delete_load(self, load_id):
        self.calls.append(("delete_load", load_id))
        if self.error is not None:
            raise self.error


class FakeService:
    def __init__(self, api=None, can_edit=True):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.company = "Industel"
        self.api = api or FakeLogisticsApi()
        self.edit = can_edit

    def logistics_service(self):
        return self.api

    def can_edit(self, area):
        return area == "logistics" and self.edit

    def can_view_nav(self, key):
        return key != "LOGISTICA" or self.edit


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for module in (page_module, dialogs_module, date_edit_module):
            item = patch.object(module, "start_worker", _sync_worker)
            item.start()
            self.addCleanup(item.stop)


class ClientAndServiceTests(unittest.TestCase):
    def test_client_builds_paths_and_payloads(self):
        http = FakeHttp()
        client = LogisticsApiClient(http)
        client.list_logs("t", stage="aprovada", search=" LOG1 ", in_load=False, limit=200, offset=0)
        client.eligible_proposals("t", search="104")
        client.log_action("t", 3, "docs", {"nf_link": "a", "xml_link": "b", "bim_link": "c"})
        client.log_action("t", 3, "items/9/resolve", {"result": "ok"})
        client.list_loads("t")
        client.create_load("t", departure_date="2026-11-08", log_ids=[1, 2])
        client.update_load("t", 5, departure_date="2026-11-09", reason="chuva")
        client.add_log_to_load("t", 5, 4)
        client.remove_log_from_load("t", 5, 4)
        client.delete_load("t", 5)
        paths = [(c[0], c[1], c[2]) for c in http.calls]
        self.assertEqual(paths[0], ("GET", "/api/v1/logistics/logs?stage=aprovada&search=LOG1&in_load=false&limit=200&offset=0", None))
        self.assertEqual(paths[1], ("GET", "/api/v1/logistics/eligible-proposals?search=104&limit=200&offset=0", None))
        self.assertEqual(paths[2], ("POST", "/api/v1/logistics/logs/3/docs", {"nf_link": "a", "xml_link": "b", "bim_link": "c"}))
        self.assertEqual(paths[3], ("POST", "/api/v1/logistics/logs/3/items/9/resolve", {"result": "ok"}))
        self.assertEqual(paths[4], ("GET", "/api/v1/logistics/loads?limit=100&offset=0", None))
        self.assertEqual(paths[5], ("POST", "/api/v1/logistics/loads", {"departure_date": "2026-11-08", "log_ids": [1, 2]}))
        self.assertEqual(paths[6], ("PATCH", "/api/v1/logistics/loads/5", {"departure_date": "2026-11-09", "reason": "chuva"}))
        self.assertEqual(paths[7], ("POST", "/api/v1/logistics/loads/5/logs", {"log_id": 4}))
        self.assertEqual(paths[8], ("DELETE", "/api/v1/logistics/loads/5/logs/4", None))
        self.assertEqual(paths[9], ("DELETE", "/api/v1/logistics/loads/5", None))

    def test_service_maps_every_api_error_code_to_portuguese(self):
        class Client:
            closed = False

            def close(self):
                self.closed = True

        client = Client()
        code_holder = {}

        class Api:
            def get_log(self, token, log_id):
                raise ApiBusinessError(code_holder["code"], "tecnico", status_code=409)

        class Storage:
            def logistics_api(self):
                return client, Api(), "tok"

        def wrap(exc):
            return AppError(str(exc), error_code=getattr(exc, "error_code", None))

        service = LogisticsService(Storage(), wrap)
        for code, message in ERROR_MESSAGES.items():
            code_holder["code"] = code
            with self.assertRaises(AppError) as caught:
                service.get_log(1)
            self.assertEqual(str(caught.exception), message)
        self.assertTrue(client.closed)
        for code in (
            "LOGISTICS_LOG_NOT_FOUND", "LOGISTICS_LOG_CODE_ALREADY_EXISTS", "LOGISTICS_INVALID_STAGE", "LOGISTICS_PROPOSAL_NOT_FOUND",
            "LOGISTICS_INSPECTION_NOT_FINISHED", "LOGISTICS_PROPOSAL_ALREADY_IN_LOG", "LOGISTICS_ITEM_NOT_FOUND", "LOGISTICS_ITEM_NOT_PENDING",
            "LOGISTICS_LOAD_NOT_FOUND", "LOGISTICS_LOG_NOT_APPROVED", "LOGISTICS_LOG_ALREADY_IN_LOAD",
            "LOGISTICS_LOG_NOT_IN_THIS_LOAD", "LOGISTICS_LOAD_LAST_LOG", "VALIDATION_ERROR", "PERMISSION_DENIED",
        ):
            self.assertIn(code, ERROR_MESSAGES)

    def test_log_in_load_keeps_the_api_message_and_details_survive(self):
        class Client:
            def close(self):
                pass

        class Api:
            def add_proposals(self, token, log_id, ids):
                raise ApiBusinessError("LOGISTICS_LOG_IN_LOAD", "técnico", status_code=409)

            def get_log(self, token, log_id):
                raise ApiBusinessError("DATE_CONFIRMATION_REQUIRED", "Há avisos", status_code=409, details={"warnings": [{"message": "x"}]})

        class Storage:
            def logistics_api(self):
                return Client(), Api(), "tok"

        def wrap(exc):
            return AppError("O LOG101 esta na carga CE-01.", error_code=exc.error_code, details=getattr(exc, "details", None))

        service = LogisticsService(Storage(), wrap)
        self.assertNotIn("LOGISTICS_LOG_IN_LOAD", ERROR_MESSAGES)
        with self.assertRaises(AppError) as caught:
            service.get_log(1)
        self.assertEqual(caught.exception.details, {"warnings": [{"message": "x"}]})

    def test_new_endpoints_build_paths_and_payloads(self):
        http = FakeHttp()
        client = LogisticsApiClient(http)
        client.update_log_dates("t", 3, {"delivery_date": "2026-12-01", "reason": "r"})
        client.log_delivery("t", 3, {"delivered_on": "2026-12-02"})
        client.load_departed("t", 5, {"departed_on": "2026-12-05"})
        client.create_load("t", departure_date="2026-11-08", log_ids=[1], confirm_dates=True)
        paths = [(c[0], c[1], c[2]) for c in http.calls]
        self.assertEqual(paths[0], ("PATCH", "/api/v1/logistics/logs/3/dates", {"delivery_date": "2026-12-01", "reason": "r"}))
        self.assertEqual(paths[1], ("POST", "/api/v1/logistics/logs/3/delivery", {"delivered_on": "2026-12-02"}))
        self.assertEqual(paths[2], ("POST", "/api/v1/logistics/loads/5/departed", {"departed_on": "2026-12-05"}))
        self.assertEqual(paths[3][2], {"departure_date": "2026-11-08", "log_ids": [1], "confirm_dates": True})

    def test_helpers(self):
        self.assertEqual(parse_date("03/11/2026", "data"), "2026-11-03")
        with self.assertRaises(ValueError) as caught:
            parse_date("2026-11-03", "data de saída")
        self.assertEqual(str(caught.exception), "Data de saída inválida. Use DD/MM/AAAA.")
        with self.assertRaises(ValueError):
            parse_date("", "data")
        with self.assertRaises(ValueError):
            check_links("a", "", "c")
        with self.assertRaises(ValueError):
            check_links("a", "b", "x" * 501)
        self.assertEqual(check_links(" a ", "b", "c"), ("a", "b", "c"))


class PermissionTests(unittest.TestCase):
    def test_logistics_permissions_map_to_the_area(self):
        self.assertEqual(api_permission_level({"logistics.view"}, "logistics"), "VIEW")
        self.assertEqual(api_permission_level({"logistics.edit"}, "logistics"), "EDIT")
        self.assertEqual(api_permission_level({"inspection.edit"}, "logistics"), "NONE")
        self.assertEqual(legacy_permissions_to_api_codes({"logistics": "EDIT"}), ["logistics.edit", "logistics.view"])

    def test_sidebar_shows_logistics_only_with_permission(self):
        self.assertEqual(NAV_LABELS["LOGISTICA"], "Logística")
        QApplication.instance() or QApplication([])
        self.assertIn("LOGISTICA", Sidebar(FakeService(can_edit=True)).buttons)
        self.assertNotIn("LOGISTICA", Sidebar(FakeService(can_edit=False)).buttons)


class PageTests(QtCase):
    def test_lists_logs_with_badge_and_tab_counts(self):
        page = LogisticsPage(FakeService(FakeLogisticsApi([_log(), _log(id=2, code="LOG102", stage="aprovada", load_code="CE-01")])))
        page.refresh()
        self.assertEqual(page.logs_table.rowCount(), 2)
        self.assertEqual(page.logs_table.item(0, 0).text(), "LOG101")
        self.assertEqual(page.logs_table.item(0, 2).text(), "10/11/2026")
        self.assertEqual(page.logs_table.item(0, 5).text(), "Data reservada")
        self.assertEqual(page.logs_table.item(0, 6).text(), "4 dias (2 úteis)")
        self.assertEqual(page.logs_table.item(0, 8).text(), "—")
        self.assertEqual(page.logs_table.item(1, 8).text(), "CE-01")
        self.assertEqual(page.tabs._options[0], ("logs", "LOGs", 2))
        self.assertIs(page.stack.currentWidget(), page.logs_table)

    def test_loads_tab_filters_on_the_client(self):
        api = FakeLogisticsApi(loads=[_load(), _load(id=6, code="CE-02", log_codes=["LOG300"], states=["EQT-AL"], proposal_count=1)])
        page = LogisticsPage(FakeService(api))
        page.tabs.set_current_key("loads")
        self.assertEqual(page.loads_table.rowCount(), 2)
        self.assertEqual(page.loads_table.item(0, 0).text(), "CE-01")
        self.assertEqual(page.loads_table.item(0, 2).text(), "LOG101, LOG102")
        self.assertEqual(page.loads_table.item(0, 3).text(), "EQT-MA, EQT-PA")
        page.search.setText("log300")
        page._filters_changed()
        self.assertEqual(page.loads_table.rowCount(), 1)
        self.assertEqual(page.loads_table.item(0, 0).text(), "CE-02")
        self.assertEqual(sum(1 for c in api.calls if c[0] == "list_loads"), 1)

    def test_primary_button_follows_the_tab(self):
        page = LogisticsPage(FakeService())
        self.assertFalse(page.new_log_button.isHidden())
        self.assertTrue(page.new_load_button.isHidden())
        page.tabs.set_current_key("loads")
        self.assertTrue(page.new_log_button.isHidden())
        self.assertFalse(page.new_load_button.isHidden())

    def test_search_goes_to_the_api_and_error_state(self):
        api = FakeLogisticsApi()
        page = LogisticsPage(FakeService(api))
        page.search.setText("EQT-MA")
        page._filters_changed()
        self.assertEqual(api.calls[-1][1]["search"], "EQT-MA")
        api.error = AppError("servidor fora do ar")
        page.refresh()
        self.assertIs(page.stack.currentWidget(), page.error_state)

    def test_loads_list_shows_departure_and_delivered_count(self):
        self.assertEqual(page_module.load_progress_text({"logs_total": 3, "logs_delivered": 2, "departed_on": "2026-12-05"}), "saiu 05/12, 2 de 3 LOGs entregues")
        self.assertEqual(page_module.load_progress_text({"logs_total": 3, "logs_delivered": 0}), "0 de 3 LOGs entregues")
        api = FakeLogisticsApi(loads=[_load(departed_on="2026-12-05", logs_total=3, logs_delivered=2)])
        page = LogisticsPage(FakeService(api))
        page.tabs.set_current_key("loads")
        self.assertEqual(page.loads_table.item(0, 5).text(), "saiu 05/12, 2 de 3 LOGs entregues")

    def test_empty_loads_tab_message(self):
        page = LogisticsPage(FakeService(FakeLogisticsApi(loads=[])))
        page.tabs.set_current_key("loads")
        self.assertIs(page.stack.currentWidget(), page.empty_state)

    def test_stale_response_is_discarded(self):
        page = LogisticsPage(FakeService())
        page._generation = 5
        page._logs_loaded({"items": [_log()], "total": 1}, 4)
        self.assertEqual(page.logs_table.rowCount(), 0)

    def test_view_only_user_has_no_edit_actions(self):
        page = LogisticsPage(FakeService(can_edit=False))
        self.assertIsNone(page.new_log_button.parent())
        self.assertIsNone(page.new_load_button.parent())
        self.assertIsNotNone(page.details_button.parent())

    def test_double_click_opens_detail_and_reloads_when_changed(self):
        api = FakeLogisticsApi()
        page = LogisticsPage(FakeService(api))
        page.refresh()
        page.logs_table.selectRow(0)
        opened = []

        class FakeDialog:
            changed = True

            def __init__(self, service, log, parent, can_edit):
                opened.append((log["code"], can_edit))

            def exec(self):
                return 0

        with patch.object(page_module, "LogDetailDialog", FakeDialog):
            page.open_selected()
        self.assertEqual(opened, [("LOG101", True)])
        self.assertEqual(sum(1 for c in api.calls if c[0] == "list_logs"), 2)


class LogDetailDialogTests(QtCase):
    def _dialog(self, can_edit=True, **changes):
        api = FakeLogisticsApi()
        log = _log(**changes)
        api.result = log
        dialog = LogDetailDialog(FakeService(api, can_edit), log, can_edit=can_edit)
        api.calls.clear()
        return dialog, api

    def test_docs_need_all_three_links(self):
        dialog, api = self._dialog()
        dialog.action_buttons[0].click()
        self.assertEqual(dialog.error_label.text(), "Informe os links de NF, XML e BIM.")
        self.assertEqual(api.calls, [])
        api.result = _log(stage="docs", nf_link="a", xml_link="b", bim_link="c")
        for key, value in (("nf", "NF-1.pdf"), ("xml", "NF-1.xml"), ("bim", "PD.pdf")):
            dialog.doc_fields[key].setText(value)
        dialog.action_buttons[0].click()
        self.assertEqual(api.calls, [("send_docs", 1, "NF-1.pdf", "NF-1.xml", "PD.pdf")])
        self.assertEqual(dialog.stage_badge.text(), "Documentação enviada")
        self.assertTrue(dialog.changed)

    def test_approve_in_docs_stage(self):
        dialog, api = self._dialog(stage="docs", nf_link="a", xml_link="b", bim_link="c")
        self.assertEqual(dialog.doc_fields, {})
        api.result = _log(stage="aprovada")
        dialog.action_buttons[0].click()
        self.assertEqual(api.calls, [("approve_log", 1)])
        self.assertEqual(dialog.stage_badge.text(), "Aprovada para entrega")

    def test_view_only_has_no_actions(self):
        dialog, _api = self._dialog(can_edit=False)
        self.assertEqual(dialog.action_buttons, [])
        self.assertEqual(dialog.doc_fields, {})
        self.assertIsNone(dialog.checklist)

    def test_resolve_pending_item(self):
        dialog, api = self._dialog()
        self.assertFalse(dialog.approve_item_button.isEnabled())
        with self.assertRaises(ValueError):
            dialog._resolve("ok")
        dialog.items_table.selectRow(1)
        self.assertTrue(dialog.approve_item_button.isEnabled())
        dialog.reject_item_button.click()
        self.assertEqual(api.calls, [("resolve_item", 1, 11, "reprovada")])
        dialog.items_table.selectRow(0)
        self.assertFalse(dialog.approve_item_button.isEnabled())

    def test_remove_requires_reason_and_selection(self):
        dialog, api = self._dialog()
        self.assertFalse(dialog.remove_item_button.isEnabled())
        dialog.items_table.selectRow(0)
        dialog.remove_item_button.click()
        self.assertEqual(dialog.error_label.text(), "Informe o motivo da remoção.")
        self.assertEqual(api.calls, [])
        dialog.reason_field.setText("cliente cancelou")
        dialog.remove_item_button.click()
        self.assertEqual(api.calls[0], ("remove_item", 1, 10, "cliente cancelou"))
        self.assertTrue(dialog.changed)

    def test_removing_last_proposal_confirms_and_closes_when_log_is_deleted(self):
        one = _log()["items"][:1]
        dialog, api = self._dialog(items=one, proposal_count=1)
        api.remove_result = {"log_deleted": True, "log": None}
        dialog.items_table.selectRow(0)
        dialog.reason_field.setText("erro de cadastro")
        with patch.object(dialogs_module.QMessageBox, "question", return_value=QMessageBox.No) as question:
            dialog.remove_item_button.click()
        self.assertTrue(question.called)
        self.assertEqual(api.calls, [])
        with patch.object(dialogs_module.QMessageBox, "question", return_value=QMessageBox.Yes):
            dialog.remove_item_button.click()
        self.assertEqual(api.calls[0], ("remove_item", 1, 10, "erro de cadastro"))
        self.assertTrue(dialog.changed)
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_rejected_inclusion_leaves_the_log_on_screen(self):
        dialog, api = self._dialog()
        self.assertEqual(dialog.items_table.rowCount(), 2)
        rejected = _log()["items"][1]
        api.result = _log(items=_log()["items"][:1], removed_items=[{**rejected, "status": "reprovada", "removal_reason": "inclusão reprovada"}], proposal_count=1)
        dialog.items_table.selectRow(1)
        dialog.reject_item_button.click()
        self.assertEqual(api.calls, [("resolve_item", 1, 11, "reprovada")])
        self.assertEqual(dialog.items_table.rowCount(), 1)
        self.assertEqual(dialog.items_table.item(0, 0).text(), "10480/B")

    def test_including_in_a_log_that_is_in_a_load_shows_the_api_message(self):
        dialog, api = self._dialog()
        message = "O LOG101 esta na carga CE-01. Tire o LOG da carga para incluir propostas."
        api.error = AppError(message, error_code="LOGISTICS_LOG_IN_LOAD")
        dialog.checklist.boxes[0][0].setChecked(True)
        dialog.action_buttons[-1].click()
        self.assertEqual(dialog.error_label.text(), message)

    @staticmethod
    def _script(fill):
        """Troca o exec() da janela de datas por um script que preenche e envia."""
        def run(dialog):
            fill(dialog)
            return 1

        return patch.object(dialogs_module.DateEditDialog, "exec", run)

    def test_header_shows_business_days_and_delivery_data(self):
        dialog, _api = self._dialog(delivered_on="2026-11-11", delivery_proof_link="https://x.example/comprovante.pdf")
        self.assertEqual(dialog.days_label.text(), "4 dias nesta etapa (2 úteis)")
        texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("11/11/2026", texts)
        self.assertIn("https://x.example/comprovante.pdf", texts)

    def test_edit_dates_sends_only_changed_with_reason(self):
        dialog, api = self._dialog()
        seen = {}

        def fill(d):
            seen["initial"] = {k: f.text() for k, f in d.date_fields.items()}
            d.submit()
            seen["nothing"] = d.error_label.text()
            d.date_fields["delivery_date"].line.setText("12/11/2026")
            d.submit()
            seen["reason"] = d.error_label.text()
            d.reason_field.setText("cliente pediu")
            d.submit()

        with self._script(fill):
            dialog.edit_dates_button.click()
        self.assertEqual(seen["initial"]["reserved_date"], "10/11/2026")
        self.assertEqual(seen["nothing"], "Nada foi alterado.")
        self.assertEqual(seen["reason"], "Informe o motivo.")
        self.assertEqual(api.calls[-1], ("update_log_dates", 1, {"delivery_date": "2026-11-12"}, "cliente pediu"))
        self.assertTrue(dialog.changed)

    def test_edit_dates_warning_confirm_resends_with_confirm_dates(self):
        dialog, api = self._dialog()
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Domingo."}]})

        def confirm(*_):
            api.error = None
            return True

        def fill(d):
            d.date_fields["delivery_date"].line.setText("15/11/2026")
            d.reason_field.setText("cliente pediu")
            with patch("app.ui.date_warnings.ask_date_confirmation", side_effect=confirm):
                d.submit()

        with self._script(fill):
            dialog.edit_dates_button.click()
        self.assertEqual([c[-1] for c in api.calls if c[0] == "update_log_dates"], ["cliente pediu", True])

    def test_delivery_registers_date_and_proof_link_without_reason_the_first_time(self):
        dialog, api = self._dialog()
        api.result = _log(delivered_on="2026-11-11", delivery_proof_link="https://x.example/a.pdf")

        def fill(d):
            d.date_fields["delivered_on"].yesterday_button.click()
            d.link_field.setText("https://x.example/a.pdf")
            d.submit()

        with self._script(fill):
            dialog.delivery_button.click()
        name, log_id, delivered, link, reason = api.calls[-1]
        self.assertEqual((name, log_id, link, reason), ("log_delivery", 1, "https://x.example/a.pdf", None))
        self.assertEqual(delivered, (date.today() - timedelta(days=1)).isoformat())

    def test_delivery_changing_a_saved_date_needs_a_reason(self):
        dialog, api = self._dialog(delivered_on="2026-11-11")
        seen = {}

        def fill(d):
            d.date_fields["delivered_on"].line.setText("12/11/2026")
            d.submit()
            seen["error"] = d.error_label.text()
            d.reason_field.setText("data errada")
            d.submit()

        with self._script(fill):
            dialog.delivery_button.click()
        self.assertEqual(seen["error"], "Informe o motivo.")
        self.assertEqual(api.calls[-1], ("log_delivery", 1, "2026-11-12", None, "data errada"))

    def test_log_in_load_blocks_removal(self):
        dialog, _api = self._dialog(load_id=5, load_code="CE-01")
        self.assertIsNone(dialog.reason_field)

    def test_include_proposals_sends_checked_ids(self):
        dialog, api = self._dialog()
        # botao "Incluir no LOG" e o ultimo registrado
        dialog.action_buttons[-1].click()
        self.assertEqual(dialog.error_label.text(), "Escolha ao menos uma proposta.")
        dialog.checklist.boxes[0][0].setChecked(True)
        dialog.action_buttons[-1].click()
        self.assertIn(("add_proposals", 1, [7]), api.calls)

    def test_api_error_is_shown_and_invalid_stage_reloads(self):
        dialog, api = self._dialog(stage="docs")
        api.error = AppError("O LOG mudou de etapa.", error_code="LOGISTICS_INVALID_STAGE")
        dialog.action_buttons[0].click()
        self.assertEqual(api.calls[-1], ("get_log", 1))
        self.assertEqual(dialog.error_label.text(), "O LOG mudou de etapa.")
        self.assertTrue(all(b.isEnabled() for b in dialog.action_buttons))
        self.assertFalse(dialog.changed)

    def test_history_lists_events_with_reason(self):
        events = [{"id": 1, "text": "ABC removida.", "reason": "cliente cancelou", "actor_user_id": 3, "actor_name": "Ana", "created_at": "2026-10-18T12:00:00Z"}]
        dialog, _api = self._dialog(events=events)
        self.assertEqual(dialog.history_table.rowCount(), 1)
        self.assertEqual(dialog.history_table.item(0, 1).text(), "Ana")
        self.assertIn("Motivo: cliente cancelou", dialog.history_table.item(0, 2).text())


class NewLogDialogTests(QtCase):
    def _dialog(self):
        api = FakeLogisticsApi()
        api.result = _log()
        return NewLogDialog(FakeService(api)), api

    def _fill(self, dialog, **values):
        dialog.state_field.setText(values.get("state", "eqt-ma"))
        dialog.code_field.setText(values.get("code", "log103"))
        dialog.requested_field.setText("10/11/2026")
        dialog.loading_field.setText("09/11/2026")
        dialog.delivery_field.setText("10/11/2026")

    def test_validations_in_order(self):
        dialog, api = self._dialog()
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "O código deve ser LOG seguido de números, ex.: LOG103.")
        self._fill(dialog)
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Escolha ao menos uma proposta.")
        self._fill(dialog, state=" ")
        dialog.checklist.boxes[0][0].setChecked(True)
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Informe o estado da Equatorial.")
        self._fill(dialog)
        dialog.loading_field.setText("2026-11-09")
        dialog.submit()
        self.assertIn("DD/MM/AAAA", dialog.error_label.text())
        self.assertNotIn("create_log", [c[0] for c in api.calls])

    def test_payload_with_available_date(self):
        dialog, api = self._dialog()
        self._fill(dialog)
        dialog.checklist.boxes[0][0].setChecked(True)
        dialog.submit()
        self.assertEqual(
            api.calls[-1],
            ("create_log", {
                "code": "LOG103", "state": "EQT-MA", "requested_date": "2026-11-10", "loading_date": "2026-11-09",
                "delivery_date": "2026-11-10", "proposal_ids": [7],
            }),
        )
        self.assertIsNotNone(dialog.created)

    def test_payload_with_nearest_date_sends_reserved_date(self):
        dialog, api = self._dialog()
        self._fill(dialog)
        dialog.checklist.boxes[0][0].setChecked(True)
        dialog.available.setChecked(False)
        dialog.reserved_field.setText("13/11/2026")
        dialog.submit()
        self.assertEqual(api.calls[-1][1]["reserved_date"], "2026-11-13")

    def test_suggested_dates_are_coherent(self):
        dialog, _api = self._dialog()
        self.assertEqual(dialog.reserved_field.text(), dialog.delivery_field.text())
        dialog.delivery_field.textEdited.emit("12/12/2026")  # digitar na entrega leva a reservada junto
        dialog.delivery_field.setText("12/12/2026")
        self.assertEqual(dialog.reserved_field.text(), "12/12/2026")
        dialog.reserved_field.textEdited.emit("13/12/2026")
        dialog.reserved_field.setText("13/12/2026")
        dialog.delivery_field.textEdited.emit("14/12/2026")
        self.assertEqual(dialog.reserved_field.text(), "13/12/2026")

    def test_date_warning_confirm_resends_same_payload_with_confirm_dates(self):
        dialog, api = self._dialog()
        self._fill(dialog)
        dialog.checklist.boxes[0][0].setChecked(True)
        warning = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"code": "WEEKEND", "field": "delivery_date", "message": "Cai num domingo."}]})
        results = [warning]
        original = api.create_log

        def create_log(payload):
            if results:
                api.calls.append(("create_log", dict(payload)))
                raise results.pop()
            return original(payload)

        api.create_log = create_log
        with patch("app.ui.date_warnings.ask_date_confirmation", return_value=True) as ask:
            dialog.submit()
        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[1], ["Cai num domingo."])
        sent = [c for c in api.calls if c[0] == "create_log"]
        self.assertNotIn("confirm_dates", sent[0][1])
        self.assertTrue(sent[1][1]["confirm_dates"])
        self.assertEqual({k: v for k, v in sent[1][1].items() if k != "confirm_dates"}, sent[0][1])
        self.assertIsNotNone(dialog.created)

    def test_date_warning_declined_keeps_data_and_reenables(self):
        dialog, api = self._dialog()
        self._fill(dialog)
        dialog.checklist.boxes[0][0].setChecked(True)
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Domingo."}]})
        with patch("app.ui.date_warnings.ask_date_confirmation", return_value=False):
            dialog.submit()
        self.assertIsNone(dialog.created)
        self.assertEqual(len([c for c in api.calls if c[0] == "create_log"]), 1)
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertEqual(dialog.delivery_field.text(), "10/11/2026")

    def test_api_error_keeps_dialog_open(self):
        dialog, api = self._dialog()
        self._fill(dialog)
        dialog.checklist.boxes[0][0].setChecked(True)
        api.error = AppError("Esse código LOG já existe.", error_code="LOGISTICS_LOG_CODE_ALREADY_EXISTS")
        dialog.submit()
        self.assertIsNone(dialog.created)
        self.assertEqual(dialog.error_label.text(), "Esse código LOG já existe.")
        self.assertTrue(dialog.create_button.isEnabled())


class NewLogStateTests(QtCase):
    ELIGIBLE = [
        {"id": 1, "proposal_number": "CP 1", "customer_name": "EQUATORIAL PIAUI", "pd_code": "5400125858", "state": "EQT-PI"},
        {"id": 2, "proposal_number": "CP 2", "customer_name": "EQUATORIAL MARANHAO", "pd_code": "5400125859", "state": "EQT-MA"},
        {"id": 3, "proposal_number": "CP 3", "customer_name": "EQUATORIAL PIAUI", "pd_code": "5400125860", "state": "EQT-PI"},
        {"id": 4, "proposal_number": "CP 4", "customer_name": "Outro", "pd_code": None, "state": None},
    ]

    def _dialog(self):
        api = FakeLogisticsApi(eligible=[dict(p) for p in self.ELIGIBLE])
        api.result = _log()
        return NewLogDialog(FakeService(api)), api

    def _hidden(self, dialog):
        return [i for box, i in dialog.checklist.boxes if box.isHidden()]

    def test_state_is_automatic_and_filters_list(self):
        dialog, api = self._dialog()
        self.assertTrue(dialog.state_field.isReadOnly())
        self.assertEqual(dialog.state_field.placeholderText(), "Definido pela proposta escolhida")
        self.assertIn("EQT-PI", dialog.checklist.boxes[0][0].text())
        dialog.checklist.boxes[0][0].setChecked(True)
        self.assertEqual(dialog.state_field.text(), "EQT-PI")
        self.assertTrue(dialog.state_field.isReadOnly())
        self.assertEqual(self._hidden(dialog), [2, 4])
        dialog.checklist.boxes[0][0].setChecked(False)
        self.assertEqual(dialog.state_field.text(), "")
        self.assertEqual(self._hidden(dialog), [])

    def test_unknown_state_makes_field_editable_and_hides_stateful(self):
        dialog, api = self._dialog()
        dialog.checklist.boxes[3][0].setChecked(True)
        self.assertFalse(dialog.state_field.isReadOnly())
        self.assertEqual(self._hidden(dialog), [1, 2, 3])
        dialog.state_field.setText("eqt-ap")
        dialog.code_field.setText("log9")
        for field, text in ((dialog.requested_field, "10/11/2026"), (dialog.loading_field, "09/11/2026"), (dialog.delivery_field, "10/11/2026")):
            field.setText(text)
        dialog.submit()
        self.assertEqual(api.calls[-1][1]["state"], "EQT-AP")
        self.assertEqual(api.calls[-1][1]["proposal_ids"], [4])

    def test_detail_include_list_matches_log_state(self):
        api = FakeLogisticsApi(eligible=[dict(p) for p in self.ELIGIBLE])
        log = _log(stage="reservada")
        log["state"] = "EQT-PI"
        api.result = log
        dialog = LogDetailDialog(FakeService(api), log, can_edit=True)
        self.assertEqual([i for _, i in dialog.checklist.boxes], [1, 3, 4])


class LoadDialogTests(QtCase):
    def test_new_load_lists_free_approved_logs_only(self):
        api = FakeLogisticsApi(logs=[_log(stage="aprovada")])
        dialog = NewLoadDialog(FakeService(api))
        self.assertEqual(api.calls[0], ("list_logs", {"stage": "aprovada", "in_load": False, "limit": 200}))
        self.assertEqual(len(dialog.checklist.boxes), 1)
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Escolha ao menos um LOG.")
        dialog.checklist.boxes[0][0].setChecked(True)
        dialog.date_field.setText("31/02/2026")
        dialog.submit()
        self.assertIn("DD/MM/AAAA", dialog.error_label.text())
        dialog.date_field.setText("08/11/2026")
        dialog.submit()
        self.assertEqual(api.calls[-1], ("create_load", "2026-11-08", [1]))
        self.assertIsNotNone(dialog.created)

    def test_new_load_departure_follows_loading_date_of_checked_logs(self):
        api = FakeLogisticsApi(logs=[_log(stage="aprovada", loading_date="2026-12-03"), _log(id=2, code="LOG102", stage="aprovada", loading_date="2026-12-05")])
        dialog = NewLoadDialog(FakeService(api))
        dialog.checklist.boxes[0][0].setChecked(True)
        self.assertEqual(dialog.date_field.text(), "03/12/2026")
        dialog.checklist.boxes[1][0].setChecked(True)
        self.assertEqual(dialog.date_field.text(), "05/12/2026")
        dialog.date_field.textEdited.emit("01/12/2026")
        dialog.date_field.setText("01/12/2026")
        dialog.checklist.boxes[0][0].setChecked(False)
        self.assertEqual(dialog.date_field.text(), "01/12/2026")

    def test_new_load_date_warning_confirm_resends_with_confirm_dates(self):
        api = FakeLogisticsApi(logs=[_log(stage="aprovada")])
        dialog = NewLoadDialog(FakeService(api))
        dialog.checklist.boxes[0][0].setChecked(True)
        dialog.date_field.setText("08/11/2026")
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Domingo."}]})

        def clear_error(*_):
            api.error = None
            return True

        with patch("app.ui.date_warnings.ask_date_confirmation", side_effect=clear_error):
            dialog.submit()
        self.assertEqual(api.calls[-2:], [("create_load", "2026-11-08", [1]), ("create_load", "2026-11-08", [1], True)])
        self.assertIsNotNone(dialog.created)

    def test_new_load_without_free_logs_shows_hint(self):
        dialog = NewLoadDialog(FakeService(FakeLogisticsApi(logs=[])))
        self.assertEqual(dialog.checklist.boxes, [])

    def _detail(self, can_edit=True, **changes):
        api = FakeLogisticsApi()
        load = _load(**changes)
        api.result = None
        dialog = LoadDetailDialog(FakeService(api, can_edit), load, can_edit=can_edit)
        api.calls.clear()
        return dialog, api

    def test_save_date_validates_and_calls_api(self):
        dialog, api = self._detail()
        dialog.date_field.setText("data")
        dialog.action_buttons[2].click()
        self.assertEqual(dialog.error_label.text(), "Data de saída inválida. Use DD/MM/AAAA.")
        dialog.date_field.setText("09/11/2026")
        dialog.action_buttons[2].click()
        self.assertEqual(dialog.error_label.text(), "Informe o motivo da mudança da saída.")
        dialog.reason_field.setText("chuva")
        dialog.action_buttons[2].click()
        self.assertEqual(api.calls[-1], ("update_load", 5, "2026-11-09", "chuva"))

    def test_save_date_warning_confirm_resends(self):
        dialog, api = self._detail()
        dialog.date_field.setText("09/11/2026")
        dialog.reason_field.setText("chuva")
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Feriado."}]})

        def clear_error(*_):
            api.error = None
            return True

        with patch("app.ui.date_warnings.ask_date_confirmation", side_effect=clear_error):
            dialog.action_buttons[2].click()
        self.assertEqual(api.calls[-2:], [("update_load", 5, "2026-11-09", "chuva"), ("update_load", 5, "2026-11-09", "chuva", True)])
        self.assertTrue(dialog.changed)

    def test_undo_load_confirms_then_deletes(self):
        dialog, api = self._detail()
        with patch.object(dialogs_module.QMessageBox, "question", return_value=QMessageBox.No):
            dialog.action_buttons[0].click()
        self.assertEqual(api.calls, [])
        with patch.object(dialogs_module.QMessageBox, "question", return_value=QMessageBox.Yes):
            dialog.action_buttons[0].click()
        self.assertEqual(api.calls, [("delete_load", 5)])
        self.assertTrue(dialog.deleted)

    def test_retire_log_and_last_log_rule(self):
        dialog, api = self._detail()
        dialog.retire_buttons[0].click()
        self.assertEqual(api.calls[-1], ("remove_log_from_load", 5, 1))
        single, api = self._detail(logs=[_log(stage="aprovada")])
        api.result = _load(logs=[_log(stage="aprovada")])
        single._reload()
        api.calls.clear()
        single.retire_buttons[0].click()
        self.assertIn("Desfazer carga", single.error_label.text())
        self.assertEqual(api.calls, [])

    def test_departed_registers_real_departure_and_shows_counts(self):
        dialog, api = self._detail()
        api.result = _load(departed_on=None, logs_total=3, logs_delivered=2)
        dialog._reload()
        texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("2 de 3", texts)

        def fill(d):
            d.date_fields["departed_on"].line.setText("05/12/2026")
            d.submit()

        with patch.object(dialogs_module.DateEditDialog, "exec", lambda d: (fill(d), 1)[1]):
            dialog.departed_button.click()
        self.assertEqual(api.calls[-1], ("load_departed", 5, "2026-12-05", None))
        self.assertTrue(dialog.changed)

    def test_departed_change_needs_reason_and_header_shows_actual_date(self):
        dialog, api = self._detail()
        api.result = _load(departed_on="2026-12-05")
        dialog._reload()
        self.assertIn("saiu em 05/12/2026", dialog.findChild(QLabel, "FilterSubtitle").text())
        seen = {}

        def fill(d):
            d.date_fields["departed_on"].line.setText("06/12/2026")
            d.submit()
            seen["error"] = d.error_label.text()
            d.reason_field.setText("atrasou")
            d.submit()

        with patch.object(dialogs_module.DateEditDialog, "exec", lambda d: (fill(d), 1)[1]):
            dialog.departed_button.click()
        self.assertEqual(seen["error"], "Informe o motivo.")
        self.assertEqual(api.calls[-1], ("load_departed", 5, "2026-12-06", "atrasou"))

    def test_view_only_has_no_actions(self):
        dialog, _api = self._detail(can_edit=False)
        self.assertEqual(dialog.action_buttons, [])
        self.assertIsNone(dialog.date_field)


if __name__ == "__main__":
    unittest.main()
