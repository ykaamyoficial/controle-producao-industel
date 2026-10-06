from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.replica import sync_engine
from app.replica.replica_db import ReplicaDatabase
from app.replica.sync_engine import (
    MODE_BOOTSTRAP,
    MODE_INCREMENTAL,
    MODE_NOOP,
    ReplicaSyncEngine,
    ReplicaSyncError,
    SyncApiClient,
)
from tests.replica_fakes import FakeSyncServer


class ReplicaSyncEngineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "replica.db"
        self.server = FakeSyncServer()
        self.db = ReplicaDatabase(self.path)
        self.engine = self._engine()

    def _engine(self, identity="http://api|7", database=None):
        return ReplicaSyncEngine(database or self.db, SyncApiClient(self.server.get_json), identity=identity)

    def _replica_state(self, database=None):
        database = database or self.db
        return {entity: {row["id"]: row for row in database.find(entity)} for entity in self.server.entities}

    def _seed(self, proposals=3):
        for index in range(1, proposals + 1):
            self.server.upsert("proposals", index, proposal_number=f"CP{index}", current_area="PRODUCAO")
            self.server.upsert("proposal_items", index * 10, proposal_id=index)

    def assertInSync(self, database=None):
        self.assertEqual(self._replica_state(database), self.server.expected_state())
        self.assertEqual((database or self.db).cursor(), self.server.seq)

    # ---- carga inicial ------------------------------------------------------
    def test_first_sync_bootstraps_from_snapshot(self):
        self._seed()
        result = self.engine.sync_once()
        self.assertEqual((result.mode, result.bootstrap_reason, result.seq), (MODE_BOOTSTRAP, "replica_vazia", self.server.seq))
        self.assertEqual(result.changed_entities, {"proposals", "proposal_items"})
        self.assertInSync()

    def test_bootstrap_on_empty_server(self):
        result = self.engine.sync_once()
        self.assertEqual(result.mode, MODE_BOOTSTRAP)
        self.assertEqual(self.db.cursor(), 0)
        self.assertInSync()

    def test_bootstrap_pages_through_large_tables(self):
        self._seed(proposals=7)
        original = sync_engine.SNAPSHOT_PAGE_SIZE
        self.addCleanup(setattr, sync_engine, "SNAPSHOT_PAGE_SIZE", original)
        client = SyncApiClient(self.server.get_json)
        engine = ReplicaSyncEngine(self.db, client, identity="http://api|7")
        client.snapshot = lambda entity, after_id, limit=2: SyncApiClient.snapshot(client, entity, after_id, 2)
        engine.sync_once()
        self.assertInSync()
        self.assertGreaterEqual(sum("snapshot" in call and "entity=proposals" in call for call in self.server.calls), 4)

    def test_writes_during_bootstrap_are_caught_by_the_incremental_step(self):
        self._seed()
        pending = [True]

        def write_while_loading(entity):
            if pending and entity == "proposal_items":
                pending.clear()
                # Proposta ja baixada muda, e uma nova nasce, depois do snapshot dela.
                self.server.upsert("proposals", 1, proposal_number="CP1", current_area="EXPEDICAO")
                self.server.upsert("proposals", 99, proposal_number="CP99", current_area="PRODUCAO")
                self.server.delete("proposal_items", 20)

        self.server.on_snapshot_page = write_while_loading
        result = self.engine.sync_once()
        self.assertEqual(result.mode, MODE_BOOTSTRAP)
        self.assertInSync()
        self.assertEqual(self.db.get("proposals", 1)["current_area"], "EXPEDICAO")

    # ---- incremental --------------------------------------------------------
    def test_client_at_version_1_receives_versions_2_to_5(self):
        self.server.upsert("proposals", 1, proposal_number="CP1", current_area="PRODUCAO")
        self.engine.sync_once()
        self.assertEqual(self.db.cursor(), 1)
        # Desktop "desligado" enquanto o servidor vai da versao 2 ate a 5.
        self.server.upsert("proposals", 2, proposal_number="CP2", current_area="PRODUCAO")
        self.server.upsert("proposal_items", 20, proposal_id=2)
        self.server.upsert("proposals", 1, proposal_number="CP1", current_area="EXPEDICAO")
        self.server.delete("proposal_items", 20)
        self.assertEqual(self.server.seq, 5)
        self.server.calls.clear()
        result = self.engine.sync_once()
        self.assertEqual((result.mode, result.seq), (MODE_INCREMENTAL, 5))
        self.assertEqual(result.changed_entities, {"proposals", "proposal_items"})
        self.assertFalse(any("snapshot" in call for call in self.server.calls))
        self.assertTrue(any("since=1" in call for call in self.server.calls))
        self.assertInSync()

    def test_nothing_new_is_a_noop(self):
        self._seed()
        self.engine.sync_once()
        result = self.engine.sync_once()
        self.assertEqual((result.mode, result.applied_changes, result.changed_entities), (MODE_NOOP, 0, set()))
        self.assertInSync()

    def test_incremental_follows_has_more_until_the_end(self):
        self.engine.sync_once()
        self._seed(proposals=6)
        original = sync_engine.CHANGES_PAGE_SIZE
        self.addCleanup(setattr, sync_engine, "CHANGES_PAGE_SIZE", original)
        client = self.engine.api
        client.changes = lambda since, limit=5: SyncApiClient.changes(client, since, 5)
        self.server.calls.clear()
        result = self.engine.sync_once()
        self.assertEqual(result.mode, MODE_INCREMENTAL)
        self.assertGreaterEqual(sum("changes" in call for call in self.server.calls), 3)
        self.assertInSync()

    def test_cursor_advances_over_events_the_user_cannot_see(self):
        self.server.entities = ["proposals"]
        self.engine.sync_once()
        self.server.tables.setdefault("expedition_items", {})[5] = {"id": 5}
        self.server._event("expedition_items", 5, "upsert")
        result = self.engine.sync_once()
        self.assertEqual((result.mode, result.seq), (MODE_NOOP, self.server.seq))
        self.assertEqual(self.db.cursor(), self.server.seq)

    def test_network_failure_keeps_replica_and_next_sync_recovers(self):
        self._seed()
        self.engine.sync_once()
        before = (self._replica_state(), self.db.cursor())
        self.server.upsert("proposals", 1, proposal_number="CP1", current_area="FINALIZADO")
        self.server.fail_next = ConnectionError("rede caiu")
        with self.assertRaises(ConnectionError):
            self.engine.sync_once()
        self.assertEqual((self._replica_state(), self.db.cursor()), before)
        self.engine.sync_once()
        self.assertInSync()

    # ---- recarga ------------------------------------------------------------
    def test_purged_log_forces_full_reload(self):
        self._seed()
        self.engine.sync_once()
        stale_cursor = self.db.cursor()
        self._seed(proposals=5)
        self.server.delete("proposals", 2)
        self.server.purge_log_up_to(stale_cursor + 3)
        result = self.engine.sync_once()
        self.assertEqual((result.mode, result.bootstrap_reason), (MODE_BOOTSTRAP, "resync_exigido"))
        self.assertInSync()
        self.assertIsNone(self.db.get("proposals", 2))

    def test_server_restored_from_backup_forces_full_reload(self):
        self._seed(proposals=5)
        self.engine.sync_once()
        restored = FakeSyncServer()
        restored.upsert("proposals", 1, proposal_number="CP1-antigo", current_area="PRODUCAO")
        self.server = restored
        engine = self._engine()
        result = engine.sync_once()
        self.assertEqual((result.mode, result.bootstrap_reason), (MODE_BOOTSTRAP, "resync_exigido"))
        self.assertInSync()

    def test_schema_version_change_forces_full_reload(self):
        self._seed()
        self.engine.sync_once()
        self.server.schema_version = 2
        result = self.engine.sync_once()
        self.assertEqual((result.mode, result.bootstrap_reason), (MODE_BOOTSTRAP, "schema_version_mudou"))
        self.assertInSync()

    def test_permission_change_reloads_and_drops_forbidden_entities(self):
        self._seed()
        self.engine.sync_once()
        self.assertEqual(self.db.count("proposal_items"), 3)
        self.server.entities = ["proposals"]
        result = self.engine.sync_once()
        self.assertEqual((result.mode, result.bootstrap_reason), (MODE_BOOTSTRAP, "entidades_mudaram"))
        self.assertEqual(self.db.entities(), ["proposals"])
        self.assertEqual(self.db.count("proposal_items"), 0)

    def test_another_user_never_inherits_the_replica(self):
        self._seed()
        self.engine.sync_once()
        other = self._engine(identity="http://api|8")
        result = other.sync_once()
        self.assertEqual((result.mode, result.bootstrap_reason), (MODE_BOOTSTRAP, "identidade_mudou"))

    def test_reopened_file_continues_incrementally(self):
        self._seed()
        self.engine.sync_once()
        self.server.upsert("proposals", 50, proposal_number="CP50", current_area="PRODUCAO")
        reopened = ReplicaDatabase(self.path)
        result = self._engine(database=reopened).sync_once()
        self.assertEqual(result.mode, MODE_INCREMENTAL)
        self.assertInSync(reopened)

    def test_server_that_never_finishes_paging_raises(self):
        self.engine.sync_once()
        original = sync_engine.MAX_PAGES_PER_SYNC
        sync_engine.MAX_PAGES_PER_SYNC = 3
        self.addCleanup(setattr, sync_engine, "MAX_PAGES_PER_SYNC", original)
        self.engine.api.changes = lambda since, limit=500: {"changes": [], "next_seq": since, "has_more": True, "resync_required": False, "schema_version": 1}
        with self.assertRaises(ReplicaSyncError):
            self.engine.sync_once()

    def test_concurrent_call_is_a_noop(self):
        self._seed()
        self.engine.sync_once()
        self.assertTrue(self.engine._lock.acquire(blocking=False))
        try:
            self.server.upsert("proposals", 60, proposal_number="CP60", current_area="PRODUCAO")
            result = self.engine.sync_once()
        finally:
            self.engine._lock.release()
        self.assertEqual(result.mode, MODE_NOOP)
        self.assertIsNone(self.db.get("proposals", 60))


if __name__ == "__main__":
    unittest.main()
