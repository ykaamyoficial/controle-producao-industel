from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.replica import fiscal_view
from app.replica.read_gate import ReplicaReadGate
from app.replica.replica_db import META_CURSOR, META_ENTITIES, ReplicaDatabase
from app.services.api_proposal_storage import OfficialProposalApiStorage

TODAY = date(2026, 10, 6)


def _proposal(pid, number, **extra):
    row = {
        "id": pid, "proposal_number": number, "customer_name": "Cliente", "project_name": "Obra", "lot": "L1",
        "parent_proposal_id": None, "partial_number": None, "active": True, "is_cancelled": False,
        "current_area": "PRODUCAO", "current_status": "EM_PRODUCAO", "general_status": "EM_PRODUCAO", "shipping_status": None,
    }
    row.update(extra)
    return row


def _record(rid, pid, **extra):
    row = {
        "id": rid, "proposal_id": pid, "active": True, "status_fiscal": "FALTA_EMITIR_NOTA_FISCAL", "fiscal_situation": None,
        "entry_date": "2026-10-05", "last_emission_at": None, "invoice_withdrawn_at": None, "version": 1,
    }
    row.update(extra)
    return row


def _item(iid, rid, **extra):
    row = {"id": iid, "fiscal_record_id": rid, "proposal_id": 0, "active": True, "status": "PENDENTE", "total_weight": "10.0000", "billed_weight": "0.0000"}
    row.update(extra)
    return row


