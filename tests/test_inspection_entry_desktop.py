from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from app.integrations.api.exceptions import ApiBusinessError
from app.integrations.api.inspections_client import InspectionsApiClient
from app.services import api_proposal_storage as storage_module
from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES, AppError
from app.services.inspection_service import InspectionService
from app.ui import inspection_dialogs as dialogs_module
from app.ui import inspection_page as page_module
from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionCategory
from app.ui.action_center.handlers import inspection as handler_module
from app.ui.action_center.provider import BackendActionProvider
from app.ui.inspection_dialogs import InspectionStartDialog, start_inspection_for_proposal
from app.ui.inspection_page import InspectionPage
from app.ui.process_form_dialog import ProcessFormDialog
from app.ui.status_dialog import StatusDialog

Q_DIALOG = "app.ui.inspection_dialogs.QMessageBox"


def _sync_worker(owner, operation, on_success, on_error, *, operation_name=None):
    try:
        result = operation()
    except Exception as exc:  # noqa: BLE001 - igual ao worker real
        on_error(exc)
    else:
        on_success(result)


def _suggestion(**changes) -> dict:
    base = {
        "proposal_id": 7, "proposal_number": "CP 700", "customer_name": "Cliente A", "is_cancelled": False,
        "order_reference": None, "project_name": "PEDIDO COMPRA 5400120719", "pd_code": "5400120719",
        "pd_source": "project_name", "existing_inspection_id": None, "conflicting_proposals": [],
    }
    return {**base, **changes}


class FakeApi:
    def __init__(self):
        self.calls: list[tuple] = []
        self.suggestion = _suggestion()
        self.errors: list[Exception] = []
        self.result = {"id": 3, "pd_code": "5400120719", "stage": "pendente", "created": True, "events": []}
        self.items: list[dict] = []
        self.to_request: list[dict] = []

    def pd_suggestion(self, proposal_id):
        self.calls.append(("suggestion", proposal_id))
        return self.suggestion

    def start_from_proposal(self, proposal_id, pd_code, confirm_customer_conflict=False):
        self.calls.append(("start", proposal_id, pd_code, confirm_customer_conflict))
        if self.errors:
            raise self.errors.pop(0)
        return self.result

    def list_inspections(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "items": self.items, "total": len(self.items), "to_request": self.to_request,
            "counts": {"open": len(self.items), "finished": 0, "to_request": len(self.to_request)},
        }

    def get(self, inspection_id):
        return self.result


class FakeService:
    def __init__(self, api=None):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.api = api or FakeApi()

    def inspection_service(self):
        return self.api

    def can_edit(self, area):
        return True


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for module in (page_module, dialogs_module):
            item = patch.object(module, "start_worker", _sync_worker)
            item.start()
            self.addCleanup(item.stop)


class ClientAndServiceTests(unittest.TestCase):
    def test_client_paths_and_payload(self):
        calls = []

        class Http:
            def get(self, path, access_token=None):
                calls.append(("GET", path, None))
                return type("R", (), {"data": {}})()

            def post(self, path, json_payload=None, access_token=None):
                calls.append(("POST", path, json_payload))
                return type("R", (), {"data": {}})()

        client = InspectionsApiClient(Http())
        client.pd_suggestion("t", 7)
        client.from_proposal("t", proposal_id=7, pd_code="PD-1", confirm_customer_conflict=True)
        self.assertEqual(calls[0], ("GET", "/api/v1/inspections/proposals/7/pd-suggestion", None))
        self.assertEqual(
            calls[1],
            ("POST", "/api/v1/inspections/from-proposal",
             {"proposal_id": 7, "pd_code": "PD-1", "confirm_customer_conflict": True}),
        )

    def test_service_keeps_error_details_and_friendly_message(self):
        class Api:
            def from_proposal(self, token, **kwargs):
                raise ApiBusinessError(
                    "INSPECTION_PD_CUSTOMER_CONFLICT", "x", status_code=409, details={"proposals": [{"id": 1}]}
                )

        class Client:
            def close(self):
                pass

        class Storage:
            def inspections_api(self):
                return Client(), Api(), "tok"

        def wrap(exc):
            return AppError(str(exc), error_code=exc.error_code, details=exc.details)

        with self.assertRaises(AppError) as caught:
            InspectionService(Storage(), wrap).start_from_proposal(1, "PD")
        self.assertEqual(caught.exception.details, {"proposals": [{"id": 1}]})
        self.assertIn("outro cliente", str(caught.exception))


