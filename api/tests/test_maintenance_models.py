from __future__ import annotations

import unittest
from datetime import datetime, timezone

from api.app.maintenance.models import (
    MaintenanceReasonCode,
    MaintenanceState,
    MaintenanceStateName,
    retry_after_seconds_for,
)
from api.app.maintenance.naming import build_maintenance_id
from api.app.maintenance.transitions import ALLOWED_TRANSITIONS, is_transition_allowed


class MaintenanceStateSerializationTests(unittest.TestCase):
    def test_round_trips_through_dict_preserving_all_fields(self):
        now = datetime(2026, 8, 12, 10, 30, tzinfo=timezone.utc)
        state = MaintenanceState(
            state=MaintenanceStateName.ACTIVE,
            maintenance_id="mnt-20260812-abc123",
            reason_code=MaintenanceReasonCode.DEPLOYMENT,
            message="Deploy em andamento.",
            policy_revision=3,
            updated_at=now,
            scheduled_start_at=now,
            started_at=now,
            expected_end_at=now,
            activated_by="pipeline",
        )

        restored = MaintenanceState.from_dict(state.to_dict())

        self.assertEqual(restored, state)

    def test_from_dict_assumes_utc_when_timestamp_has_no_timezone(self):
        data = {
            "state": "OFF", "maintenance_id": "mnt-none", "reason_code": "MANUAL_ADMIN",
            "message": "", "policy_revision": 0, "updated_at": "2026-08-12T10:00:00",
        }
        restored = MaintenanceState.from_dict(data)
        self.assertEqual(restored.updated_at.tzinfo, timezone.utc)

    def test_initial_off_has_predictable_placeholder_id(self):
        state = MaintenanceState.initial_off()
        self.assertEqual(state.state, MaintenanceStateName.OFF)
        self.assertEqual(state.maintenance_id, "mnt-none")
        self.assertEqual(state.policy_revision, 0)

    def test_is_blocking_true_only_for_active_and_recovery(self):
        blocking = {MaintenanceStateName.ACTIVE, MaintenanceStateName.RECOVERY}
        for name in MaintenanceStateName:
            state = MaintenanceState.initial_off().replace(state=name)
            self.assertEqual(state.is_blocking, name in blocking, msg=name)


class RetryAfterTests(unittest.TestCase):
    def test_none_for_off_and_scheduled(self):
        for name in (MaintenanceStateName.OFF, MaintenanceStateName.SCHEDULED):
            state = MaintenanceState.initial_off().replace(state=name)
            self.assertIsNone(retry_after_seconds_for(state, default_seconds=30))

    def test_default_seconds_for_draining_active_recovery(self):
        for name in (MaintenanceStateName.DRAINING, MaintenanceStateName.ACTIVE, MaintenanceStateName.RECOVERY):
            state = MaintenanceState.initial_off().replace(state=name)
            self.assertEqual(retry_after_seconds_for(state, default_seconds=45), 45)


class MaintenanceIdNamingTests(unittest.TestCase):
    def test_format_is_stable_and_prefixed(self):
        moment = datetime(2026, 8, 12, tzinfo=timezone.utc)
        identifier = build_maintenance_id(now=moment)
        self.assertTrue(identifier.startswith("mnt-20260812-"))

    def test_two_calls_never_collide(self):
        moment = datetime(2026, 8, 12, tzinfo=timezone.utc)
        first = build_maintenance_id(now=moment)
        second = build_maintenance_id(now=moment)
        self.assertNotEqual(first, second)


class TransitionTableTests(unittest.TestCase):
    """Fase 14, Secao 13 -- exercita a tabela literal do prompt tecnico."""

    def test_allowed_transitions_match_specification(self):
        S = MaintenanceStateName
        expected = {
            S.OFF: {S.SCHEDULED, S.DRAINING, S.ACTIVE},
            S.SCHEDULED: {S.DRAINING, S.ACTIVE, S.OFF},
            S.DRAINING: {S.ACTIVE, S.OFF},
            S.ACTIVE: {S.RECOVERY},
            S.RECOVERY: {S.OFF},
        }
        for source, targets in expected.items():
            self.assertEqual(set(ALLOWED_TRANSITIONS[source]), targets, msg=source)

    def test_forbidden_transitions_are_rejected(self):
        S = MaintenanceStateName
        forbidden = [
            (S.ACTIVE, S.SCHEDULED),
            (S.RECOVERY, S.ACTIVE),
            (S.OFF, S.RECOVERY),
            (S.SCHEDULED, S.RECOVERY),
        ]
        for source, target in forbidden:
            self.assertFalse(is_transition_allowed(source, target), msg=f"{source}->{target}")

    def test_self_transition_is_not_a_defined_edge(self):
        # Repetir o estado atual e idempotencia (Secao 27), tratada pela camada de
        # servico -- a tabela pura da maquina de estados nao inclui self-loops.
        for name in MaintenanceStateName:
            self.assertFalse(is_transition_allowed(name, name), msg=name)


if __name__ == "__main__":
    unittest.main()
