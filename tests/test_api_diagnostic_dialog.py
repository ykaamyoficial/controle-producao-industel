from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.integrations.api.client import DesktopApiClient  # noqa: E402
from app.integrations.api.config import DesktopApiConfigStore  # noqa: E402
from app.ui.api_diagnostic_dialog import ApiDiagnosticDialog  # noqa: E402


def _pump_until(predicate, *, timeout: float = 5.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Condicao nao atingida dentro do timeout (possivel deadlock/thread travada).")
        app.processEvents()
        time.sleep(0.005)


def _client_factory(handler):
    def factory(settings):
        return DesktopApiClient(settings, transport=httpx.MockTransport(handler))

    return factory


_COMPATIBLE_PAYLOAD = {
    # >= app.version.MINIMUM_API_VERSION (0.8.1) -- ver nota em test_diagnostic_service.py
    "server_version": "0.9.0",
    "api_contract_version": "v1",
    "database_revision": "rev1",
    "minimum_desktop_version": "0.1.0",
    "recommended_desktop_version": "0.1.0",
    "maintenance_mode": False,
}


def _healthy_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/system/compatibility":
        return httpx.Response(200, json=_COMPATIBLE_PAYLOAD)
    return httpx.Response(200, json={"overall_status": "HEALTHY", "checks": [{"name": "database", "status": "PASS", "duration_ms": 1}]})


def _db_down_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/system/compatibility":
        return httpx.Response(200, json=_COMPATIBLE_PAYLOAD)
    return httpx.Response(503, json={"overall_status": "UNHEALTHY", "checks": [{"name": "database", "status": "FAIL", "duration_ms": 3}]})


class ApiDiagnosticDialogDiagnosticBlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _store(self, temp_dir: str) -> DesktopApiConfigStore:
        store = DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")
        store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")
        return store

    def test_run_button_triggers_diagnostic_and_renders_ok_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = ApiDiagnosticDialog(store=store, diagnostic_client_factory=_client_factory(_healthy_handler))
            dialog.show()

            dialog.diag_run_button.click()
            _pump_until(lambda: dialog._diagnostic_result is not None)

            self.assertIn("OK", dialog.diag_status_label.text())
            self.assertEqual(dialog.diag_checks_list.count(), 9)  # Fase 4 (7) + Fase 6 (VERSION_ENDPOINT, COMPATIBILITY)
            self.assertTrue(dialog.diag_copy_button.isEnabled())

    def test_ui_is_not_blocked_while_diagnostic_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = ApiDiagnosticDialog(store=store, diagnostic_client_factory=_client_factory(_healthy_handler))
            dialog.show()

            dialog.diag_run_button.click()
            # o botao desabilita imediatamente (prova de que a chamada nao e sincrona bloqueante)
            self.assertFalse(dialog.diag_run_button.isEnabled())
            _pump_until(lambda: dialog._diagnostic_result is not None)
            self.assertTrue(dialog.diag_run_button.isEnabled())

    def test_error_state_is_rendered_with_recommendation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = ApiDiagnosticDialog(store=store, diagnostic_client_factory=_client_factory(_db_down_handler))
            dialog.show()

            dialog.diag_run_button.click()
            _pump_until(lambda: dialog._diagnostic_result is not None)

            self.assertIn("ERRO", dialog.diag_status_label.text())
            items_text = [dialog.diag_checks_list.item(i).text() for i in range(dialog.diag_checks_list.count())]
            db_line = next(text for text in items_text if "PostgreSQL" in text)
            self.assertIn("[ERRO]", db_line)
            self.assertIn("Sugestao", db_line)

    def test_second_run_replaces_previous_checks_without_duplicating_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = ApiDiagnosticDialog(store=store, diagnostic_client_factory=_client_factory(_healthy_handler))
            dialog.show()

            dialog.diag_run_button.click()
            _pump_until(lambda: dialog._diagnostic_result is not None)
            first_count = dialog.diag_checks_list.count()

            dialog._diagnostic_result = None
            dialog.diag_run_button.click()
            _pump_until(lambda: dialog._diagnostic_result is not None)

            self.assertEqual(dialog.diag_checks_list.count(), first_count)

    def test_copy_report_puts_sanitized_text_on_clipboard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = ApiDiagnosticDialog(store=store, diagnostic_client_factory=_client_factory(_db_down_handler))
            dialog.show()

            dialog.diag_run_button.click()
            _pump_until(lambda: dialog._diagnostic_result is not None)
            dialog.diag_copy_button.click()

            clipboard_text = QApplication.clipboard().text()
            self.assertIn("SISTEMA CONTROLE PRODUCAO - DIAGNOSTICO", clipboard_text)
            self.assertIn("DATABASE_HEALTH", clipboard_text)
            self.assertNotIn("Authorization", clipboard_text)
            self.assertNotIn("Bearer", clipboard_text)


if __name__ == "__main__":
    unittest.main()
