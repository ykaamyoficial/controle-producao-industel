from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.services.update_coordinator import UpdateLaunchResult  # noqa: E402
from app.ui.update_dialog import UpdateDialog  # noqa: E402


def _pump_until(predicate, *, timeout: float = 5.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Condicao nao atingida dentro do timeout (possivel deadlock/thread travada).")
        app.processEvents()
        time.sleep(0.005)


_UPDATE_INFO = {
    "current_version": "2.4.9",
    "latest_version": "2.5.0",
    "published_at": "2026-08-01",
    "release_notes": "Correcoes diversas.",
}


class _FakeCoordinator:
    def __init__(self, result: UpdateLaunchResult, *, calls: list):
        self._result = result
        self._calls = calls

    def start_required_update(self, *, expected_version=None):
        self._calls.append(expected_version)
        return self._result


class UpdateDialogOrchestratorFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _confirm_yes(self):
        return patch("app.ui.update_dialog.QMessageBox.question", return_value=QMessageBox.Yes)

    def _suppress_warning_box(self):
        return patch("app.ui.update_dialog.QMessageBox.warning", return_value=QMessageBox.Ok)

    def test_confirming_update_delegates_to_update_coordinator_with_expected_version(self):
        calls: list = []
        launch_result = UpdateLaunchResult(launched=True, request_id="req-1", updater_pid=123, target_version="2.5.0")
        dialog = UpdateDialog(
            _UPDATE_INFO,
            update_coordinator_factory=lambda: _FakeCoordinator(launch_result, calls=calls),
        )
        dialog.show()

        with self._confirm_yes():
            dialog.download_update()
        _pump_until(lambda: dialog.update_launched)

        self.assertEqual(calls, ["2.5.0"])
        self.assertTrue(dialog.update_launched)
        self.assertFalse(dialog.isVisible())

    def test_declining_confirmation_never_calls_coordinator(self):
        calls: list = []
        launch_result = UpdateLaunchResult(launched=True, request_id="req-1", updater_pid=123, target_version="2.5.0")
        dialog = UpdateDialog(
            _UPDATE_INFO,
            update_coordinator_factory=lambda: _FakeCoordinator(launch_result, calls=calls),
        )
        dialog.show()

        with patch("app.ui.update_dialog.QMessageBox.question", return_value=QMessageBox.No):
            dialog.download_update()

        self.assertEqual(calls, [])
        self.assertFalse(dialog.update_launched)
        self.assertTrue(dialog.isVisible())

    def test_launch_failure_keeps_dialog_open_and_reenables_button(self):
        calls: list = []
        launch_result = UpdateLaunchResult(launched=False, request_id=None, updater_pid=None, error_message="SHA-256 nao confere")
        dialog = UpdateDialog(
            _UPDATE_INFO,
            update_coordinator_factory=lambda: _FakeCoordinator(launch_result, calls=calls),
        )
        dialog.show()

        with self._confirm_yes(), self._suppress_warning_box():
            dialog.download_update()
        _pump_until(lambda: dialog.download_button.isEnabled())

        self.assertFalse(dialog.update_launched)
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.download_button.isEnabled())
        self.assertEqual(dialog.download_button.text(), "Atualizar agora")

    def test_coordinator_exception_does_not_crash_dialog(self):
        class _RaisingCoordinator:
            def start_required_update(self, *, expected_version=None):
                raise RuntimeError("erro inesperado de rede")

        dialog = UpdateDialog(_UPDATE_INFO, update_coordinator_factory=_RaisingCoordinator)
        dialog.show()

        with self._confirm_yes(), self._suppress_warning_box():
            dialog.download_update()
        _pump_until(lambda: dialog.download_button.isEnabled())

        self.assertFalse(dialog.update_launched)
        self.assertTrue(dialog.isVisible())


if __name__ == "__main__":
    unittest.main()
