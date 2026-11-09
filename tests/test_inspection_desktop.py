from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLabel

from app.integrations.api.exceptions import ApiBusinessError
from app.integrations.api.inspections_client import InspectionsApiClient
from app.services.api_proposal_storage import api_permission_level, legacy_permissions_to_api_codes
from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES, AppError
from app.services.inspection_service import InspectionService
from app.ui import date_edit_dialog as date_edit_module
from app.ui.components import date_quick_field as date_quick_field_module
from app.ui import inspection_dialogs as dialogs_module
from app.ui import inspection_page as page_module
from app.ui import inspection_progress as progress_module
from app.ui.inspection_dialogs import (
    InspectionDetailDialog,
    NewInspectionDialog,
    check_link,
    days_text,
    history_registro,
    format_date,
    parse_visit_date,
)
from app.ui.inspection_page import InspectionPage
from app.ui.sidebar import NAV_LABELS, Sidebar


FIXED_TODAY = date(2026, 11, 10)


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
        "rejection_reason": None, "stage_since": "2026-10-15T10:00:00Z", "stage_since_date": "2026-10-15", "days_in_stage": 5,
        "business_days_in_stage": 3, "finished": False,
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
        self.lookup_result: dict = {"proposal_id": 7, "proposal_number": "CP 05610", "customer_name": "Cliente", "is_cancelled": False}

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

    def proposal_lookup(self, number):
        self.calls.append(("proposal_lookup", number))
        if self.error is not None:
            raise self.error
        return self.lookup_result

    def transition(self, inspection_id, action, payload=None):
        return self._respond("transition", inspection_id, action, dict(payload or {}))

    def catch_up(self, inspection_id, steps, confirm_dates=False):
        return self._respond("catch_up", inspection_id, [dict(step) for step in steps], confirm_dates)

    def reschedule_visit(self, inspection_id, visit_date, reason, confirm_dates=False):
        return self._respond("reschedule_visit", inspection_id, visit_date, reason, confirm_dates)

    def correct_occurred_on(self, inspection_id, event_id, occurred_on, reason):
        return self._respond("correct_occurred_on", inspection_id, event_id, occurred_on, reason)


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
            patch.object(progress_module, "start_worker", _sync_worker),
            patch.object(date_edit_module, "start_worker", _sync_worker),
            patch.object(progress_module, "local_today", lambda: FIXED_TODAY),
            patch.object(date_quick_field_module, "local_today", lambda: FIXED_TODAY),
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

    def test_client_and_service_proposal_lookup(self):
        http = FakeHttp()
        InspectionsApiClient(http).proposal_lookup("t", "cp 05610")
        self.assertEqual(http.calls[0], ("GET", "/api/v1/inspections/proposal-lookup?number=cp+05610", None))

        class Client:
            def close(self):
                pass

        class Api:
            def proposal_lookup(self, token, number):
                raise AppError("cru", error_code="INSPECTION_PROPOSAL_NOT_FOUND")

        class Storage:
            def inspections_api(self):
                return Client(), Api(), "t"

        with self.assertRaises(AppError) as ctx:
            InspectionService(Storage(), lambda exc: exc).proposal_lookup("CP 99999")
        self.assertIn("Confira o número (ex.: CP 05610)", str(ctx.exception))

    def test_client_and_service_new_endpoints(self):
        http = FakeHttp()
        client = InspectionsApiClient(http)
        client.catch_up("t", 7, {"steps": [{"action": "approve"}]})
        client.reschedule_visit("t", 7, {"visit_date": "2026-12-01", "reason": "chuva"})
        client.correct_occurred_on("t", 7, 3, {"occurred_on": "2026-11-01", "reason": "erro"})
        self.assertEqual(http.calls[0], ("POST", "/api/v1/inspections/7/catch-up", {"steps": [{"action": "approve"}]}))
        self.assertEqual(http.calls[1], ("POST", "/api/v1/inspections/7/reschedule-visit", {"visit_date": "2026-12-01", "reason": "chuva"}))
        self.assertEqual(http.calls[2], ("POST", "/api/v1/inspections/7/events/3/occurred-on", {"occurred_on": "2026-11-01", "reason": "erro"}))

        sent = []

        class Api:
            def catch_up(self, token, inspection_id, payload):
                sent.append(("catch_up", payload))

            def reschedule_visit(self, token, inspection_id, payload):
                sent.append(("reschedule", payload))

            def action(self, token, inspection_id, action, payload):
                sent.append((action, payload))

        class Client:
            def close(self):
                pass

        class Storage:
            def inspections_api(self):
                return Client(), Api(), "tok"

        service = InspectionService(Storage(), lambda exc: exc)
        service.catch_up(1, [{"action": "approve"}])
        service.catch_up(1, [{"action": "approve"}], confirm_dates=True)
        service.reschedule_visit(1, "2026-12-01", "chuva", True)
        service.transition(1, "nqt", {"nqt_code": "N"})
        self.assertEqual(sent[0], ("catch_up", {"steps": [{"action": "approve"}]}))
        self.assertEqual(sent[1], ("catch_up", {"steps": [{"action": "approve"}], "confirm_dates": True}))
        self.assertEqual(sent[2], ("reschedule", {"visit_date": "2026-12-01", "reason": "chuva", "confirm_dates": True}))
        self.assertEqual(sent[3], ("nqt", {"nqt_code": "N"}))

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
        self.assertEqual(days_text(6, business=4), "6 dias (4 úteis)")
        self.assertEqual(days_text(1, business=1), "1 dia (1 útil)")
        self.assertEqual(days_text(6, long=True, business=4), "6 dias nesta etapa (4 úteis)")


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
        self.assertEqual(page.table.item(0, 5).text(), "—")
        self.assertEqual(page.table.item(0, 6).text(), "5 dias (3 úteis)")
        self.assertEqual(page.table.item(1, 2).text(), "NQT-0412")
        self.assertIs(page.stack.currentWidget(), page.table)
        self.assertEqual(page.segments._options, [("all", "Todas", 2), ("open", "Em andamento", 1), ("fim", "Finalizadas", 1)])

    def test_visit_date_is_listed(self):
        api = FakeInspectionApi([_item(stage="inloco", decision_type="inloco", visit_date="2026-11-20")])
        page = InspectionPage(FakeService(api))
        page.refresh()
        self.assertEqual(page.table.horizontalHeaderItem(5).text(), "Visita")
        self.assertEqual(page.table.item(0, 5).text(), "20/11/2026")

    def test_register_button_opens_the_progress_window_and_reloads(self):
        api = FakeInspectionApi()
        page = InspectionPage(FakeService(api))
        page.refresh()
        page.table.selectRow(0)
        opened = []

        class FakeDialog:
            result_data = {"id": 1}

            def __init__(self, service, inspection, parent):
                opened.append(inspection["pd_code"])

            def exec(self):
                return 1

        with patch.object(page_module, "RecordProgressDialog", FakeDialog):
            page.register_button.click()
        self.assertEqual(opened, ["PD-1201"])
        self.assertEqual(sum(1 for call in api.calls if call[0] == "list"), 2)

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

    def test_shows_situation_with_business_days_and_visit(self):
        dialog, _api = self._dialog("inloco", decision_type="inloco", visit_date="2026-11-20")
        self.assertEqual(dialog.days_label.text(), "5 dias nesta etapa (3 úteis)")
        self.assertEqual(dialog.stage_badge.text(), "Inspeção in loco")
        self.assertTrue(dialog.record_button.text().startswith("Registrar andamento"))
        self.assertEqual([b.text() for b in dialog.action_buttons], ["Registrar andamento", "Atualizar atrasado", "Remarcar visita", "Corrigir data do andamento"])
        self.assertIn("Visita in loco", " ".join(label.text() for label in dialog.findChildren(QLabel)))

    def test_pending_stage_and_finished_stage(self):
        dialog, _api = self._dialog("pendente")
        self.assertEqual(dialog.stage_badge.text(), "Solicitação pendente")
        self.assertEqual(dialog.trail.steps()[0]["name"], "Solicitação pendente")
        dialog, _api = self._dialog("fim", doc_link="\\\\servidor\\bim\\PD.pdf", finished=True)
        self.assertNotIn("Registrar andamento", [b.text() for b in dialog.action_buttons])
        self.assertIn("liberado para a Logística", dialog.step_label.text())

    def test_view_only_has_no_actions(self):
        dialog, _api = self._dialog("solicitada", can_edit=False)
        self.assertEqual(dialog.action_buttons, [])

    def test_record_button_opens_window_and_redraws_with_result(self):
        dialog, api = self._dialog("solicitada")

        class FakeRecord:
            result_data = _item(stage="nqt", nqt_code="NQT-1", events=[])

            def __init__(self, service, data, parent):
                pass

            def exec(self):
                return 1

        with patch.object(dialogs_module, "RecordProgressDialog", FakeRecord):
            dialog.record_button.click()
        self.assertEqual(dialog.stage_badge.text(), "NQT gerado")
        self.assertTrue(dialog.changed)

    def test_stale_record_window_reloads_the_detail(self):
        dialog, api = self._dialog("solicitada")

        class StaleRecord:
            result_data = None
            stale = True

            def __init__(self, service, data, parent):
                pass

            def exec(self):
                return 0

        with patch.object(dialogs_module, "RecordProgressDialog", StaleRecord):
            dialog.record_button.click()
        self.assertEqual(api.calls, [("get", 1)])
        self.assertFalse(dialog.changed)
        self.assertEqual(dialog.error_label.text(), "A inspeção mudou de etapa; os dados foram atualizados.")
        self.assertFalse(dialog.error_label.isHidden())

    def test_catch_up_button_opens_catch_up_window(self):
        dialog, _api = self._dialog("solicitada")
        opened = []

        class FakeCatchUp:
            result_data = _item(stage="doc", events=[])

            def __init__(self, service, data, parent):
                opened.append(data["stage"])

            def exec(self):
                return 1

        with patch.object(dialogs_module, "CatchUpDialog", FakeCatchUp):
            dialog.catch_up_button.click()
        self.assertEqual(opened, ["solicitada"])
        self.assertEqual(dialog.stage_badge.text(), "Aguardando DOC BIM")

    def test_reschedule_visit_requires_new_date_and_reason(self):
        dialog, api = self._dialog("inloco", decision_type="inloco", visit_date="2026-11-20")
        api.result = _item(stage="inloco", visit_date="2026-11-27", events=[])
        captured = {}
        real = dialogs_module.DateEditDialog

        def run(self_dialog):
            captured["field"] = self_dialog.date_fields["visit_date"].text()
            self_dialog.submit()
            captured["error"] = self_dialog.error_label.text()
            self_dialog.date_fields["visit_date"].line.setText("27/11/2026")
            self_dialog.submit()
            captured["error2"] = self_dialog.error_label.text()
            self_dialog.reason_field.setText("chuva forte")
            self_dialog.submit()
            return 1

        with patch.object(real, "exec", run):
            dialog.reschedule_button.click()
        self.assertEqual(captured["field"], "20/11/2026")
        self.assertEqual(captured["error"], "Nada foi alterado.")
        self.assertEqual(captured["error2"], "Informe o motivo.")
        self.assertEqual(api.calls[-1], ("reschedule_visit", 1, "2026-11-27", "chuva forte", False))
        self.assertTrue(dialog.changed)

    def test_reschedule_date_warning_confirm_resends_with_confirm_dates(self):
        dialog, api = self._dialog("inloco", decision_type="inloco", visit_date="2026-11-20")
        warning = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Domingo."}]})
        api.error = warning

        def confirm(_parent, _messages):
            api.error = None
            return True

        def run(self_dialog):
            self_dialog.date_fields["visit_date"].line.setText("22/11/2026")
            self_dialog.reason_field.setText("cliente pediu")
            with patch("app.ui.date_warnings.ask_date_confirmation", side_effect=confirm):
                self_dialog.submit()
            return 1

        with patch.object(dialogs_module.DateEditDialog, "exec", run):
            dialog.reschedule_button.click()
        self.assertEqual([c[:5] for c in api.calls if c[0] == "reschedule_visit"], [
            ("reschedule_visit", 1, "2026-11-22", "cliente pediu", False),
            ("reschedule_visit", 1, "2026-11-22", "cliente pediu", True),
        ])

    def test_history_shows_both_dates_from_to_and_note(self):
        events = [
            {"id": 1, "kind": "transition", "stage": "pendente", "attempt": 1, "text": "Solicitacao pendente", "occurred_on": "2026-10-01",
             "actor_name": "Ana", "created_at": "2026-10-01T12:00:00Z"},
            {"id": 2, "kind": "transition", "stage": "solicitada", "attempt": 1, "text": "Inspecao solicitada no portal", "occurred_on": "2026-10-03",
             "note": "falei com o portal", "actor_name": "Ana", "created_at": "2026-10-10T12:00:00Z"},
            {"id": 3, "kind": "visit_rescheduled", "stage": "solicitada", "attempt": 1, "text": "Visita remarcada", "reason": "chuva",
             "occurred_on": "2026-10-11", "created_at": "2026-10-11T12:00:00Z"},
        ]
        dialog, _api = self._dialog("solicitada", events=events)
        table = dialog.history_table
        self.assertEqual(table.horizontalHeaderItem(0).text(), "Aconteceu em")
        self.assertEqual(table.horizontalHeaderItem(1).text(), "Registrado em")
        self.assertEqual(table.item(1, 0).text(), "03/10/2026")
        self.assertIn("10/10/2026", table.item(1, 1).text())
        text = table.item(1, 5).text()
        self.assertIn("De Solicitação pendente para Inspeção solicitada", text)
        self.assertIn("Observação: falei com o portal", text)
        self.assertNotIn("De ", table.item(2, 5).text())
        self.assertIn("Motivo: chuva", table.item(2, 5).text())
        self.assertEqual(history_registro(events[0], None), "Solicitacao pendente")

    def test_correct_event_date_only_for_transitions_with_reason(self):
        events = [
            {"id": 5, "kind": "transition", "stage": "solicitada", "attempt": 1, "text": "Inspecao solicitada", "occurred_on": "2026-10-03",
             "created_at": "2026-10-10T12:00:00Z"},
            {"id": 6, "kind": "note", "stage": "solicitada", "attempt": 1, "text": "Nota", "occurred_on": "2026-10-04", "created_at": "2026-10-11T12:00:00Z"},
        ]
        dialog, api = self._dialog("solicitada", events=events)
        dialog.correct_button.click()
        self.assertIn("Selecione", dialog.error_label.text())
        dialog.history_table.selectRow(1)
        dialog.correct_button.click()
        self.assertEqual(api.calls, [])
        dialog.history_table.selectRow(0)
        api.result = _item(stage="solicitada", events=events)

        def run(self_dialog):
            self_dialog.date_fields["occurred_on"].line.setText("01/10/2026")
            self_dialog.reason_field.setText("digitei errado")
            self_dialog.submit()
            return 1

        with patch.object(dialogs_module.DateEditDialog, "exec", run):
            dialog.correct_button.click()
        self.assertEqual(api.calls[0], ("correct_occurred_on", 1, 5, "2026-10-01", "digitei errado"))
        self.assertTrue(dialog.changed)


