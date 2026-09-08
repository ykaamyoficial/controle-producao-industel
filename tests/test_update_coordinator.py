from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiSettings
from app.services.update_coordinator import UpdateCoordinator
from app.updater.manifest_gate import ManifestGateError
from app.updater.manifest_provider import ManifestFetchError


def _settings(*, enabled: bool = True, base_url: str = "http://127.0.0.1:8000") -> DesktopApiSettings:
    return DesktopApiSettings(enabled=enabled, base_url=base_url, connect_timeout=3.0, read_timeout=10.0)


class _FakeStore:
    def __init__(self, settings: DesktopApiSettings):
        self._settings = settings

    def load_settings(self) -> DesktopApiSettings:
        return self._settings


class UpdateCoordinatorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._app_data_patch = patch("app.updater.paths.get_app_data_dir", return_value=self.tmp / "appdata")
        self._app_data_patch.start()
        self.addCleanup(self._app_data_patch.stop)

        self.package = self.tmp / "Setup-2.6.0.exe"
        self.package.write_bytes(b"novo-binario-real" * 2000)
        self.manifest_dict = {
            "manifest_schema_version": 1, "release_version": "2.6.0", "channel": "production",
            "published_at": "2026-08-11T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
            "artifact": {
                "filename": self.package.name, "size_bytes": self.package.stat().st_size,
                "sha256": hashlib.sha256(self.package.read_bytes()).hexdigest(), "content_type": "application/octet-stream",
            },
        }

    def _fake_manifest_provider(self, *, tampered: bool = False):
        manifest_dict = dict(self.manifest_dict)
        if tampered:
            manifest_dict = dict(manifest_dict)
            manifest_dict["artifact"] = dict(manifest_dict["artifact"])
            manifest_dict["artifact"]["sha256"] = "f" * 64

        class FakeManifestProvider:
            def __init__(self, url):
                self.url = url

            def fetch(self):
                return manifest_dict

        return FakeManifestProvider

    def _fake_downloader(self, source, destination_dir, *, expected_size=None):
        destination_dir.mkdir(parents=True, exist_ok=True)
        dest = destination_dir / self.package.name
        dest.write_bytes(self.package.read_bytes())
        return dest

    def _coordinator(self, **overrides) -> UpdateCoordinator:
        defaults = dict(
            config_store_factory=lambda: _FakeStore(_settings()),
            manifest_provider_factory=self._fake_manifest_provider(),
            downloader=self._fake_downloader,
            process_launcher=lambda executable_path, args=None, cwd=None: 4242,
            install_dir=str(self.tmp / "install"),
            executable_path=str(self.tmp / "install" / "ControleProducao.exe"),
        )
        defaults.update(overrides)
        return UpdateCoordinator(**defaults)


