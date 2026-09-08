from __future__ import annotations

import socket
import ssl
import tempfile
import unittest
from pathlib import Path

import httpx

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore
from app.services.diagnostic_service import (
    DiagnosticErrorCode,
    DiagnosticStatus,
    build_report_text,
    classify_connect_exception,
    classify_tls_exception,
    run_diagnostics,
)


def _client_factory(handler):
    def factory(settings):
        return DesktopApiClient(settings, transport=httpx.MockTransport(handler))

    return factory


_COMPATIBLE_PAYLOAD = {
    # >= app.version.MINIMUM_API_VERSION (0.8.1) -- fixture ficou obsoleta quando
    # o minimo subiu; um server 0.8.0 hoje e SERVER_UPDATE_REQUIRED, nao "compativel".
    "server_version": "0.9.0",
    "api_contract_version": "v1",
    "database_revision": "rev1",
    "minimum_desktop_version": "0.1.0",
    "recommended_desktop_version": "0.1.0",
    "maintenance_mode": False,
}


def _healthy_ready_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/system/compatibility":
        return httpx.Response(200, json=_COMPATIBLE_PAYLOAD)
    return httpx.Response(
        200,
        json={
            "overall_status": "HEALTHY",
            "checks": [
                {"name": "database", "status": "PASS", "duration_ms": 2, "message": "ok"},
            ],
        },
    )


def _db_down_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/system/compatibility":
        return httpx.Response(200, json=_COMPATIBLE_PAYLOAD)
    return httpx.Response(
        503,
        json={
            "overall_status": "UNHEALTHY",
            "checks": [
                {"name": "database", "status": "FAIL", "duration_ms": 5, "message": "PostgreSQL indisponivel", "error_code": "DATABASE_UNAVAILABLE"},
            ],
        },
    )


def _generic_500_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text="Internal Server Error")


def _not_found_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "not found"}})


def _unauthorized_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": {"code": "TOKEN_EXPIRED", "message": "expired"}})


def _timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("timed out")


def _connect_error_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("boom", request=request) from ConnectionRefusedError("refused")


def _tls_untrusted_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("boom", request=request) from ssl.SSLCertVerificationError(
        "certificate verify failed: self-signed certificate in certificate chain"
    )


def _tls_expired_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("boom", request=request) from ssl.SSLCertVerificationError(
        "certificate verify failed: certificate has expired"
    )


def _tls_hostname_mismatch_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("boom", request=request) from ssl.SSLCertVerificationError(
        "Hostname mismatch, certificate is not valid for 'servidor-errado'."
    )


def _tls_handshake_failed_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("boom", request=request) from ssl.SSLError("unknown protocol")


def _redirect_to_https_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(308, headers={"Location": "https://192.168.1.50/api/v1/health/ready"})


def _never_called_factory(settings):
    raise AssertionError("nenhuma chamada HTTP deveria ocorrer aqui")


class ClassifyConnectExceptionTests(unittest.TestCase):
    def test_dns_failure_is_classified(self):
        cause = socket.gaierror("getaddrinfo failed")
        exc = RuntimeError("wrapped")
        exc.__cause__ = cause
        self.assertEqual(classify_connect_exception(exc), DiagnosticErrorCode.HOST_RESOLUTION_FAILED)

    def test_connection_refused_is_classified(self):
        cause = ConnectionRefusedError("refused")
        exc = RuntimeError("wrapped")
        exc.__cause__ = cause
        self.assertEqual(classify_connect_exception(exc), DiagnosticErrorCode.CONNECTION_REFUSED)

    def test_network_unreachable_is_classified(self):
        cause = OSError("Network is unreachable")
        exc = RuntimeError("wrapped")
        exc.__cause__ = cause
        self.assertEqual(classify_connect_exception(exc), DiagnosticErrorCode.NETWORK_UNREACHABLE)

    def test_unknown_cause_falls_back_to_connection_refused(self):
        exc = RuntimeError("something else entirely")
        self.assertEqual(classify_connect_exception(exc), DiagnosticErrorCode.CONNECTION_REFUSED)


