from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.replica import expedition_view
from app.replica.replica_db import META_CURSOR, ReplicaDatabase


def _proposal(pid, number, **extra):
    row = {
        "id": pid, "proposal_number": number, "customer_name": "Cliente", "project_name": "Obra", "lot": "L1",
        "parent_proposal_id": None, "partial_number": None, "active": True, "is_cancelled": False,
        "current_status": "EM_SEPARACAO", "general_status": "EM_EXPEDICAO", "shipping_status": "EM_SEPARACAO",
        "version": 3, "updated_at": "2026-10-01T10:00:00+00:00",
    }
    row.update(extra)
    return row


def _item(iid, pid, **extra):
    row = {
        "id": iid, "proposal_id": pid, "proposal_item_id": iid * 10, "active": True, "status": "EM_SEPARACAO", "origin": "PRODUCAO",
        "available_quantity": "2.0000", "separated_quantity": "0.0000", "delivered_quantity": "0.0000", "remanaged_quantity": "0.0000",
    }
    row.update(extra)
    return row


class ExpeditionViewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = ReplicaDatabase(Path(self._tmp.name) / "replica.db")

    def _load(self, proposals, items):
        self.db.replace_all(tables={"proposals": proposals, "expedition_items": items}, meta={META_CURSOR: 1})

    def _list(self, **params):
        return expedition_view.list_expedition_proposals(self.db, **params)

    def _numbers(self, **params):
        return [row["proposal_number"] for row in self._list(**params)["items"]]

    def test_empty_replica(self):
        self._load([], [])
        self.assertEqual(self._list(), {"items": [], "total": 0, "limit": 50, "offset": 0})

    def test_only_proposals_with_pending_expedition_balance_are_listed(self):
        self._load(
            [_proposal(1, "PENDENTE"), _proposal(2, "SEM-ITENS"), _proposal(3, "ENTREGUE"), _proposal(4, "INATIVO"), _proposal(5, "REMANEJADO"), _proposal(6, "STATUS-ENTREGUE")],
            [
                _item(1, 1),
                _item(3, 3, delivered_quantity="2.0000"),
                _item(4, 4, active=False),
                _item(5, 5, remanaged_quantity="2.0000"),
                _item(6, 6, status="ENTREGUE"),
            ],
        )
        self.assertEqual(self._numbers(), ["PENDENTE"])

    def test_cancelled_or_inactive_proposals_are_hidden(self):
        self._load(
            [
                _proposal(1, "OK"),
                _proposal(2, "FLAG", is_cancelled=True),
                _proposal(3, "STATUS", current_status="CANCELADA"),
                _proposal(4, "GERAL", general_status="CANCELADA"),
                _proposal(5, "INATIVA", active=False),
            ],
            [_item(pid, pid) for pid in range(1, 6)],
        )
        self.assertEqual(self._numbers(), ["OK"])

    def test_order_is_status_then_most_recent_then_id(self):
        self._load(
            [
                _proposal(1, "ENTREGUE-PARCIAL", shipping_status="ENTREGUE_PARCIAL"),
                _proposal(2, "SEPARADO", shipping_status="SEPARADO"),
                _proposal(3, "INICIADA", shipping_status="SEPARACAO_INICIADA"),
                _proposal(4, "ANTIGA", updated_at="2026-09-01T10:00:00+00:00"),
                _proposal(5, "RECENTE", updated_at="2026-10-05T10:00:00.250000+00:00"),
                _proposal(6, "SEM-DATA", updated_at=None),
                _proposal(7, "EMPATE-A", updated_at="2026-09-15T10:00:00+00:00"),
                _proposal(8, "EMPATE-B", updated_at="2026-09-15T10:00:00+00:00"),
                _proposal(9, "DESCONHECIDO", shipping_status="OUTRO_STATUS"),
            ],
            [_item(pid, pid) for pid in range(1, 10)],
        )
        self.assertEqual(
            self._numbers(),
            ["RECENTE", "EMPATE-A", "EMPATE-B", "ANTIGA", "SEM-DATA", "INICIADA", "SEPARADO", "ENTREGUE-PARCIAL", "DESCONHECIDO"],
        )

    def test_mixed_proposal_in_another_area_shows_as_waiting_separation(self):
        self._load(
            [_proposal(1, "MISTA", shipping_status=None, current_status="EM_GALVANIZACAO"), _proposal(2, "SEPARADO", shipping_status="", current_status="SEPARADO")],
            [_item(1, 1), _item(2, 2)],
        )
        rows = {row["proposal_number"]: row for row in self._list()["items"]}
        self.assertEqual(rows["MISTA"]["shipping_status"], "EM_SEPARACAO")
        self.assertEqual(rows["MISTA"]["actions"][0]["id"], "START_SEPARATION")
        self.assertEqual(rows["SEPARADO"]["shipping_status"], "SEPARADO")
        self.assertEqual(self._numbers(), ["MISTA", "SEPARADO"])

    def test_search_is_case_insensitive_substring_over_number_customer_project_lot(self):
        self._load(
            [
                _proposal(1, "CP-100", customer_name="Alfa Ltda"),
                _proposal(2, "CP-200", customer_name="Beta", project_name="Usina Alfa"),
                _proposal(3, "CP-300", customer_name="Gama", project_name=None, lot="lote-ALFA"),
                _proposal(4, "CP-400", customer_name="Delta"),
            ],
            [_item(pid, pid) for pid in range(1, 5)],
        )
        self.assertEqual(sorted(self._numbers(search="  alfa ")), ["CP-100", "CP-200", "CP-300"])
        self.assertEqual(self._numbers(search="cp-4"), ["CP-400"])
        self.assertEqual(self._numbers(search="%"), [])
        self.assertEqual(self._list(search="alfa")["total"], 3)
        self.assertEqual(len(self._numbers(search="")), 4)

    def test_pagination_keeps_total(self):
        self._load([_proposal(pid, f"CP-{pid}", updated_at=None) for pid in range(1, 8)], [_item(pid, pid) for pid in range(1, 8)])
        page = self._list(limit=3, offset=3)
        self.assertEqual([row["id"] for row in page["items"]], [4, 5, 6])
        self.assertEqual((page["total"], page["limit"], page["offset"]), (7, 3, 3))
        self.assertEqual(self._list(limit=3, offset=30)["items"], [])

    def test_summary_totals_and_actions(self):
        self._load(
            [_proposal(1, "CP-1", shipping_status="SEPARACAO_INICIADA", parent_proposal_id=9, partial_number=2)],
            [
                _item(1, 1, available_quantity="10.0000", separated_quantity="4.0000", delivered_quantity="1.0000", remanaged_quantity="2.0000", origin="PRODUCAO"),
                _item(2, 1, available_quantity="5.5000", origin="GALVANIZACAO"),
                _item(3, 1, available_quantity="3.0000", separated_quantity="3.0000", delivered_quantity="3.0000", origin="ALMOXARIFADO"),
                _item(4, 1, available_quantity="99.0000", active=False),
            ],
        )
        row = self._list()["items"][0]
        self.assertEqual(
            row,
            {
                "id": 1, "parent_proposal_id": 9, "partial_number": 2, "proposal_number": "CP-1", "customer_name": "Cliente",
                "project_name": "Obra", "lot": "L1", "shipping_status": "SEPARACAO_INICIADA", "general_status": "EM_EXPEDICAO", "version": 3,
                "item_count": 2,
                "available_quantity": "15.5000",
                "separated_quantity": "4.0000",
                "delivered_quantity": "4.0000",
                "pending_quantity": "12.5000",
                "origins": ["GALVANIZACAO", "PRODUCAO"],
                "actions": [
                    {"id": "SEPARATE_ITEMS", "label": "Registrar separacao", "enabled": True, "reason": None},
                    {"id": "REGISTER_DELIVERY", "label": "Registrar entrega", "enabled": True, "reason": None},
                    {"id": "REMANAGE_MATERIAL", "label": "Remanejar material", "enabled": True, "reason": None},
                ],
            },
        )

    def test_delivery_action_explains_why_it_is_disabled(self):
        self._load([_proposal(1, "CP-1")], [_item(1, 1)])
        actions = {action["id"]: action for action in self._list()["items"][0]["actions"]}
        self.assertEqual(list(actions), ["START_SEPARATION", "SEPARATE_ITEMS", "REGISTER_DELIVERY", "REMANAGE_MATERIAL"])
        self.assertEqual(actions["REGISTER_DELIVERY"], {"id": "REGISTER_DELIVERY", "label": "Registrar entrega", "enabled": False, "reason": "Separe itens antes da entrega"})
        self.assertTrue(actions["START_SEPARATION"]["enabled"])


if __name__ == "__main__":
    unittest.main()
