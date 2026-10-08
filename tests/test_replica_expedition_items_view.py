from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.replica import expedition_items_view
from app.replica.read_gate import ReplicaReadGate
from app.replica.replica_db import META_CURSOR, META_ENTITIES, ReplicaDatabase


def _proposal(pid, number, **extra):
    row = {
        "id": pid, "proposal_number": number, "customer_name": "Cliente", "project_name": "Obra", "lot": "L1",
        "current_status": "EM_EXPEDICAO", "general_status": "EM_EXPEDICAO", "is_cancelled": False, "active": True, "version": 3,
    }
    row.update(extra)
    return row


def _item(iid, number, **extra):
    row = {
        "id": iid, "item_number": number, "product_code": f"COD{iid}", "description": f"Peca {iid}", "unit": "un", "active": True,
    }
    row.update(extra)
    return row


def _exp(eid, proposal_id, item_id, **extra):
    row = {
        "id": eid, "proposal_id": proposal_id, "proposal_item_id": item_id, "available_quantity": "10.0000",
        "separated_quantity": "0.0000", "delivered_quantity": "0.0000", "remanaged_quantity": "0.0000",
        "origin": "PRODUCAO", "status": "EM_SEPARACAO", "version": 2, "active": True,
    }
    row.update(extra)
    return row


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = ReplicaDatabase(Path(self._tmp.name) / "replica.db")

    def _load(self, proposals, items, exp, invoices=None):
        tables = {"proposals": proposals, "proposal_items": items, "expedition_items": exp}
        if invoices is not None:
            tables["fiscal_invoices"] = invoices
        self.db.replace_all(tables=tables, meta={META_CURSOR: 1, META_ENTITIES: ",".join(tables)})

    def _ids(self, **filters):
        return [row["id"] for row in expedition_items_view.list_expedition_items(self.db, **filters)["items"]]


