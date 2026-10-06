from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.orm import Session

from api.app.modules.auth.permissions import FISCAL_VIEW, PROPOSALS_VIEW
from api.app.modules.sync import capture, service
from api.app.modules.sync.registry import ENTITY_BY_MODEL, ENTITY_BY_NAME, SYNC_ENTITIES


class SyncRegistryTests(unittest.TestCase):
    def test_every_entity_has_integer_id_and_permission(self):
        self.assertEqual(len(ENTITY_BY_NAME), len(SYNC_ENTITIES))
        self.assertEqual(len(ENTITY_BY_MODEL), len(SYNC_ENTITIES))
        for entity in SYNC_ENTITIES:
            table = entity.model.__table__
            self.assertEqual(entity.name, table.name)
            self.assertEqual([column.name for column in table.primary_key.columns], ["id"])
            self.assertTrue(entity.permissions)

    def test_sensitive_tables_are_not_replicated(self):
        for forbidden in ("users", "roles", "permissions", "auth_sessions", "security_events", "chat_messages"):
            self.assertNotIn(forbidden, ENTITY_BY_NAME)


class SyncSerializationTests(unittest.TestCase):
    def test_values_become_json_safe(self):
        row = service.serialize_row(
            {
                "id": 7,
                "weight": Decimal("12.5000"),
                "day": date(2026, 10, 6),
                "at": datetime(2026, 10, 6, 12, 30, tzinfo=timezone.utc),
                "blob": b"\x00\x01",
                "note": None,
                "flag": True,
            }
        )
        self.assertEqual(
            row,
            {"id": 7, "weight": "12.5000", "day": "2026-10-06", "at": "2026-10-06T12:30:00+00:00", "blob": None, "note": None, "flag": True},
        )

    def test_collapse_keeps_last_event_per_row_in_seq_order(self):
        events = [
            (1, "proposals", 10, "upsert"),
            (2, "proposal_items", 5, "upsert"),
            (3, "proposals", 10, "upsert"),
            (4, "proposal_items", 5, "delete"),
            (5, "proposals", 11, "upsert"),
        ]
        self.assertEqual(
            service.collapse_events(events),
            [(3, "proposals", 10, "upsert"), (4, "proposal_items", 5, "delete"), (5, "proposals", 11, "upsert")],
        )


class SyncPermissionTests(unittest.TestCase):
    def _names(self, permissions, superuser=False):
        actor = SimpleNamespace(is_superuser=superuser)
        with patch.object(service, "effective_permissions", return_value=set(permissions)):
            return [entity.name for entity in service.allowed_entities(actor)]

    def test_superuser_sees_everything(self):
        self.assertEqual(self._names([], superuser=True), [entity.name for entity in SYNC_ENTITIES])

    def test_no_permission_sees_nothing(self):
        self.assertEqual(self._names([]), [])

    def test_fiscal_user_sees_proposals_and_fiscal_only(self):
        names = self._names([FISCAL_VIEW])
        self.assertIn("proposals", names)
        self.assertIn("fiscal_records", names)
        self.assertNotIn("expedition_items", names)
        self.assertNotIn("galvanization_loads", names)

    def test_proposals_user_does_not_see_area_tables(self):
        self.assertEqual(self._names([PROPOSALS_VIEW]), ["proposals", "proposal_items"])


class RecordChangeTests(unittest.TestCase):
    def test_last_operation_wins_and_moves_to_the_end(self):
        session = Session()
        capture.record_change(session, "proposals", 1)
        capture.record_change(session, "proposal_items", 2)
        capture.record_change(session, "proposals", 1, capture.OP_DELETE)
        self.assertEqual(
            list(session.info[capture._PENDING].items()),
            [(("proposal_items", 2), "upsert"), (("proposals", 1), "delete")],
        )

    def test_rejects_unknown_entity_and_operation(self):
        session = Session()
        with self.assertRaises(ValueError):
            capture.record_change(session, "users", 1)
        with self.assertRaises(ValueError):
            capture.record_change(session, "proposals", 1, "truncate")

    def test_rollback_discards_pending_changes(self):
        session = Session()
        capture.record_change(session, "proposals", 1)
        capture._discard_changes(session)
        self.assertNotIn(capture._PENDING, session.info)


if __name__ == "__main__":
    unittest.main()
