from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.backend_adapter import VersionConflictError
from app.ui.planned_load_dialog import PlannedLoadDialog


def _detail(**overrides):
    base = {
        "id": 1,
        "code": "PL-0001",
        "status": "Pronta para montar",
        "expected_ship_date": "2026-08-25",
        "carrier_name": "Transportes Ana",
        "vehicle_info": "Caminhao ABC-1234",
        "responsible_user_id": 7,
        "responsible_user_name": "Bruno",
        "notes": "",
        "total_planned_quantity": "10",
        "total_available_quantity": "10",
        "total_missing_quantity": "0",
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
                "currently_available_quantity": "10",
                "missing_quantity": "0",
                "free_for_other_plans_quantity": "0",
                "has_divergence": False,
                "divergence_reason": None,
                "notes": "",
                "version": 2,
                "active": True,
            }
        ],
        "history": [],
    }
    base.update(overrides)
    return base


def _build_result(**overrides):
    base = {
        "planned_load_id": 1,
        "fully_available": True,
        "total_planned_quantity": "10",
        "total_available_quantity": "10",
        "total_missing_quantity": "0",
        "ready_items": [
            {
                "proposal_item_id": 9001,
                "item_number": "1",
                "description": "Item planejado",
                "planned_quantity": "10",
                "available_quantity": "10",
            }
        ],
        "pending_items": [],
    }
    base.update(overrides)
    return base


class FakePlannedLoadBuildFlowService:
    def __init__(self):
        self.stored = {1: _detail()}
        self.build_result = _build_result()
        self.build_calls = []
        self.cancel_calls = []
        self.mark_converted_calls = []
        self.mark_converted_result = None
        self.mark_converted_exception = None
        self.cancel_exception = None

    def planned_load_detail(self, planned_load_id):
        return dict(self.stored[planned_load_id])

    def build_planned_load(self, planned_load_id):
        self.build_calls.append(planned_load_id)
        return dict(self.build_result)

    def cancel_planned_load(self, planned_load_id, version):
        self.cancel_calls.append((planned_load_id, version))
        if self.cancel_exception is not None:
            raise self.cancel_exception
        current = dict(self.stored[planned_load_id])
        current["status"] = "Cancelada"
        current["version"] = current.get("version", 1) + 1
        self.stored[planned_load_id] = current
        return current

    def mark_planned_load_converted(self, planned_load_id, version, real_load_id):
        self.mark_converted_calls.append((planned_load_id, version, real_load_id))
        if self.mark_converted_exception is not None:
            raise self.mark_converted_exception
        if self.mark_converted_result is not None:
            return dict(self.mark_converted_result)
        current = dict(self.stored[planned_load_id])
        current["status"] = "Convertida em carga"
        current["converted_load_id"] = real_load_id
        current["version"] = current.get("version", 1) + 1
        self.stored[planned_load_id] = current
        return current


def _fake_galvanization_dialog(*, exec_result=1, saved=True, load_id=555):
    fake = MagicMock()
    fake.exec.return_value = exec_result
    fake.saved = saved
    fake.load_id = load_id
    return fake


class PlannedLoadBuildFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = FakePlannedLoadBuildFlowService()

    # -- fully_available=True -------------------------------------------

    def test_build_fully_available_opens_galvanization_dialog_preselected(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        fake_load_dialog = _fake_galvanization_dialog()
        with patch(
            "app.ui.planned_load_dialog.GalvanizationLoadDialog", return_value=fake_load_dialog
        ) as ctor, patch("app.ui.planned_load_dialog.QMessageBox.information"):
            dialog.build_load()
        self.assertEqual(self.service.build_calls, [1])
        ctor.assert_called_once_with(self.service, preselected_item_ids=[9001], parent=dialog)
        fake_load_dialog.exec.assert_called_once()

    def test_mark_converted_called_after_galvanization_dialog_saves(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        fake_load_dialog = _fake_galvanization_dialog(load_id=777)
        with patch("app.ui.planned_load_dialog.GalvanizationLoadDialog", return_value=fake_load_dialog), patch(
            "app.ui.planned_load_dialog.QMessageBox.information"
        ):
            dialog.build_load()
        self.assertEqual(self.service.mark_converted_calls, [(1, 3, 777)])
        self.assertTrue(dialog.saved)
        self.assertTrue(dialog.result())

    def test_mark_converted_not_called_when_galvanization_dialog_cancelled(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        fake_load_dialog = _fake_galvanization_dialog(exec_result=0, saved=False, load_id=None)
        with patch("app.ui.planned_load_dialog.GalvanizationLoadDialog", return_value=fake_load_dialog):
            dialog.build_load()
        self.assertEqual(self.service.mark_converted_calls, [])
        self.assertFalse(dialog.saved)
        self.assertFalse(dialog.result())

    def test_mark_converted_not_called_when_dialog_accepted_but_not_saved(self):
        # Defesa extra: exec() aceito mas `saved`/`load_id` nao setados nunca
        # deveria acontecer no GalvanizationLoadDialog real, mas o fluxo aqui
        # nao deve chamar mark-converted sem os dois.
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        fake_load_dialog = _fake_galvanization_dialog(exec_result=1, saved=False, load_id=None)
        with patch("app.ui.planned_load_dialog.GalvanizationLoadDialog", return_value=fake_load_dialog):
            dialog.build_load()
        self.assertEqual(self.service.mark_converted_calls, [])

    # -- fully_available=False -------------------------------------------

    def test_build_partial_availability_shows_summary_with_wait_and_partial_options(self):
        self.service.build_result = _build_result(
            fully_available=False,
            total_available_quantity="6",
            total_missing_quantity="4",
            pending_items=[
                {
                    "proposal_item_id": 9002,
                    "item_number": "2",
                    "description": "Item pendente",
                    "planned_quantity": "4",
                    "available_quantity": "0",
                    "missing_quantity": "4",
                }
            ],
        )
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        with patch("app.ui.planned_load_dialog.GalvanizationLoadDialog") as ctor:
            with patch(
                "app.ui.planned_load_dialog.PlannedLoadBuildSummaryDialog"
            ) as summary_ctor:
                fake_summary = MagicMock()
                fake_summary.exec.return_value = 0  # "Aguardar"
                summary_ctor.return_value = fake_summary
                dialog.build_load()
        summary_ctor.assert_called_once_with(self.service.build_result, parent=dialog)
        fake_summary.exec.assert_called_once()
        ctor.assert_not_called()
        self.assertEqual(self.service.mark_converted_calls, [])

    def test_build_partial_availability_wait_option_does_nothing(self):
        self.service.build_result = _build_result(fully_available=False, total_missing_quantity="4")
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        with patch("app.ui.planned_load_dialog.GalvanizationLoadDialog") as ctor, patch(
            "app.ui.planned_load_dialog.PlannedLoadBuildSummaryDialog"
        ) as summary_ctor:
            fake_summary = MagicMock()
            fake_summary.exec.return_value = 0
            summary_ctor.return_value = fake_summary
            dialog.build_load()
        ctor.assert_not_called()
        self.assertEqual(self.service.mark_converted_calls, [])
        self.assertFalse(dialog.saved)

    def test_build_partial_availability_partial_option_opens_galvanization_dialog_with_ready_only(self):
        self.service.build_result = _build_result(
            fully_available=False,
            total_missing_quantity="4",
            ready_items=[
                {
                    "proposal_item_id": 9001,
                    "item_number": "1",
                    "description": "Item planejado",
                    "planned_quantity": "6",
                    "available_quantity": "6",
                }
            ],
            pending_items=[
                {
                    "proposal_item_id": 9002,
                    "item_number": "2",
                    "description": "Item pendente",
                    "planned_quantity": "4",
                    "available_quantity": "0",
                    "missing_quantity": "4",
                }
            ],
        )
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        fake_load_dialog = _fake_galvanization_dialog(load_id=888)
        with patch(
            "app.ui.planned_load_dialog.GalvanizationLoadDialog", return_value=fake_load_dialog
        ) as ctor, patch("app.ui.planned_load_dialog.PlannedLoadBuildSummaryDialog") as summary_ctor, patch(
            "app.ui.planned_load_dialog.QMessageBox.information"
        ):
            fake_summary = MagicMock()
            fake_summary.exec.return_value = 1  # "Montar carga parcial"
            summary_ctor.return_value = fake_summary
            dialog.build_load()
        ctor.assert_called_once_with(self.service, preselected_item_ids=[9001], parent=dialog)
        self.assertEqual(self.service.mark_converted_calls, [(1, 3, 888)])

    # -- erro generico no build (rede de seguranca) -----------------------

    def test_build_error_shows_critical_and_does_not_open_anything(self):
        def failing_build(planned_load_id):
            raise RuntimeError("O planejamento nao possui itens para montar carga.")

        self.service.build_planned_load = failing_build
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        with patch("app.ui.planned_load_dialog.GalvanizationLoadDialog") as ctor, patch(
            "app.ui.planned_load_dialog.QMessageBox.critical"
        ) as critical:
            dialog.build_load()
        critical.assert_called_once()
        ctor.assert_not_called()

    # -- habilitacao dos botoes conforme status/itens ----------------------

    def test_build_and_cancel_buttons_disabled_for_closed_status(self):
        self.service.stored[1] = _detail(status="Convertida em carga")
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        self.assertFalse(dialog.build_load_button.isEnabled())
        self.assertFalse(dialog.cancel_planning_button.isEnabled())

    def test_build_button_disabled_without_items(self):
        self.service.stored[1] = _detail(items=[])
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        self.assertFalse(dialog.build_load_button.isEnabled())
        self.assertTrue(dialog.cancel_planning_button.isEnabled())

    def test_buttons_disabled_for_unsaved_new_dialog(self):
        dialog = PlannedLoadDialog(self.service)
        self.assertFalse(dialog.build_load_button.isEnabled())
        self.assertFalse(dialog.cancel_planning_button.isEnabled())

    # -- cancelamento -------------------------------------------------------

    def test_cancel_planning_confirmed_calls_service_and_updates_status(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        with patch(
            "app.ui.planned_load_dialog.QMessageBox.question", return_value=QMessageBox.Yes
        ) as question, patch("app.ui.planned_load_dialog.QMessageBox.information"):
            dialog.cancel_planning()
        question.assert_called_once()
        self.assertEqual(self.service.cancel_calls, [(1, 3)])
        self.assertEqual(dialog._detail.get("status"), "Cancelada")
        self.assertFalse(dialog.build_load_button.isEnabled())
        self.assertFalse(dialog.cancel_planning_button.isEnabled())

    def test_cancel_planning_declined_does_nothing(self):
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        with patch("app.ui.planned_load_dialog.QMessageBox.question", return_value=QMessageBox.No):
            dialog.cancel_planning()
        self.assertEqual(self.service.cancel_calls, [])

    def test_cancel_planning_version_conflict_offers_reload(self):
        def failing_cancel(planned_load_id, version):
            raise VersionConflictError("versao desatualizada")

        self.service.cancel_planned_load = failing_cancel
        dialog = PlannedLoadDialog(self.service, planned_load_id=1)
        with patch(
            "app.ui.planned_load_dialog.QMessageBox.question", return_value=QMessageBox.Yes
        ) as question:
            dialog.cancel_planning()
        # Uma pergunta para confirmar o cancelamento, outra para oferecer o
        # reload apos o conflito de versao.
        self.assertEqual(question.call_count, 2)
        self.assertEqual(dialog._detail.get("status"), "Pronta para montar")


if __name__ == "__main__":
    unittest.main()
