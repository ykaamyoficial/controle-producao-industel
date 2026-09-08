from __future__ import annotations

import unittest
from datetime import datetime, timezone

from api.app.audit.models import (
    ActorType,
    AuditEventType,
    Component,
    EventResult,
    EventSeverity,
    InstallationUpdateStatus,
    UpdateAuditEvent,
)


def _make_event(**overrides) -> UpdateAuditEvent:
    defaults = dict(
        event_type=AuditEventType.DEPLOYMENT_STARTED,
        severity=EventSeverity.INFO,
        actor_type=ActorType.DEPLOY_RUNNER,
        component=Component.DEPLOYMENT,
        result=EventResult.STARTED,
        message="deploy iniciado",
    )
    defaults.update(overrides)
    return UpdateAuditEvent(**defaults)


class EventIdentityTests(unittest.TestCase):
    def test_two_events_get_distinct_event_ids(self):
        first = _make_event()
        second = _make_event()
        self.assertNotEqual(first.event_id, second.event_id)

    def test_occurred_at_defaults_to_timezone_aware_now(self):
        event = _make_event()
        self.assertIsNotNone(event.occurred_at.tzinfo)

    def test_event_is_frozen_and_immutable(self):
        event = _make_event()
        with self.assertRaises(Exception):
            event.message = "alterado"  # type: ignore[misc]

    def test_replace_produces_a_new_event_without_mutating_original(self):
        event = _make_event()
        changed = event.replace(message="outro texto")
        self.assertEqual(event.message, "deploy iniciado")
        self.assertEqual(changed.message, "outro texto")
        self.assertEqual(changed.event_id, event.event_id)


class RoundTripTests(unittest.TestCase):
    def test_to_dict_from_dict_round_trip_preserves_all_fields(self):
        event = _make_event(
            correlation_id="upd-20260812-abcd1234", release_id="3.3.0", deployment_id="dep-1",
            maintenance_id="mnt-1", installation_id="pc-1", version="3.3.0", channel="PILOT",
            metadata={"sha256": "abc123"},
        )
        restored = UpdateAuditEvent.from_dict(event.to_dict())
        self.assertEqual(restored, event)

    def test_from_dict_defaults_naive_occurred_at_to_utc(self):
        payload = _make_event().to_dict()
        payload["occurred_at"] = "2026-08-12T10:00:00"
        restored = UpdateAuditEvent.from_dict(payload)
        self.assertEqual(restored.occurred_at.tzinfo, timezone.utc)

    def test_from_row_reconstructs_event_from_orm_like_object(self):
        class FakeRow:
            event_id = "11111111-1111-1111-1111-111111111111"
            event_type = "RELEASE_AUTHORIZED"
            occurred_at = datetime.now(timezone.utc)
            severity = "INFO"
            actor_type = "ADMIN_API"
            actor_id = "release.admin"
            component = "UPDATE_SERVER"
            result = "SUCCEEDED"
            correlation_id = "upd-20260812-deadbeef"
            release_id = "3.3.0"
            deployment_id = None
            maintenance_id = None
            installation_id = None
            version = "3.3.0"
            channel = None
            message = "release autorizada"
            event_metadata = {"actor": "release.admin"}

        event = UpdateAuditEvent.from_row(FakeRow())
        self.assertEqual(event.event_type, AuditEventType.RELEASE_AUTHORIZED)
        self.assertEqual(event.metadata, {"actor": "release.admin"})

    def test_from_row_defaults_missing_metadata_to_empty_dict(self):
        class FakeRow:
            event_id = "22222222-2222-2222-2222-222222222222"
            event_type = "RELEASE_AUTHORIZED"
            occurred_at = datetime.now(timezone.utc)
            severity = "INFO"
            actor_type = "ADMIN_API"
            actor_id = None
            component = "UPDATE_SERVER"
            result = "SUCCEEDED"
            correlation_id = None
            release_id = None
            deployment_id = None
            maintenance_id = None
            installation_id = None
            version = None
            channel = None
            message = "sem metadata"
            event_metadata = None

        event = UpdateAuditEvent.from_row(FakeRow())
        self.assertEqual(event.metadata, {})


class InstallationUpdateStatusTests(unittest.TestCase):
    def test_to_dict_serializes_datetimes_as_iso_strings(self):
        status = InstallationUpdateStatus(
            installation_id="pc-1", machine_name="PC-1", channel="PRODUCTION", current_version="3.3.0",
            last_seen_at=datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
            last_update_version="3.3.0", last_update_result="SUCCEEDED",
            last_update_at=datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
            compatibility_state="COMPATIBLE",
        )
        payload = status.to_dict()
        self.assertEqual(payload["last_seen_at"], "2026-08-12T10:00:00+00:00")
        self.assertEqual(payload["last_update_at"], "2026-08-12T09:00:00+00:00")

    def test_to_dict_handles_none_datetimes(self):
        status = InstallationUpdateStatus(
            installation_id="pc-1", machine_name=None, channel="PRODUCTION", current_version=None,
            last_seen_at=None, last_update_version=None, last_update_result=None,
            last_update_at=None, compatibility_state=None,
        )
        payload = status.to_dict()
        self.assertIsNone(payload["last_seen_at"])
        self.assertIsNone(payload["last_update_at"])


if __name__ == "__main__":
    unittest.main()
