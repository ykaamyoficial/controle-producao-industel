from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.app.channels.exceptions import (
    ArtifactMismatchError,
    ConcurrentPromotionOperationError,
    InvalidPromotionTransitionError,
    PilotGatesNotMetError,
    ReleaseNotEligibleError,
)
from api.app.channels.gates import evaluate_pilot_gates
from api.app.channels.models import Channel, PilotGates, PromotionStatus, ReportSignal
from api.app.channels.service import build_default_service, is_version_eligible_for_channel
from api.app.core.config import get_settings
from api.app.updates import service as updates_service
from api.app.updates.exceptions import ReleaseNotFoundError
from api.app.updates.models import ReleaseState

ACTOR = "release.admin"


def _write_manifest_and_package(tmp: Path, *, version: str = "3.3.0") -> tuple[Path, Path]:
    package = tmp / f"pkg-{version}.exe"
    package.write_bytes(b"conteudo-real-do-instalador" * 1000)
    manifest_data = {
        "manifest_schema_version": 1, "release_version": version, "channel": "production",
        "published_at": "2026-08-12T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
        "artifact": {
            "filename": package.name, "size_bytes": package.stat().st_size,
            "sha256": hashlib.sha256(package.read_bytes()).hexdigest(), "content_type": "application/octet-stream",
        },
    }
    manifest_path = tmp / f"manifest-{version}.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    return manifest_path, package


class ChannelServiceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._previous_repo_dir = os.environ.get("UPDATE_REPOSITORY_DIR")
        self._previous_secret = os.environ.get("SECRET_KEY")
        os.environ["UPDATE_REPOSITORY_DIR"] = str(self.tmp / "repo")
        os.environ["SECRET_KEY"] = "local-test-only-secret-key-32-characters-min"
        get_settings.cache_clear()
        self.service = build_default_service()

    def tearDown(self):
        for key, value in (("UPDATE_REPOSITORY_DIR", self._previous_repo_dir), ("SECRET_KEY", self._previous_secret)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    def _ready_release(self, version: str = "3.3.0"):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, version=version)
        return updates_service.sync_release(manifest_path=manifest_path, package_path=package_path)


