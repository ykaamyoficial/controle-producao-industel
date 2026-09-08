from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from api.app.maintenance.exceptions import ConcurrentMaintenanceOperationError, InvalidMaintenanceTransitionError
from api.app.maintenance.models import MaintenanceReasonCode, MaintenanceStateName
from api.app.maintenance.service import CORRUPTED_STATE_MAINTENANCE_ID, MaintenanceService
from api.app.maintenance.store import MaintenanceStateStore

ACTOR = "ana.admin"


class MaintenanceServiceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.service = self._new_service()

    def _new_service(self) -> MaintenanceService:
        return MaintenanceService(
            store=MaintenanceStateStore(self.dir / "maintenance.json"),
            lock_path=self.dir / ".maintenance.lock",
            lock_timeout_seconds=5,
        )


class HappyPathTransitionsTests(MaintenanceServiceTestCase):
    def test_off_by_default(self):
        self.assertEqual(self.service.get_state().state, MaintenanceStateName.OFF)

    def test_full_lifecycle_schedule_draining_active_recovery_off(self):
        scheduled = self.service.schedule_maintenance(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="Deploy programado",
            scheduled_start_at=datetime.now(timezone.utc) + timedelta(hours=1),
            expected_end_at=None, activated_by=ACTOR,
        )
        self.assertEqual(scheduled.state, MaintenanceStateName.SCHEDULED)

        draining = self.service.begin_draining(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="Esvaziando",
            expected_end_at=None, activated_by=ACTOR,
        )
        self.assertEqual(draining.state, MaintenanceStateName.DRAINING)
        self.assertEqual(draining.maintenance_id, scheduled.maintenance_id, "mesma janela, id preservado")

        active = self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="Em manutencao",
            expected_end_at=None, activated_by=ACTOR,
        )
        self.assertEqual(active.state, MaintenanceStateName.ACTIVE)
        self.assertIsNotNone(active.started_at)
        self.assertEqual(active.maintenance_id, scheduled.maintenance_id)

        recovery = self.service.begin_recovery(activated_by=ACTOR)
        self.assertEqual(recovery.state, MaintenanceStateName.RECOVERY)
        self.assertEqual(recovery.maintenance_id, scheduled.maintenance_id)

        off = self.service.finish_maintenance(activated_by=ACTOR)
        self.assertEqual(off.state, MaintenanceStateName.OFF)

    def test_off_to_active_directly_emergency_path(self):
        active = self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.EMERGENCY_MAINTENANCE, message="Incidente",
            expected_end_at=None, activated_by=ACTOR,
        )
        self.assertEqual(active.state, MaintenanceStateName.ACTIVE)

    def test_cancel_scheduled_returns_to_off(self):
        self.service.schedule_maintenance(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="x",
            scheduled_start_at=datetime.now(timezone.utc) + timedelta(hours=1),
            expected_end_at=None, activated_by=ACTOR,
        )
        off = self.service.cancel_scheduled_maintenance(activated_by=ACTOR)
        self.assertEqual(off.state, MaintenanceStateName.OFF)

    def test_cancel_draining_returns_to_off_without_ever_activating(self):
        self.service.begin_draining(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="x",
            expected_end_at=None, activated_by=ACTOR,
        )
        off = self.service.cancel_scheduled_maintenance(activated_by=ACTOR)
        self.assertEqual(off.state, MaintenanceStateName.OFF)

    def test_policy_revision_increments_on_every_real_transition(self):
        first = self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.MANUAL_ADMIN, message="x", expected_end_at=None, activated_by=ACTOR,
        )
        second = self.service.begin_recovery(activated_by=ACTOR)
        self.assertEqual(second.policy_revision, first.policy_revision + 1)


