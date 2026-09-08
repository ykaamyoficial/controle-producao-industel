from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.compatibility_check import CompatibilityCheckResult  # noqa: E402
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


class CompatibilityGateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_compatible_result_closes_dialog_and_sets_proceed_true(self):
        result = CompatibilityCheckResult(CompatibilityStatus.COMPATIBLE, "3.2.0")
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertTrue(dialog.proceed)
        self.assertFalse(dialog.isVisible())

    def test_update_available_result_closes_dialog_and_sets_proceed_true(self):
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_AVAILABLE, "3.1.5")
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertTrue(dialog.proceed)

    def test_update_required_result_blocks_and_shows_retry_and_exit(self):
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_REQUIRED, "3.0.0")
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertFalse(dialog.proceed)
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.retry_button.isVisible())
        self.assertTrue(dialog.exit_button.isVisible())

    def test_maintenance_result_blocks_operation(self):
        result = CompatibilityCheckResult(CompatibilityStatus.MAINTENANCE, "3.0.0")
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertFalse(dialog.proceed)

    def test_check_failed_blocks_operation(self):
        result = CompatibilityCheckResult(CompatibilityStatus.CHECK_FAILED, "3.0.0")
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        self.assertFalse(dialog.proceed)

    def test_unexpected_exception_becomes_check_failed_not_a_crash(self):
        def failing_check():
            raise RuntimeError("falha de rede simulada")

        dialog = CompatibilityGateDialog(failing_check)
        _pump_until(lambda: dialog.check_result is not None)
        self.assertFalse(dialog.proceed)
        self.assertEqual(dialog.check_result.state, CompatibilityStatus.CHECK_FAILED)

    def test_exit_button_sets_proceed_false_and_closes_dialog(self):
        result = CompatibilityCheckResult(CompatibilityStatus.INCOMPATIBLE, "3.0.0")
        dialog = CompatibilityGateDialog(lambda: result)
        dialog.show()
        _pump_until(lambda: dialog.check_result is not None)
        dialog.exit_button.click()
        self.assertFalse(dialog.proceed)
        self.assertFalse(dialog.isVisible())

    def test_retry_reruns_the_check_and_ignores_clicks_while_in_flight(self):
        calls = {"count": 0}

        def check():
            calls["count"] += 1
            if calls["count"] == 1:
                return CompatibilityCheckResult(CompatibilityStatus.CHECK_FAILED, "3.0.0")
            return CompatibilityCheckResult(CompatibilityStatus.COMPATIBLE, "3.2.0")

        dialog = CompatibilityGateDialog(check)
        _pump_until(lambda: dialog.check_result is not None)
        self.assertEqual(calls["count"], 1)

        # Duplo clique rapido no Tentar novamente nao pode disparar duas checagens concorrentes.
        dialog.retry_button.click()
        dialog.retry_button.click()
        dialog.retry_button.click()
        _pump_until(lambda: dialog.proceed)
        self.assertEqual(calls["count"], 2)
        self.assertTrue(dialog.proceed)


if __name__ == "__main__":
    unittest.main()
