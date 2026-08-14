from __future__ import annotations

import unittest

import httpx

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiSettings
from app.services import update_distribution_client as udc


def _settings(*, enabled: bool = True, base_url: str = "http://127.0.0.1:8000") -> DesktopApiSettings:
    return DesktopApiSettings(enabled=enabled, base_url=base_url, connect_timeout=3.0, read_timeout=10.0)


class _FakeStore:
    def __init__(self, settings: DesktopApiSettings):
        self._settings = settings

    def load_settings(self) -> DesktopApiSettings:
        return self._settings


def _client_factory_for(handler):
    transport = httpx.MockTransport(handler)

    def factory(settings):
        return DesktopApiClient(settings, transport=transport)

    return factory


class _FakeInstallationIdentity:
    installation_id = "fake-installation-id"
    machine_name = "fake-machine"
    os_version = "fake-os"


def _fake_identity_provider() -> _FakeInstallationIdentity:
    return _FakeInstallationIdentity()


def _manifest_payload(version: str = "2.6.0", **overrides) -> dict:
    base = {
        "manifest_schema_version": 1, "release_version": version, "channel": "production",
        "published_at": "2026-08-11T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
        "artifact": {"filename": f"Setup-{version}.exe", "size_bytes": 123, "sha256": "a" * 64, "content_type": "application/octet-stream"},
        "release_notes": "notas",
    }
    base.update(overrides)
    return base