class ExpeditionItemsViewTests(_Case):
    def test_row_has_the_api_shape(self):
        self._load([_proposal(1, "CP-1")], [_item(11, "1", unit="kg")], [_exp(21, 1, 11, separated_quantity="4.0000", delivered_quantity="1.0000", remanaged_quantity="0.5000")])
        self.assertEqual(
            expedition_items_view.list_expedition_items(self.db),
            {
                "items": [{
                    "id": 21, "proposal_id": 1, "proposal_item_id": 11, "item_number": "1", "product_code": "COD11",
                    "description": "Peca 11", "unit": "kg", "available_quantity": "10.0000", "separated_quantity": "4.0000",
                    "delivered_quantity": "1.0000", "remanaged_quantity": "0.5000", "pending_quantity": "8.5000",
                    "origin": "PRODUCAO", "status": "EM_SEPARACAO", "version": 2, "proposal_number": "CP-1",
                    "proposal_version": 3, "customer_name": "Cliente", "project_name": "Obra", "lot": "L1",
                }],
                "total": 1, "limit": 50, "offset": 0,
            },
        )

    def test_by_default_only_items_with_balance_that_are_not_delivered(self):
        self._load(
            [_proposal(1, "CP-1")], [_item(11, "1"), _item(12, "2"), _item(13, "3"), _item(14, "4")],
            [
                _exp(21, 1, 11),
                _exp(22, 1, 12, status="ENTREGUE", delivered_quantity="10.0000"),
                _exp(23, 1, 13, delivered_quantity="6.0000", remanaged_quantity="4.0000"),  # sem saldo
                _exp(24, 1, 14, delivered_quantity="4.0000"),
            ],
        )
        self.assertEqual(self._ids(), [21, 24])
        self.assertEqual(self._ids(pending_only=True), [21, 24])
        self.assertEqual(self._ids(pending_only="true"), [21, 24])

    def test_without_pending_only_the_delivered_come_back_only_for_proposals_still_in_expedition(self):
        self._load(
            [_proposal(1, "CP-1"), _proposal(2, "CP-2")], [_item(11, "1"), _item(12, "2"), _item(13, "1")],
            [
                _exp(21, 1, 11),
                _exp(22, 1, 12, status="ENTREGUE", delivered_quantity="10.0000"),
                _exp(23, 2, 13, status="ENTREGUE", delivered_quantity="10.0000"),  # CP-2 inteira entregue
            ],
        )
        self.assertEqual(self._ids(pending_only=False), [21, 22])
        self.assertEqual(self._ids(pending_only="false"), [21, 22])

    def test_cancelled_inactive_and_missing_rows_are_left_out(self):
        self._load(
            [_proposal(1, "CP-1"), _proposal(2, "CP-2", is_cancelled=True), _proposal(3, "CP-3", active=False), _proposal(4, "CP-4", current_status="CANCELADA"), _proposal(5, "CP-5", general_status="CANCELADA")],
            [_item(11, "1"), _item(12, "1"), _item(13, "1"), _item(14, "1"), _item(15, "1"), _item(16, "2", active=False), _item(17, "3")],
            [_exp(21, 1, 11), _exp(22, 2, 12), _exp(23, 3, 13), _exp(24, 4, 14), _exp(25, 5, 15), _exp(26, 1, 16), _exp(27, 1, 17, active=False)],
        )
        self.assertEqual(self._ids(), [21])

    def test_order_is_situation_then_proposal_then_item(self):
        self._load(
            [_proposal(1, "CP-1"), _proposal(2, "CP-2")], [_item(11, "1"), _item(12, "2"), _item(13, "1"), _item(14, "2")],
            [
                _exp(21, 1, 11, status="SEPARADO"),
                _exp(22, 1, 12, status="EM_SEPARACAO"),
                _exp(23, 2, 13, status="SEPARACAO_INICIADA"),
                _exp(24, 2, 14, status="EM_SEPARACAO"),
            ],
        )
        self.assertEqual(self._ids(), [22, 24, 23, 21])

    def test_status_filter_is_exact_and_case_insensitive(self):
        self._load([_proposal(1, "CP-1")], [_item(11, "1"), _item(12, "2")], [_exp(21, 1, 11, status="SEPARADO"), _exp(22, 1, 12)])
        self.assertEqual(self._ids(status="separado"), [21])
        self.assertEqual(self._ids(status=" EM_SEPARACAO "), [22])
        self.assertEqual(self._ids(status="ENTREGUE"), [])

    def test_search_looks_at_proposal_customer_site_lot_code_and_description(self):
        self._load(
            [_proposal(1, "CP-100", customer_name="Alfa Ltda", project_name="Usina Norte", lot="L-9"), _proposal(2, "CP-200", customer_name="Beta", project_name=None, lot=None)],
            [_item(11, "1", product_code="450.8", description="GRADE QDCA"), _item(12, "1", product_code=None, description="POSTE")],
            [_exp(21, 1, 11), _exp(22, 2, 12)],
        )
        for needle, expected in (("cp-100", [21]), ("ALFA", [21]), ("usina", [21]), ("l-9", [21]), ("450.8", [21]), ("grade", [21]), ("poste", [22]), ("  beta ", [22]), ("%", []), ("nada", [])):
            with self.subTest(needle=needle):
                self.assertEqual(self._ids(search=needle), expected)

    def test_search_finds_the_proposal_by_an_active_invoice_number(self):
        self._load(
            [_proposal(1, "CP-1"), _proposal(2, "CP-2")], [_item(11, "1"), _item(12, "1")], [_exp(21, 1, 11), _exp(22, 2, 12)],
            invoices=[
                {"id": 1, "proposal_id": 1, "invoice_number": "1001", "active": True},
                {"id": 2, "proposal_id": 2, "invoice_number": "2002", "active": False},
                {"id": 3, "proposal_id": 2, "invoice_number": "REGISTRO-7-20261003", "active": True},
            ],
        )
        self.assertEqual(self._ids(search="1001"), [21])
        self.assertEqual(self._ids(search="2002"), [])  # NF cancelada
        self.assertEqual(self._ids(search="REGISTRO"), [])  # marcador, nao e numero de nota

    def test_paging_and_total(self):
        self._load([_proposal(1, "CP-1")], [_item(i, str(i)) for i in range(11, 16)], [_exp(i + 10, 1, i) for i in range(11, 16)])
        page = expedition_items_view.list_expedition_items(self.db, limit=2, offset=1)
        self.assertEqual([row["id"] for row in page["items"]], [22, 23])
        self.assertEqual((page["total"], page["limit"], page["offset"]), (5, 2, 1))
        self.assertEqual(self._ids(limit=5, offset=50), [])

    def test_pending_quantity_is_never_negative(self):
        self._load([_proposal(1, "CP-1")], [_item(11, "1")], [_exp(21, 1, 11, available_quantity="3.0000", delivered_quantity="5.0000", status="ENTREGUE")])
        row = expedition_items_view.list_expedition_items(self.db, pending_only=False)
        self.assertEqual(row["items"], [])  # sem saldo e sem item pendente na proposta
        self._load([_proposal(1, "CP-1")], [_item(11, "1"), _item(12, "2")], [_exp(21, 1, 11, available_quantity="3.0000", delivered_quantity="5.0000", status="ENTREGUE"), _exp(22, 1, 12)])
        rows = expedition_items_view.list_expedition_items(self.db, pending_only=False)["items"]
        self.assertEqual({row["id"]: row["pending_quantity"] for row in rows}, {21: "0.0000", 22: "10.0000"})

    def test_the_view_refuses_filters_it_does_not_know(self):
        self.assertFalse(expedition_items_view.can_serve({"search": "x", "customer": "y"}))
        with self.assertRaises(ValueError):
            expedition_items_view.list_expedition_items(self.db, customer="y")

    def test_empty_replica_gives_an_empty_page(self):
        self.assertEqual(expedition_items_view.list_expedition_items(self.db), {"items": [], "total": 0, "limit": 50, "offset": 0})


class RequiredEntitiesTests(unittest.TestCase):
    def test_a_search_also_needs_the_invoices(self):
        self.assertEqual(expedition_items_view.required_entities({}), ("proposals", "proposal_items", "expedition_items"))
        self.assertEqual(expedition_items_view.required_entities({"search": "  "}), ("proposals", "proposal_items", "expedition_items"))
        self.assertIn("fiscal_invoices", expedition_items_view.required_entities({"search": "1001"}))

    def test_the_gate_keeps_the_list_on_the_api_without_the_needed_entities(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = ReplicaDatabase(Path(tmp) / "replica.db")
            database.replace_all(
                tables={"proposals": [], "proposal_items": [], "expedition_items": []},
                meta={META_CURSOR: 1, META_ENTITIES: "proposals,proposal_items,expedition_items"},
            )
            gate = ReplicaReadGate(database)
            gate.complete_sync(gate.begin_sync())
            self.assertTrue(gate.can_read(expedition_items_view.required_entities({})))
            # Usuario sem permissao de Fiscal: a busca vai a API (que e quem sabe das NFs).
            self.assertFalse(gate.can_read(expedition_items_view.required_entities({"search": "1001"})))


if __name__ == "__main__":
    unittest.main()