class ProposalFieldTests(unittest.TestCase):
    def test_payloads_and_reading_carry_requires_inspection(self):
        data = {"proposta": "CP1", "cliente": "C", "precisa_inspecao": True, "itens": []}
        self.assertTrue(storage_module._proposal_create_payload(data, None)["requires_inspection"])
        self.assertFalse(storage_module._proposal_create_payload({**data, "precisa_inspecao": False}, None)["requires_inspection"])
        self.assertTrue(storage_module._proposal_update_payload(data, {"version": 1})["requires_inspection"])
        self.assertTrue(storage_module._api_proposal_to_process({"requires_inspection": True})["precisa_inspecao"])
        self.assertFalse(storage_module._api_proposal_to_process({})["precisa_inspecao"])

    def test_unmark_blocked_message_is_clear(self):
        exc = ApiBusinessError("INSPECTION_UNMARK_BLOCKED", "x", status_code=409)
        self.assertIn("já existe inspeção", storage_module.user_message_for_api_error(exc))


class FormServiceSpy:
    def __init__(self, requires=False):
        self.requires = requires
        self.saved = []

    def official_proposals_enabled(self):
        return True

    def can_edit_process(self):
        return True

    def item_no_production_reasons(self):
        return []

    def save_process(self, data, process_id=None, import_metadata=None):
        self.saved.append(data)
        return 1

    def get_process_dict(self, _id):
        return {"id": 10, "proposta": "CP1", "cliente": "C", "precisa_inspecao": self.requires}

    def proposal_items(self, _id):
        return []


class FormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_checkbox_default_unchecked_and_saved(self):
        service = FormServiceSpy()
        form = ProcessFormDialog(service)
        self.assertFalse(form.requires_inspection.isChecked())
        form.fields["proposta"].setText("CP1")
        form.fields["cliente"].setText("C")
        form.requires_inspection.setChecked(True)
        form.save()
        self.assertTrue(service.saved[0]["precisa_inspecao"])
        form.close()

    def test_edit_loads_checkbox(self):
        form = ProcessFormDialog(FormServiceSpy(requires=True), process_id=10)
        self.assertTrue(form.requires_inspection.isChecked())
        form.close()


class StartDialogTests(QtCase):
    def _dialog(self, api=None, **suggestion):
        api = api or FakeApi()
        api.suggestion = _suggestion(**suggestion)
        return InspectionStartDialog(FakeService(api), 7), api

    def test_prefills_suggestion_and_starts(self):
        dialog, api = self._dialog()
        self.assertEqual(dialog.pd_field.text(), "5400120719")
        self.assertTrue(dialog.pd_field.isEnabled())
        self.assertFalse(hasattr(dialog, "registered"))
        dialog.submit()
        self.assertEqual(api.calls[-1], ("start", 7, "5400120719", False))
        self.assertTrue(dialog.created)
        self.assertEqual(dialog.result["id"], 3)

    def test_no_suggestion_requires_typing(self):
        dialog, api = self._dialog(pd_code=None, pd_source=None)
        self.assertEqual(dialog.pd_field.text(), "")
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Informe o PD principal.")
        self.assertFalse(any(call[0] == "start" for call in api.calls))

    def test_order_reference_locks_pd(self):
        dialog, _api = self._dialog(order_reference="PD-9", pd_code="PD-9", pd_source="order_reference")
        self.assertEqual(dialog.pd_field.text(), "PD-9")
        self.assertFalse(dialog.pd_field.isEnabled())

    def test_cancelled_proposal_blocks_start(self):
        dialog, api = self._dialog(is_cancelled=True)
        self.assertFalse(dialog.start_button.isEnabled())
        self.assertIn("cancelada", dialog.error_label.text())

    def test_customer_conflict_needs_explicit_confirmation(self):
        api = FakeApi()
        conflict = AppError("conflito", error_code="INSPECTION_PD_CUSTOMER_CONFLICT",
                            details={"proposals": [{"id": 2, "proposal_number": "CP 9", "customer_name": "Outro"}]})
        api.errors = [conflict]
        dialog, api = self._dialog(api)
        with patch(Q_DIALOG + ".question", return_value=QMessageBox.Yes) as question:
            dialog.submit()
        self.assertEqual(question.call_count, 1)
        starts = [call for call in api.calls if call[0] == "start"]
        self.assertEqual([call[3] for call in starts], [False, True])
        self.assertIsNotNone(dialog.result)

    def test_customer_conflict_declined_does_not_resend(self):
        api = FakeApi()
        api.errors = [AppError("conflito", error_code="INSPECTION_PD_CUSTOMER_CONFLICT", details={"proposals": []})]
        dialog, api = self._dialog(api)
        with patch(Q_DIALOG + ".question", return_value=QMessageBox.No):
            dialog.submit()
        self.assertEqual(len([c for c in api.calls if c[0] == "start"]), 1)
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.start_button.isEnabled())

    def test_pd_differs_from_order_fixes_pd(self):
        api = FakeApi()
        api.errors = [AppError("difere", error_code="INSPECTION_PD_DIFFERS_FROM_ORDER", details={"order_reference": "PD-OFICIAL"})]
        dialog, api = self._dialog(api)
        dialog.submit()
        self.assertEqual(dialog.pd_field.text(), "PD-OFICIAL")
        self.assertFalse(dialog.pd_field.isEnabled())
        self.assertEqual(dialog.error_label.text(), "difere")

    def test_cancelled_error_disables_button(self):
        api = FakeApi()
        api.errors = [AppError("cancelada", error_code="PROPOSAL_CANCELLED_TERMINAL")]
        dialog, _api = self._dialog(api)
        dialog.submit()
        self.assertFalse(dialog.start_button.isEnabled())

    def test_existing_inspection_warns_and_opens_it(self):
        api = FakeApi()
        api.result = {"id": 3, "pd_code": "PD", "stage": "nqt", "created": False, "events": []}
        opened = []

        class FakeDetail:
            def __init__(self, service, inspection, parent=None, **kwargs):
                opened.append(inspection["id"])

            def exec(self):
                return 0

        with patch(Q_DIALOG + ".information") as info, \
                patch.object(dialogs_module, "InspectionDetailDialog", FakeDetail), \
                patch.object(InspectionStartDialog, "exec", lambda self: self.submit() or 1):
            changed = start_inspection_for_proposal(FakeService(api), 7)
        self.assertTrue(changed)
        self.assertEqual(info.call_count, 1)
        self.assertEqual(opened, [3])