class RecordProgressTests(QtCase):
    def _dialog(self, stage, **changes):
        api = FakeInspectionApi()
        item = _item(stage=stage, events=[], **changes)
        api.result = item
        dialog = progress_module.RecordProgressDialog(FakeService(api), item)
        return dialog, api

    def _fields(self, dialog):
        return {name for name, widget in dialog.form.field_widgets.items() if not widget.isHidden()}

    def test_header_summary_and_defaults(self):
        dialog, _api = self._dialog("nqt", nqt_code="NQT-1")
        self.assertEqual(dialog.windowTitle(), "Registrar andamento")
        self.assertIn("PD-1201", dialog.findChild(QLabel, "FilterSubtitle").text())
        self.assertIn("NQT gerado", dialog.findChild(QLabel, "FilterSubtitle").text())
        self.assertEqual(sorted(dialog.form.radios), ["dispensed", "on_site"])
        self.assertEqual(dialog.summary.text(), "Vai acontecer: NQT gerado → Dispensada, falta o PIT")
        self.assertEqual(dialog.form.occurred.text(), FIXED_TODAY.strftime("%d/%m/%Y"))
        self.assertEqual(dialog.register_button.text(), "Registrar")

    def test_date_shortcuts_and_any_date_is_accepted(self):
        dialog, api = self._dialog("cadastro")
        dialog.form.occurred.yesterday_button.click()
        self.assertEqual(dialog.form.occurred.text(), (FIXED_TODAY - timedelta(days=1)).strftime("%d/%m/%Y"))
        dialog.form.occurred.today_button.click()
        dialog.form.occurred.line.setText("01/01/2031")  # futuro
        dialog.submit()
        self.assertEqual(api.calls[-1], ("transition", 1, "register-pd", {"occurred_on": "2031-01-01"}))
        dialog, api = self._dialog("cadastro")
        dialog.form.occurred.line.setText("31/02/2026")
        dialog.submit()
        self.assertIn("DD/MM/AAAA", dialog.error_label.text())
        self.assertEqual(api.calls, [])

    def test_nqt_field_validation_and_payload(self):
        dialog, api = self._dialog("solicitada")
        self.assertEqual(self._fields(dialog), {"nqt_code"})
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Informe o código NQT.")
        dialog.form.field_widgets["nqt_code"].setText("nqt-0431")
        dialog.form.note.setText("portal liberou")
        api.result = _item(stage="nqt", nqt_code="NQT-0431", events=[])
        dialog.submit()
        sent = api.calls[-1]
        self.assertEqual(sent[:3], ("transition", 1, "nqt"))
        self.assertEqual(sent[3]["nqt_code"], "NQT-0431")
        self.assertEqual(sent[3]["note"], "portal liberou")
        self.assertEqual(dialog.result_data["stage"], "nqt")

    def test_fields_follow_the_chosen_outcome(self):
        dialog, api = self._dialog("nqt", nqt_code="NQT-1")
        self.assertEqual(self._fields(dialog), set())
        dialog.submit()
        self.assertEqual(api.calls[-1][2:4], ("decision", {"decision": "dispensa", "occurred_on": FIXED_TODAY.isoformat()}))
        dialog, api = self._dialog("nqt", nqt_code="NQT-1")
        dialog.form.radios["on_site"].setChecked(True)
        self.assertEqual(self._fields(dialog), {"visit_date"})
        self.assertEqual(dialog.summary.text(), "Vai acontecer: NQT gerado → Inspeção in loco")
        dialog.submit()
        self.assertIn("data da visita", dialog.error_label.text())
        dialog.form.field_widgets["visit_date"].line.setText("20/11/2026")
        dialog.submit()
        self.assertEqual(api.calls[-1][3]["visit_date"], "2026-11-20")
        self.assertEqual(api.calls[-1][3]["decision"], "inloco")

    def test_reject_needs_reason_and_approve_does_not(self):
        dialog, api = self._dialog("inloco", decision_type="inloco", visit_date="2026-11-03")
        dialog.form.radios["rejected"].setChecked(True)
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Informe o motivo da reprovação.")
        dialog.form.field_widgets["reason"].setText("furo fora de medida")
        dialog.submit()
        self.assertEqual(api.calls[-1][2], "reject")
        self.assertEqual(api.calls[-1][3]["reason"], "furo fora de medida")
        dialog, api = self._dialog("inloco", decision_type="inloco", visit_date="2026-11-03")
        dialog.submit()
        self.assertEqual(api.calls[-1][2], "approve")

    def test_pit_and_doc_validate_links(self):
        for stage, action, field, fragment in (("dispensa", "pit", "pit_link", "PIT"), ("doc", "doc", "doc_link", "DOC BIM")):
            dialog, api = self._dialog(stage)
            self.assertEqual(self._fields(dialog), {field})
            dialog.submit()
            self.assertIn(fragment, dialog.error_label.text())
            dialog.form.field_widgets[field].line.setText("x" * 501)
            dialog.submit()
            self.assertIn("500", dialog.error_label.text())
            dialog.form.field_widgets[field].line.setText("\\\\servidor\\bim\\PD1201.pdf")
            dialog.submit()
            self.assertEqual(api.calls[-1][2], action)
            self.assertEqual(api.calls[-1][3][field], "\\\\servidor\\bim\\PD1201.pdf")

    def test_pending_stage_has_two_ways_to_request(self):
        dialog, api = self._dialog("pendente")
        self.assertEqual(sorted(dialog.form.radios), ["needs_pd", "requested"])
        dialog.form.radios["needs_pd"].setChecked(True)
        dialog.submit()
        self.assertEqual(api.calls[-1][2:4], ("request", {"pd_registered": False, "occurred_on": FIXED_TODAY.isoformat()}))

    def test_date_warning_confirm_resends_same_payload_with_confirm_dates(self):
        dialog, api = self._dialog("nqt", nqt_code="NQT-1")
        dialog.form.radios["on_site"].setChecked(True)
        dialog.form.field_widgets["visit_date"].line.setText("22/11/2026")
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Domingo."}]})

        with patch("app.ui.date_warnings.ask_date_confirmation", side_effect=AssertionError("sem QMessageBox")):
            dialog.submit()
            self.assertFalse(dialog.warning_panel.isHidden())
            self.assertEqual(dialog.warning_panel.label.text(), "Domingo.")
            self.assertIsNone(dialog.result_data)
            api.error = None
            dialog.warning_panel.confirm_button.click()
        first, second = [c for c in api.calls if c[0] == "transition"]
        self.assertNotIn("confirm_dates", first[3])
        self.assertTrue(second[3].pop("confirm_dates"))
        self.assertEqual(first[3], second[3])
        self.assertIsNotNone(dialog.result_data)

    def test_date_warning_declined_keeps_window_and_data(self):
        dialog, api = self._dialog("nqt", nqt_code="NQT-1")
        dialog.form.radios["on_site"].setChecked(True)
        dialog.form.field_widgets["visit_date"].line.setText("22/11/2026")
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Domingo."}]})
        with patch("app.ui.date_warnings.ask_date_confirmation", side_effect=AssertionError("sem QMessageBox")):
            dialog.submit()
            self.assertFalse(dialog.warning_panel.isHidden())
            with patch.object(dialog.form.field_widgets["visit_date"].line, "setFocus") as visit_focus, patch.object(
                dialog.form.occurred.line, "setFocus"
            ) as occurred_focus:
                dialog.warning_panel.choose_button.click()
            visit_focus.assert_called_once()
            occurred_focus.assert_not_called()
        self.assertTrue(dialog.warning_panel.isHidden())
        self.assertIsNone(dialog.result_data)
        self.assertTrue(dialog.register_button.isEnabled())
        self.assertEqual(dialog.form.field_widgets["visit_date"].text(), "22/11/2026")
        self.assertEqual(len([c for c in api.calls if c[0] == "transition"]), 1)

    def test_date_warning_panel_is_scrolled_into_view(self):
        dialog, _api = self._dialog("cadastro")
        with patch("app.ui.inspection_progress.QScrollArea.ensureWidgetVisible") as ensure:
            dialog.warning_panel.show_messages(["Domingo."])
            QApplication.processEvents()
        ensure.assert_called_once_with(dialog.warning_panel)

    def test_changing_any_field_hides_the_date_warning_panel(self):
        dialog, api = self._dialog("cadastro")
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Domingo."}]})
        dialog.submit()
        self.assertFalse(dialog.warning_panel.isHidden())
        dialog.form.occurred.line.setText("02/11/2026")
        self.assertTrue(dialog.warning_panel.isHidden())
        dialog.submit()
        self.assertFalse(dialog.warning_panel.isHidden())
        dialog.form.note.setText("x")
        self.assertTrue(dialog.warning_panel.isHidden())

    def test_invalid_stage_closes_the_window_and_flags_reload(self):
        dialog, api = self._dialog("cadastro")
        api.error = AppError("A inspeção mudou de etapa. Os dados foram atualizados.", error_code="INSPECTION_INVALID_STAGE")
        dialog.submit()
        self.assertTrue(dialog.stale)
        self.assertEqual(dialog.result(), 0)
        self.assertTrue(dialog.error_label.isHidden())

    def test_api_error_is_shown_in_the_window(self):
        dialog, api = self._dialog("solicitada")
        dialog.form.field_widgets["nqt_code"].setText("NQT-9")
        api.error = AppError("Esse NQT já está registrado em outro PD.", error_code="INSPECTION_NQT_ALREADY_EXISTS")
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Esse NQT já está registrado em outro PD.")
        self.assertTrue(dialog.register_button.isEnabled())

    def test_finished_inspection_has_nothing_to_register(self):
        dialog, _api = self._dialog("fim", finished=True)
        self.assertFalse(dialog.register_button.isEnabled())

    def test_catch_up_button_opens_catch_up_and_closes_with_result(self):
        dialog, _api = self._dialog("solicitada")

        class FakeCatchUp:
            result_data = {"id": 1, "stage": "doc"}

            def __init__(self, service, data, parent):
                pass

            def exec(self):
                return 1

        with patch.object(progress_module, "CatchUpDialog", FakeCatchUp):
            dialog.catch_up_button.click()
        self.assertEqual(dialog.result_data["stage"], "doc")
        self.assertEqual(dialog.result(), 1)


