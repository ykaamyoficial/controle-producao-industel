from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.integrations.api.models import SystemCompatibilityDto  # noqa: E402
from app.services.compatibility_check import CompatibilityCheckResult  # noqa: E402
from app.services.update_coordinator import UpdateLaunchResult  # noqa: E402
from app.ui.compatibility_gate_dialog import CompatibilityGateDialog  # noqa: E402
from app.versioning.models import CompatibilityStatus  # noqa: E402


def _pump_until(predicate, *, timeout: float = 5.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Condicao nao atingida dentro do timeout (possivel deadlock/thread travada).")
        app.processEvents()
        time.sleep(0.005)


def _dto(**overrides) -> SystemCompatibilityDto:
    base = dict(
        server_version="3.2.0", api_contract_version="v1", database_revision="rev1",
        minimum_desktop_version="3.1.0", recommended_desktop_version="3.2.0", maintenance_mode=False,
    )
    base.update(overrides)
    return SystemCompatibilityDto(**base)


class CompatibilityGateDialogUpdateFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_update_recommended_closes_dialog_and_sets_proceed_true(self):
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_RECOMMENDED, "3.1.5", dto=_dto())
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertTrue(dialog.proceed)
        self.assertFalse(dialog.isVisible())

    def test_required_without_authorized_version_hides_update_now_button(self):
        dto = _dto(authorized_update_version=None)
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_REQUIRED, "3.0.0", dto=dto)
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertFalse(dialog.update_now_button.isVisible())
        self.assertTrue(dialog.retry_button.isVisible())
        self.assertTrue(dialog.exit_button.isVisible())

    def test_required_with_authorized_version_shows_update_now_button(self):
        dto = _dto(authorized_update_version="3.2.0")
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_REQUIRED, "3.0.0", dto=dto)
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertTrue(dialog.update_now_button.isVisible())

    def test_incompatible_with_authorized_version_shows_update_now_button(self):
        dto = _dto(authorized_update_version="3.2.0")
        result = CompatibilityCheckResult(CompatibilityStatus.INCOMPATIBLE, "9.0.0", dto=dto)
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertTrue(dialog.update_now_button.isVisible())

    def test_update_available_never_shows_update_now_button(self):
        # UPDATE_AVAILABLE/RECOMMENDED nao bloqueiam -- o dialogo ja fecha sozinho,
        # entao o botao nunca chega a ser avaliado/mostrado.
        dto = _dto(authorized_update_version="3.2.0")
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_AVAILABLE, "3.1.5", dto=dto)
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertFalse(dialog.update_now_button.isVisible())

    def test_clicking_update_now_launches_and_closes_with_proceed_false(self):
        dto = _dto(authorized_update_version="3.2.0")
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_REQUIRED, "3.0.0", dto=dto)
        launch_calls = []

        def fake_launcher(expected_version):
            launch_calls.append(expected_version)
            return UpdateLaunchResult(launched=True, request_id="req-1", updater_pid=123, target_version="3.2.0")

        dialog = CompatibilityGateDialog(lambda: result, update_launcher=fake_launcher)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        dialog.update_now_button.click()
        _pump_until(lambda: dialog.update_launched)

        self.assertEqual(launch_calls, ["3.2.0"])
        self.assertTrue(dialog.update_launched)
        self.assertFalse(dialog.proceed)
        self.assertFalse(dialog.isVisible())

    def test_update_launch_failure_keeps_dialog_open_and_reenables_buttons(self):
        dto = _dto(authorized_update_version="3.2.0")
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_REQUIRED, "3.0.0", dto=dto)

        def failing_launcher(expected_version):
            return UpdateLaunchResult(launched=False, request_id=None, updater_pid=None, error_message="SHA-256 nao confere")

        dialog = CompatibilityGateDialog(lambda: result, update_launcher=failing_launcher)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        dialog.update_now_button.click()
        _pump_until(lambda: dialog.update_now_button.isEnabled())

        self.assertFalse(dialog.update_launched)
        self.assertTrue(dialog.isVisible())
        self.assertIn("SHA-256", dialog.message_label.text())

    def test_update_launcher_exception_does_not_crash_dialog(self):
        dto = _dto(authorized_update_version="3.2.0")
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_REQUIRED, "3.0.0", dto=dto)

        def crashing_launcher(expected_version):
            raise RuntimeError("erro inesperado")

        dialog = CompatibilityGateDialog(lambda: result, update_launcher=crashing_launcher)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        dialog.update_now_button.click()
        _pump_until(lambda: dialog.update_now_button.isEnabled())

        self.assertFalse(dialog.update_launched)
        self.assertTrue(dialog.isVisible())

    def test_required_message_includes_minimum_version(self):
        dto = _dto()
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_REQUIRED, "3.0.0", dto=dto)
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertIn(dto.minimum_desktop_version, dialog.message_label.text())


if __name__ == "__main__":
    unittest.main()