class InvalidTransitionTests(MaintenanceServiceTestCase):
    def test_active_to_scheduled_is_rejected(self):
        self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.MANUAL_ADMIN, message="x", expected_end_at=None, activated_by=ACTOR,
        )
        with self.assertRaises(InvalidMaintenanceTransitionError):
            self.service.schedule_maintenance(
                reason_code=MaintenanceReasonCode.MANUAL_ADMIN, message="x",
                scheduled_start_at=datetime.now(timezone.utc), expected_end_at=None, activated_by=ACTOR,
            )

    def test_recovery_to_active_without_explicit_action_is_rejected(self):
        self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.MANUAL_ADMIN, message="x", expected_end_at=None, activated_by=ACTOR,
        )
        self.service.begin_recovery(activated_by=ACTOR)
        with self.assertRaises(InvalidMaintenanceTransitionError):
            self.service.activate_maintenance(
                reason_code=MaintenanceReasonCode.MANUAL_ADMIN, message="x", expected_end_at=None, activated_by=ACTOR,
            )

    def test_recovery_requires_prior_active(self):
        with self.assertRaises(InvalidMaintenanceTransitionError):
            self.service.begin_recovery(activated_by=ACTOR)

    def test_finish_maintenance_requires_recovery(self):
        self.service.schedule_maintenance(
            reason_code=MaintenanceReasonCode.MANUAL_ADMIN, message="x",
            scheduled_start_at=datetime.now(timezone.utc), expected_end_at=None, activated_by=ACTOR,
        )
        with self.assertRaises(InvalidMaintenanceTransitionError):
            self.service.finish_maintenance(activated_by=ACTOR)


class IdempotencyTests(MaintenanceServiceTestCase):
    """Fase 14, Secao 27: repetir a mesma ativacao nao corrompe o estado."""

    def test_activating_twice_with_same_maintenance_id_is_a_noop(self):
        first = self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="x", expected_end_at=None,
            activated_by=ACTOR, maintenance_id="mnt-fixed-001",
        )
        second = self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="x", expected_end_at=None,
            activated_by=ACTOR, maintenance_id="mnt-fixed-001",
        )
        self.assertEqual(first, second)

    def test_activating_with_different_maintenance_id_while_already_active_is_rejected(self):
        self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="x", expected_end_at=None,
            activated_by=ACTOR, maintenance_id="mnt-fixed-001",
        )
        with self.assertRaises(InvalidMaintenanceTransitionError):
            self.service.activate_maintenance(
                reason_code=MaintenanceReasonCode.DEPLOYMENT, message="x", expected_end_at=None,
                activated_by="deploy-pipeline", maintenance_id="mnt-fixed-002",
            )

    def test_double_finish_is_harmless(self):
        self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.MANUAL_ADMIN, message="x", expected_end_at=None, activated_by=ACTOR,
        )
        self.service.begin_recovery(activated_by=ACTOR)
        self.service.finish_maintenance(activated_by=ACTOR)
        off_again = self.service.finish_maintenance(activated_by=ACTOR)
        self.assertEqual(off_again.state, MaintenanceStateName.OFF)


class RestartRecoveryTests(MaintenanceServiceTestCase):
    def test_active_state_survives_new_service_instance_pointed_at_same_directory(self):
        self.service.activate_maintenance(
            reason_code=MaintenanceReasonCode.DATABASE_MIGRATION, message="Migrando",
            expected_end_at=None, activated_by=ACTOR,
        )

        restarted = self._new_service()
        self.assertEqual(restarted.get_state().state, MaintenanceStateName.ACTIVE)

    def test_corrupted_file_falls_back_to_active_never_off(self):
        maintenance_json = self.dir / "maintenance.json"
        maintenance_json.parent.mkdir(parents=True, exist_ok=True)
        maintenance_json.write_text("{ nao e json valido", encoding="utf-8")

        state = self.service.get_state()

        self.assertEqual(state.state, MaintenanceStateName.ACTIVE)
        self.assertEqual(state.maintenance_id, CORRUPTED_STATE_MAINTENANCE_ID)

    def test_corrupted_file_is_not_silently_rewritten_by_a_read(self):
        maintenance_json = self.dir / "maintenance.json"
        maintenance_json.parent.mkdir(parents=True, exist_ok=True)
        maintenance_json.write_text("{ nao e json valido", encoding="utf-8")

        self.service.get_state()

        self.assertEqual(maintenance_json.read_text(encoding="utf-8"), "{ nao e json valido")


class ConcurrencyTests(MaintenanceServiceTestCase):
    def test_concurrent_admin_operation_is_rejected_while_lock_is_held(self):
        lock_path = self.dir / ".maintenance.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text('{"owner": "other-admin", "pid": 1, "hostname": "h", "acquired_at_utc": "' + datetime.now(timezone.utc).isoformat() + '"}', encoding="utf-8")

        with self.assertRaises(ConcurrentMaintenanceOperationError):
            self.service.activate_maintenance(
                reason_code=MaintenanceReasonCode.MANUAL_ADMIN, message="x", expected_end_at=None, activated_by=ACTOR,
            )


if __name__ == "__main__":
    unittest.main()
