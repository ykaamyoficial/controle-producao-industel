from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.replica import proposals_view
from app.replica.read_gate import ReplicaReadGate
from app.replica.replica_db import META_CURSOR, META_ENTITIES, ReplicaDatabase
from app.services.api_proposal_storage import OfficialProposalApiStorage


def _proposal(pid, number, **extra):
    row = {
        "id": pid, "legacy_id": None, "proposal_number": number, "customer_name": "Cliente", "project_name": "Obra",
        "order_reference": "PC1", "lot": "L1", "proposal_date": "2026-07-20", "deadline_date": "2026-07-30",
        "current_area": "PRODUCAO", "current_status": "EM_PRODUCAO", "is_partial": False, "parent_proposal_id": None,
        "is_cancelled": False, "is_completed": False, "legacy_updated_at": None, "synced_at": "2026-07-20T10:00:00+00:00",
        "updated_at": "2026-07-20T10:00:00+00:00", "version": 2, "active": True, "notes": "nao sai na lista",
    }
    row.update(extra)
    return row


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = ReplicaDatabase(Path(self._tmp.name) / "replica.db")

    def _load(self, proposals):
        self.db.replace_all(tables={"proposals": list(proposals)}, meta={META_CURSOR: 1, META_ENTITIES: "proposals"})


class ProposalsViewTests(_Case):
    def _ids(self, **filters):
        return [row["id"] for row in proposals_view.list_proposals(self.db, **filters)["items"]]

    def test_item_has_the_api_shape(self):
        self._load([_proposal(1, "CP-1", legacy_updated_at="2026-07-21T08:00:00.500000+00:00")])
        self.assertEqual(
            proposals_view.list_proposals(self.db),
            {
                "items": [{
                    "id": 1, "legacy_id": None, "proposal_number": "CP-1", "customer_name": "Cliente", "project_name": "Obra",
                    "order_reference": "PC1", "lot": "L1", "proposal_date": "2026-07-20", "deadline_date": "2026-07-30",
                    "current_area": "PRODUCAO", "current_status": "EM_PRODUCAO", "is_partial": False, "parent_proposal_id": None,
                    "is_cancelled": False, "is_completed": False, "legacy_updated_at": "2026-07-21T08:00:00.500000Z",
                    "synced_at": "2026-07-20T10:00:00Z", "version": 2, "active": True,
                }],
                "total": 1, "limit": 50, "offset": 0,
            },
        )

    def test_only_parent_proposals_are_listed(self):
        self._load([_proposal(1, "MAE"), _proposal(2, "FILHA", parent_proposal_id=1), _proposal(3, "INATIVA", active=False), _proposal(4, "CANCELADA", is_cancelled=True)])
        self.assertEqual(sorted(self._ids()), [1, 3, 4])

    def test_default_order_is_most_recently_updated_first_then_id(self):
        self._load([
            _proposal(1, "A", updated_at="2026-07-01T10:00:00+00:00"),
            _proposal(2, "B", updated_at="2026-07-03T10:00:00.250000+00:00"),
            _proposal(3, "C", updated_at="2026-07-03T10:00:00+00:00"),
            _proposal(4, "D", updated_at="2026-07-01T10:00:00+00:00"),
        ])
        self.assertEqual(self._ids(), [2, 3, 1, 4])
        self.assertEqual(self._ids(sort_dir="asc"), [1, 4, 3, 2])

    def test_null_sort_values_follow_postgres(self):
        self._load([_proposal(1, "A", deadline_date="2026-08-01"), _proposal(2, "B", deadline_date=None), _proposal(3, "C", deadline_date="2026-07-01"), _proposal(4, "D", deadline_date=None)])
        self.assertEqual(self._ids(sort_by="deadline_date", sort_dir="asc"), [3, 1, 2, 4])
        self.assertEqual(self._ids(sort_by="deadline_date", sort_dir="desc"), [2, 4, 1, 3])

    def test_text_filters_behave_like_ilike(self):
        self._load([
            _proposal(1, "CP-100", customer_name="Alfa Ltda", project_name="Usina Norte", lot="L-9"),
            _proposal(2, "CP-200", customer_name="BETA 100%", project_name=None, lot="norte"),
            _proposal(3, "XP-300", customer_name="Gama_Sul", project_name="Sul", lot=None),
        ])
        self.assertEqual(sorted(self._ids(customer="alfa")), [1])
        self.assertEqual(sorted(self._ids(proposal_number="cp-")), [1, 2])
        self.assertEqual(sorted(self._ids(project="NORTE")), [1, 2])
        self.assertEqual(sorted(self._ids(customer="a_")), [1, 2, 3])  # `_` = qualquer caractere
        self.assertEqual(sorted(self._ids(customer="a%l")), [1, 3])  # `%` = qualquer trecho
        self.assertEqual(sorted(self._ids(customer="100\\%")), [2])  # `\%` = porcento literal
        self.assertEqual(sorted(self._ids(customer="a\\_")), [3])
        self.assertEqual(self._ids(project="inexistente"), [])

    def test_exact_flag_and_date_filters(self):
        self._load([
            _proposal(1, "A", current_area="EXPEDICAO", current_status="SEPARADO", is_completed=True, proposal_date="2026-06-01", legacy_updated_at="2026-06-02T00:00:00+00:00"),
            _proposal(2, "B", is_cancelled=True, proposal_date="2026-07-01"),
            _proposal(3, "C", is_partial=True, proposal_date=None, legacy_updated_at="2026-01-01T00:00:00+00:00"),
        ])
        self.assertEqual(self._ids(current_area="EXPEDICAO"), [1])
        self.assertEqual(self._ids(current_status="SEPARADO"), [1])
        self.assertEqual(self._ids(is_completed=True), [1])
        self.assertEqual(sorted(self._ids(is_completed=False)), [2, 3])
        self.assertEqual(self._ids(is_cancelled="true"), [2])
        self.assertEqual(self._ids(is_partial=True), [3])
        self.assertEqual(self._ids(date_from="2026-06-15"), [2])
        self.assertEqual(self._ids(date_to=date(2026, 6, 15)), [1])
        self.assertEqual(self._ids(updated_after="2026-03-01T00:00:00+00:00"), [1])
        self.assertEqual(sorted(self._ids(customer=None, current_status="", is_partial=None)), [1, 2, 3])

    def test_pagination_keeps_total(self):
        self._load([_proposal(pid, f"CP-{pid}") for pid in range(1, 8)])
        page = proposals_view.list_proposals(self.db, limit=3, offset=3)
        self.assertEqual([row["id"] for row in page["items"]], [4, 5, 6])
        self.assertEqual((page["total"], page["limit"], page["offset"]), (7, 3, 3))

    def test_requests_the_replica_cannot_reproduce_are_refused(self):
        self.assertTrue(proposals_view.can_serve({}))
        self.assertTrue(proposals_view.can_serve({"customer": "x", "sort_by": "proposal_date", "sort_dir": "asc", "limit": 10, "offset": 0}))
        self.assertFalse(proposals_view.can_serve({"sort_by": "proposal_number"}))  # collation do PostgreSQL
        self.assertFalse(proposals_view.can_serve({"sort_dir": "qualquer"}))
        self.assertFalse(proposals_view.can_serve({"filtro_novo": 1}))
        self._load([])
        with self.assertRaises(ValueError):
            proposals_view.list_proposals(self.db, sort_by="proposal_number")


