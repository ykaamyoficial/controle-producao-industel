from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.app.deployment.exceptions import (
    ConcurrentDeploymentOperationError,
    InvalidDeploymentTransitionError,
    RollbackFailedError,
    RollbackNotAllowedError,
)
from api.app.deployment.models import DeploymentState, DeploymentStatus
from api.app.deployment.service import DeploymentOrchestrator
from api.app.deployment.state_store import DeploymentStateStore
from api.app.health.models import SmokeStatus
from api.tests._deployment_test_support import FakeDocker, fake_smoke_runner_factory

NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


def _healthy_state(**overrides) -> DeploymentState:
    base = dict(
        deployment_id="deploy_prev_healthy",
        started_at_utc=NOW,
        finished_at_utc=NOW + timedelta(minutes=2),
        target_version="0.9.0",
        target_image_ref="registry/api:0.9.0",
        status=DeploymentStatus.HEALTHY,
        source="manual",
        database_revision_before="20260802_0012",
        database_revision_after="20260803_0013",
    )
    base.update(overrides)
    return DeploymentState(**base)


def _failed_state(**overrides) -> DeploymentState:
    base = dict(
        deployment_id="deploy_new_failed",
        started_at_utc=NOW + timedelta(hours=1),
        target_version="1.0.0",
        target_image_ref="registry/api:1.0.0",
        status=DeploymentStatus.FAILED,
        source="manual",
        database_revision_before="20260803_0013",
    )
    base.update(overrides)
    return DeploymentState(**base)


class DeploymentOrchestratorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.store = DeploymentStateStore(self.dir)
        self.docker = FakeDocker()

    def _orchestrator(self, *, docker=None, smoke_status: SmokeStatus = SmokeStatus.PASS) -> DeploymentOrchestrator:
        return DeploymentOrchestrator(
            state_store=self.store,
            lock_path=self.dir / ".deployment.lock",
            lock_timeout_seconds=60,
            container_name="controle_producao_api",
            network="fake-net",
            health_base_url="http://127.0.0.1:18000",
            validation_timeout_seconds=1.0,
            smoke_runner_factory=fake_smoke_runner_factory(smoke_status),
            docker=docker or self.docker,
        )


class BeginDeploymentTests(DeploymentOrchestratorTestCase):
    def test_captures_previous_healthy_release(self):
        self.store.save(_healthy_state())
        orchestrator = self._orchestrator()
        state = orchestrator.begin_deployment(target_version="1.0.0", target_image_ref="registry/api:1.0.0", database_revision_before="20260803_0013")
        self.assertEqual(state.status, DeploymentStatus.PREPARING)
        self.assertEqual(state.previous_version, "0.9.0")
        self.assertEqual(state.previous_image_ref, "registry/api:0.9.0")

    def test_no_previous_healthy_release_leaves_fields_none(self):
        orchestrator = self._orchestrator()
        state = orchestrator.begin_deployment(target_version="1.0.0", target_image_ref="registry/api:1.0.0", database_revision_before=None)
        self.assertIsNone(state.previous_version)

    def test_rejects_when_a_non_terminal_deployment_is_pending(self):
        self.store.save(_healthy_state())
        orchestrator = self._orchestrator()
        first = orchestrator.begin_deployment(target_version="1.0.0", target_image_ref="registry/api:1.0.0", database_revision_before="20260803_0013")
        self.assertEqual(first.status, DeploymentStatus.PREPARING)
        with self.assertRaises(ConcurrentDeploymentOperationError):
            orchestrator.begin_deployment(target_version="1.1.0", target_image_ref="registry/api:1.1.0", database_revision_before="20260803_0013")