class _FiscalCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = ReplicaDatabase(Path(self._tmp.name) / "replica.db")
        patcher = patch.object(fiscal_view, "_today", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _load(self, proposals, records, items=()):
        self.db.replace_all(
            tables={"proposals": list(proposals), "fiscal_records": list(records), "fiscal_items": list(items)},
            meta={META_CURSOR: 1, META_ENTITIES: "proposals,fiscal_records,fiscal_items"},
        )


class FiscalViewTests(_FiscalCase):
    def _list(self, **params):
        return fiscal_view.list_fiscal_records(self.db, **params)

    def _numbers(self, **params):
        return [row["proposal_number"] for row in self._list(**params)["items"]]

    def test_empty_replica(self):
        self._load([], [])
        self.assertEqual(self._list(), {"items": [], "total": 0, "limit": 50, "offset": 0})
        self.assertEqual(
            fiscal_view.fiscal_indicators(self.db),
            {"falta_emitir": 0, "nf_parcial": 0, "nf_emitida": 0, "pendencia_critica": 0, "entregues_sem_nf": 0,
             "peso_pendente": "0.0000", "peso_faturado": "0.0000", "mais_7_dias_sem_emissao": 0},
        )

    def test_universe_excludes_inactive_cancelled_and_children_outside_expedition(self):
        self._load(
            [
                _proposal(1, "MAE"),
                _proposal(2, "FILHA-PRODUCAO", parent_proposal_id=1, current_area="PRODUCAO"),
                _proposal(3, "FILHA-EXPEDICAO", parent_proposal_id=1, current_area="EXPEDICAO"),
                _proposal(4, "CANCELADA", is_cancelled=True),
                _proposal(5, "STATUS-CANCELADA", general_status="CANCELADA"),
                _proposal(6, "REGISTRO-INATIVO"),
                _proposal(7, "PROPOSTA-INATIVA", active=False),
            ],
            [_record(pid, pid) for pid in range(1, 6)] + [_record(6, 6, active=False), _record(7, 7), _record(8, 99)],
        )
        # Proposta inativa nao sai da lista fiscal (a API tambem nao filtra `active` aqui).
        self.assertEqual(sorted(self._numbers()), ["FILHA-EXPEDICAO", "MAE", "PROPOSTA-INATIVA"])

    def test_situation_precedence(self):
        cases = [
            ({"fiscal_situation": "NF_RETIRADA_CLIENTE", "status_fiscal": "NOTA_FISCAL_EMITIDA"}, "ENTREGUE", "NF_RETIRADA_CLIENTE"),
            ({"status_fiscal": "NOTA_FISCAL_EMITIDA"}, "ENTREGUE", "NF_EMITIDA"),
            ({"status_fiscal": "NOTA_FISCAL_PARCIAL"}, "ENTREGUE", "NF_PARCIAL"),
            ({}, "ENTREGUE", "PENDENCIA_FISCAL_CRITICA"),
            ({}, "SEPARADO", "DISPONIVEL_PARA_EMISSAO"),
            ({}, "ENTREGUE_PARCIAL", "DISPONIVEL_PARA_EMISSAO"),
            ({}, None, "CP_EM_PROCESSAMENTO"),
            ({}, "OUTRO", "CP_EM_PROCESSAMENTO"),
        ]
        for record_extra, shipping_status, expected in cases:
            with self.subTest(expected=expected, shipping_status=shipping_status):
                self.assertEqual(fiscal_view.situation(_record(1, 1, **record_extra), _proposal(1, "X", shipping_status=shipping_status)), expected)

    def test_order_is_situation_then_entry_date_then_newest_id(self):
        self._load(
            [
                _proposal(1, "RETIRADA"), _proposal(2, "EMITIDA"), _proposal(3, "PROCESSANDO"), _proposal(4, "PARCIAL"),
                _proposal(5, "DISPONIVEL", shipping_status="SEPARADO"), _proposal(6, "CRITICA-NOVA", shipping_status="ENTREGUE"),
                _proposal(7, "CRITICA-ANTIGA", shipping_status="ENTREGUE"), _proposal(8, "CRITICA-MESMA-DATA", shipping_status="ENTREGUE"),
            ],
            [
                _record(1, 1, status_fiscal="NOTA_FISCAL_EMITIDA", fiscal_situation="NF_RETIRADA_CLIENTE"),
                _record(2, 2, status_fiscal="NOTA_FISCAL_EMITIDA"),
                _record(3, 3),
                _record(4, 4, status_fiscal="NOTA_FISCAL_PARCIAL"),
                _record(5, 5),
                _record(6, 6, entry_date="2026-10-04"),
                _record(7, 7, entry_date="2026-09-01"),
                _record(8, 8, entry_date="2026-10-04"),
            ],
        )
        self.assertEqual(
            self._numbers(),
            ["CRITICA-ANTIGA", "CRITICA-MESMA-DATA", "CRITICA-NOVA", "DISPONIVEL", "PARCIAL", "PROCESSANDO", "EMITIDA", "RETIRADA"],
        )

    def test_filters_by_status_situation_and_search(self):
        self._load(
            [_proposal(1, "CP-1", customer_name="Alfa", shipping_status="ENTREGUE"), _proposal(2, "CP-2", customer_name="Beta"), _proposal(3, "CP-3", customer_name="Alfa Sul")],
            [_record(1, 1), _record(2, 2, status_fiscal="NOTA_FISCAL_EMITIDA"), _record(3, 3)],
        )
        self.assertEqual(self._numbers(status="NOTA_FISCAL_EMITIDA"), ["CP-2"])
        self.assertEqual(self._numbers(situation_filter="PENDENCIA_FISCAL_CRITICA"), ["CP-1"])
        self.assertEqual(sorted(self._numbers(search=" ALFA ")), ["CP-1", "CP-3"])
        self.assertEqual(self._numbers(status="FALTA_EMITIR_NOTA_FISCAL", situation_filter="CP_EM_PROCESSAMENTO", search="alfa"), ["CP-3"])
        self.assertEqual(self._list(search="alfa")["total"], 2)

    def test_pagination_keeps_total(self):
        self._load([_proposal(pid, f"CP-{pid}") for pid in range(1, 8)], [_record(pid, pid) for pid in range(1, 8)])
        page = self._list(limit=3, offset=2)
        self.assertEqual([row["id"] for row in page["items"]], [5, 4, 3])
        self.assertEqual((page["total"], page["limit"], page["offset"]), (7, 3, 2))

    def test_summary_weights_counts_and_actions(self):
        self._load(
            [_proposal(1, "CP-1", parent_proposal_id=None, partial_number=None, shipping_status="SEPARADO", current_area="EXPEDICAO", current_status="SEPARADO")],
            [_record(9, 1, status_fiscal="NOTA_FISCAL_PARCIAL", entry_date="2026-09-01", last_emission_at="2026-09-20T12:30:00+00:00", version=4)],
            [
                _item(1, 9, status="FATURADO", total_weight="10.0000", billed_weight="10.0000"),
                _item(2, 9, status="PARCIAL", total_weight="20.5000", billed_weight="5.2500"),
                _item(3, 9, status="PENDENTE", total_weight=None, billed_weight="0.0000"),
                _item(4, 9, status="PENDENTE", total_weight="0.0000", billed_weight="0.0000"),
                _item(5, 9, active=False, total_weight="999.0000", billed_weight="999.0000"),
            ],
        )
        self.assertEqual(
            self._list()["items"][0],
            {
                "id": 9, "proposal_id": 1, "parent_proposal_id": None, "partial_number": None, "proposal_number": "CP-1",
                "customer_name": "Cliente", "project_name": "Obra", "lot": "L1", "current_area": "EXPEDICAO", "current_status": "SEPARADO",
                "shipping_status": "SEPARADO", "status_fiscal": "NOTA_FISCAL_PARCIAL", "fiscal_situation": "NF_PARCIAL",
                "entry_date": "2026-09-01", "last_emission_at": "2026-09-20T12:30:00Z", "invoice_withdrawn_at": None, "version": 4,
                "item_count": 4, "pending_items": 3, "billed_items": 1,
                "total_weight": "30.5000", "billed_weight": "15.2500", "pending_weight": "15.2500",
                "weight_known_items": 2, "weight_total_items": 4, "weight_complete": False,
                "critical_pending": False, "older_than_7_days": False,
                "actions": [
                    {"id": "REGISTER_FISCAL_INVOICE", "label": "Registrar emissao fiscal", "enabled": True, "reason": None},
                    {"id": "VIEW_FISCAL_DETAIL", "label": "Ver detalhes", "enabled": True, "reason": None},
                ],
            },
        )

    def test_actions_for_issued_and_withdrawn_invoices(self):
        self._load(
            [_proposal(1, "EMITIDA"), _proposal(2, "RETIRADA")],
            [_record(1, 1, status_fiscal="NOTA_FISCAL_EMITIDA"), _record(2, 2, status_fiscal="NOTA_FISCAL_EMITIDA", fiscal_situation="NF_RETIRADA_CLIENTE")],
            [_item(1, 1, status="FATURADO"), _item(2, 2, status="FATURADO")],
        )
        rows = {row["proposal_number"]: row for row in self._list()["items"]}
        self.assertEqual([action["id"] for action in rows["EMITIDA"]["actions"]], ["REGISTER_FISCAL_INVOICE", "VIEW_FISCAL_DETAIL", "MARK_INVOICE_WITHDRAWN"])
        self.assertEqual(rows["EMITIDA"]["actions"][0], {"id": "REGISTER_FISCAL_INVOICE", "label": "Registrar emissao fiscal", "enabled": False, "reason": "Sem saldo fiscal pendente"})
        self.assertEqual([action["id"] for action in rows["RETIRADA"]["actions"]], ["REGISTER_FISCAL_INVOICE", "VIEW_FISCAL_DETAIL"])
        self.assertTrue(rows["EMITIDA"]["weight_complete"])

    def test_older_than_7_days_needs_more_than_seven_days_without_emission(self):
        self._load(
            [_proposal(pid, f"CP-{pid}") for pid in range(1, 5)],
            [
                _record(1, 1, entry_date="2026-09-28"),  # 8 dias
                _record(2, 2, entry_date="2026-09-29"),  # 7 dias exatos
                _record(3, 3, entry_date="2026-09-01", last_emission_at="2026-09-02T00:00:00+00:00"),
                _record(4, 4, entry_date="2026-09-01", status_fiscal="NOTA_FISCAL_EMITIDA"),
            ],
        )
        flags = {row["id"]: row["older_than_7_days"] for row in self._list()["items"]}
        self.assertEqual(flags, {1: True, 2: False, 3: False, 4: False})
        self.assertEqual(fiscal_view.fiscal_indicators(self.db)["mais_7_dias_sem_emissao"], 1)

    def test_indicators(self):
        self._load(
            [
                _proposal(1, "FALTA"), _proposal(2, "PARCIAL"), _proposal(3, "EMITIDA"), _proposal(4, "CRITICA", shipping_status="ENTREGUE"),
                _proposal(5, "CANCELADA", is_cancelled=True),
            ],
            [
                _record(1, 1), _record(2, 2, status_fiscal="NOTA_FISCAL_PARCIAL"), _record(3, 3, status_fiscal="NOTA_FISCAL_EMITIDA"),
                _record(4, 4), _record(5, 5),
            ],
            [
                _item(1, 1, total_weight="10.0000", billed_weight="0.0000"),
                _item(2, 2, total_weight="20.0000", billed_weight="8.0000"),
                _item(3, 2, total_weight=None, billed_weight="1.5000"),
                _item(4, 3, total_weight="30.0000", billed_weight="30.0000"),
                _item(5, 4, total_weight="4.0000", billed_weight="0.0000"),
                _item(6, 4, active=False, total_weight="100.0000", billed_weight="100.0000"),
                _item(7, 5, total_weight="500.0000", billed_weight="500.0000"),
            ],
        )
        self.assertEqual(
            fiscal_view.fiscal_indicators(self.db),
            {"falta_emitir": 2, "nf_parcial": 1, "nf_emitida": 1, "pendencia_critica": 1, "entregues_sem_nf": 1,
             "peso_pendente": "26.0000", "peso_faturado": "39.5000", "mais_7_dias_sem_emissao": 0},
        )


class StorageFiscalReadTests(_FiscalCase):
    def setUp(self):
        super().setUp()
        self.storage = OfficialProposalApiStorage()
        self.api_calls: list[tuple[str, dict]] = []

        def fake_client():
            def list_fiscal_records(token, **filters):
                self.api_calls.append(("list", filters))
                return {"items": [{"id": 77, "proposal_id": 7, "proposal_number": "DA-API"}], "total": 1}

            def fiscal_indicators(token):
                self.api_calls.append(("indicators", {}))
                return {"falta_emitir": 99}

            return SimpleNamespace(close=lambda: None), SimpleNamespace(list_fiscal_records=list_fiscal_records, fiscal_indicators=fiscal_indicators), "token"

        self.storage._client = fake_client
        self._load([_proposal(1, "DA-REPLICA")], [_record(5, 1)], [_item(1, 5)])
        self.gate = ReplicaReadGate(self.db)

    def _open(self):
        self.gate.complete_sync(self.gate.begin_sync())
        self.storage.replica_gate = self.gate

    def test_without_gate_uses_the_api_with_the_translated_filters(self):
        page = self.storage.fiscal_rows_page({"text": "abc", "status_fiscal": "NOTA_FISCAL_EMITIDA", "situacao_fiscal": "NF_EMITIDA", "limit": 20, "offset": 40})
        self.assertEqual(self.api_calls, [("list", {"search": "abc", "status": "NOTA_FISCAL_EMITIDA", "situation": "NF_EMITIDA", "limit": 20, "offset": 40})])
        self.assertEqual(page["total"], 1)
        self.assertEqual(self.storage.fiscal_indicators(), {"falta_emitir": 99})

    def test_open_gate_reads_list_and_indicators_from_the_replica(self):
        self._open()
        page = self.storage.fiscal_rows_page({"limit": 50, "offset": 0})
        self.assertEqual([row["fiscal_processo_id"] for row in page["items"]], [5])
        self.assertEqual(page["total"], 1)
        self.assertEqual(self.storage.fiscal_rows({})[0]["processo_id"], 1)
        self.assertEqual(self.storage.fiscal_indicators()["falta_emitir"], 1)
        self.assertEqual(self.api_calls, [])

    def test_same_rows_whatever_the_source(self):
        api_shaped = fiscal_view.list_fiscal_records(self.db, limit=50, offset=0)

        def fake_client():
            return SimpleNamespace(close=lambda: None), SimpleNamespace(list_fiscal_records=lambda token, **filters: api_shaped), "token"

        self.storage._client = fake_client
        from_api = self.storage.fiscal_rows_page({})
        self._open()
        self.assertEqual(self.storage.fiscal_rows_page({}), from_api)

    def test_closed_gate_falls_back_to_the_api(self):
        self._open()
        self.gate.write_started()
        self.gate.write_finished()
        self.storage.fiscal_rows_page({})
        self.storage.fiscal_indicators()
        self.assertEqual([name for name, _filters in self.api_calls], ["list", "indicators"])

    def test_user_without_fiscal_entities_uses_the_api(self):
        self.db.replace_all(tables={"proposals": [_proposal(1, "X")]}, meta={META_CURSOR: 1, META_ENTITIES: "proposals,expedition_items"})
        self._open()
        self.storage.fiscal_rows_page({})
        self.assertEqual([name for name, _filters in self.api_calls], ["list"])

    def test_replica_error_falls_back_to_the_api(self):
        self._open()
        self.db.apply_changes([{"entity": "fiscal_records", "id": 6, "op": "upsert", "row": {"id": 6, "proposal_id": 1, "active": True, "entry_date": None}}], cursor=2)
        self.storage.fiscal_rows_page({})
        self.assertEqual([name for name, _filters in self.api_calls], ["list"])


if __name__ == "__main__":
    unittest.main()