class RunDiagnosticsTests(unittest.TestCase):
    def _store(self, temp_dir: str) -> DesktopApiConfigStore:
        return DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")

    def _by_code(self, result, code):
        return next(c for c in result.checks if c.code == code)

    def test_missing_configuration_marks_config_present_error_and_rest_not_tested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            result = run_diagnostics(config_store=store, client_factory=_never_called_factory)

            self.assertEqual(result.overall_status, DiagnosticStatus.ERROR)
            self.assertEqual(self._by_code(result, "CONFIG_PRESENT").status, DiagnosticStatus.ERROR)
            self.assertEqual(self._by_code(result, "CONFIG_PRESENT").error_code, DiagnosticErrorCode.CFG_MISSING)
            for code in ("URL_VALID", "HOST_RESOLUTION", "API_REACHABLE", "HEALTH_HTTP", "API_HEALTH", "DATABASE_HEALTH"):
                self.assertEqual(self._by_code(result, code).status, DiagnosticStatus.NOT_TESTED)

    def test_invalid_persisted_url_marks_url_valid_error_without_http_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store._service.update(lambda config: config.update({"desktop_api": {"enabled": True, "base_url": "http://0.0.0.0:8000"}}))

            result = run_diagnostics(config_store=store, client_factory=_never_called_factory)

            self.assertEqual(self._by_code(result, "CONFIG_PRESENT").status, DiagnosticStatus.OK)
            self.assertEqual(self._by_code(result, "URL_VALID").status, DiagnosticStatus.ERROR)
            self.assertEqual(self._by_code(result, "URL_VALID").error_code, DiagnosticErrorCode.CFG_INVALID)
            self.assertEqual(self._by_code(result, "HOST_RESOLUTION").status, DiagnosticStatus.NOT_TESTED)

    def test_host_resolution_failure_is_classified_and_stops_chain(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://this-host-should-not-exist.invalid:8000")

            result = run_diagnostics(config_store=store, client_factory=_never_called_factory)

            self.assertEqual(self._by_code(result, "HOST_RESOLUTION").status, DiagnosticStatus.ERROR)
            self.assertEqual(self._by_code(result, "HOST_RESOLUTION").error_code, DiagnosticErrorCode.HOST_RESOLUTION_FAILED)
            self.assertEqual(self._by_code(result, "API_REACHABLE").status, DiagnosticStatus.NOT_TESTED)

    def test_timeout_is_classified_as_connect_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_timeout_handler))

            self.assertEqual(self._by_code(result, "API_REACHABLE").status, DiagnosticStatus.ERROR)
            self.assertEqual(self._by_code(result, "API_REACHABLE").error_code, DiagnosticErrorCode.CONNECT_TIMEOUT)
            self.assertEqual(self._by_code(result, "HEALTH_HTTP").status, DiagnosticStatus.NOT_TESTED)

    def test_connection_refused_is_classified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_connect_error_handler))

            self.assertEqual(self._by_code(result, "API_REACHABLE").status, DiagnosticStatus.ERROR)
            self.assertEqual(self._by_code(result, "API_REACHABLE").error_code, DiagnosticErrorCode.CONNECTION_REFUSED)

    def test_healthy_response_yields_overall_ok(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_healthy_ready_handler))

            self.assertEqual(result.overall_status, DiagnosticStatus.OK)
            for check in result.checks:
                self.assertEqual(check.status, DiagnosticStatus.OK, check.code)

    def test_503_with_database_unavailable_is_api_reachable_and_db_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_db_down_handler))

            self.assertEqual(self._by_code(result, "API_REACHABLE").status, DiagnosticStatus.OK)
            self.assertEqual(self._by_code(result, "HEALTH_HTTP").status, DiagnosticStatus.OK)
            self.assertEqual(self._by_code(result, "DATABASE_HEALTH").status, DiagnosticStatus.ERROR)
            self.assertEqual(self._by_code(result, "DATABASE_HEALTH").error_code, DiagnosticErrorCode.DB_UNAVAILABLE)
            self.assertEqual(result.overall_status, DiagnosticStatus.ERROR)

    def test_generic_500_is_api_reachable_but_not_confused_with_network_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_generic_500_handler))

            self.assertEqual(self._by_code(result, "API_REACHABLE").status, DiagnosticStatus.OK)
            self.assertEqual(self._by_code(result, "HEALTH_HTTP").status, DiagnosticStatus.ERROR)
            self.assertEqual(self._by_code(result, "HEALTH_HTTP").error_code, DiagnosticErrorCode.HTTP_UNEXPECTED)
            self.assertNotIn(self._by_code(result, "HEALTH_HTTP").error_code, (DiagnosticErrorCode.CONNECTION_REFUSED, DiagnosticErrorCode.HOST_RESOLUTION_FAILED, DiagnosticErrorCode.NETWORK_UNREACHABLE, DiagnosticErrorCode.CONNECT_TIMEOUT))

    def test_404_is_classified_as_http_unexpected_route_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_not_found_handler))

            self.assertEqual(self._by_code(result, "API_REACHABLE").status, DiagnosticStatus.OK)
            self.assertEqual(self._by_code(result, "HEALTH_HTTP").status, DiagnosticStatus.ERROR)
            self.assertEqual(self._by_code(result, "HEALTH_HTTP").error_code, DiagnosticErrorCode.HTTP_UNEXPECTED)

    def test_401_is_treated_as_server_response_not_offline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_unauthorized_handler))

            # a API foi alcancada normalmente -- 401 nunca pode virar erro de rede.
            self.assertEqual(self._by_code(result, "API_REACHABLE").status, DiagnosticStatus.OK)
            health_check = self._by_code(result, "HEALTH_HTTP")
            self.assertEqual(health_check.status, DiagnosticStatus.ERROR)
            self.assertNotIn(health_check.error_code, (DiagnosticErrorCode.CONNECTION_REFUSED, DiagnosticErrorCode.HOST_RESOLUTION_FAILED, DiagnosticErrorCode.NETWORK_UNREACHABLE, DiagnosticErrorCode.CONNECT_TIMEOUT))

    def test_report_text_is_sanitized_and_contains_no_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://usuario:senha123@192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_db_down_handler))
            report = build_report_text(result)

            self.assertNotIn("senha123", report)
            self.assertNotIn("usuario", report)
            self.assertIn("DATABASE_HEALTH", report)
            self.assertIn(result.overall_status.value, report)