class CheckForUpdatesTests(unittest.TestCase):
    def test_disabled_integration_returns_no_update_without_network_call(self):
        called = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["count"] += 1
            return httpx.Response(200, json={})

        result = udc.check_for_updates(
            current_version="2.5.2",
            identity_provider=_fake_identity_provider,
            config_store_factory=lambda: _FakeStore(_settings(enabled=False)),
            client_factory=_client_factory_for(handler),
        )
        self.assertFalse(result["update_available"])
        self.assertEqual(called["count"], 0)
        self.assertNotIn("error", result)

    def test_no_release_authorized_returns_no_update(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"available": False}, headers={"content-type": "application/json"})

        result = udc.check_for_updates(
            current_version="2.5.2",
            identity_provider=_fake_identity_provider,
            config_store_factory=lambda: _FakeStore(_settings()),
            client_factory=_client_factory_for(handler),
        )
        self.assertFalse(result["update_available"])
        self.assertEqual(result["assets"], [])

    def test_authorized_newer_release_reports_update_available_with_absolute_download_url(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/updates/desktop":
                return httpx.Response(200, json={
                    "available": True, "version": "2.6.0", "release_state": "AUTHORIZED",
                    "manifest_url": "/api/v1/updates/desktop/2.6.0/manifest?grant=abc",
                    "package_url": "/api/v1/updates/desktop/2.6.0/package?grant=abc",
                }, headers={"content-type": "application/json"})
            return httpx.Response(200, json=_manifest_payload(), headers={"content-type": "application/json"})

        result = udc.check_for_updates(
            current_version="2.5.2",
            identity_provider=_fake_identity_provider,
            config_store_factory=lambda: _FakeStore(_settings(base_url="http://127.0.0.1:9000")),
            client_factory=_client_factory_for(handler),
        )
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest_version"], "2.6.0")
        self.assertEqual(result["sha256"], "a" * 64)
        self.assertEqual(len(result["assets"]), 1)
        self.assertEqual(result["assets"][0]["browser_download_url"], "http://127.0.0.1:9000/api/v1/updates/desktop/2.6.0/package?grant=abc")
        self.assertEqual(result["assets"][0]["name"], "Setup-2.6.0.exe")

    def test_authorized_release_not_newer_than_current_reports_no_update(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/updates/desktop":
                return httpx.Response(200, json={
                    "available": True, "version": "2.5.2", "release_state": "AUTHORIZED",
                    "manifest_url": "/api/v1/updates/desktop/2.5.2/manifest?grant=abc",
                    "package_url": "/api/v1/updates/desktop/2.5.2/package?grant=abc",
                }, headers={"content-type": "application/json"})
            return httpx.Response(200, json=_manifest_payload("2.5.2"), headers={"content-type": "application/json"})

        result = udc.check_for_updates(
            current_version="2.5.2",
            identity_provider=_fake_identity_provider,
            config_store_factory=lambda: _FakeStore(_settings()),
            client_factory=_client_factory_for(handler),
        )
        self.assertFalse(result["update_available"])

    def test_server_connection_failure_is_reported_gracefully_without_raising(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusado")

        result = udc.check_for_updates(
            current_version="2.5.2",
            identity_provider=_fake_identity_provider,
            config_store_factory=lambda: _FakeStore(_settings()),
            client_factory=_client_factory_for(handler),
        )
        self.assertFalse(result["update_available"])
        self.assertIn("error", result)
        self.assertIn("user_message", result)

    def test_manifest_fetch_failure_is_reported_gracefully(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/updates/desktop":
                return httpx.Response(200, json={
                    "available": True, "version": "2.6.0", "release_state": "AUTHORIZED",
                    "manifest_url": "/api/v1/updates/desktop/2.6.0/manifest?grant=abc",
                    "package_url": "/api/v1/updates/desktop/2.6.0/package?grant=abc",
                }, headers={"content-type": "application/json"})
            return httpx.Response(404, json={"error": {"code": "UPDATE_RELEASE_NOT_AUTHORIZED", "message": "nao encontrada"}}, headers={"content-type": "application/json"})

        result = udc.check_for_updates(
            current_version="2.5.2",
            identity_provider=_fake_identity_provider,
            config_store_factory=lambda: _FakeStore(_settings()),
            client_factory=_client_factory_for(handler),
        )
        self.assertFalse(result["update_available"])
        self.assertIn("error", result)

    def test_sends_persistent_installation_id_in_discovery_query(self):
        seen_paths = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(str(request.url))
            return httpx.Response(200, json={"available": False}, headers={"content-type": "application/json"})

        udc.check_for_updates(
            current_version="2.5.2",
            identity_provider=_fake_identity_provider,
            config_store_factory=lambda: _FakeStore(_settings()),
            client_factory=_client_factory_for(handler),
        )
        self.assertTrue(any("installation_id=fake-installation-id" in path for path in seen_paths))

    def test_identity_resolution_failure_never_blocks_discovery(self):
        def _failing_provider():
            raise RuntimeError("disco indisponivel")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"available": False}, headers={"content-type": "application/json"})

        result = udc.check_for_updates(
            current_version="2.5.2",
            identity_provider=_failing_provider,
            config_store_factory=lambda: _FakeStore(_settings()),
            client_factory=_client_factory_for(handler),
        )
        self.assertFalse(result["update_available"])
        self.assertNotIn("error", result)

    def test_never_contacts_github(self):
        seen_hosts = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_hosts.append(request.url.host)
            return httpx.Response(200, json={"available": False}, headers={"content-type": "application/json"})

        udc.check_for_updates(
            current_version="2.5.2",
            identity_provider=_fake_identity_provider,
            config_store_factory=lambda: _FakeStore(_settings()),
            client_factory=_client_factory_for(handler),
        )
        self.assertTrue(all("github" not in host for host in seen_hosts))


class DiagnosticProbeUrlTests(unittest.TestCase):
    def test_returns_none_when_integration_disabled(self):
        self.assertIsNone(udc.diagnostic_probe_url(config_store_factory=lambda: _FakeStore(_settings(enabled=False))))

    def test_returns_server_health_url_when_enabled(self):
        url = udc.diagnostic_probe_url(config_store_factory=lambda: _FakeStore(_settings(base_url="http://127.0.0.1:8000")))
        self.assertEqual(url, "http://127.0.0.1:8000/api/v1/system/health")
        self.assertNotIn("github", url)


if __name__ == "__main__":
    unittest.main()
