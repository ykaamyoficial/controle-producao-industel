from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore
from app.services.bootstrap_service import (
    BootstrapErrorCode,
    BootstrapState,
    probe_health,
    run_bootstrap,
)


def _client_factory(handler):
    def factory(settings):
        return DesktopApiClient(settings, transport=httpx.MockTransport(handler))

    return factory


def _healthy_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"status": "healthy", "service": "controle-producao-api"})


def _unhealthy_body_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"status": "degraded"})


def _timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timeout")


def _connect_error_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("offline")


def _http_500_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": {"code": "INTERNAL", "message": "boom"}})


def _service_unavailable_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"error": {"code": "DATABASE_UNAVAILABLE", "message": "db down"}})


def _never_called_factory(settings):
    raise AssertionError("nenhuma chamada HTTP deveria ocorrer para configuracao invalida")


class ProbeHealthTests(unittest.TestCase):
    def test_healthy_response_is_ready(self):
        ok, code = probe_health("http://192.168.1.50:8000", client_factory=_client_factory(_healthy_handler))
        self.assertTrue(ok)
        self.assertEqual(code, BootstrapErrorCode.READY)

    def test_unhealthy_body_is_reported(self):
        ok, code = probe_health("http://192.168.1.50:8000", client_factory=_client_factory(_unhealthy_body_handler))
        self.assertFalse(ok)
        self.assertEqual(code, BootstrapErrorCode.API_UNHEALTHY)

    def test_timeout_is_classified(self):
        ok, code = probe_health("http://192.168.1.50:8000", client_factory=_client_factory(_timeout_handler))
        self.assertFalse(ok)
        self.assertEqual(code, BootstrapErrorCode.TIMEOUT)

    def test_connection_refused_is_classified(self):
        ok, code = probe_health("http://192.168.1.50:8000", client_factory=_client_factory(_connect_error_handler))
        self.assertFalse(ok)
        self.assertEqual(code, BootstrapErrorCode.DNS_OR_CONNECT_ERROR)

    def test_http_500_is_classified_as_health_http_error(self):
        ok, code = probe_health("http://192.168.1.50:8000", client_factory=_client_factory(_http_500_handler))
        self.assertFalse(ok)
        self.assertEqual(code, BootstrapErrorCode.HEALTH_HTTP_ERROR)

    def test_503_is_classified_as_unhealthy(self):
        ok, code = probe_health("http://192.168.1.50:8000", client_factory=_client_factory(_service_unavailable_handler))
        self.assertFalse(ok)
        self.assertEqual(code, BootstrapErrorCode.API_UNHEALTHY)


class RunBootstrapTests(unittest.TestCase):
    def test_persisted_valid_config_and_healthy_api_releases_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_bootstrap(config_store=store, client_factory=_client_factory(_healthy_handler))

            self.assertEqual(result.state, BootstrapState.READY_FOR_LOGIN)
            self.assertEqual(result.base_url, "http://192.168.1.50:8000")
            self.assertEqual(result.source, "persisted")

    def test_missing_config_with_working_bootstrap_saves_and_releases_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")
            self.assertFalse(store.is_configured())

            result = run_bootstrap(
                config_store=store,
                client_factory=_client_factory(_healthy_handler),
                bootstrap_url_provider=lambda: "http://192.168.1.77:8000",
            )

            self.assertEqual(result.state, BootstrapState.READY_FOR_LOGIN)
            self.assertEqual(result.source, "bootstrap_default")
            # salvamento bem-sucedido passa a ser consumido pelo cliente central:
            # uma nova instancia lendo o mesmo arquivo enxerga o valor salvo.
            reloaded = DesktopApiConfigStore(config_path=store.config_path)
            self.assertTrue(reloaded.is_configured())
            self.assertEqual(reloaded.load_settings().base_url, "http://192.168.1.77:8000")

    def test_missing_config_and_missing_bootstrap_requests_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")

            result = run_bootstrap(config_store=store, client_factory=_never_called_factory, bootstrap_url_provider=lambda: None)

            self.assertEqual(result.state, BootstrapState.NEEDS_CONFIGURATION)
            self.assertEqual(result.error_code, BootstrapErrorCode.CONFIG_MISSING)
            self.assertEqual(result.source, "none")

    def test_invalid_persisted_config_does_not_call_http_and_requests_correction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            store = DesktopApiConfigStore(config_path=config_path)
            # grava um valor invalido diretamente (contornando save_settings, que ja
            # validaria) para simular um arquivo corrompido/editado manualmente.
            store._service.update(lambda config: config.update({"desktop_api": {"enabled": True, "base_url": "http://0.0.0.0:8000"}}))

            result = run_bootstrap(config_store=store, client_factory=_never_called_factory)

            self.assertEqual(result.state, BootstrapState.NEEDS_CONFIGURATION)
            self.assertEqual(result.error_code, BootstrapErrorCode.CONFIG_INVALID)

    def test_timeout_on_persisted_config_returns_controlled_state_without_erasing_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_bootstrap(config_store=store, client_factory=_client_factory(_timeout_handler))

            self.assertEqual(result.state, BootstrapState.API_UNREACHABLE)
            self.assertEqual(result.error_code, BootstrapErrorCode.TIMEOUT)
            # a falha temporaria nao apaga nem sobrescreve a configuracao existente.
            self.assertEqual(store.load_settings().base_url, "http://192.168.1.50:8000")

    def test_connection_refused_on_persisted_config_returns_controlled_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_bootstrap(config_store=store, client_factory=_client_factory(_connect_error_handler))

            self.assertEqual(result.state, BootstrapState.API_UNREACHABLE)
            self.assertEqual(result.error_code, BootstrapErrorCode.DNS_OR_CONNECT_ERROR)

    def test_api_unhealthy_on_persisted_config_does_not_release_login(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_bootstrap(config_store=store, client_factory=_client_factory(_unhealthy_body_handler))

            self.assertEqual(result.state, BootstrapState.API_UNREACHABLE)
            self.assertEqual(result.error_code, BootstrapErrorCode.API_UNHEALTHY)

    def test_bootstrap_default_unreachable_does_not_save_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")

            result = run_bootstrap(
                config_store=store,
                client_factory=_client_factory(_connect_error_handler),
                bootstrap_url_provider=lambda: "http://192.168.1.77:8000",
            )

            self.assertEqual(result.state, BootstrapState.NEEDS_CONFIGURATION)
            self.assertFalse(store.is_configured())


if __name__ == "__main__":
    unittest.main()