class AuthorizePilotTests(ChannelServiceTestCase):
    def test_authorize_pilot_from_ready_release_promotes_fase12_state_too(self):
        self._ready_release()
        state = self.service.authorize_pilot("3.3.0", actor=ACTOR)
        self.assertEqual(state.status, PromotionStatus.PILOT_AUTHORIZED)
        self.assertEqual(state.channel, Channel.PILOT)
        release = updates_service.get_release("3.3.0")
        self.assertEqual(release.state, ReleaseState.AUTHORIZED)

    def test_authorize_pilot_snapshots_current_hashes(self):
        self._ready_release()
        release = updates_service.authorize_release("3.3.0")
        state = self.service.authorize_pilot("3.3.0", actor=ACTOR)
        self.assertEqual(state.artifact_sha256, release.artifact.sha256)
        self.assertTrue(state.manifest_sha256)

    def test_authorize_pilot_for_nonexistent_release_is_rejected(self):
        with self.assertRaises(ReleaseNotEligibleError):
            self.service.authorize_pilot("9.9.9", actor=ACTOR)

    def test_authorize_pilot_twice_is_idempotent(self):
        self._ready_release()
        first = self.service.authorize_pilot("3.3.0", actor=ACTOR)
        second = self.service.authorize_pilot("3.3.0", actor=ACTOR)
        self.assertEqual(first, second)

    def test_authorize_pilot_after_pilot_paused_is_rejected(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        self.service.pause_pilot("3.3.0", actor=ACTOR)
        with self.assertRaises(InvalidPromotionTransitionError):
            self.service.authorize_pilot("3.3.0", actor=ACTOR)


class PauseResumeFailTests(ChannelServiceTestCase):
    def test_pause_then_resume_returns_to_pilot_authorized(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        paused = self.service.pause_pilot("3.3.0", actor=ACTOR)
        self.assertEqual(paused.status, PromotionStatus.PILOT_PAUSED)
        resumed = self.service.resume_pilot("3.3.0", actor=ACTOR)
        self.assertEqual(resumed.status, PromotionStatus.PILOT_AUTHORIZED)

    def test_paused_pilot_is_not_eligible_for_pilot_channel(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        self.service.pause_pilot("3.3.0", actor=ACTOR)
        self.assertFalse(is_version_eligible_for_channel("3.3.0", Channel.PILOT, service=self.service))

    def test_fail_pilot_marks_failed(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        failed = self.service.fail_pilot("3.3.0", actor=ACTOR, note="crash no boot")
        self.assertEqual(failed.status, PromotionStatus.PILOT_FAILED)

    def test_failed_pilot_cannot_be_approved_or_promoted(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        self.service.fail_pilot("3.3.0", actor=ACTOR)
        with self.assertRaises(InvalidPromotionTransitionError):
            self.service.promote_to_production("3.3.0", actor=ACTOR)


class ApproveAndPromoteTests(ChannelServiceTestCase):
    def _approved_state(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        gates = PilotGates(min_pilot_clients_updated=1, observation_minutes=0)
        evaluation = evaluate_pilot_gates(
            gates=gates, pilot_client_count=1,
            reports=[ReportSignal(installation_id="pc-1", release_version="3.3.0", update_result="SUCCESS", app_start_result="SUCCESS", compatibility_result="OK")],
            pilot_authorized_at=datetime.now(timezone.utc) - timedelta(hours=1), now=datetime.now(timezone.utc),
        )
        return self.service.approve_pilot("3.3.0", actor=ACTOR, evaluation=evaluation)

    def test_approve_pilot_requires_eligible_evaluation(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        gates = PilotGates(min_pilot_clients_updated=5, observation_minutes=0)
        evaluation = evaluate_pilot_gates(
            gates=gates, pilot_client_count=1, reports=[],
            pilot_authorized_at=datetime.now(timezone.utc) - timedelta(hours=1), now=datetime.now(timezone.utc),
        )
        with self.assertRaises(PilotGatesNotMetError):
            self.service.approve_pilot("3.3.0", actor=ACTOR, evaluation=evaluation)

    def test_approved_pilot_can_be_promoted(self):
        self._approved_state()
        promoted = self.service.promote_to_production("3.3.0", actor=ACTOR)
        self.assertEqual(promoted.status, PromotionStatus.PRODUCTION_AUTHORIZED)
        self.assertEqual(promoted.channel, Channel.PRODUCTION)
        self.assertEqual(promoted.promoted_by, ACTOR)

    def test_promotion_never_changes_version_manifest_or_hash(self):
        approved = self._approved_state()
        promoted = self.service.promote_to_production("3.3.0", actor=ACTOR)
        self.assertEqual(promoted.version, approved.version)
        self.assertEqual(promoted.manifest_sha256, approved.manifest_sha256)
        self.assertEqual(promoted.artifact_sha256, approved.artifact_sha256)

    def test_promotion_rejects_when_artifact_hash_diverged(self):
        approved = self._approved_state()
        # Simula um artefato diferente publicado sob o mesmo numero de versao
        # (nunca deveria acontecer no fluxo normal -- Fase 12 e imutavel --
        # mas a promocao precisa recusar mesmo assim, Secao 4/12).
        tampered = approved.replace(artifact_sha256="f" * 64)
        self.service._store.save(tampered)
        with self.assertRaises(ArtifactMismatchError):
            self.service.promote_to_production("3.3.0", actor=ACTOR)

    def test_promoting_twice_is_idempotent(self):
        self._approved_state()
        first = self.service.promote_to_production("3.3.0", actor=ACTOR)
        second = self.service.promote_to_production("3.3.0", actor=ACTOR)
        self.assertEqual(first, second)

    def test_pilot_authorized_without_approval_cannot_be_promoted(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        with self.assertRaises(InvalidPromotionTransitionError):
            self.service.promote_to_production("3.3.0", actor=ACTOR)


class RevokeTests(ChannelServiceTestCase):
    def test_revoke_pilot_also_revokes_fase12_release(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        revoked = self.service.revoke("3.3.0", actor=ACTOR, reason="bug critico encontrado")
        self.assertEqual(revoked.status, PromotionStatus.REVOKED)
        release = updates_service.get_release("3.3.0")
        self.assertEqual(release.state, ReleaseState.REVOKED)

    def test_revoked_release_is_no_longer_eligible_for_any_channel(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        self.service.revoke("3.3.0", actor=ACTOR, reason="x")
        self.assertFalse(is_version_eligible_for_channel("3.3.0", Channel.PILOT, service=self.service))
        self.assertFalse(is_version_eligible_for_channel("3.3.0", Channel.PRODUCTION, service=self.service))

    def test_revoking_production_release_does_not_affect_a_different_version(self):
        self._ready_release(version="3.3.0")
        self._ready_release(version="3.4.0")
        self.service.authorize_pilot("3.4.0", actor=ACTOR)
        self.service.revoke("3.4.0", actor=ACTOR, reason="x")
        release_a = updates_service.get_release("3.3.0")
        self.assertEqual(release_a.state, ReleaseState.READY)


class DiscoveryResolutionTests(ChannelServiceTestCase):
    def test_ungated_authorized_release_visible_to_every_channel(self):
        # Release nunca entrou no pipeline de canal -- continua visivel a
        # todos, como antes da Fase 15 (compatibilidade com o fluxo direto
        # da Fase 12).
        self._ready_release()
        updates_service.authorize_release("3.3.0")
        for channel in Channel:
            with self.subTest(channel=channel):
                self.assertTrue(is_version_eligible_for_channel("3.3.0", channel, service=self.service))

    def test_pilot_only_release_not_eligible_for_production(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        self.assertFalse(is_version_eligible_for_channel("3.3.0", Channel.PRODUCTION, service=self.service))
        self.assertTrue(is_version_eligible_for_channel("3.3.0", Channel.PILOT, service=self.service))

    def test_resolve_discovery_state_picks_highest_eligible_version(self):
        self._ready_release(version="3.3.0")
        self._ready_release(version="3.4.0")
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        self.service.authorize_pilot("3.4.0", actor=ACTOR)
        resolved = self.service.resolve_discovery_state(Channel.PILOT)
        self.assertEqual(resolved.version, "3.4.0")


class ConcurrencyTests(ChannelServiceTestCase):
    def test_concurrent_promotion_operation_is_rejected_while_lock_held(self):
        self._ready_release()
        self.service.authorize_pilot("3.3.0", actor=ACTOR)
        lock_path = self.service._lock_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            '{"owner": "other-admin", "pid": 1, "hostname": "h", "acquired_at_utc": "'
            + datetime.now(timezone.utc).isoformat() + '"}',
            encoding="utf-8",
        )
        with self.assertRaises(ConcurrentPromotionOperationError):
            self.service.pause_pilot("3.3.0", actor=ACTOR)


if __name__ == "__main__":
    unittest.main()
