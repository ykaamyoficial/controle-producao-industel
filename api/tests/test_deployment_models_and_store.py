from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.app.deployment.models import DeploymentState, DeploymentStatus
from api.app.deployment.state_store import DeploymentStateStore

NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


def _state(**overrides) -> DeploymentState:
    base = dict(
        deployment_id="deploy_20260811T120000Z_v1.0.0_aaaaaaaa",
        started_at_utc=NOW,
        target_version="1.0.0",
        target_image_ref="registry/api:1.0.0",
        status=DeploymentStatus.PREPARING,
        source="manual",
    )
    base.update(overrides)
    return DeploymentState(**base)


class DeploymentStateModelTests(unittest.TestCase):
    def test_is_terminal_true_for_healthy_rolled_back_rollback_failed_and_manual_intervention(self):
        for status in (
            DeploymentStatus.HEALTHY, DeploymentStatus.ROLLED_BACK,
            DeploymentStatus.ROLLBACK_FAILED, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED,
        ):
            self.assertTrue(_state(status=status).is_terminal, status)

    def test_is_terminal_false_for_in_flight_statuses(self):
        for status in (
            DeploymentStatus.PREPARING, DeploymentStatus.DEPLOYING,
            DeploymentStatus.VALIDATING, DeploymentStatus.FAILED, DeploymentStatus.ROLLING_BACK,
        ):
            self.assertFalse(_state(status=status).is_terminal, status)

    def test_to_dict_and_from_dict_round_trip(self):
        state = _state(
            finished_at_utc=NOW + timedelta(minutes=5),
            previous_version="0.9.0",
            previous_image_ref="registry/api:0.9.0",
            database_revision_before="20260801_0011",
            database_revision_after="20260810_0015",
            rollback_allowed=True,
            rollback_reason="teste",
        )
        restored = DeploymentState.from_dict(state.to_dict())
        self.assertEqual(restored, state)

    def test_replace_produces_new_instance_without_mutating_original(self):
        state = _state()
        moved = state.replace(status=DeploymentStatus.DEPLOYING)
        self.assertEqual(state.status, DeploymentStatus.PREPARING)
        self.assertEqual(moved.status, DeploymentStatus.DEPLOYING)


class DeploymentStateStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = DeploymentStateStore(Path(self._tmp.name))

    def test_save_then_load_round_trips(self):
        state = _state()
        self.store.save(state)
        loaded = self.store.load(state.deployment_id)
        self.assertEqual(loaded, state)

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load("nao-existe"))

    def test_list_all_sorted_by_started_at_utc(self):
        older = _state(deployment_id="d1", started_at_utc=NOW)
        newer = _state(deployment_id="d2", started_at_utc=NOW + timedelta(hours=1))
        self.store.save(newer)
        self.store.save(older)
        self.assertEqual([s.deployment_id for s in self.store.list_all()], ["d1", "d2"])

    def test_last_healthy_ignores_non_healthy_and_picks_most_recent_by_time_not_by_id_text(self):
        # id textualmente "menor" mas cronologicamente mais recente -- o store
        # nunca deve inferir "ultima release saudavel" por ordenacao de string.
        first_healthy = _state(deployment_id="z_old", started_at_utc=NOW, status=DeploymentStatus.HEALTHY)
        failed = _state(deployment_id="a_mid", started_at_utc=NOW + timedelta(hours=1), status=DeploymentStatus.FAILED)
        second_healthy = _state(deployment_id="a_new", started_at_utc=NOW + timedelta(hours=2), status=DeploymentStatus.HEALTHY)
        for state in (first_healthy, failed, second_healthy):
            self.store.save(state)
        self.assertEqual(self.store.last_healthy().deployment_id, "a_new")

    def test_last_healthy_returns_none_when_no_healthy_release_exists(self):
        self.store.save(_state(status=DeploymentStatus.FAILED))
        self.assertIsNone(self.store.last_healthy())

    def test_latest_returns_most_recent_regardless_of_status(self):
        self.store.save(_state(deployment_id="d1", started_at_utc=NOW, status=DeploymentStatus.HEALTHY))
        self.store.save(_state(deployment_id="d2", started_at_utc=NOW + timedelta(hours=1), status=DeploymentStatus.FAILED))
        self.assertEqual(self.store.latest().deployment_id, "d2")

    def test_corrupted_state_file_is_skipped_not_raised(self):
        self.store.save(_state())
        corrupted = Path(self._tmp.name) / "corrupted.json"
        corrupted.write_text("{not valid json", encoding="utf-8")
        # nao deve levantar excecao, apenas ignorar o arquivo ilegivel.
        self.assertEqual(len(self.store.list_all()), 1)

    def test_save_is_atomic_no_leftover_temp_files(self):
        self.store.save(_state())
        leftovers = list(Path(self._tmp.name).glob(".deployment-tmp-*"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