class CatchUpTests(QtCase):
    def _dialog(self, stage="solicitada"):
        api = FakeInspectionApi()
        item = _item(stage=stage, events=[])
        api.result = dict(item, stage="doc")
        return progress_module.CatchUpDialog(FakeService(api), item), api

    def test_chain_of_steps_is_sent_at_once_with_each_date(self):
        dialog, api = self._dialog("solicitada")
        self.assertEqual(len(dialog.rows), 1)
        dialog.rows[0].field_widgets["nqt_code"].setText("nqt-7")
        dialog.rows[0].occurred.line.setText("01/10/2026")
        dialog.add_row()
        self.assertEqual(dialog.rows[1].stage, "nqt")
        dialog.rows[1].radios["dispensed"].setChecked(True)
        dialog.rows[1].occurred.line.setText("05/10/2026")
        dialog.add_row()
        self.assertEqual(dialog.rows[2].stage, "dispensa")
        dialog.rows[2].field_widgets["pit_link"].line.setText("https://pit.example/1")
        dialog.rows[2].occurred.line.setText("09/10/2026")
        dialog.rows[2].note.setText("anexado")
        dialog.submit()
        self.assertEqual(len(api.calls), 1)
        name, inspection_id, steps, confirm = api.calls[0]
        self.assertEqual((name, inspection_id, confirm), ("catch_up", 1, False))
        self.assertEqual(steps, [
            {"action": "nqt", "nqt_code": "NQT-7", "occurred_on": "2026-10-01"},
            {"action": "decision", "decision": "dispensa", "occurred_on": "2026-10-05"},
            {"action": "pit", "pit_link": "https://pit.example/1", "occurred_on": "2026-10-09", "note": "anexado"},
        ])
        self.assertEqual(dialog.result_data["stage"], "doc")

    def test_changing_an_outcome_drops_the_following_steps(self):
        dialog, _api = self._dialog("nqt")
        dialog.rows[0].radios["on_site"].setChecked(True)
        dialog.add_row()
        self.assertEqual(dialog.rows[1].stage, "inloco")
        dialog.rows[0].radios["dispensed"].setChecked(True)
        self.assertEqual(len(dialog.rows), 1)
        dialog.add_row()
        self.assertEqual(dialog.rows[1].stage, "dispensa")

    def test_cannot_add_after_the_last_stage_and_can_remove(self):
        dialog, _api = self._dialog("doc")
        self.assertFalse(dialog.add_button.isEnabled())
        dialog.add_row()
        self.assertEqual(len(dialog.rows), 1)
        dialog, _api = self._dialog("solicitada")
        dialog.add_row()
        self.assertTrue(dialog.remove_button.isEnabled())
        dialog.remove_button.click()
        self.assertEqual(len(dialog.rows), 1)

    def test_invalid_step_names_the_step_and_sends_nothing(self):
        dialog, api = self._dialog("solicitada")
        dialog.rows[0].field_widgets["nqt_code"].setText("NQT-1")
        dialog.add_row()
        dialog.rows[1].radios["on_site"].setChecked(True)
        dialog.submit()
        self.assertTrue(dialog.error_label.text().startswith("Etapa 2:"))
        self.assertEqual(api.calls, [])

    def test_api_step_index_is_shown_and_warning_confirm_resends(self):
        dialog, api = self._dialog("solicitada")
        dialog.rows[0].field_widgets["nqt_code"].setText("NQT-1")
        api.error = AppError("Fora de ordem", error_code="OUTRO", details={"step_index": 0})
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Etapa 1: Fora de ordem")
        api.error = AppError("Passo 1: fora de ordem", error_code="OUTRO", details={"step_index": 0})
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Passo 1: fora de ordem")
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Feriado."}]})

        with patch("app.ui.date_warnings.ask_date_confirmation", side_effect=AssertionError("sem QMessageBox")):
            dialog.submit()
            self.assertFalse(dialog.warning_panel.isHidden())
            self.assertEqual(dialog.warning_panel.label.text(), "Feriado.")
            dialog.rows[0].note.setText("mudou")
            self.assertTrue(dialog.warning_panel.isHidden())
            dialog.submit()
            api.error = None
            dialog.warning_panel.confirm_button.click()
        calls = [c for c in api.calls if c[0] == "catch_up"]
        self.assertEqual([c[3] for c in calls], [False, False, False, False, True])
        self.assertIsNotNone(dialog.result_data)

    def test_catch_up_invalid_stage_after_first_step_keeps_window_with_error(self):
        dialog, api = self._dialog("solicitada")
        dialog.rows[0].field_widgets["nqt_code"].setText("NQT-1")
        api.error = AppError("Passo 2: mudou", error_code="INSPECTION_INVALID_STAGE", details={"step_index": 1})
        dialog.submit()
        self.assertFalse(dialog.stale)
        self.assertEqual(dialog.error_label.text(), "Passo 2: mudou")

    def test_catch_up_choose_another_date_focuses_the_row_with_visit_date(self):
        dialog, api = self._dialog("nqt")
        dialog.rows[0].radios["on_site"].setChecked(True)
        dialog.rows[0].field_widgets["visit_date"].line.setText("22/11/2026")
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Domingo."}]})
        dialog.submit()
        with patch.object(dialog.rows[0].field_widgets["visit_date"].line, "setFocus") as focus:
            dialog.warning_panel.choose_button.click()
        focus.assert_called_once()
        dialog.rows[0].radios["dispensed"].setChecked(True)
        self.assertIs(dialog.rows[0].focus_line(), dialog.rows[0].occurred.line)

    def test_invalid_stage_closes_catch_up_and_flags_reload(self):
        dialog, api = self._dialog("solicitada")
        dialog.rows[0].field_widgets["nqt_code"].setText("NQT-1")
        api.error = AppError("Passo 1: mudou", error_code="INSPECTION_INVALID_STAGE", details={"step_index": 0})
        dialog.submit()
        self.assertTrue(dialog.stale)
        self.assertEqual(dialog.result(), 0)


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

    def test_pd_number_still_creates_inspection(self):
        api = FakeInspectionApi()
        dialog = NewInspectionDialog(FakeService(api))
        dialog.pd_field.setText("PD-9")
        dialog.submit()
        self.assertEqual(api.calls, [("create", "PD-9")])
        self.assertIsNone(dialog.proposal_id)
        self.assertEqual(dialog.created["stage"], "solicitada")

    def test_cp_number_looks_up_proposal_without_creating_inspection(self):
        api = FakeInspectionApi()
        dialog = NewInspectionDialog(FakeService(api))
        dialog.pd_field.setText(" cp 05610 ")
        dialog.submit()
        self.assertEqual(api.calls, [("proposal_lookup", "cp 05610")])
        self.assertEqual(dialog.proposal_id, 7)
        self.assertEqual(dialog.proposal_label, "CP 05610")
        self.assertIsNone(dialog.created)
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_proposal_not_found_shows_error_in_field(self):
        api = FakeInspectionApi()
        api.error = AppError("Não achei proposta ativa com esse número.", error_code="INSPECTION_PROPOSAL_NOT_FOUND")
        dialog = NewInspectionDialog(FakeService(api))
        dialog.pd_field.setText("CP 99999")
        dialog.submit()
        self.assertIsNone(dialog.proposal_id)
        self.assertIn("Não achei proposta", dialog.error_label.text())
        self.assertTrue(dialog.create_button.isEnabled())