class TransitionTests(DeploymentOrchestratorTestCase):
    def test_happy_path_preparing_to_healthy(self):
        orchestrator = self._orchestrator()
        state = orchestrator.begin_deployment(target_version="1.0.0", target_image_ref="registry/api:1.0.0", database_revision_before="20260803_0013")
        state = orchestrator.mark_deploying(state.deployment_id)
        self.assertEqual(state.status, DeploymentStatus.DEPLOYING)
        state = orchestrator.mark_validating(state.deployment_id)
        self.assertEqual(state.status, DeploymentStatus.VALIDATING)
        state = orchestrator.mark_healthy(state.deployment_id, database_revision_after="20260810_0015")
        self.assertEqual(state.status, DeploymentStatus.HEALTHY)
        self.assertIsNotNone(state.finished_at_utc)

    def test_invalid_transition_raises_and_does_not_change_persisted_state(self):
        orchestrator = self._orchestrator()
        state = orchestrator.begin_deployment(target_version="1.0.0", target_image_ref="registry/api:1.0.0", database_revision_before=None)
        with self.assertRaises(InvalidDeploymentTransitionError):
            orchestrator.mark_healthy(state.deployment_id, database_revision_after="x")
        self.assertEqual(self.store.load(state.deployment_id).status, DeploymentStatus.PREPARING)

    def test_mark_failed_from_deploying(self):
        orchestrator = self._orchestrator()
        state = orchestrator.begin_deployment(target_version="1.0.0", target_image_ref="registry/api:1.0.0", database_revision_before=None)
        state = orchestrator.mark_deploying(state.deployment_id)
        state = orchestrator.mark_failed(state.deployment_id, reason="crash no boot")
        self.assertEqual(state.status, DeploymentStatus.FAILED)
        self.assertEqual(state.error_message, "crash no boot")


class RollbackTests(DeploymentOrchestratorTestCase):
    def test_no_previous_healthy_release_raises_and_escalates_failed_deployment(self):
        self.store.save(_failed_state())
        orchestrator = self._orchestrator()
        with self.assertRaises(RollbackNotAllowedError):
            orchestrator.rollback_to_previous_healthy_release(
                current_database_revision="20260803_0013", reason="teste", failed_deployment_id="deploy_new_failed",
            )
        escalated = self.store.load("deploy_new_failed")
        self.assertEqual(escalated.status, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED)
        self.assertEqual(escalated.rollback_allowed, False)
        self.assertEqual(len(self.docker.calls), 0, "nenhuma acao Docker deve ocorrer quando o rollback e negado")

    def test_destructive_migration_since_previous_release_blocks_rollback(self):
        # previous ficou em 20260803_0013; o banco atual ja passou pela
        # DESTRUCTIVE 20260807_0014 -- rollback deve ser negado.
        self.store.save(_healthy_state())
        self.store.save(_failed_state())
        orchestrator = self._orchestrator()
        with self.assertRaises(RollbackNotAllowedError):
            orchestrator.rollback_to_previous_healthy_release(
                current_database_revision="20260810_0015", reason="teste", failed_deployment_id="deploy_new_failed",
            )
        escalated = self.store.load("deploy_new_failed")
        self.assertEqual(escalated.status, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED)
        self.assertIn("20260807_0014", escalated.rollback_reason)
        self.assertEqual(len(self.docker.calls), 0)

    def test_successful_rollback_swaps_container_and_reaches_rolled_back(self):
        self.store.save(_healthy_state())
        self.store.save(_failed_state())
        orchestrator = self._orchestrator()
        result = orchestrator.rollback_to_previous_healthy_release(
            current_database_revision="20260803_0013", reason="regressao", failed_deployment_id="deploy_new_failed",
        )
        self.assertEqual(result.status, DeploymentStatus.ROLLED_BACK)
        self.assertEqual(result.target_version, "0.9.0")
        self.assertEqual(result.target_image_ref, "registry/api:0.9.0")
        self.assertEqual(self.docker.stopped, ["controle_producao_api"])
        self.assertEqual(self.docker.run_args[0]["image_ref"], "registry/api:0.9.0")
        # o registro FAILED original permanece FAILED, apenas anotado -- o
        # historico anterior nunca e reescrito para outro status.
        original = self.store.load("deploy_new_failed")
        self.assertEqual(original.status, DeploymentStatus.FAILED)
        self.assertTrue(original.rollback_allowed)

    def test_rollback_without_a_linked_failed_deployment_still_succeeds(self):
        self.store.save(_healthy_state())
        orchestrator = self._orchestrator()
        result = orchestrator.rollback_to_previous_healthy_release(current_database_revision="20260803_0013", reason="reversao manual")
        self.assertEqual(result.status, DeploymentStatus.ROLLED_BACK)

    def test_idempotent_when_container_already_running_target_image(self):
        self.store.save(_healthy_state())
        self.docker.running_image = "registry/api:0.9.0"
        orchestrator = self._orchestrator()
        result = orchestrator.rollback_to_previous_healthy_release(current_database_revision="20260803_0013", reason="reexecucao idempotente")
        self.assertEqual(result.status, DeploymentStatus.ROLLED_BACK)
        self.assertEqual(self.docker.stopped, [], "nao deve reiniciar um container que ja esta na imagem alvo")
        self.assertEqual(self.docker.run_args, [])

    def test_container_unhealthy_after_swap_fails_and_escalates(self):
        self.store.save(_healthy_state())
        unhealthy_docker = FakeDocker(healthy_after_run=False)
        orchestrator = self._orchestrator(docker=unhealthy_docker)
        with self.assertRaises(RollbackFailedError):
            orchestrator.rollback_to_previous_healthy_release(current_database_revision="20260803_0013", reason="teste")
        latest = self.store.latest()
        self.assertEqual(latest.status, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED)

    def test_smoke_test_failure_after_swap_fails_and_escalates(self):
        self.store.save(_healthy_state())
        orchestrator = self._orchestrator(smoke_status=SmokeStatus.FAIL)
        with self.assertRaises(RollbackFailedError):
            orchestrator.rollback_to_previous_healthy_release(current_database_revision="20260803_0013", reason="teste")
        latest = self.store.latest()
        self.assertEqual(latest.status, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED)

    def test_concurrent_rollback_blocked_while_lock_is_held(self):
        self.store.save(_healthy_state())
        orchestrator = self._orchestrator()
        lock_path = self.dir / ".deployment.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            '{"owner": "outro-processo", "pid": 1, "hostname": "h", "acquired_at_utc": "%s"}' % datetime.now(timezone.utc).isoformat(),
            encoding="utf-8",
        )
        with self.assertRaises(ConcurrentDeploymentOperationError):
            orchestrator.rollback_to_previous_healthy_release(current_database_revision="20260803_0013", reason="teste")