class StorageProposalsReadTests(_Case):
    def setUp(self):
        super().setUp()
        self.storage = OfficialProposalApiStorage()
        self.api_calls: list[dict] = []

        def fake_client():
            def list_proposals(token, **filters):
                self.api_calls.append(filters)
                return {"items": [{"id": 77, "proposal_number": "DA-API", "customer_name": "X"}], "total": 1}

            return SimpleNamespace(close=lambda: None), SimpleNamespace(list_proposals=list_proposals), "token"

        self.storage._client = fake_client
        self._load([_proposal(1, "DA-REPLICA")])
        self.gate = ReplicaReadGate(self.db)

    def _open(self):
        self.gate.complete_sync(self.gate.begin_sync())
        self.storage.replica_gate = self.gate

    def _numbers(self, **filters):
        return [row["proposta"] for row in self.storage.list_proposals(**filters)]

    def test_without_gate_reads_from_the_api(self):
        self.assertEqual(self._numbers(sort_by="updated_at", sort_dir="desc", limit=200, offset=0), ["DA-API"])
        self.assertEqual(self.api_calls, [{"sort_by": "updated_at", "sort_dir": "desc", "limit": 200, "offset": 0}])

    def test_open_gate_reads_from_the_replica(self):
        self._open()
        self.assertEqual(self._numbers(customer=None, current_status=None, sort_by="updated_at", sort_dir="desc", limit=200, offset=0), ["DA-REPLICA"])
        self.assertEqual(self.storage.list_proposals_page(limit=50, offset=0)["total"], 1)
        self.assertEqual(self.api_calls, [])

    def test_unsupported_sort_goes_to_the_api_even_with_the_gate_open(self):
        self._open()
        self.assertEqual(self._numbers(sort_by="proposal_number", sort_dir="asc"), ["DA-API"])

    def test_closed_gate_falls_back_to_the_api(self):
        self._open()
        self.gate.write_started()
        self.gate.write_finished()
        self.assertEqual(self._numbers(limit=50, offset=0), ["DA-API"])

    def test_duplicate_check_always_asks_the_api(self):
        # Outro usuario pode ter criado a proposta ha instantes; a replica pode nao ter ainda.
        self._open()
        self.assertFalse(self.storage.proposal_exists("da-replica"))
        self.assertTrue(self.storage.proposal_exists(" da-api "))
        self.assertEqual(self.api_calls, [{"proposal_number": "DA-REPLICA", "limit": 2, "offset": 0}, {"proposal_number": "DA-API", "limit": 2, "offset": 0}])


if __name__ == "__main__":
    unittest.main()
