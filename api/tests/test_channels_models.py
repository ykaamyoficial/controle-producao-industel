from __future__ import annotations

import unittest
from datetime import datetime, timezone

from api.app.channels.models import (
    Channel,
    DEFAULT_CHANNEL,
    PILOT_VISIBLE_STATUSES,
    PRODUCTION_VISIBLE_STATUSES,
    PromotionStatus,
    ReleaseChannelState,
)
from api.app.channels.transitions import ALLOWED_TRANSITIONS, is_transition_allowed


class DefaultChannelTests(unittest.TestCase):
    def test_fallback_channel_is_production(self):
        # Secao 8: "sem configuracao explicita = PRODUCTION"
        self.assertEqual(DEFAULT_CHANNEL, Channel.PRODUCTION)


class ReleaseChannelStateSerializationTests(unittest.TestCase):
    def test_round_trips_through_dict(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
        state = ReleaseChannelState(
            version="3.3.0", channel=Channel.PILOT, status=PromotionStatus.PILOT_AUTHORIZED,
            manifest_sha256="a" * 64, artifact_sha256="b" * 64, policy_revision=1,
            created_at=now, updated_at=now, pilot_authorized_at=now, actor="admin", note="teste",
        )
        restored = ReleaseChannelState.from_dict(state.to_dict())
        self.assertEqual(restored, state)

    def test_from_dict_assumes_utc_when_timestamp_naive(self):
        data = {
            "version": "1.0.0", "channel": "PILOT", "status": "DRAFT",
            "manifest_sha256": "a" * 64, "artifact_sha256": "b" * 64, "policy_revision": 0,
            "created_at": "2026-08-12T10:00:00", "updated_at": "2026-08-12T10:00:00",
        }
        restored = ReleaseChannelState.from_dict(data)
        self.assertEqual(restored.created_at.tzinfo, timezone.utc)


class VisibilityRulesTests(unittest.TestCase):
    def test_pilot_visible_statuses_include_promoted_release(self):
        # Secao 11: um cliente PILOT nao "perde" a release so porque foi
        # aprovada/promovida.
        self.assertIn(PromotionStatus.PILOT_AUTHORIZED, PILOT_VISIBLE_STATUSES)
        self.assertIn(PromotionStatus.PILOT_APPROVED, PILOT_VISIBLE_STATUSES)
        self.assertIn(PromotionStatus.PRODUCTION_AUTHORIZED, PILOT_VISIBLE_STATUSES)
        self.assertNotIn(PromotionStatus.PILOT_PAUSED, PILOT_VISIBLE_STATUSES)
        self.assertNotIn(PromotionStatus.PILOT_FAILED, PILOT_VISIBLE_STATUSES)
        self.assertNotIn(PromotionStatus.REVOKED, PILOT_VISIBLE_STATUSES)

    def test_production_visible_statuses_only_after_promotion(self):
        self.assertEqual(PRODUCTION_VISIBLE_STATUSES, frozenset({PromotionStatus.PRODUCTION_AUTHORIZED}))


class TransitionTableTests(unittest.TestCase):
    def test_allowed_transitions_match_specification(self):
        S = PromotionStatus
        expected = {
            S.DRAFT: {S.PILOT_AUTHORIZED},
            S.PILOT_AUTHORIZED: {S.PILOT_PAUSED, S.PILOT_FAILED, S.PILOT_APPROVED, S.REVOKED},
            S.PILOT_PAUSED: {S.PILOT_AUTHORIZED, S.PILOT_FAILED, S.REVOKED},
            S.PILOT_APPROVED: {S.PRODUCTION_AUTHORIZED, S.REVOKED},
            S.PILOT_FAILED: {S.REVOKED},
            S.PRODUCTION_AUTHORIZED: {S.REVOKED},
            S.REVOKED: set(),
        }
        for source, targets in expected.items():
            self.assertEqual(set(ALLOWED_TRANSITIONS[source]), targets, msg=source)

    def test_draft_cannot_jump_straight_to_production(self):
        self.assertFalse(is_transition_allowed(PromotionStatus.DRAFT, PromotionStatus.PRODUCTION_AUTHORIZED))

    def test_pilot_failed_cannot_be_promoted(self):
        self.assertFalse(is_transition_allowed(PromotionStatus.PILOT_FAILED, PromotionStatus.PRODUCTION_AUTHORIZED))

    def test_pilot_approved_can_be_promoted(self):
        self.assertTrue(is_transition_allowed(PromotionStatus.PILOT_APPROVED, PromotionStatus.PRODUCTION_AUTHORIZED))

    def test_revoked_is_terminal(self):
        for target in PromotionStatus:
            with self.subTest(target=target):
                self.assertFalse(is_transition_allowed(PromotionStatus.REVOKED, target))


if __name__ == "__main__":
    unittest.main()
