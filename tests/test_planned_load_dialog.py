from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.backend_adapter import VersionConflictError
from app.ui.planned_load_dialog import PlannedLoadDialog


def _run_synchronously(_owner, operation, on_success, on_error, **_kwargs):
    # Ver justificativa em tests/test_galvanization_load_manager_dialog.py:
    # `start_worker` roda em QThread real e entrega o resultado via signal
    # QueuedConnection (so na volta ao loop de eventos). Patchar
    # `start_worker` para rodar tudo inline evita callback pendente
    # disparando mais tarde com uma QMessageBox real ja fora do bloco
    # patchado.
    try:
        result = operation()
    except Exception as exc:
        on_error(exc)
    else:
        on_success(result)
    return None


def _detail(**overrides):
    base = {
        "id": 1,
        "code": "PL-0001",
        "status": "Planejamento",
        "expected_ship_date": "2026-08-25",
        "carrier_name": "Transportes Ana",
        "vehicle_info": "Caminhao ABC-1234",
        "responsible_user_id": 7,
        "responsible_user_name": "Bruno",
        "notes": "Observacao existente",
        "total_planned_quantity": "10",
        "total_available_quantity": "6",
        "total_missing_quantity": "4",
        "version": 3,
        "active": True,
        "items": [
            {
                "id": 501,
                "proposal_id": 10,
                "proposal_number": "CP00101",
                "customer_name": "MNS",
                "proposal_item_id": 9001,
                "item_number": "1",
                "product_code": "COD-A",
                "description": "Item planejado",
                "total_quantity": "10",
                "planned_quantity": "10",
                "currently_available_quantity": "6",
                "missing_quantity": "4",
                "free_for_other_plans_quantity": "0",
                "has_divergence": True,
                "divergence_reason": "SALDO_INSUFICIENTE",
                "notes": "",
                "version": 2,
                "active": True,
            }
        ],
        "history": [],
    }
    base.update(overrides)
    return base


class FakePlannedLoadDialogService:
    def __init__(self):
        self.stored = {1: _detail()}
        self.update_calls = []
        self.create_calls = []
        self.add_items_calls = []
        self.update_item_calls = []
        self.delete_item_calls = []

    def planned_load_detail(self, planned_load_id):
        return dict(self.stored[planned_load_id])

    def create_planned_load(self, payload):
        self.create_calls.append(payload)
        created = _detail(id=99, version=1, items=[])
        self.stored[99] = created
        return created

    def update_planned_load(self, planned_load_id, payload):
        self.update_calls.append((planned_load_id, payload))
        current = dict(self.stored[planned_load_id])
        current.update({k: v for k, v in payload.items() if k != "version"})
        current["version"] = current.get("version", 1) + 1
        self.stored[planned_load_id] = current
        return current

    def add_planned_load_items(self, planned_load_id, items):
        self.add_items_calls.append((planned_load_id, items))
        current = dict(self.stored[planned_load_id])
        new_items = list(current.get("items") or [])
        for entry in items:
            new_items.append(
                {
                    "id": 900 + len(new_items),
                    "proposal_id": 20,
                    "proposal_number": "CP00202",
                    "customer_name": "ABC",
                    "proposal_item_id": entry["proposal_item_id"],
                    "item_number": "2",
                    "product_code": "COD-B",
                    "description": "Item adicionado",
                    "total_quantity": "5",
                    "planned_quantity": entry["planned_quantity"],
                    "currently_available_quantity": "5",
                    "missing_quantity": "0",
                    "free_for_other_plans_quantity": "0",
                    "has_divergence": False,
                    "divergence_reason": None,
                    "notes": entry.get("notes"),
                    "version": 1,
                    "active": True,
                }
            )
        current["items"] = new_items
        self.stored[planned_load_id] = current
        return current

    def update_planned_load_item(self, planned_load_id, item_id, payload):
        self.update_item_calls.append((planned_load_id, item_id, payload))
        current = dict(self.stored[planned_load_id])
        items = []
        for row in current.get("items") or []:
            if row["id"] == item_id:
                row = dict(row)
                row["planned_quantity"] = payload.get("planned_quantity", row["planned_quantity"])
                row["version"] = row["version"] + 1
            items.append(row)
        current["items"] = items
        self.stored[planned_load_id] = current
        return current

    def delete_planned_load_item(self, planned_load_id, item_id, version):
        self.delete_item_calls.append((planned_load_id, item_id, version))
        current = dict(self.stored[planned_load_id])
        current["items"] = [row for row in (current.get("items") or []) if row["id"] != item_id]
        self.stored[planned_load_id] = current
        return current


