from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.replica.read_gate import ReplicaReadGate
from app.replica.replica_db import META_CURSOR, META_ENTITIES, ReplicaDatabase
from app.services.api_proposal_storage import OfficialProposalApiStorage, _BorrowedApiClient

ENTITIES = ("proposals", "expedition_items")


class _GateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = ReplicaDatabase(Path(self._tmp.name) / "replica.db")
        self.writes: list[bool] = []
        self.gate = ReplicaReadGate(self.db, on_write=lambda: self.writes.append(True))

    def _load(self, entities="proposals,expedition_items", tables=None):
        self.db.replace_all(tables=tables or {}, meta={META_CURSOR: 1, META_ENTITIES: entities})

    def _sync(self):
        self.gate.complete_sync(self.gate.begin_sync())


class ReplicaReadGateTests(_GateCase):
    def test_closed_until_the_first_sync_of_the_session(self):
        self._load()  # arquivo de um dia anterior, ainda nao sincronizado hoje
        self.assertFalse(self.gate.can_read(ENTITIES))
        self._sync()
        self.assertTrue(self.gate.can_read(ENTITIES))

    def test_closed_when_replica_has_no_data(self):
        self._sync()
        self.assertFalse(self.gate.can_read(ENTITIES))

    def test_closed_when_user_cannot_see_a_required_entity(self):
        self._load(entities="proposals,fiscal_records")
        self._sync()
        self.assertFalse(self.gate.can_read(ENTITIES))
        self.assertTrue(self.gate.can_read(("proposals",)))

    def test_write_closes_until_a_sync_started_after_the_response(self):
        self._load()
        self._sync()
        self.gate.write_started()
        self.assertFalse(self.gate.can_read(ENTITIES))
        self.gate.write_finished()
        self.assertFalse(self.gate.can_read(ENTITIES))
        self.assertEqual(self.writes, [True])
        self._sync()
        self.assertTrue(self.gate.can_read(ENTITIES))

    def test_sync_that_started_before_the_write_finished_does_not_open(self):
        self._load()
        self._sync()
        early = self.gate.begin_sync()  # sync em voo
        self.gate.write_started()
        during = self.gate.begin_sync()  # sync iniciado com a escrita ainda em voo
        self.gate.write_finished()
        self.gate.complete_sync(early)
        self.gate.complete_sync(during)
        self.assertFalse(self.gate.can_read(ENTITIES))
        self._sync()
        self.assertTrue(self.gate.can_read(ENTITIES))

    def test_older_sync_result_never_reopens_after_a_newer_one(self):
        self._load()
        old = self.gate.begin_sync()
        self._sync()
        self.gate.complete_sync(old)
        self.assertTrue(self.gate.can_read(ENTITIES))

    def test_only_writes_to_replicated_areas_count(self):
        is_write = ReplicaReadGate.is_write
        self.assertTrue(is_write("POST", "/api/v1/shipping/proposals/3/start-separation"))
        self.assertTrue(is_write("PUT", "/api/v1/proposals/3"))
        self.assertTrue(is_write("delete", "/api/v1/galvanization/loads/1"))
        self.assertFalse(is_write("GET", "/api/v1/shipping/proposals"))
        self.assertFalse(is_write("POST", "/api/v1/chat/conversations/1/read"))
        self.assertFalse(is_write("POST", "/api/v1/notifications/9/read"))
        self.assertFalse(is_write("POST", "/api/v1/auth/refresh"))


class _FakeHttpClient:
    def __init__(self, error: Exception | None = None):
        self.calls: list[tuple[str, str]] = []
        self.error = error

    def request(self, method, path, **_kwargs):
        self.calls.append((method, path))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(data={})


