from __future__ import annotations

import unittest

import httpx

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import (
    ApiConnectionError,
    ApiTimeoutError,
    ApiUnavailableError,
    ApiUnexpectedResponseError,
)
from app.integrations.api.models import SystemCompatibilityDto
from app.integrations.api.system_client import SystemApiClient


def _settings() -> DesktopApiSettings:
    return DesktopApiSettings(enabled=True, base_url="http://127.0.0.1:8000", connect_timeout=1, read_timeout=1)


_VALID_PAYLOAD = {
    "server_version": "0.8.0",
    "api_contract_version": "v1",
    "database_revision": "20260810_0015",
    "minimum_desktop_version": "2.5.2",
    "recommended_desktop_version": "2.5.2",
    "maintenance_mode": False,
}


class SystemApiClientCompatibilityTests(unittest.TestCase):
    def test_valid_response_is_deserialized_correctly(self):
        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=_VALID_PAYLOAD)))
        dto = SystemApiClient(client).compatibility()
        client.close()

        self.assertIsInstance(dto, SystemCompatibilityDto)
        self.assertEqual(dto.server_version, "0.8.0")
        self.assertEqual(dto.api_contract_version, "v1")
        self.assertEqual(dto.database_revision, "20260810_0015")
        self.assertEqual(dto.minimum_desktop_version, "2.5.2")
        self.assertEqual(dto.recommended_desktop_version, "2.5.2")
        self.assertFalse(dto.maintenance_mode)

    def test_timeout_raises_api_timeout_error(self):
        def handler(_request: httpx.Request):
            raise httpx.TimeoutException("timeout")

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        with self.assertRaises(ApiTimeoutError):
            SystemApiClient(client).compatibility()
        client.close()

    def test_connection_refused_raises_api_connection_error(self):
        def handler(_request: httpx.Request):
            raise httpx.ConnectError("refused")

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        with self.assertRaises(ApiConnectionError):
            SystemApiClient(client).compatibility()
        client.close()

    def test_503_raises_api_unavailable_error(self):
        client = DesktopApiClient(
            _settings(),
            transport=httpx.MockTransport(lambda _r: httpx.Response(503, json={"error": {"code": "DATABASE_UNAVAILABLE", "message": "indisponivel"}})),
        )
        with self.assertRaises(ApiUnavailableError):
            SystemApiClient(client).compatibility()
        client.close()

    def test_malformed_json_raises_api_unexpected_response_error(self):
        client = DesktopApiClient(
            _settings(),
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})),
        )
        with self.assertRaises(ApiUnexpectedResponseError):
            SystemApiClient(client).compatibility()
        client.close()

    def test_missing_required_field_raises_api_unexpected_response_error(self):
        payload = dict(_VALID_PAYLOAD)
        del payload["minimum_desktop_version"]
        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload)))
        with self.assertRaises(ApiUnexpectedResponseError):
            SystemApiClient(client).compatibility()
        client.close()

    def test_retries_on_transient_failure_since_endpoint_is_idempotent(self):
        attempts = {"count": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=_VALID_PAYLOAD)

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        dto = SystemApiClient(client).compatibility()
        client.close()

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(dto.server_version, "0.8.0")

    def test_desktop_version_is_sent_as_query_param(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = request.url.query.decode()
            return httpx.Response(200, json=_VALID_PAYLOAD)

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        SystemApiClient(client).compatibility(desktop_version="2.5.2")
        client.close()

        self.assertEqual(captured["query"], "desktop_version=2.5.2")

    def test_no_desktop_version_sends_no_query_string(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = request.url.query.decode()
            return httpx.Response(200, json=_VALID_PAYLOAD)

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        SystemApiClient(client).compatibility()
        client.close()

        self.assertEqual(captured["query"], "")

    def test_fase13_fields_parse_when_present(self):
        payload = dict(_VALID_PAYLOAD)
        payload.update({
            "desktop_state": "UPDATE_REQUIRED", "enforcement": "REQUIRED",
            "authorized_update_version": "2.6.0", "policy_revision": 5,
            "grace_until": "2026-08-15T18:00:00+00:00", "message": "Atualize agora",
        })
        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload)))
        dto = SystemApiClient(client).compatibility(desktop_version="2.5.2")
        client.close()

        self.assertEqual(dto.desktop_state, "UPDATE_REQUIRED")
        self.assertEqual(dto.enforcement, "REQUIRED")
        self.assertEqual(dto.authorized_update_version, "2.6.0")
        self.assertEqual(dto.policy_revision, 5)
        self.assertEqual(dto.message, "Atualize agora")

    def test_fase13_fields_default_safely_when_absent_from_old_server(self):
        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=_VALID_PAYLOAD)))
        dto = SystemApiClient(client).compatibility(desktop_version="2.5.2")
        client.close()

        self.assertIsNone(dto.desktop_state)
        self.assertEqual(dto.enforcement, "NONE")
        self.assertIsNone(dto.authorized_update_version)
        self.assertEqual(dto.policy_revision, 0)

    def test_retries_still_work_when_desktop_version_query_param_is_present(self):
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=_VALID_PAYLOAD)

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        dto = SystemApiClient(client).compatibility(desktop_version="2.5.2")
        client.close()

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(dto.server_version, "0.8.0")


if __name__ == "__main__":
    unittest.main()
