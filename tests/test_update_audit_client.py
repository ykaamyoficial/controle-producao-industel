from __future__ import annotations

import unittest

import httpx

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import ApiPermissionError
from app.integrations.api.update_audit_client import UpdateAuditApiClient

TOKEN = "fake-access-token"


def _settings() -> DesktopApiSettings:
    return DesktopApiSettings(enabled=True, base_url="http://127.0.0.1:8000", connect_timeout=1, read_timeout=1)


class UpdateAuditApiClientTests(unittest.TestCase):
    def test_list_events_sends_bearer_token_and_only_provided_filters(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["query"] = request.url.query.decode()
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 50, "offset": 0})

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        data = UpdateAuditApiClient(client).list_events(TOKEN, version="3.3.0", limit=10, offset=0)
        client.close()

        self.assertEqual(captured["path"], "/api/v1/admin/update-audit/events")
        self.assertEqual(captured["auth"], f"Bearer {TOKEN}")
        self.assertIn("version=3.3.0", captured["query"])
        self.assertIn("limit=10", captured["query"])
        self.assertNotIn("event_type=", captured["query"])
        self.assertEqual(data, {"items": [], "total": 0, "limit": 50, "offset": 0})

    def test_list_events_omits_empty_string_filters(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = request.url.query.decode()
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 50, "offset": 0})

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        UpdateAuditApiClient(client).list_events(TOKEN, event_type="", channel=None, result="FAILED")
        client.close()

        self.assertNotIn("event_type=", captured["query"])
        self.assertNotIn("channel=", captured["query"])
        self.assertIn("result=FAILED", captured["query"])

    def test_get_event_hits_the_detail_path_with_auth(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"event_id": "evt-1"})

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        data = UpdateAuditApiClient(client).get_event(TOKEN, "evt-1")
        client.close()

        self.assertEqual(captured["path"], "/api/v1/admin/update-audit/events/evt-1")
        self.assertEqual(captured["auth"], f"Bearer {TOKEN}")
        self.assertEqual(data["event_id"], "evt-1")

    def test_get_timeline_hits_the_timeline_path(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 0, "offset": 0})

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        UpdateAuditApiClient(client).get_timeline(TOKEN, "upd-20260812-abcd1234")
        client.close()

        self.assertEqual(captured["path"], "/api/v1/admin/update-audit/timeline/upd-20260812-abcd1234")

    def test_get_installation_status_hits_the_installations_path(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json={"installation_id": "pc-1"})

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        data = UpdateAuditApiClient(client).get_installation_status(TOKEN, "pc-1")
        client.close()

        self.assertEqual(captured["path"], "/api/v1/admin/update-audit/installations/pc-1")
        self.assertEqual(data["installation_id"], "pc-1")

    def test_get_release_events_hits_the_releases_path(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 0, "offset": 0})

        client = DesktopApiClient(_settings(), transport=httpx.MockTransport(handler))
        UpdateAuditApiClient(client).get_release_events(TOKEN, "3.3.0")
        client.close()

        self.assertEqual(captured["path"], "/api/v1/admin/update-audit/releases/3.3.0")

    def test_403_raises_api_permission_error(self):
        client = DesktopApiClient(
            _settings(),
            transport=httpx.MockTransport(lambda _r: httpx.Response(403, json={"error": {"code": "FORBIDDEN", "message": "sem permissao"}})),
        )
        with self.assertRaises(ApiPermissionError):
            UpdateAuditApiClient(client).list_events(TOKEN)
        client.close()


if __name__ == "__main__":
    unittest.main()
