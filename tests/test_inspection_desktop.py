from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.integrations.api.exceptions import ApiBusinessError
from app.integrations.api.inspections_client import InspectionsApiClient
from app.services.api_proposal_storage import api_permission_level, legacy_permissions_to_api_codes
from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES, AppError
from app.services.inspection_service import InspectionService
from app.ui import inspection_dialogs as dialogs_module
from app.ui import inspection_page as page_module
from app.ui.inspection_dialogs import (
    InspectionDetailDialog,
    NewInspectionDialog,
    check_link,
    days_text,
    format_date,
    parse_visit_date,
)
from app.ui.inspection_page import InspectionPage
from app.ui.sidebar import NAV_LABELS, Sidebar


def _sync_worker(owner, operation, on_success, on_error, *, operation_name=None):
    try:
        result = operation()
    except Exception as exc:  # noqa: BLE001 - igual ao worker real
        on_error(exc)
    else:
        on_success(result)


def _item(**changes) -> dict:
    base = {
        "id": 1, "pd_code": "PD-1201", "proposal_numbers": ["CP 100", "CP 101"], "nqt_code": None, "stage": "solicitada",
        "attempt": 1, "decision_type": None, "visit_date": None, "pit_link": None, "doc_link": None,
        "rejection_reason": None, "stage_since": "2026-10-15T10:00:00Z", "days_in_stage": 5, "finished": False,
        "created_at": "2026-10-15T10:00:00Z", "updated_at": "2026-10-15T10:00:00Z",
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


class FakeInspectionApi:
    """Servico de inspecao falso: cada chamada fica em `calls`; `result` e o
    InspectionDetail devolvido (ou `error` e levantado)."""

    def __init__(self, items=None):
        self.items = items if items is not None else [_item()]
        self.calls: list[tuple] = []
        self.error: Exception | None = None
        self.result: dict | None = None

    def _respond(self, name, *args):
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error
        return self.result if self.result is not None else _item(events=[])

    def list_inspections(self, **kwargs):
        self.calls.append(("list", kwargs))
        if self.error is not None:
            raise self.error
        finished = sum(1 for item in self.items if item["stage"] == "fim")
        return {"items": self.items, "total": len(self.items), "counts": {"open": len(self.items) - finished, "finished": finished}}

    def get(self, inspection_id):
        return self._respond("get", inspection_id)

    def create(self, pd_code):
        return self._respond("create", pd_code)

    def request(self, inspection_id, pd_registered):
        return self._respond("request", inspection_id, pd_registered)

    def register_pd(self, inspection_id):
        return self._respond("register_pd", inspection_id)

    def register_nqt(self, inspection_id, code):
        return self._respond("register_nqt", inspection_id, code)

    def decide(self, inspection_id, decision, visit_date=None):
        return self._respond("decide", inspection_id, decision, visit_date)

    def register_pit(self, inspection_id, link):
        return self._respond("register_pit", inspection_id, link)

    def approve(self, inspection_id):
        return self._respond("approve", inspection_id)

    def reject(self, inspection_id, reason):
        return self._respond("reject", inspection_id, reason)

    def register_doc(self, inspection_id, link):
        return self._respond("register_doc", inspection_id, link)


class FakeService:
    def __init__(self, api=None, can_edit=True):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.company = "Industel"
        self.api = api or FakeInspectionApi()
        self.edit = can_edit

    def inspection_service(self):
        return self.api

    def can_edit(self, area):
        return area == "inspection" and self.edit

    def can_view_nav(self, key):
        return key != "INSPECAO" or self.edit


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patches = [
            patch.object(page_module, "start_worker", _sync_worker),
            patch.object(dialogs_module, "start_worker", _sync_worker),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)


class ClientAndServiceTests(unittest.TestCase):
    def test_client_builds_paths_and_payloads(self):
        http = FakeHttp()
        client = InspectionsApiClient(http)
        client.list("t", stage="open", search=" PD 1 ", limit=50, offset=100)
        client.finished("t", pd_code="PD-1")
        client.create("t", pd_code="PD-1")
        client.action("t", 7, "request", {"pd_registered": False})
        client.action("t", 7, "decision", {"decision": "inloco", "visit_date": "2026-11-03"})
        client.action("t", 7, "approve")
        self.assertEqual(http.calls[0], ("GET", "/api/v1/inspections?stage=open&search=PD+1&limit=50&offset=100", None))
        self.assertEqual(http.calls[1], ("GET", "/api/v1/inspections/finished?pd_code=PD-1", None))
        self.assertEqual(http.calls[2], ("POST", "/api/v1/inspections", {"pd_code": "PD-1"}))
        self.assertEqual(http.calls[3], ("POST", "/api/v1/inspections/7/request", {"pd_registered": False}))
        self.assertEqual(http.calls[4], ("POST", "/api/v1/inspections/7/decision", {"decision": "inloco", "visit_date": "2026-11-03"}))
        self.assertEqual(http.calls[5], ("POST", "/api/v1/inspections/7/approve", {}))

    def test_service_maps_api_error_codes_to_friendly_messages(self):
        class Api:
            def get(self, token, inspection_id):
                raise ApiBusinessError("INSPECTION_NQT_ALREADY_EXISTS", "duplicado", status_code=409)

        class Client:
            closed = False

            def close(self):
                self.closed = True

        client = Client()

        class Storage:
            def inspections_api(self):
                return client, Api(), "tok"

        def wrap(exc):
            return AppError(str(exc), error_code=getattr(exc, "error_code", None))

        service = InspectionService(Storage(), wrap)
        with self.assertRaises(AppError) as caught:
            service.get(3)
        self.assertEqual(str(caught.exception), "Esse NQT já está registrado em outro PD.")
        self.assertEqual(caught.exception.error_code, "INSPECTION_NQT_ALREADY_EXISTS")
        self.assertTrue(client.closed)

    def test_helpers(self):
        self.assertEqual(format_date("2026-11-03"), "03/11/2026")
        self.assertEqual(parse_visit_date("03/11/2026"), "2026-11-03")
        with self.assertRaises(ValueError):
            parse_visit_date("2026-11-03")
        with self.assertRaises(ValueError):
            check_link("  ", "PIT")
        with self.assertRaises(ValueError):
            check_link("x" * 501, "PIT")
        self.assertEqual(days_text(1, long=True), "1 dia nesta etapa")
        self.assertEqual(days_text(5), "5 d")


class PermissionTests(unittest.TestCase):
    def test_inspection_permissions_map_to_the_area(self):
        self.assertEqual(api_permission_level({"inspection.view"}, "inspection"), "VIEW")
        self.assertEqual(api_permission_level({"inspection.edit"}, "inspection"), "EDIT")
        self.assertEqual(api_permission_level({"proposals.view"}, "inspection"), "NONE")
        self.assertEqual(legacy_permissions_to_api_codes({"inspection": "EDIT"}), ["inspection.edit", "inspection.view"])

    def test_sidebar_hides_inspection_without_permission(self):
        self.assertEqual(NAV_LABELS["INSPECAO"], "Inspeção")
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        self.assertIn("INSPECAO", Sidebar(FakeService(can_edit=True)).buttons)
        self.assertNotIn("INSPECAO", Sidebar(FakeService(can_edit=False)).buttons)


class PageTests(QtCase):
    def test_lists_rows_counts_and_badge(self):
        api = FakeInspectionApi([_item(), _item(id=2, pd_code="PD-1180", stage="fim", nqt_code="NQT-0412", finished=True)])
        page = InspectionPage(FakeService(api))
        page.refresh()
        self.assertEqual(page.table.rowCount(), 2)
        self.assertEqual(page.table.item(0, 0).text(), "PD-1201")
        self.assertEqual(page.table.item(0, 1).text(), "CP 100, CP 101")
        self.assertEqual(page.table.item(0, 2).text(), "—")
        self.assertEqual(page.table.item(0, 3).text(), "Inspeção solicitada")
        self.assertEqual(page.table.item(0, 5).text(), "5 d")
        self.assertEqual(page.table.item(1, 2).text(), "NQT-0412")
        self.assertIs(page.stack.currentWidget(), page.table)
        self.assertEqual(page.segments._options, [("all", "Todas", 2), ("open", "Em andamento", 1), ("fim", "Finalizadas", 1)])

    def test_segment_and_search_are_sent_to_the_api(self):
        api = FakeInspectionApi()
        page = InspectionPage(FakeService(api))
        page.segments.set_current_key("open")
        self.assertEqual(api.calls[-1][1]["stage"], "open")
        page.search.setText("NQT-04")
        page._filters_changed()
        self.assertEqual(api.calls[-1][1]["search"], "NQT-04")
        page.clear_filters()
        self.assertIsNone(api.calls[-1][1]["stage"])
        self.assertEqual(api.calls[-1][1]["search"], "")

    def test_empty_and_error_states(self):
        api = FakeInspectionApi([])
        page = InspectionPage(FakeService(api))
        page.refresh()
        self.assertIs(page.stack.currentWidget(), page.empty_state)
        api.error = AppError("servidor fora do ar")
        page.refresh()
        self.assertIs(page.stack.currentWidget(), page.error_state)

    def test_stale_response_is_discarded(self):
        page = InspectionPage(FakeService())
        page._generation = 5
        page._loaded({"items": [_item()], "total": 1, "counts": {"open": 1, "finished": 0}}, 4)
        self.assertEqual(page.table.rowCount(), 0)

    def test_view_only_user_has_no_edit_actions(self):
        page = InspectionPage(FakeService(can_edit=False))
        self.assertIsNone(page.new_button.parent())
        self.assertIsNone(page.register_button.parent())
        self.assertIsNotNone(page.details_button.parent())

    def test_double_click_opens_detail_and_reloads_when_changed(self):
        api = FakeInspectionApi()
        page = InspectionPage(FakeService(api))
        page.refresh()
        page.table.selectRow(0)
        opened = []

        class FakeDialog:
            changed = True

            def __init__(self, service, inspection, parent, can_edit):
                opened.append((inspection["pd_code"], can_edit))

            def exec(self):
                return 0

        with patch.object(page_module, "InspectionDetailDialog", FakeDialog):
            page.open_selected()
        self.assertEqual(opened, [("PD-1201", True)])
        self.assertEqual(sum(1 for call in api.calls if call[0] == "list"), 2)


class DetailDialogTests(QtCase):
    def _dialog(self, stage="solicitada", can_edit=True, **changes):
        api = FakeInspectionApi()
        item = _item(stage=stage, **{"events": [], **changes})
        api.result = item
        dialog = InspectionDetailDialog(FakeService(api, can_edit), item, can_edit=can_edit)
        api.calls.clear()
        return dialog, api

    def test_nqt_requires_code_then_calls_api_and_redraws(self):
        dialog, api = self._dialog("solicitada")
        dialog.action_buttons[0].click()
        self.assertEqual(api.calls, [])
        self.assertEqual(dialog.error_label.text(), "Informe o código NQT.")
        api.result = _item(stage="nqt", nqt_code="NQT-0431", events=[])
        dialog.field.setText("nqt-0431")
        dialog.action_buttons[0].click()
        self.assertEqual(api.calls, [("register_nqt", 1, "NQT-0431")])
        self.assertEqual(dialog.stage_badge.text(), "NQT gerado")
        self.assertTrue(dialog.changed)

    def test_on_site_requires_valid_date(self):
        dialog, api = self._dialog("nqt", nqt_code="NQT-1")
        dispense, on_site = dialog.action_buttons
        on_site.click()
        self.assertEqual(dialog.error_label.text(), "Informe a data da visita.")
        dialog.field.setText("31/02/2026")
        on_site.click()
        self.assertEqual(dialog.error_label.text(), "Data da visita inválida. Use DD/MM/AAAA.")
        self.assertEqual(api.calls, [])
        dialog.field.setText("03/11/2026")
        on_site.click()
        self.assertEqual(api.calls, [("decide", 1, "inloco", "2026-11-03")])
        dialog, api = self._dialog("nqt", nqt_code="NQT-1")
        dialog.action_buttons[0].click()
        self.assertEqual(api.calls, [("decide", 1, "dispensa", None)])

    def test_reject_needs_reason_and_approve_does_not(self):
        dialog, api = self._dialog("inloco", decision_type="inloco", visit_date="2026-11-03")
        reject, approve = dialog.action_buttons
        reject.click()
        self.assertEqual(dialog.error_label.text(), "Informe o motivo da reprovação.")
        dialog.field.setText("furo fora de medida")
        reject.click()
        self.assertEqual(api.calls, [("reject", 1, "furo fora de medida")])
        dialog, api = self._dialog("inloco", decision_type="inloco", visit_date="2026-11-03")
        dialog.action_buttons[1].click()
        self.assertEqual(api.calls, [("approve", 1)])

    def test_pit_and_doc_validate_links(self):
        for stage, call, fragment in (("dispensa", "register_pit", "PIT"), ("doc", "register_doc", "DOC BIM")):
            dialog, api = self._dialog(stage)
            dialog.action_buttons[0].click()
            self.assertIn(fragment, dialog.error_label.text())
            dialog.field.setText("x" * 501)
            dialog.action_buttons[0].click()
            self.assertIn("500", dialog.error_label.text())
            dialog.field.setText("\\\\servidor\\bim\\PD1201.pdf")
            dialog.action_buttons[0].click()
            self.assertEqual(api.calls, [(call, 1, "\\\\servidor\\bim\\PD1201.pdf")])

    def test_pending_stage_shows_label_and_request_action(self):
        for registered in (True, False):
            dialog, api = self._dialog("pendente")
            self.assertEqual(dialog.stage_badge.text(), "Solicitação pendente")
            self.assertEqual([b.text() for b in dialog.action_buttons], ["Solicitar inspeção"])
            self.assertEqual(dialog.trail.steps()[0]["name"], "Solicitação pendente")
            dialog.registered_check.setChecked(registered)
            api.result = _item(stage="solicitada" if registered else "cadastro", events=[])
            dialog.action_buttons[0].click()
            self.assertEqual(api.calls, [("request", 1, registered)])

    def test_register_pd_and_finished_stage(self):
        dialog, api = self._dialog("cadastro")
        dialog.action_buttons[0].click()
        self.assertEqual(api.calls, [("register_pd", 1)])
        dialog, _api = self._dialog("fim", doc_link="\\\\servidor\\bim\\PD.pdf", finished=True)
        self.assertEqual(dialog.action_buttons, [])
        self.assertIsNone(dialog.field)
        self.assertIn("liberado para a Logística", dialog.step_label.text())

    def test_view_only_has_no_field_or_actions(self):
        dialog, _api = self._dialog("solicitada", can_edit=False)
        self.assertEqual(dialog.action_buttons, [])
        self.assertIsNone(dialog.field)

    def test_api_error_is_shown_and_invalid_stage_reloads(self):
        dialog, api = self._dialog("solicitada")
        api.error = AppError("Esse NQT já está registrado em outro PD.", error_code="INSPECTION_NQT_ALREADY_EXISTS")
        dialog.field.setText("NQT-9")
        dialog.action_buttons[0].click()
        self.assertEqual(dialog.error_label.text(), "Esse NQT já está registrado em outro PD.")
        self.assertTrue(all(button.isEnabled() for button in dialog.action_buttons))
        self.assertFalse(dialog.changed)
        api.error = AppError("mudou", error_code="INSPECTION_INVALID_STAGE")
        dialog.action_buttons[0].click()
        self.assertEqual(api.calls[-1], ("get", 1))

    def test_history_lists_events_with_reason(self):
        events = [{"id": 1, "stage": "solicitada", "attempt": 2, "text": "Reprovada no in loco.", "reason": "furo fora de medida",
                   "actor_user_id": 3, "actor_name": "Ana", "created_at": "2026-10-18T12:00:00Z"}]
        dialog, _api = self._dialog("solicitada", events=events)
        api = dialog.api
        api.result = _item(events=events)
        dialog._reload()
        self.assertEqual(dialog.history_table.rowCount(), 1)
        self.assertEqual(dialog.history_table.item(0, 1).text(), "Ana")
        self.assertIn("Motivo: furo fora de medida", dialog.history_table.item(0, 4).text())


class NewInspectionDialogTests(QtCase):
    def test_requires_pd_and_does_not_ask_registration(self):
        api = FakeInspectionApi()
        api.result = _item(stage="pendente")
        dialog = NewInspectionDialog(FakeService(api))
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Informe o PD principal.")
        dialog.pd_field.setText(" PD-9 ")
        self.assertFalse(hasattr(dialog, "registered"))
        dialog.submit()
        self.assertEqual(api.calls, [("create", "PD-9")])
        self.assertEqual(dialog.created["stage"], "pendente")

    def test_api_error_keeps_dialog_open(self):
        api = FakeInspectionApi()
        api.error = AppError("Esse PD não existe nas propostas ativas.", error_code="INSPECTION_PD_NOT_FOUND")
        dialog = NewInspectionDialog(FakeService(api))
        dialog.pd_field.setText("PD-0")
        dialog.submit()
        self.assertIsNone(dialog.created)
        self.assertIn("não existe", dialog.error_label.text())
        self.assertTrue(dialog.create_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
