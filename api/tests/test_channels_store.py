from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from api.app.channels.models import Channel, PromotionStatus, ReleaseChannelState
from api.app.channels.store import ChannelPromotionStore


def _state(**overrides) -> ReleaseChannelState:
    base = ReleaseChannelState(
        version="3.3.0", channel=Channel.PILOT, status=PromotionStatus.PILOT_AUTHORIZED,
        manifest_sha256="a" * 64, artifact_sha256="b" * 64, policy_revision=1,
        created_at=datetime(2026, 8, 12, tzinfo=timezone.utc), updated_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    return base.replace(**overrides) if overrides else base


class ChannelPromotionStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ChannelPromotionStore(Path(self._tmp.name))

    def test_load_returns_none_for_unknown_version(self):
        self.assertIsNone(self.store.load("9.9.9"))

    def test_save_then_load_round_trips(self):
        state = _state()
        self.store.save(state)
        self.assertEqual(self.store.load("3.3.0"), state)

    def test_save_writes_atomically_no_leftover_tmp_files(self):
        self.store.save(_state())
        leftovers = list(Path(self._tmp.name).glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_list_all_returns_every_version(self):
        self.store.save(_state(version="1.0.0"))
        self.store.save(_state(version="2.0.0"))
        versions = {record.version for record in self.store.list_all()}
        self.assertEqual(versions, {"1.0.0", "2.0.0"})

    def test_corrupted_file_is_skipped_not_raised(self):
        self.store.save(_state(version="1.0.0"))
        (Path(self._tmp.name) / "2.0.0.json").write_text("{ corrompido", encoding="utf-8")
        self.assertIsNone(self.store.load("2.0.0"))
        versions = {record.version for record in self.store.list_all()}
        self.assertEqual(versions, {"1.0.0"})

    def test_second_save_overwrites_previous_completely(self):
        self.store.save(_state(policy_revision=1))
        self.store.save(_state(policy_revision=2, status=PromotionStatus.PILOT_APPROVED))
        loaded = self.store.load("3.3.0")
        self.assertEqual(loaded.policy_revision, 2)
        self.assertEqual(loaded.status, PromotionStatus.PILOT_APPROVED)


if __name__ == "__main__":
    unittest.main()
