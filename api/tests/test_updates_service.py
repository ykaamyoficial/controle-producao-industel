from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from api.app.core.config import get_settings
from api.app.updates import service
from api.app.updates.exceptions import (
    ReleaseImmutableError,
    ReleaseInvalidStateError,
    ReleaseNotAuthorizedError,
    ReleaseNotFoundError,
    ReleaseValidationError,
)
from api.app.updates.models import ReleaseState


def _write_manifest_and_package(tmp: Path, *, version: str = "2.6.0", size_mismatch: bool = False, hash_mismatch: bool = False, minimum_server_version: str = "0.8.0", api_contract_version: str = "v1") -> tuple[Path, Path]:
    package = tmp / f"pkg-{version}.exe"
    package.write_bytes(b"conteudo-real-do-instalador" * 1000)
    real_size = package.stat().st_size
    real_sha256 = hashlib.sha256(package.read_bytes()).hexdigest()

    manifest_data = {
        "manifest_schema_version": 1,
        "release_version": version,
        "channel": "production",
        "published_at": "2026-08-11T12:00:00Z",
        "minimum_server_version": minimum_server_version,
        "api_contract_version": api_contract_version,
        "artifact": {
            "filename": package.name,
            "size_bytes": real_size + 1000 if size_mismatch else real_size,
            "sha256": ("f" * 64) if hash_mismatch else real_sha256,
            "content_type": "application/octet-stream",
        },
    }
    manifest_path = tmp / f"manifest-{version}.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    return manifest_path, package


class UpdatesServiceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._previous_repo_dir = os.environ.get("UPDATE_REPOSITORY_DIR")
        self._previous_secret = os.environ.get("SECRET_KEY")
        os.environ["UPDATE_REPOSITORY_DIR"] = str(self.tmp / "repo")
        os.environ["SECRET_KEY"] = "local-test-only-secret-key-32-characters-min"
        get_settings.cache_clear()

    def tearDown(self):
        for key, value in (("UPDATE_REPOSITORY_DIR", self._previous_repo_dir), ("SECRET_KEY", self._previous_secret)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


class SyncReleaseTests(UpdatesServiceTestCase):
    def test_valid_release_moves_from_staging_to_ready(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        record = service.sync_release(manifest_path=manifest_path, package_path=package_path)
        self.assertEqual(record.state, ReleaseState.READY)
        self.assertTrue((service.paths.ready_version_dir("2.6.0") / "manifest.json").is_file())
        self.assertTrue((service.paths.ready_version_dir("2.6.0") / package_path.name).is_file())

    def test_size_mismatch_never_authorized_ends_failed(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, size_mismatch=True)
        with self.assertRaises(ReleaseValidationError):
            service.sync_release(manifest_path=manifest_path, package_path=package_path)
        record = service._state_store().load("2.6.0")
        self.assertEqual(record.state, ReleaseState.FAILED)
        self.assertFalse(service.paths.ready_version_dir("2.6.0").exists())

    def test_hash_mismatch_never_authorized_ends_failed(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, hash_mismatch=True)
        with self.assertRaises(ReleaseValidationError):
            service.sync_release(manifest_path=manifest_path, package_path=package_path)
        record = service._state_store().load("2.6.0")
        self.assertEqual(record.state, ReleaseState.FAILED)

    def test_missing_manifest_source_raises_before_touching_repository(self):
        _, package_path = _write_manifest_and_package(self.tmp)
        with self.assertRaises(ReleaseValidationError):
            service.sync_release(manifest_path=self.tmp / "nope.json", package_path=package_path)
        self.assertEqual(service.list_releases(), [])

    def test_missing_package_source_raises(self):
        manifest_path, _ = _write_manifest_and_package(self.tmp)
        with self.assertRaises(ReleaseValidationError):
            service.sync_release(manifest_path=manifest_path, package_path=self.tmp / "nope.exe")

    def test_invalid_manifest_schema_raises(self):
        bad_manifest = self.tmp / "bad.json"
        bad_manifest.write_text('{"manifest_schema_version": 99}', encoding="utf-8")
        _, package_path = _write_manifest_and_package(self.tmp)
        with self.assertRaises(ReleaseValidationError):
            service.sync_release(manifest_path=bad_manifest, package_path=package_path)

    def test_resync_same_version_different_hash_is_immutable_violation(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)

        other_package = self.tmp / "different.exe"
        other_package.write_bytes(b"outro-conteudo-completamente-diferente" * 500)
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_data["artifact"]["filename"] = other_package.name
        manifest_data["artifact"]["size_bytes"] = other_package.stat().st_size
        manifest_data["artifact"]["sha256"] = hashlib.sha256(other_package.read_bytes()).hexdigest()
        other_manifest = self.tmp / "other_manifest.json"
        other_manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

        with self.assertRaises(ReleaseImmutableError):
            service.sync_release(manifest_path=other_manifest, package_path=other_package)

    def test_resync_same_version_same_hash_is_idempotent_noop(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        first = service.sync_release(manifest_path=manifest_path, package_path=package_path)
        second = service.sync_release(manifest_path=manifest_path, package_path=package_path)
        self.assertEqual(first.artifact.sha256, second.artifact.sha256)
        self.assertEqual(second.state, ReleaseState.READY)

    def test_resync_after_revoke_is_rejected(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        service.authorize_release("2.6.0")
        service.revoke_release("2.6.0", reason="teste")
        with self.assertRaises(ReleaseInvalidStateError):
            service.sync_release(manifest_path=manifest_path, package_path=package_path)

    def test_incompatible_api_contract_still_reaches_ready_not_blocked_at_sync(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, api_contract_version="v99-nao-existe")
        record = service.sync_release(manifest_path=manifest_path, package_path=package_path)
        self.assertEqual(record.state, ReleaseState.READY)


class AuthorizeReleaseTests(UpdatesServiceTestCase):
    def test_authorize_ready_release_succeeds(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        record = service.authorize_release("2.6.0")
        self.assertEqual(record.state, ReleaseState.AUTHORIZED)
        self.assertIsNotNone(record.authorized_at)

    def test_authorize_is_idempotent(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        service.authorize_release("2.6.0")
        record = service.authorize_release("2.6.0")
        self.assertEqual(record.state, ReleaseState.AUTHORIZED)

    def test_authorize_missing_version_raises_not_found(self):
        with self.assertRaises(ReleaseNotFoundError):
            service.authorize_release("9.9.9")

    def test_authorize_incompatible_api_contract_is_refused(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, api_contract_version="v99-nao-existe")
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        with self.assertRaises(ReleaseValidationError):
            service.authorize_release("2.6.0")

    def test_authorize_server_below_minimum_is_refused(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, minimum_server_version="999.0.0")
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        with self.assertRaises(ReleaseValidationError):
            service.authorize_release("2.6.0")

    def test_authorize_failed_release_is_rejected(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, hash_mismatch=True)
        with self.assertRaises(ReleaseValidationError):
            service.sync_release(manifest_path=manifest_path, package_path=package_path)
        with self.assertRaises(ReleaseInvalidStateError):
            service.authorize_release("2.6.0")


class RevokeReleaseTests(UpdatesServiceTestCase):
    def test_revoke_authorized_release_succeeds(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        service.authorize_release("2.6.0")
        record = service.revoke_release("2.6.0", reason="bug critico")
        self.assertEqual(record.state, ReleaseState.REVOKED)
        self.assertEqual(record.revoked_reason, "bug critico")

    def test_revoke_is_idempotent(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        service.authorize_release("2.6.0")
        service.revoke_release("2.6.0", reason="motivo 1")
        record = service.revoke_release("2.6.0", reason="motivo 2")
        self.assertEqual(record.state, ReleaseState.REVOKED)

    def test_revoke_ready_release_is_rejected(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        with self.assertRaises(ReleaseInvalidStateError):
            service.revoke_release("2.6.0", reason="teste")

    def test_revoke_missing_version_raises_not_found(self):
        with self.assertRaises(ReleaseNotFoundError):
            service.revoke_release("9.9.9", reason="teste")

    def test_revoked_release_files_stay_on_disk_for_diagnostics(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        service.authorize_release("2.6.0")
        service.revoke_release("2.6.0", reason="teste")
        self.assertTrue(service.paths.ready_version_dir("2.6.0").exists())


class DiscoveryAndServingTests(UpdatesServiceTestCase):
    def test_discovery_reports_unavailable_when_nothing_authorized(self):
        self.assertEqual(service.get_discovery_info(), {"available": False})

    def test_discovery_reports_ready_but_not_authorized_release_as_unavailable(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        self.assertEqual(service.get_discovery_info(), {"available": False})

    def test_discovery_reports_authorized_release_with_grant_urls(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        service.authorize_release("2.6.0")
        info = service.get_discovery_info()
        self.assertTrue(info["available"])
        self.assertEqual(info["version"], "2.6.0")
        self.assertIn("grant=", info["manifest_url"])
        self.assertIn("grant=", info["package_url"])

    def test_discovery_picks_highest_semver_among_multiple_authorized(self):
        for version in ("2.6.0", "2.7.0", "2.6.5"):
            manifest_path, package_path = _write_manifest_and_package(self.tmp, version=version)
            service.sync_release(manifest_path=manifest_path, package_path=package_path)
            service.authorize_release(version)
        info = service.get_discovery_info()
        self.assertEqual(info["version"], "2.7.0")

    def test_get_manifest_bytes_returns_persisted_content_only_when_authorized(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        with self.assertRaises(ReleaseNotAuthorizedError):
            service.get_manifest_bytes("2.6.0")
        service.authorize_release("2.6.0")
        payload = json.loads(service.get_manifest_bytes("2.6.0"))
        self.assertEqual(payload["release_version"], "2.6.0")

    def test_get_manifest_bytes_unknown_version_raises_not_authorized(self):
        with self.assertRaises(ReleaseNotAuthorizedError):
            service.get_manifest_bytes("9.9.9")

    def test_resolve_package_for_download_only_when_authorized(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        with self.assertRaises(ReleaseNotAuthorizedError):
            service.resolve_package_for_download("2.6.0")
        service.authorize_release("2.6.0")
        resolved_path, record = service.resolve_package_for_download("2.6.0")
        self.assertTrue(resolved_path.is_file())
        self.assertEqual(record.state, ReleaseState.AUTHORIZED)

    def test_revoked_release_is_never_served(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        service.authorize_release("2.6.0")
        service.revoke_release("2.6.0", reason="teste")
        with self.assertRaises(ReleaseNotAuthorizedError):
            service.resolve_package_for_download("2.6.0")
        with self.assertRaises(ReleaseNotAuthorizedError):
            service.get_manifest_bytes("2.6.0")
        self.assertEqual(service.get_discovery_info(), {"available": False})


class RecoverIncompleteStagingTests(UpdatesServiceTestCase):
    def test_removes_leftover_staging_directories(self):
        service.paths.ensure_repository_dirs()
        stale = service.paths.staging_dir() / "2.6.0-leftover"
        stale.mkdir(parents=True)
        (stale / "partial.exe").write_bytes(b"x")
        removed = service.recover_incomplete_staging()
        self.assertIn("2.6.0-leftover", removed)
        self.assertFalse(stale.exists())

    def test_noop_when_staging_is_clean(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        self.assertEqual(service.recover_incomplete_staging(), [])


if __name__ == "__main__":
    unittest.main()