class RecoveryTests(DeploymentOrchestratorTestCase):
    def test_no_history_returns_none(self):
        orchestrator = self._orchestrator()
        self.assertIsNone(orchestrator.recover_incomplete_deployment_state(running_container_image=None, running_container_healthy=None))

    def test_already_terminal_state_is_untouched(self):
        self.store.save(_healthy_state())
        orchestrator = self._orchestrator()
        recovered = orchestrator.recover_incomplete_deployment_state(running_container_image="anything", running_container_healthy=True)
        self.assertEqual(recovered.status, DeploymentStatus.HEALTHY)

    def test_stuck_deploying_resolves_to_healthy_when_target_image_confirmed_running(self):
        self.store.save(_failed_state(deployment_id="stuck", status=DeploymentStatus.DEPLOYING, target_image_ref="registry/api:1.0.0"))
        orchestrator = self._orchestrator()
        recovered = orchestrator.recover_incomplete_deployment_state(running_container_image="registry/api:1.0.0", running_container_healthy=True)
        self.assertEqual(recovered.status, DeploymentStatus.HEALTHY)

    def test_stuck_rolling_back_resolves_to_rolled_back_when_target_image_confirmed_running(self):
        self.store.save(_failed_state(deployment_id="stuck-rb", status=DeploymentStatus.ROLLING_BACK, target_image_ref="registry/api:0.9.0"))
        orchestrator = self._orchestrator()
        recovered = orchestrator.recover_incomplete_deployment_state(running_container_image="registry/api:0.9.0", running_container_healthy=True)
        self.assertEqual(recovered.status, DeploymentStatus.ROLLED_BACK)

    def test_ambiguous_observation_escalates_to_manual_intervention(self):
        self.store.save(_failed_state(deployment_id="stuck-amb", status=DeploymentStatus.VALIDATING, target_image_ref="registry/api:1.0.0"))
        orchestrator = self._orchestrator()
        recovered = orchestrator.recover_incomplete_deployment_state(running_container_image="registry/api:1.0.0", running_container_healthy=False)
        self.assertEqual(recovered.status, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED)

    def test_no_running_container_at_all_escalates_to_manual_intervention(self):
        self.store.save(_failed_state(deployment_id="stuck-none", status=DeploymentStatus.DEPLOYING, target_image_ref="registry/api:1.0.0"))
        orchestrator = self._orchestrator()
        recovered = orchestrator.recover_incomplete_deployment_state(running_container_image=None, running_container_healthy=None)
        self.assertEqual(recovered.status, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED)


if __name__ == "__main__":
    unittest.main()