class BorrowedClientGateTests(_GateCase):
    def _client(self, http):
        return _BorrowedApiClient(SimpleNamespace(replica_gate=self.gate), http)

    def test_write_through_the_api_closes_the_gate_and_asks_for_a_sync(self):
        self._load()
        self._sync()
        self._client(_FakeHttpClient()).post("/api/v1/shipping/proposals/1/start-separation", json_payload={}, access_token="t")
        self.assertFalse(self.gate.can_read(ENTITIES))
        self.assertEqual(self.writes, [True])

    def test_failed_write_also_closes_the_gate(self):
        # A API pode ter gravado antes de a resposta se perder.
        self._load()
        self._sync()
        with self.assertRaises(ConnectionError):
            self._client(_FakeHttpClient(ConnectionError("queda"))).post("/api/v1/proposals", json_payload={}, access_token="t")
        self.assertFalse(self.gate.can_read(ENTITIES))
        self.assertEqual(self.writes, [True])

    def test_reads_and_chat_writes_keep_the_gate_open(self):
        self._load()
        self._sync()
        client = self._client(_FakeHttpClient())
        client.get("/api/v1/shipping/proposals", access_token="t")
        client.post("/api/v1/chat/conversations/1/read", json_payload={}, access_token="t")
        self.assertTrue(self.gate.can_read(ENTITIES))
        self.assertEqual(self.writes, [])

    def test_storage_without_gate_behaves_as_before(self):
        http = _FakeHttpClient()
        _BorrowedApiClient(SimpleNamespace(), http).post("/api/v1/proposals", json_payload={}, access_token="t")
        self.assertEqual(http.calls, [("POST", "/api/v1/proposals")])


class StorageExpeditionReadTests(_GateCase):
    def setUp(self):
        super().setUp()
        self.storage = OfficialProposalApiStorage()
        self.api_rows = [{"id": 77, "proposal_number": "DA-API"}]
        self.api_calls = 0

        def fake_client():
            self.api_calls += 1
            proposals = SimpleNamespace(list_expedition_proposals=lambda token, **filters: {"items": self.api_rows, "total": 1})
            return SimpleNamespace(close=lambda: None), proposals, "token"

        self.storage._client = fake_client

    def _load_expedition(self):
        proposal = {
            "id": 5, "proposal_number": "DA-REPLICA", "customer_name": "Cliente", "active": True, "is_cancelled": False,
            "current_status": "EM_SEPARACAO", "general_status": "EM_EXPEDICAO", "shipping_status": "EM_SEPARACAO", "version": 1,
        }
        item = {
            "id": 50, "proposal_id": 5, "active": True, "status": "EM_SEPARACAO", "origin": "PRODUCAO",
            "available_quantity": "2.0000", "separated_quantity": "0.0000", "delivered_quantity": "0.0000", "remanaged_quantity": "0.0000",
        }
        self._load(tables={"proposals": [proposal], "expedition_items": [item]})

    def _numbers(self, **filters):
        page = self.storage.list_expedition_proposals_page(**filters)
        return [row.get("proposta") or row.get("proposal_number") for row in page["items"]], page["total"]

    def test_without_gate_reads_from_the_api(self):
        self._load_expedition()
        self._numbers(limit=50, offset=0)
        self.assertEqual(self.api_calls, 1)

    def test_open_gate_reads_from_the_replica_without_calling_the_api(self):
        self._load_expedition()
        self._sync()
        self.storage.replica_gate = self.gate
        numbers, total = self._numbers(limit=50, offset=0, search=None)
        self.assertEqual((numbers, total), (["DA-REPLICA"], 1))
        self.assertEqual(self.api_calls, 0)
        self.assertEqual(self.storage.list_expedition_proposals(limit=200, offset=0)[0]["id"], 5)

    def test_closed_gate_falls_back_to_the_api(self):
        self._load_expedition()
        self._sync()
        self.storage.replica_gate = self.gate
        self.gate.write_started()
        self.gate.write_finished()
        numbers, _total = self._numbers(limit=50, offset=0)
        self.assertEqual(numbers, ["DA-API"])
        self.assertEqual(self.api_calls, 1)

    def test_replica_error_falls_back_to_the_api(self):
        self._load_expedition()
        self._sync()
        self.storage.replica_gate = self.gate
        self.db.apply_changes([{"entity": "expedition_items", "id": 51, "op": "upsert", "row": {"id": 51, "proposal_id": 5, "active": True, "status": "X", "available_quantity": "nao-e-numero"}}], cursor=2)
        numbers, _total = self._numbers(limit=50, offset=0)
        self.assertEqual(numbers, ["DA-API"])
        self.assertEqual(self.api_calls, 1)


if __name__ == "__main__":
    unittest.main()
