from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.replica import factory
from app.replica.replica_db import ReplicaDatabase
from app.replica.sync_engine import MODE_BOOTSTRAP
from tests.replica_fakes import FakeSyncServer


class ReplicaFactoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.dict(os.environ, {"CONTROLE_PRODUCAO_REPLICA_DIR": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled_by_default(self):
        self.assertFalse(factory.replica_enabled(None))
        self.assertFalse(factory.replica_enabled({}))
        self.assertFalse(factory.replica_enabled({"local_replica": {"enabled": False}}))
        self.assertFalse(factory.replica_enabled({"local_replica": True}))
        self.assertTrue(factory.replica_enabled({"local_replica": {"enabled": True}}))

    def test_each_server_and_user_gets_its_own_file(self):
        base = factory.replica_path(factory.replica_identity("http://api:8000/", "7"))
        self.assertEqual(base.parent, Path(self._tmp.name))
        self.assertEqual(base, factory.replica_path(factory.replica_identity("HTTP://API:8000", "7")))
        self.assertNotEqual(base, factory.replica_path(factory.replica_identity("http://api:8000", "8")))
        self.assertNotEqual(base, factory.replica_path(factory.replica_identity("http://outro:8000", "7")))

    def test_packaged_app_uses_the_windows_user_folder(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}), patch.object(factory, "is_packaged", return_value=True):
            os.environ.pop("CONTROLE_PRODUCAO_REPLICA_DIR")
            self.assertEqual(factory.get_replica_dir(), Path(r"C:\Users\x\AppData\Local") / "ControleProducao" / "replica")

    def test_build_wires_database_and_engine_to_the_logged_user(self):
        server = FakeSyncServer()
        server.upsert("proposals", 1, proposal_number="CP1")
        storage = SimpleNamespace(api_base_url=lambda: "http://api:8000", sync_get_json=server.get_json)
        service = SimpleNamespace(official_proposal_storage=storage, user={"id": 7, "login": "cleibe"})
        database, engine = factory.build_replica_sync(service)
        self.assertIsInstance(database, ReplicaDatabase)
        self.assertEqual(engine.identity, "http://api:8000|7")
        self.assertEqual(engine.sync_once().mode, MODE_BOOTSTRAP)
        self.assertEqual(database.get("proposals", 1)["proposal_number"], "CP1")

    def test_build_requires_logged_user(self):
        service = SimpleNamespace(official_proposal_storage=SimpleNamespace(api_base_url=lambda: "http://api"), user=None)
        with self.assertRaises(RuntimeError):
            factory.build_replica_sync(service)


if __name__ == "__main__":
    unittest.main()
