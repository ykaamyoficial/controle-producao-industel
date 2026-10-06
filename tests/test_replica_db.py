from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from app.replica import replica_db
from app.replica.replica_db import META_CURSOR, META_LAYOUT, ReplicaDatabase


class ReplicaDatabaseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sub" / "replica.db"
        self.db = ReplicaDatabase(self.path)

    def _load(self):
        self.db.replace_all(
            tables={
                "proposals": [
                    {"id": 1, "proposal_number": "CP1", "current_area": "EXPEDICAO", "active": True, "customer_name": "Alfa"},
                    {"id": 2, "proposal_number": "CP2", "current_area": "PRODUCAO", "active": True, "customer_name": "Beta"},
                ],
                "proposal_items": [
                    {"id": 10, "proposal_id": 1, "quantity": "2.0000"},
                    {"id": 11, "proposal_id": 1, "quantity": "3.0000"},
                    {"id": 12, "proposal_id": 2, "quantity": "1.0000"},
                ],
            },
            meta={META_CURSOR: 5},
        )

    def test_new_file_is_empty_and_has_no_cursor(self):
        self.assertTrue(self.path.exists())
        self.assertIsNone(self.db.cursor())
        self.assertEqual(self.db.entities(), [])
        self.assertEqual(self.db.count("proposals"), 0)
        self.assertIsNone(self.db.get("proposals", 1))
        self.assertEqual(self.db.find("proposals"), [])

    def test_replace_all_stores_full_rows_and_indexes(self):
        self._load()
        self.assertEqual(self.db.cursor(), 5)
        self.assertEqual(self.db.entities(), ["proposal_items", "proposals"])
        self.assertEqual(self.db.get("proposals", 2)["customer_name"], "Beta")
        self.assertEqual([row["id"] for row in self.db.find("proposal_items", proposal_id=1)], [10, 11])
        self.assertEqual([row["id"] for row in self.db.find("proposals", current_area="PRODUCAO", active=True)], [2])
        self.assertEqual([row["id"] for row in self.db.find("proposal_items", proposal_id=[1, 2])], [10, 11, 12])
        self.assertEqual(self.db.find("proposal_items", proposal_id=[]), [])

    def test_find_rejects_non_indexed_column(self):
        self._load()
        with self.assertRaises(ValueError):
            self.db.find("proposals", customer_name="Alfa")

    def test_apply_changes_upserts_deletes_and_moves_cursor(self):
        self._load()
        touched = self.db.apply_changes(
            [
                {"seq": 6, "entity": "proposals", "id": 1, "op": "upsert", "row": {"id": 1, "proposal_number": "CP1", "current_area": "FINALIZADO", "active": True}},
                {"seq": 7, "entity": "proposal_items", "id": 11, "op": "delete", "row": None},
                {"seq": 8, "entity": "proposals", "id": 3, "op": "upsert", "row": {"id": 3, "proposal_number": "CP3", "current_area": "PRODUCAO", "active": True}},
            ],
            cursor=8,
        )
        self.assertEqual(touched, {"proposals", "proposal_items"})
        self.assertEqual(self.db.cursor(), 8)
        self.assertEqual(self.db.get("proposals", 1)["current_area"], "FINALIZADO")
        self.assertEqual([row["id"] for row in self.db.find("proposals", current_area="PRODUCAO")], [2, 3])
        self.assertIsNone(self.db.get("proposal_items", 11))

    def test_applying_the_same_page_twice_is_idempotent(self):
        self._load()
        page = [
            {"seq": 6, "entity": "proposals", "id": 2, "op": "upsert", "row": {"id": 2, "proposal_number": "CP2", "current_area": "EXPEDICAO", "active": True}},
            {"seq": 7, "entity": "proposal_items", "id": 12, "op": "delete", "row": None},
        ]
        self.db.apply_changes(page, cursor=7)
        first = (self.db.find("proposals"), self.db.find("proposal_items"), self.db.cursor())
        self.db.apply_changes(page, cursor=7)
        self.assertEqual((self.db.find("proposals"), self.db.find("proposal_items"), self.db.cursor()), first)

    def test_cursor_never_goes_backwards(self):
        self._load()
        self.db.apply_changes([], cursor=9)
        self.db.apply_changes([], cursor=7)
        self.assertEqual(self.db.cursor(), 9)

    def test_failure_in_the_middle_rolls_back_rows_and_cursor(self):
        self._load()
        with self.assertRaises(Exception):
            self.db.apply_changes(
                [
                    {"seq": 6, "entity": "proposals", "id": 1, "op": "upsert", "row": {"id": 1, "proposal_number": "MUDOU"}},
                    {"seq": 7, "entity": "nome invalido;", "id": 1, "op": "upsert", "row": {"id": 1}},
                ],
                cursor=7,
            )
        self.assertEqual(self.db.cursor(), 5)
        self.assertEqual(self.db.get("proposals", 1)["proposal_number"], "CP1")

    def test_unknown_entity_from_newer_server_gets_generic_table(self):
        self._load()
        self.db.apply_changes([{"seq": 6, "entity": "entidade_nova", "id": 4, "op": "upsert", "row": {"id": 4, "x": 1}}], cursor=6)
        self.assertEqual(self.db.get("entidade_nova", 4), {"id": 4, "x": 1})

    def test_replace_all_removes_tables_that_are_no_longer_sent(self):
        self._load()
        self.db.replace_all(tables={"proposals": [{"id": 9, "proposal_number": "CP9"}]}, meta={META_CURSOR: 20})
        self.assertEqual(self.db.entities(), ["proposals"])
        self.assertEqual([row["id"] for row in self.db.find("proposals")], [9])
        self.assertEqual(self.db.cursor(), 20)

    def test_reopening_keeps_data(self):
        self._load()
        again = ReplicaDatabase(self.path)
        self.assertEqual(again.cursor(), 5)
        self.assertEqual(again.count("proposal_items"), 3)

    def test_layout_version_change_discards_the_replica(self):
        self._load()
        original = replica_db.LOCAL_LAYOUT_VERSION
        replica_db.LOCAL_LAYOUT_VERSION = original + 1
        self.addCleanup(setattr, replica_db, "LOCAL_LAYOUT_VERSION", original)
        rebuilt = ReplicaDatabase(self.path)
        self.assertIsNone(rebuilt.cursor())
        self.assertEqual(rebuilt.entities(), [])
        self.assertEqual(rebuilt.get_meta(META_LAYOUT), str(original + 1))

    def test_corrupted_file_is_recreated(self):
        self._load()
        for suffix in ("-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        self.path.write_bytes(b"isto nao e um banco sqlite" * 50)
        rebuilt = ReplicaDatabase(self.path)
        self.assertIsNone(rebuilt.cursor())
        self.assertEqual(rebuilt.entities(), [])

    def test_reader_in_another_thread_sees_committed_state(self):
        self._load()
        seen: list[int] = []
        thread = threading.Thread(target=lambda: seen.append(self.db.count("proposal_items")))
        thread.start()
        thread.join(5)
        self.assertEqual(seen, [3])

    def test_uses_wal_journal(self):
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