class _FakePickerDialog:
    """Substitui `PlannedLoadItemPickerDialog` nos testes -- o picker em si
    tem sua propria suite (`test_planned_load_item_picker_dialog.py`); aqui
    so precisamos que `PlannedLoadDialog` chame `get_selected_items()`
    corretamente apos um `exec()` aceito."""

    accepted = True
    items: list[dict] = []

    def __init__(self, service, parent=None):
        pass

    def exec(self):
        return 1 if self.accepted else 0

    def get_selected_items(self):
        return list(self.items)


class PlannedLoadDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = FakePlannedLoadDialogService()

    def test_new_dialog_starts_empty_with_editable_code(self):
        dialog = PlannedLoadDialog(self.service)
        self.assertFalse(dialog.code_field.isReadOnly())
        self.assertEqual(dialog.items_model.rowCount(), 0)
        self.assertIsNone(dialog.planned_load_id)

    def test_editing_existing_loads_detail_and_makes_code_readonly(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        self.assertTrue(dialog.code_field.isReadOnly())
        self.assertEqual(dialog.code_field.text(), "PL-0001")
        self.assertEqual(dialog.carrier_name.text(), "Transportes Ana")
        self.assertEqual(dialog.expected_ship_date.text(), "25/08/2026")
        self.assertEqual(dialog.responsible_user_id.text(), "7")
        self.assertEqual(dialog.items_model.rowCount(), 1)
        self.assertEqual(dialog.version, 3)

    def test_save_existing_calls_update_with_expected_version_and_accepts(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        dialog.carrier_name.setText("Nova transportadora")
        with patch("app.ui.planned_load_dialog.start_worker", side_effect=_run_synchronously):
            dialog.save()
        self.assertEqual(len(self.service.update_calls), 1)
        called_id, payload = self.service.update_calls[0]
        self.assertEqual(called_id, 1)
        self.assertEqual(payload["version"], 3)
        self.assertEqual(payload["carrier_name"], "Nova transportadora")
        self.assertNotIn("code", payload)
        self.assertNotIn("items", payload)
        self.assertTrue(dialog.saved)
        self.assertTrue(dialog.result())

    def test_save_new_sends_code_and_pending_items_then_accepts(self):
        dialog = PlannedLoadDialog(self.service)
        dialog.code_field.setText("PL-CUSTOM")
        dialog.carrier_name.setText("Transportadora Nova")
        dialog._pending_items[9001] = {
            "proposal_item_id": 9001,
            "planned_quantity": 3.5,
            "notes": "obs",
            "proposal_number": "CP00101",
            "customer_name": "MNS",
            "item_number": "1",
            "description": "Item planejado",
        }
        with patch("app.ui.planned_load_dialog.start_worker", side_effect=_run_synchronously):
            dialog.save()
        self.assertEqual(len(self.service.create_calls), 1)
        payload = self.service.create_calls[0]
        self.assertEqual(payload["code"], "PL-CUSTOM")
        self.assertEqual(payload["carrier_name"], "Transportadora Nova")
        self.assertEqual(
            payload["items"],
            [{"proposal_item_id": 9001, "planned_quantity": "3.5", "notes": "obs"}],
        )
        self.assertTrue(dialog.saved)
        self.assertTrue(dialog.result())

    def test_save_rejects_non_numeric_responsible_id(self):
        dialog = PlannedLoadDialog(self.service)
        dialog.responsible_user_id.setText("abc")
        with patch("app.ui.planned_load_dialog.QMessageBox.warning") as warning:
            dialog.save()
        warning.assert_called_once()
        self.assertEqual(len(self.service.create_calls), 0)

    def test_add_items_in_new_dialog_stages_locally_without_api_call(self):
        dialog = PlannedLoadDialog(self.service)
        picker = _FakePickerDialog
        picker.accepted = True
        picker.items = [
            {
                "proposal_item_id": 42,
                "planned_quantity": 2.0,
                "notes": None,
                "proposal_number": "CP00303",
                "customer_name": "XPTO",
                "item_number": "1",
                "description": "Item novo",
            }
        ]
        with patch("app.ui.planned_load_dialog.PlannedLoadItemPickerDialog", picker):
            dialog.open_item_picker()
        self.assertEqual(len(self.service.add_items_calls), 0)
        self.assertEqual(dialog.items_model.rowCount(), 1)
        self.assertEqual(dialog.items_model.item_row_at(0)["proposal_item_id"], 42)

    def test_add_items_in_existing_dialog_calls_api_and_refreshes_table(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        picker = _FakePickerDialog
        picker.accepted = True
        picker.items = [
            {
                "proposal_item_id": 8888,
                "planned_quantity": 1.0,
                "notes": None,
                "proposal_number": "CP00202",
                "customer_name": "ABC",
                "item_number": "2",
                "description": "Item adicionado",
            }
        ]
        with patch("app.ui.planned_load_dialog.PlannedLoadItemPickerDialog", picker):
            dialog.open_item_picker()
        self.assertEqual(len(self.service.add_items_calls), 1)
        called_id, items_payload = self.service.add_items_calls[0]
        self.assertEqual(called_id, 1)
        self.assertEqual(items_payload, [{"proposal_item_id": 8888, "planned_quantity": "1.0", "notes": None}])
        self.assertEqual(dialog.items_model.rowCount(), 2)

    def test_remove_selected_item_in_new_dialog_removes_locally(self):
        dialog = PlannedLoadDialog(self.service)
        dialog._pending_items[9001] = {
            "proposal_item_id": 9001,
            "planned_quantity": 3.5,
            "notes": None,
            "proposal_number": "CP00101",
            "customer_name": "MNS",
            "item_number": "1",
            "description": "Item planejado",
        }
        dialog._refresh_pending_table()
        dialog.items_table.selectRow(0)
        dialog.remove_selected_item()
        self.assertEqual(dialog.items_model.rowCount(), 0)
        self.assertEqual(len(self.service.delete_item_calls), 0)

    def test_remove_selected_item_in_existing_dialog_calls_delete_with_version(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        dialog.items_table.selectRow(0)
        dialog.remove_selected_item()
        self.assertEqual(self.service.delete_item_calls, [(1, 501, 2)])
        self.assertEqual(dialog.items_model.rowCount(), 0)

    def test_remove_without_selection_shows_warning(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        with patch("app.ui.planned_load_dialog.QMessageBox.warning") as warning:
            dialog.remove_selected_item()
        warning.assert_called_once()

    def test_edit_quantity_in_existing_dialog_calls_update_with_version(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        dialog.items_table.selectRow(0)
        with patch("app.ui.planned_load_dialog.QInputDialog.getDouble", return_value=(7.0, True)):
            dialog._edit_selected_quantity()
        self.assertEqual(len(self.service.update_item_calls), 1)
        called_load_id, called_item_id, payload = self.service.update_item_calls[0]
        self.assertEqual((called_load_id, called_item_id), (1, 501))
        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["planned_quantity"], "7.0")

    def test_edit_quantity_cancelled_does_not_call_service(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        dialog.items_table.selectRow(0)
        with patch("app.ui.planned_load_dialog.QInputDialog.getDouble", return_value=(7.0, False)):
            dialog._edit_selected_quantity()
        self.assertEqual(len(self.service.update_item_calls), 0)

    def test_save_error_shows_critical_and_keeps_dialog_open(self):
        def failing_update(planned_load_id, payload):
            raise RuntimeError("conflito de versao")

        self.service.update_planned_load = failing_update
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        with patch("app.ui.planned_load_dialog.start_worker", side_effect=_run_synchronously), patch(
            "app.ui.planned_load_dialog.QMessageBox.critical"
        ) as critical:
            dialog.save()
        critical.assert_called_once()
        self.assertFalse(dialog.saved)
        self.assertFalse(dialog.result())

    # -- historico (FASE_PL6) --------------------------------------------

    def test_history_table_populated_from_detail(self):
        self.service.stored[1] = _detail(
            history=[
                {
                    "id": 1,
                    "event_type": "PLANNED_LOAD_CREATED",
                    "from_status": None,
                    "to_status": "Planejamento",
                    "actor_name": "Bruno",
                    "metadata": {},
                    "created_at": "2026-08-15T10:30:00Z",
                },
                {
                    "id": 2,
                    "event_type": "PLANNED_LOAD_ITEM_ADDED",
                    "from_status": None,
                    "to_status": None,
                    "actor_name": None,
                    "metadata": {},
                    "created_at": "2026-08-16T08:00:00Z",
                },
            ]
        )
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        self.assertEqual(dialog.history_table.rowCount(), 2)
        self.assertEqual(dialog.history_table.item(0, 0).text(), "Planejamento criado")
        self.assertEqual(dialog.history_table.item(0, 1).text(), "- -> Planejamento")
        self.assertEqual(dialog.history_table.item(0, 2).text(), "Bruno")
        self.assertEqual(dialog.history_table.item(1, 0).text(), "Item adicionado")
        self.assertEqual(dialog.history_table.item(1, 2).text(), "Sistema")
        # `isVisible()` so reflete visibilidade real de tela (sempre False num
        # dialogo nunca exibido via `.show()`) -- `isHidden()` reflete o flag
        # explicito que `_load_history_rows` manipula, que e o que importa aqui
        # (mesmo padrao documentado em tests/test_planned_loads_page.py).
        self.assertTrue(dialog.history_empty_label.isHidden())

    def test_history_table_empty_shows_placeholder(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        self.assertEqual(dialog.history_table.rowCount(), 0)
        self.assertFalse(dialog.history_empty_label.isHidden())

    # -- conflito de versao (VersionConflictError, FASE_PL6) -------------

    def test_save_existing_version_conflict_offers_reload_and_preserves_fields(self):
        def failing_update(planned_load_id, payload):
            raise VersionConflictError("versao desatualizada")

        self.service.update_planned_load = failing_update
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        dialog.carrier_name.setText("Transportadora digitada pelo usuario")
        with patch("app.ui.planned_load_dialog.start_worker", side_effect=_run_synchronously), patch(
            "app.ui.planned_load_dialog.QMessageBox.question", return_value=QMessageBox.Yes
        ) as question:
            dialog.save()
        question.assert_called_once()
        # Recarregou (version novo veio de `planned_load_detail`) mas manteve o
        # texto que o usuario tinha digitado, para ele so confirmar de novo.
        self.assertEqual(dialog.carrier_name.text(), "Transportadora digitada pelo usuario")
        self.assertFalse(dialog.saved)
        self.assertFalse(dialog.result())

    def test_save_existing_version_conflict_declined_keeps_dialog_untouched(self):
        def failing_update(planned_load_id, payload):
            raise VersionConflictError("versao desatualizada")

        self.service.update_planned_load = failing_update
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        with patch("app.ui.planned_load_dialog.start_worker", side_effect=_run_synchronously), patch(
            "app.ui.planned_load_dialog.QMessageBox.question", return_value=QMessageBox.No
        ):
            dialog.save()
        self.assertFalse(dialog.saved)
        self.assertEqual(dialog.carrier_name.text(), "Transportes Ana")

    def test_edit_quantity_version_conflict_reopens_input_with_pending_value(self):
        def failing_update(planned_load_id, item_id, payload):
            raise VersionConflictError("versao desatualizada")

        self.service.update_planned_load_item = failing_update
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        dialog.items_table.selectRow(0)
        with patch(
            "app.ui.planned_load_dialog.QInputDialog.getDouble", side_effect=[(9.0, True), (9.0, False)]
        ) as get_double, patch(
            "app.ui.planned_load_dialog.QMessageBox.question", return_value=QMessageBox.Yes
        ) as question:
            dialog._edit_selected_quantity()
        question.assert_called_once()
        self.assertEqual(get_double.call_count, 2)
        # Segunda chamada reabre com o valor pendente (9.0) pre-preenchido.
        second_call_args = get_double.call_args_list[1][0]
        self.assertIn(9.0, second_call_args)

    def test_remove_item_version_conflict_offers_reload(self):
        def failing_delete(planned_load_id, item_id, version):
            raise VersionConflictError("versao desatualizada")

        self.service.delete_planned_load_item = failing_delete
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        dialog.items_table.selectRow(0)
        with patch("app.ui.planned_load_dialog.QMessageBox.question", return_value=QMessageBox.Yes) as question:
            dialog.remove_selected_item()
        question.assert_called_once()
        # Recarregou via `planned_load_detail` -- item ainda presente no fake.
        self.assertEqual(dialog.items_model.rowCount(), 1)

    def test_add_items_version_conflict_offers_reload(self):
        def failing_add(planned_load_id, items):
            raise VersionConflictError("versao desatualizada")

        self.service.add_planned_load_items = failing_add
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        picker = _FakePickerDialog
        picker.accepted = True
        picker.items = [
            {
                "proposal_item_id": 8888,
                "planned_quantity": 1.0,
                "notes": None,
                "proposal_number": "CP00202",
                "customer_name": "ABC",
                "item_number": "2",
                "description": "Item adicionado",
            }
        ]
        with patch("app.ui.planned_load_dialog.PlannedLoadItemPickerDialog", picker), patch(
            "app.ui.planned_load_dialog.QMessageBox.question", return_value=QMessageBox.Yes
        ) as question:
            dialog.open_item_picker()
        question.assert_called_once()
        self.assertEqual(dialog.items_model.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
