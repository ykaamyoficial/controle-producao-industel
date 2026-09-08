from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from api.app.core.config import get_settings
from api.app.core.versioning import CompatibilityPolicy, CompatibilityStatus, EnforcementMode
from api.app.updates import service
from api.app.updates.policy import DEFAULT_POLICY, DesktopUpdatePolicyRecord, evaluate_for_desktop, resolve_effective_policy


def _policy() -> CompatibilityPolicy:
    return CompatibilityPolicy(
        minimum_desktop_version="3.1.0", recommended_desktop_version="3.2.0",
        server_version="3.2.0", api_contract_version="v1", database_schema_version="rev1",
    )


def _record(**overrides) -> DesktopUpdatePolicyRecord:
    base = dict(enforcement=EnforcementMode.NONE, authorized_release_version=None, grace_until=None, message="", policy_revision=1, updated_at=None)
    base.update(overrides)
    return DesktopUpdatePolicyRecord(**base)


class ResolveEffectivePolicyTests(unittest.TestCase):
    """Filesystem-only: resolve_effective_policy so consulta o repositorio de
    releases da Fase 12 (ReleaseStateStore), sem tocar em banco de dados."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._previous_repo_dir = os.environ.get("UPDATE_REPOSITORY_DIR")
        os.environ["UPDATE_REPOSITORY_DIR"] = str(self.tmp / "repo")
        get_settings.cache_clear()

    def tearDown(self):
        if self._previous_repo_dir is None:
            os.environ.pop("UPDATE_REPOSITORY_DIR", None)
        else:
            os.environ["UPDATE_REPOSITORY_DIR"] = self._previous_repo_dir
        get_settings.cache_clear()

    def _publish_authorized(self, version: str = "3.2.0") -> None:
        package = self.tmp / f"pkg-{version}.exe"
        package.write_bytes(b"conteudo" * 1000)
        manifest_data = {
            "manifest_schema_version": 1, "release_version": version, "channel": "production",
            "published_at": "2026-08-11T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
            "artifact": {"filename": package.name, "size_bytes": package.stat().st_size, "sha256": hashlib.sha256(package.read_bytes()).hexdigest()},
        }
        manifest_path = self.tmp / f"manifest-{version}.json"
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
        service.sync_release(manifest_path=manifest_path, package_path=package)
        service.authorize_release(version)

    def test_no_authorized_release_configured_passes_through_unchanged(self):
        record = _record(enforcement=EnforcementMode.OPTIONAL, authorized_release_version=None)
        effective = resolve_effective_policy(record)
        self.assertEqual(effective.enforcement, EnforcementMode.OPTIONAL)
        self.assertIsNone(effective.authorized_update_version)

    def test_authorized_release_passes_through(self):
        self._publish_authorized("3.2.0")
        record = _record(enforcement=EnforcementMode.REQUIRED, authorized_release_version="3.2.0")
        effective = resolve_effective_policy(record)
        self.assertEqual(effective.enforcement, EnforcementMode.REQUIRED)
        self.assertEqual(effective.authorized_update_version, "3.2.0")

    def test_nonexistent_release_degrades_required_to_recommended(self):
        record = _record(enforcement=EnforcementMode.REQUIRED, authorized_release_version="9.9.9")
        effective = resolve_effective_policy(record)
        self.assertEqual(effective.enforcement, EnforcementMode.RECOMMENDED)
        self.assertIsNone(effective.authorized_update_version)

    def test_revoked_release_degrades_required_to_recommended(self):
        self._publish_authorized("3.2.0")
        service.revoke_release("3.2.0", reason="teste")
        record = _record(enforcement=EnforcementMode.REQUIRED, authorized_release_version="3.2.0")
        effective = resolve_effective_policy(record)
        self.assertEqual(effective.enforcement, EnforcementMode.RECOMMENDED)
        self.assertIsNone(effective.authorized_update_version)

    def test_ready_but_not_authorized_release_is_never_used(self):
        manifest_path, package_path = self._write_ready_only()
        record = _record(enforcement=EnforcementMode.REQUIRED, authorized_release_version="3.2.0")
        effective = resolve_effective_policy(record)
        self.assertIsNone(effective.authorized_update_version)
        self.assertEqual(effective.enforcement, EnforcementMode.RECOMMENDED)

    def _write_ready_only(self):
        package = self.tmp / "pkg-3.2.0.exe"
        package.write_bytes(b"conteudo" * 1000)
        manifest_data = {
            "manifest_schema_version": 1, "release_version": "3.2.0", "channel": "production",
            "published_at": "2026-08-11T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
            "artifact": {"filename": package.name, "size_bytes": package.stat().st_size, "sha256": hashlib.sha256(package.read_bytes()).hexdigest()},
        }
        manifest_path = self.tmp / "manifest-3.2.0.json"
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
        service.sync_release(manifest_path=manifest_path, package_path=package)  # READY, nao autorizado
        return manifest_path, package

    def test_degraded_enforcement_never_exceeds_required(self):
        # se enforcement ja era menor que REQUIRED (ex.: OPTIONAL) apontando pra uma
        # versao invalida, a degradacao nao "promove" para RECOMMENDED -- so limita.
        record = _record(enforcement=EnforcementMode.OPTIONAL, authorized_release_version="9.9.9")
        effective = resolve_effective_policy(record)
        self.assertEqual(effective.enforcement, EnforcementMode.OPTIONAL)
        self.assertIsNone(effective.authorized_update_version)


class EvaluateForDesktopTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["UPDATE_REPOSITORY_DIR"] = str(Path(self._tmp.name) / "repo")
        get_settings.cache_clear()

    def tearDown(self):
        os.environ.pop("UPDATE_REPOSITORY_DIR", None)
        get_settings.cache_clear()

    def test_combines_effective_policy_and_version_math(self):
        record = _record(enforcement=EnforcementMode.RECOMMENDED, policy_revision=7)
        evaluation = evaluate_for_desktop("3.1.5", _policy(), record)
        self.assertEqual(evaluation.desktop_state, CompatibilityStatus.UPDATE_RECOMMENDED)
        self.assertEqual(evaluation.policy_revision, 7)

    def test_default_policy_never_blocks_a_compatible_version(self):
        evaluation = evaluate_for_desktop("3.2.0", _policy(), DEFAULT_POLICY)
        self.assertEqual(evaluation.desktop_state, CompatibilityStatus.COMPATIBLE)
        self.assertEqual(evaluation.enforcement, EnforcementMode.NONE)


class DesktopUpdatePolicyRecordSerializationTests(unittest.TestCase):
    def test_round_trips_through_dict(self):
        grace = datetime.now(UTC) + timedelta(hours=2)
        record = _record(enforcement=EnforcementMode.REQUIRED, authorized_release_version="3.2.0", grace_until=grace, message="Atualize agora", policy_revision=9, updated_at=datetime.now(UTC))
        restored = DesktopUpdatePolicyRecord.from_stored(record.to_dict())
        self.assertEqual(restored.enforcement, EnforcementMode.REQUIRED)
        self.assertEqual(restored.authorized_release_version, "3.2.0")
        self.assertEqual(restored.policy_revision, 9)
        self.assertEqual(restored.message, "Atualize agora")

    def test_missing_optional_fields_default_safely(self):
        restored = DesktopUpdatePolicyRecord.from_stored({})
        self.assertEqual(restored.enforcement, EnforcementMode.NONE)
        self.assertIsNone(restored.authorized_release_version)
        self.assertIsNone(restored.grace_until)


if __name__ == "__main__":
    unittest.main()