class NewInspectionPageFlowTests(QtCase):
    def _fake_dialog(self, *, accepted: bool, proposal_id=None):
        class FakeNew:
            def __init__(self, service, parent=None):
                self.proposal_id = proposal_id
                self.proposal_label = "CP 05610"
                self.created = None

            def exec(self):
                return 1 if accepted else 0

        return FakeNew

    def test_open_new_with_proposal_starts_inspection_flow(self):
        api = FakeInspectionApi()
        page = InspectionPage(FakeService(api))
        page.refresh()
        lists_before = sum(1 for call in api.calls if call[0] == "list")
        with patch.object(page_module, "NewInspectionDialog", self._fake_dialog(accepted=True, proposal_id=7)), patch.object(
            page_module, "start_inspection_for_proposal", return_value=True
        ) as start:
            page.open_new()
        start.assert_called_once()
        self.assertEqual(start.call_args.args[1], 7)
        self.assertEqual(start.call_args.kwargs["proposal_label"], "Proposta CP 05610")
        self.assertEqual(sum(1 for call in api.calls if call[0] == "list"), lists_before + 1)

    def test_open_new_with_cancelled_dialog_does_nothing(self):
        api = FakeInspectionApi()
        page = InspectionPage(FakeService(api))
        with patch.object(page_module, "NewInspectionDialog", self._fake_dialog(accepted=False)), patch.object(
            page_module, "start_inspection_for_proposal"
        ) as start:
            page.open_new()
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