class ClassifyTlsExceptionTests(unittest.TestCase):
    def test_untrusted_certificate_is_classified(self):
        cause = ssl.SSLCertVerificationError("certificate verify failed: self-signed certificate in certificate chain")
        exc = RuntimeError("wrapped")
        exc.__cause__ = cause
        self.assertEqual(classify_tls_exception(exc), DiagnosticErrorCode.TLS_CERT_UNTRUSTED)

    def test_expired_certificate_is_classified(self):
        cause = ssl.SSLCertVerificationError("certificate verify failed: certificate has expired")
        exc = RuntimeError("wrapped")
        exc.__cause__ = cause
        self.assertEqual(classify_tls_exception(exc), DiagnosticErrorCode.TLS_CERT_EXPIRED)

    def test_hostname_mismatch_is_classified(self):
        cause = ssl.SSLCertVerificationError("Hostname mismatch, certificate is not valid for 'servidor-errado'.")
        exc = RuntimeError("wrapped")
        exc.__cause__ = cause
        self.assertEqual(classify_tls_exception(exc), DiagnosticErrorCode.TLS_HOSTNAME_MISMATCH)

    def test_generic_ssl_error_is_classified_as_handshake_failed(self):
        cause = ssl.SSLError("unknown protocol")
        exc = RuntimeError("wrapped")
        exc.__cause__ = cause
        self.assertEqual(classify_tls_exception(exc), DiagnosticErrorCode.TLS_HANDSHAKE_FAILED)

    def test_non_tls_cause_returns_none(self):
        cause = ConnectionRefusedError("refused")
        exc = RuntimeError("wrapped")
        exc.__cause__ = cause
        self.assertIsNone(classify_tls_exception(exc))


class RunDiagnosticsTlsTests(unittest.TestCase):
    def _store(self, temp_dir: str) -> DesktopApiConfigStore:
        return DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")

    def _by_code(self, result, code):
        return next(c for c in result.checks if c.code == code)

    def test_untrusted_certificate_is_not_confused_with_offline_server(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="https://192.168.1.50")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_tls_untrusted_handler))

            reachable = self._by_code(result, "API_REACHABLE")
            self.assertEqual(reachable.status, DiagnosticStatus.ERROR)
            self.assertEqual(reachable.error_code, DiagnosticErrorCode.TLS_CERT_UNTRUSTED)
            self.assertNotEqual(reachable.error_code, DiagnosticErrorCode.CONNECTION_REFUSED)
            self.assertNotEqual(reachable.error_code, DiagnosticErrorCode.HOST_RESOLUTION_FAILED)

    def test_expired_certificate_is_classified_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="https://192.168.1.50")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_tls_expired_handler))

            self.assertEqual(self._by_code(result, "API_REACHABLE").error_code, DiagnosticErrorCode.TLS_CERT_EXPIRED)

    def test_hostname_mismatch_is_classified_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="https://192.168.1.50")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_tls_hostname_mismatch_handler))

            self.assertEqual(self._by_code(result, "API_REACHABLE").error_code, DiagnosticErrorCode.TLS_HOSTNAME_MISMATCH)

    def test_generic_handshake_failure_is_classified_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="https://192.168.1.50")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_tls_handshake_failed_handler))

            self.assertEqual(self._by_code(result, "API_REACHABLE").error_code, DiagnosticErrorCode.TLS_HANDSHAKE_FAILED)

    def test_http_redirect_to_https_is_classified_as_https_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_redirect_to_https_handler))

            self.assertEqual(self._by_code(result, "API_REACHABLE").status, DiagnosticStatus.OK)
            health_check = self._by_code(result, "HEALTH_HTTP")
            self.assertEqual(health_check.status, DiagnosticStatus.ERROR)
            self.assertEqual(health_check.error_code, DiagnosticErrorCode.HTTPS_REQUIRED)

    def test_tls_error_report_never_contains_certificate_or_secret_material(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="https://192.168.1.50")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_tls_untrusted_handler))
            report = build_report_text(result)

            for forbidden in ("BEGIN CERTIFICATE", "PRIVATE KEY", "Authorization", "Bearer"):
                self.assertNotIn(forbidden, report)