class PageTests(QtCase):
    def test_to_request_rows_badge_and_start(self):
        api = FakeApi()
        api.items = [{"id": 1, "pd_code": "PD-1", "proposal_numbers": ["CP 1"], "stage": "solicitada", "attempt": 1, "days_in_stage": 2}]
        api.to_request = [
            {"row_type": "to_request", "pd_code": None, "pd_source": None, "proposal_id": 7,
             "proposal_numbers": ["CP 700"], "customer_name": "Cliente A", "proposals": []},
        ]
        page = InspectionPage(FakeService(api))
        page.refresh()
        self.assertEqual(page.table.rowCount(), 2)
        self.assertEqual(page.table.item(0, 3).text(), "A solicitar")
        self.assertEqual(page.table.item(0, 0).text(), "Digitar o PD")
        self.assertEqual(page.table.item(1, 3).text(), "Inspeção solicitada")
        self.assertEqual(page.segments._options[0], ("all", "Todas", 2))
        page.table.selectRow(0)
        self.assertTrue(page.start_button.isEnabled())
        self.assertFalse(page.register_button.isEnabled())
        calls = []
        with patch.object(page_module, "start_inspection_for_proposal", lambda *a, **k: calls.append((a[1], k)) or True):
            page.start_selected()
        self.assertEqual(calls[0][0], 7)
        self.assertEqual(sum(1 for c in api.calls if c[0] == "list"), 2)
        page.table.selectRow(1)
        self.assertFalse(page.start_button.isEnabled())
        self.assertTrue(page.register_button.isEnabled())


class ActionCenterTests(QtCase):
    def test_registry_and_provider_category(self):
        registry = StatusDialog._build_registry()
        self.assertIsNotNone(registry.resolve("ADD_TO_INSPECTION", "CONTROLE GERAL"))

        class Svc:
            def process_actions(self, process_id, area, row_context=None):
                return [{"id": "ADD_TO_INSPECTION", "label": "Adicionar à inspeção", "icon": "inspection", "status": "", "area": "CONTROLE GERAL"}]

        context = ProposalActionContext(proposal_id=7, area="CONTROLE GERAL", current_status="AGUARDANDO_LIBERACAO", proposal_number="CP", client_name="C")
        descriptor = BackendActionProvider(Svc()).get_actions(context)[0]
        self.assertEqual(descriptor.category, ActionCategory.NORMAL)
        self.assertTrue(descriptor.description)

    def test_handler_opens_dialog_and_closes_center_only_when_changed(self):
        class Center:
            service = object()
            accepted = False

            def accept(self):
                self.accepted = True

        context = ProposalActionContext(proposal_id=7, area="CONTROLE GERAL", current_status="X", proposal_number="CP 700", client_name="Cliente A")
        for changed in (True, False):
            center = Center()
            seen = []
            with patch.object(handler_module, "start_inspection_for_proposal", lambda s, pid, parent, **k: seen.append((pid, k)) or changed):
                result = handler_module.AddToInspectionHandler().execute(context, None, center)
            self.assertEqual(seen[0][0], 7)
            self.assertEqual(center.accepted, changed)
            self.assertEqual(result.changed, changed)


if __name__ == "__main__":
    unittest.main()
