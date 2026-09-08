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
from app.ui.first_access_dialog import FirstAccessDialog  # noqa: E402


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


def _healthy_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"status": "healthy", "service": "controle-producao-api"})


def _connect_error_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("offline")


def _never_called_factory(settings):
    raise AssertionError("nenhuma chamada HTTP deveria ocorrer para valor invalido")


class FirstAccessDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _store(self, temp_dir: str) -> DesktopApiConfigStore:
        return DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")

    def test_silent_success_closes_dialog_without_showing_form(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")
            dialog = FirstAccessDialog(config_store=store, client_factory=_client_factory(_healthy_handler))
            dialog.show()
            _pump_until(lambda: not dialog.isVisible())
            self.assertTrue(dialog.proceed)
            self.assertEqual(dialog.result_base_url, "http://192.168.1.50:8000")
            self.assertFalse(dialog.field_container.isVisible())

    def test_missing_configuration_shows_form(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = FirstAccessDialog(config_store=store, client_factory=_never_called_factory, bootstrap_url_provider=lambda: None)
            dialog.show()
            _pump_until(lambda: dialog.field_container.isVisible())
            self.assertTrue(dialog.save_button.isVisible())
            self.assertTrue(dialog.test_button.isVisible())
            self.assertFalse(dialog.save_button.isEnabled())

    def test_unreachable_persisted_config_prefills_field_and_shows_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")
            dialog = FirstAccessDialog(config_store=store, client_factory=_client_factory(_connect_error_handler))
            dialog.show()
            _pump_until(lambda: dialog.field_container.isVisible())
            self.assertEqual(dialog.url_field.text(), "http://192.168.1.50:8000")
            self.assertTrue(dialog.retry_known_button.isVisible())
            self.assertIn("configurado", dialog.message_label.text())

    def test_invalid_value_never_triggers_http_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = FirstAccessDialog(config_store=store, client_factory=_never_called_factory, bootstrap_url_provider=lambda: None)
            dialog.show()
            _pump_until(lambda: dialog.field_container.isVisible())

            dialog.url_field.setText("http://0.0.0.0:8000")
            dialog._test_connection()

            self.assertIn("0.0.0.0", dialog.status_label.text())
            self.assertFalse(dialog.save_button.isEnabled())

    def test_successful_test_enables_save_and_saving_persists_and_closes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = FirstAccessDialog(config_store=store, client_factory=_client_factory(_healthy_handler), bootstrap_url_provider=lambda: None)
            dialog.show()
            _pump_until(lambda: dialog.field_container.isVisible())

            dialog.url_field.setText("http://192.168.1.77:8000")
            dialog._test_connection()
            _pump_until(lambda: dialog.save_button.isEnabled())

            dialog.save_button.click()
            _pump_until(lambda: not dialog.isVisible())

            self.assertTrue(dialog.proceed)
            self.assertEqual(dialog.result_base_url, "http://192.168.1.77:8000")
            reloaded = DesktopApiConfigStore(config_path=store.config_path)
            self.assertEqual(reloaded.load_settings().base_url, "http://192.168.1.77:8000")

    def test_editing_field_after_successful_test_disables_save_until_retested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = FirstAccessDialog(config_store=store, client_factory=_client_factory(_healthy_handler), bootstrap_url_provider=lambda: None)
            dialog.show()
            _pump_until(lambda: dialog.field_container.isVisible())

            dialog.url_field.setText("http://192.168.1.77:8000")
            dialog._test_connection()
            _pump_until(lambda: dialog.save_button.isEnabled())

            dialog.url_field.setText("http://192.168.1.78:8000")
            self.assertFalse(dialog.save_button.isEnabled())

            # O setEnabled(False) acima agenda um repaint do save_button
            # (ModernButton/AppIconButton) que nunca e processado se o
            # teste termina aqui: o dialog nao e fechado e so sobrevive
            # via um ciclo de referencia (botao -> slot conectado ->
            # dialog -> botao), entao o Python so o libera num ciclo do
            # GC em momento imprevisivel -- podendo cair durante o
            # app.processEvents() de um teste completamente diferente
            # mais adiante e entregar aquele repaint pendente contra um
            # ModernButton ja destruido (AttributeError em _badge_count
            # dentro de AppIconButton.paintEvent). Fechar e drenar a fila
            # aqui evita deixar esse estado pendurado.
            dialog.close()
            for _ in range(5):
                self.app.processEvents()

    def test_failed_test_keeps_save_disabled_and_does_not_touch_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = FirstAccessDialog(config_store=store, client_factory=_client_factory(_connect_error_handler), bootstrap_url_provider=lambda: None)
            dialog.show()
            _pump_until(lambda: dialog.field_container.isVisible())

            dialog.url_field.setText("http://192.168.1.99:8000")
            dialog._test_connection()
            _pump_until(lambda: dialog.status_label.text() != "Status: testando...")

            self.assertFalse(dialog.save_button.isEnabled())
            self.assertFalse(store.is_configured())

    def test_exit_button_rejects_with_proceed_false(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            dialog = FirstAccessDialog(config_store=store, client_factory=_never_called_factory, bootstrap_url_provider=lambda: None)
            dialog.show()
            _pump_until(lambda: dialog.field_container.isVisible())

            dialog.exit_button.click()

            self.assertFalse(dialog.proceed)
            self.assertFalse(dialog.isVisible())


if __name__ == "__main__":
    unittest.main()