def _compat_handler(compatibility_payload=None, *, compatibility_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/system/compatibility":
            return httpx.Response(compatibility_status, json=compatibility_payload)
        return httpx.Response(200, json={"overall_status": "HEALTHY", "checks": [{"name": "database", "status": "PASS", "duration_ms": 1}]})

    return handler


class RunDiagnosticsCompatibilityTests(unittest.TestCase):
    """Fase 6, Secao 12: VERSION_ENDPOINT/COMPATIBILITY reaproveitam
    app.versioning.compatibility -- nao reimplementam a regra aqui."""

    def _store(self, temp_dir: str) -> DesktopApiConfigStore:
        return DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json")

    def _by_code(self, result, code):
        return next(c for c in result.checks if c.code == code)

    def test_compatible_combination_yields_ok_compatibility(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")
            payload = dict(_COMPATIBLE_PAYLOAD, minimum_desktop_version="0.0.1", recommended_desktop_version="0.0.1")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_compat_handler(payload)))

            self.assertEqual(self._by_code(result, "VERSION_ENDPOINT").status, DiagnosticStatus.OK)
            self.assertEqual(self._by_code(result, "COMPATIBILITY").status, DiagnosticStatus.OK)
            self.assertEqual(result.overall_status, DiagnosticStatus.OK)

    def test_server_older_than_minimum_api_version_is_server_update_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")
            payload = dict(_COMPATIBLE_PAYLOAD, server_version="0.0.1", minimum_desktop_version="0.0.1", recommended_desktop_version="0.0.1")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_compat_handler(payload)))

            compat = self._by_code(result, "COMPATIBILITY")
            self.assertEqual(compat.status, DiagnosticStatus.ERROR)
            self.assertEqual(compat.error_code, DiagnosticErrorCode.SERVER_UPDATE_REQUIRED)
            self.assertEqual(result.overall_status, DiagnosticStatus.ERROR)

    def test_desktop_older_than_minimum_desktop_version_is_client_update_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")
            payload = dict(_COMPATIBLE_PAYLOAD, minimum_desktop_version="99.0.0", recommended_desktop_version="99.0.0")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_compat_handler(payload)))

            compat = self._by_code(result, "COMPATIBILITY")
            self.assertEqual(compat.status, DiagnosticStatus.ERROR)
            self.assertEqual(compat.error_code, DiagnosticErrorCode.CLIENT_UPDATE_REQUIRED)

    def test_malformed_compatibility_payload_is_version_metadata_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_compat_handler({"unexpected": "shape"})))

            version_endpoint = self._by_code(result, "VERSION_ENDPOINT")
            self.assertEqual(version_endpoint.status, DiagnosticStatus.ERROR)
            self.assertEqual(version_endpoint.error_code, DiagnosticErrorCode.VERSION_METADATA_INVALID)
            self.assertEqual(self._by_code(result, "COMPATIBILITY").status, DiagnosticStatus.NOT_TESTED)

    def test_compatibility_endpoint_failure_is_version_endpoint_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_compat_handler(None, compatibility_status=500)))

            version_endpoint = self._by_code(result, "VERSION_ENDPOINT")
            self.assertEqual(version_endpoint.status, DiagnosticStatus.ERROR)
            self.assertEqual(version_endpoint.error_code, DiagnosticErrorCode.VERSION_ENDPOINT_UNAVAILABLE)

    def test_update_recommended_does_not_block_overall_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")
            payload = dict(_COMPATIBLE_PAYLOAD, minimum_desktop_version="0.0.1", recommended_desktop_version="99.0.0")

            result = run_diagnostics(config_store=store, client_factory=_client_factory(_compat_handler(payload)))

            compat = self._by_code(result, "COMPATIBILITY")
            self.assertEqual(compat.status, DiagnosticStatus.WARNING)
            self.assertEqual(result.overall_status, DiagnosticStatus.WARNING)

    def test_compatibility_check_is_read_only_no_installation_id_sent(self):
        seen_query = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/system/compatibility":
                seen_query["installation_id"] = request.url.params.get("installation_id")
                return httpx.Response(200, json=dict(_COMPATIBLE_PAYLOAD, minimum_desktop_version="0.0.1", recommended_desktop_version="0.0.1"))
            return httpx.Response(200, json={"overall_status": "HEALTHY", "checks": [{"name": "database", "status": "PASS", "duration_ms": 1}]})

        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            run_diagnostics(config_store=store, client_factory=_client_factory(handler))

            self.assertIsNone(seen_query.get("installation_id"))


if __name__ == "__main__":
    unittest.main()
