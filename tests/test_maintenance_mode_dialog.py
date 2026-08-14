from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.integrations.api.models import MaintenanceInfoDto, SystemCompatibilityDto  # noqa: E402
from app.services.compatibility_check import CompatibilityCheckResult  # noqa: E402
from app.ui.maintenance_mode_dialog import MaintenanceModeDialog  # noqa: E402
from app.versioning.models import CompatibilityStatus  # noqa: E402


def _pump_until(predicate, *, timeout: float = 5.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Condicao nao atingida dentro do timeout (possivel deadlock/thread travada).")
        app.processEvents()
        time.sleep(0.005)


def _maintenance_result(**overrides) -> CompatibilityCheckResult:
    maintenance = MaintenanceInfoDto(
        state="ACTIVE", maintenance_id="mnt-20260812-000001",
        message="Sistema em atualizacao.", expected_end_at="2026-08-12T11:00:00+00:00",
        retry_after_seconds=30,
    )
    dto = SystemCompatibilityDto(
        server_version="3.2.0", api_contract_version="v1", database_revision="20260810_0015",
        minimum_desktop_version="3.1.0", recommended_desktop_version="3.2.0",
        maintenance_mode=True, maintenance=maintenance,
    )
    defaults = dict(state=CompatibilityStatus.MAINTENANCE, local_desktop_version="3.2.0", dto=dto)
    defaults.update(overrides)
    return CompatibilityCheckResult(**defaults)


class MaintenanceModeDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_shows_message_and_eta_from_initial_result(self):
        result = _maintenance_result()
        dialog = MaintenanceModeDialog(lambda: result, result, auto_start_timer=False)
        self.assertIn("Sistema em atualizacao", dialog.message_label.text())
        self.assertIn("2026-08-12T11:00:00", dialog.details_label.text())
        self.assertIn("ACTIVE", dialog.status_label.text())

    def test_does_not_show_raw_503_error_text(self):
        result = _maintenance_result()
        dialog = MaintenanceModeDialog(lambda: result, result, auto_start_timer=False)
        rendered = dialog.message_label.text() + dialog.details_label.text() + dialog.status_label.text()
        self.assertNotIn("503", rendered)
        self.assertNotIn("Traceback", rendered)

    def test_manual_retry_that_clears_maintenance_closes_dialog_and_proceeds(self):
        initial = _maintenance_result()
        cleared = CompatibilityCheckResult(CompatibilityStatus.COMPATIBLE, "3.2.0")
        calls = {"count": 0}

        def check():
            calls["count"] += 1
            return cleared

        dialog = MaintenanceModeDialog(check, initial, auto_start_timer=False)
        dialog.show()
        dialog.retry_button.click()
        _pump_until(lambda: dialog.proceed)

        self.assertTrue(dialog.proceed)
        self.assertEqual(calls["count"], 1)

    def test_still_in_maintenance_after_poll_keeps_dialog_open_and_reschedules(self):
        initial = _maintenance_result()
        still_active = _maintenance_result()

        dialog = MaintenanceModeDialog(lambda: still_active, initial, auto_start_timer=False)
        dialog.show()
        dialog.retry_button.click()
        _pump_until(lambda: not dialog._checking)

        self.assertFalse(dialog.proceed)
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog._timer.isActive())

    def test_transport_failure_during_poll_applies_backoff_without_crashing(self):
        initial = _maintenance_result()

        def failing_check():
            raise RuntimeError("falha de rede simulada")

        dialog = MaintenanceModeDialog(failing_check, initial, auto_start_timer=False)
        base_interval = dialog._poll_interval_ms
        dialog.show()
        dialog.retry_button.click()
        _pump_until(lambda: not dialog._checking)

        self.assertFalse(dialog.proceed)
        self.assertGreater(dialog._poll_interval_ms, base_interval)

    def test_close_button_sets_proceed_false_and_stops_timer(self):
        result = _maintenance_result()
        dialog = MaintenanceModeDialog(lambda: result, result, auto_start_timer=True)
        dialog.show()
        dialog.exit_button.click()
        self.assertFalse(dialog.proceed)
        self.assertFalse(dialog._timer.isActive())

    def test_retry_after_seconds_drives_the_poll_interval(self):
        result = _maintenance_result()
        dialog = MaintenanceModeDialog(lambda: result, result, auto_start_timer=False)
        self.assertEqual(dialog._poll_interval_ms, 30_000)

    def test_missing_maintenance_info_falls_back_to_generic_message(self):
        result = CompatibilityCheckResult(CompatibilityStatus.MAINTENANCE, "3.0.0", dto=None)
        dialog = MaintenanceModeDialog(lambda: result, result, auto_start_timer=False)
        self.assertIn("manutencao", dialog.message_label.text().lower())


if __name__ == "__main__":
    unittest.main()