class StartUpdateTests(UpdateCoordinatorTestCase):
    def test_valid_manifest_and_package_launches_updater(self):
        launched = {}

        def launcher(executable_path, args=None, cwd=None):
            launched["executable_path"] = executable_path
            launched["args"] = args
            return 4242

        coordinator = self._coordinator(process_launcher=launcher)
        result = coordinator.start_update(manifest_url="/api/v1/updates/desktop/2.6.0/manifest?grant=abc", package_url="/api/v1/updates/desktop/2.6.0/package?grant=abc")

        self.assertTrue(result.launched)
        self.assertEqual(result.target_version, "2.6.0")
        self.assertEqual(result.updater_pid, 4242)
        self.assertIsNone(result.error_message)
        self.assertIn("--request", launched["args"])

    def test_manifest_fetch_failure_never_launches_updater(self):
        class FailingProvider:
            def __init__(self, url):
                pass

            def fetch(self):
                raise ManifestFetchError("falha de rede")

        launched = {"called": False}
        coordinator = self._coordinator(manifest_provider_factory=FailingProvider, process_launcher=lambda *a, **k: launched.__setitem__("called", True) or 1)
        result = coordinator.start_update(manifest_url="/x/manifest", package_url="/x/package")

        self.assertFalse(result.launched)
        self.assertIsNotNone(result.error_message)
        self.assertFalse(launched["called"])

    def test_tampered_artifact_never_launches_updater(self):
        launched = {"called": False}
        coordinator = self._coordinator(
            manifest_provider_factory=self._fake_manifest_provider(tampered=True),
            process_launcher=lambda *a, **k: launched.__setitem__("called", True) or 1,
        )
        result = coordinator.start_update(manifest_url="/x/manifest", package_url="/x/package")

        self.assertFalse(result.launched)
        self.assertIn("reprovado", result.error_message.lower())
        self.assertFalse(launched["called"])

    def test_launcher_failure_is_reported_without_raising(self):
        def failing_launcher(executable_path, args=None, cwd=None):
            raise OSError("nao foi possivel iniciar o processo")

        coordinator = self._coordinator(process_launcher=failing_launcher)
        result = coordinator.start_update(manifest_url="/x/manifest", package_url="/x/package")

        self.assertFalse(result.launched)
        self.assertIn("Updater", result.error_message)

    def test_updater_launch_command_uses_python_module_invocation_when_not_packaged(self):
        launched = {}

        def launcher(executable_path, args=None, cwd=None):
            launched["executable_path"] = str(executable_path)
            launched["args"] = args
            return 1

        coordinator = self._coordinator(process_launcher=launcher)
        coordinator.start_update(manifest_url="/x/manifest", package_url="/x/package")

        self.assertIn("python", launched["executable_path"].lower())
        self.assertEqual(launched["args"][0], "-m")
        self.assertEqual(launched["args"][1], "app.updater")

    def test_request_json_carries_hash_and_size_from_manifest_not_guessed(self):
        import json

        coordinator = self._coordinator()
        result = coordinator.start_update(manifest_url="/x/manifest", package_url="/x/package")

        request_path = (self.tmp / "appdata" / "updater" / "manifest" / f"{result.request_id}-request.json")
        data = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(data["package_expected_hash"], self.manifest_dict["artifact"]["sha256"])
        self.assertEqual(data["package_expected_size"], self.manifest_dict["artifact"]["size_bytes"])
        self.assertEqual(data["target_version"], "2.6.0")


class StartRequiredUpdateTests(UpdateCoordinatorTestCase):
    def _discovery_handler(self, *, version="2.6.0"):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/updates/desktop":
                return httpx.Response(200, json={
                    "available": True, "version": version, "release_state": "AUTHORIZED",
                    "manifest_url": "/api/v1/updates/desktop/2.6.0/manifest?grant=abc",
                    "package_url": "/api/v1/updates/desktop/2.6.0/package?grant=abc",
                }, headers={"content-type": "application/json"})
            return httpx.Response(404)

        return handler

    def _client_factory(self, handler):
        transport = httpx.MockTransport(handler)

        def factory(settings):
            return DesktopApiClient(settings, transport=transport)

        return factory

    def test_discovers_and_launches_when_version_matches_expectation(self):
        coordinator = self._coordinator(client_factory=self._client_factory(self._discovery_handler()))
        result = coordinator.start_required_update(expected_version="2.6.0")
        self.assertTrue(result.launched)
        self.assertEqual(result.target_version, "2.6.0")

    def test_no_expected_version_still_works(self):
        coordinator = self._coordinator(client_factory=self._client_factory(self._discovery_handler()))
        result = coordinator.start_required_update()
        self.assertTrue(result.launched)

    def test_version_mismatch_is_rejected_before_any_download(self):
        coordinator = self._coordinator(client_factory=self._client_factory(self._discovery_handler(version="9.9.9")))
        result = coordinator.start_required_update(expected_version="2.6.0")
        self.assertFalse(result.launched)
        self.assertIn("mudou", result.error_message.lower())

    def test_nothing_available_is_reported_clearly(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"available": False}, headers={"content-type": "application/json"})

        coordinator = self._coordinator(client_factory=self._client_factory(handler))
        result = coordinator.start_required_update()
        self.assertFalse(result.launched)
        self.assertIsNotNone(result.error_message)

    def test_disabled_integration_never_attempts_a_network_call(self):
        called = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["count"] += 1
            return httpx.Response(200, json={"available": False})

        coordinator = self._coordinator(
            config_store_factory=lambda: _FakeStore(_settings(enabled=False)),
            client_factory=self._client_factory(handler),
        )
        result = coordinator.start_required_update()
        self.assertFalse(result.launched)
        self.assertEqual(called["count"], 0)


if __name__ == "__main__":
    unittest.main()
