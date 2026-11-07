"""Almoxarifado: baixa no estoque (POST /warehouse/proposals/{id}/stock-deduction) e pista do desfazer."""

from __future__ import annotations

import asyncio
import unittest

from sqlalchemy import select, text

from api.app.database.session import get_engine, get_sessionmaker
from api.app.modules.proposals.models import ProposalEvent
from api.tests._warehouse_support import WarehouseApiTestCase, _integration_enabled

API = "/api/v1"


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class WarehouseStockDeductionTests(WarehouseApiTestCase):
    # ---- helpers ------------------------------------------------------------
    def _version(self, proposal_id):
        return self._row(proposal_id).version

    def _deduct(self, proposal_id, deducted=True, *, version=None, headers=None, rid=None):
        merged = {**(headers or self.headers), **({"X-Request-ID": rid} if rid else {})}
        return self.client.post(
            f"{API}/warehouse/proposals/{proposal_id}/stock-deduction",
            json={"version": version if version is not None else self._version(proposal_id), "deducted": deducted},
            headers=merged,
        )

    def _status(self, proposal_id, status, rid=None):
        merged = {**self.headers, **({"X-Request-ID": rid} if rid else {})}
        return self.client.post(f"{API}/warehouse/proposals/{proposal_id}/status", json={"version": self._version(proposal_id), "status": status}, headers=merged)

    def _enter(self, number):
        response = self.client.post(f"{API}/warehouse/proposals/enter", json={"numbers": [number]}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"][0]["result"]

    def _stock_events(self, proposal_id):
        async def go():
            async with get_sessionmaker()() as session:
                rows = (await session.execute(
                    select(ProposalEvent).where(ProposalEvent.proposal_id == proposal_id, ProposalEvent.event_type.like("WAREHOUSE_STOCK_%")).order_by(ProposalEvent.id)
                )).scalars().all()
                return [(row.event_type, row.request_id, row.to_status, row.metadata_) for row in rows]

        return asyncio.run(go())

    def _candidate(self, proposal_id, lane=None, headers=None):
        response = self.client.get(f"{API}/proposals/{proposal_id}/undo/candidate", params={"lane": lane or "GERAL"}, headers=headers or self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _undo(self, proposal_id, target, key):
        return self.client.post(
            f"{API}/proposals/{proposal_id}/undo",
            json={"expected_version": self._version(proposal_id), "target_request_id": target, "reason": "Engano", "idempotency_key": key},
            headers=self.headers,
        )

    # ---- baixa --------------------------------------------------------------
    def test_confirmar_e_desfazer_baixa(self):
        proposal_id = self._make("B-1", warehouse_status="SEPARADO")
        before = self._version(proposal_id)
        self.assertEqual(self._warehouse_list()["pending_stock_deduction"], 1)

        confirmed = self._deduct(proposal_id)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        body = confirmed.json()
        self.assertTrue(body["stock_deducted"])
        self.assertTrue(body["stock_deducted_at"])
        self.assertEqual((body["id"], body["warehouse_status"], body["version"]), (proposal_id, "SEPARADO", before + 1))
        row = self._row(proposal_id)
        self.assertEqual(row.warehouse_stock_deducted_by_user_id, 1)
        self.assertEqual(self._warehouse_list()["pending_stock_deduction"], 0)
        # SEPARADO baixado continua na aba
        self.assertEqual(self._warehouse_numbers(), {"B-1"})

        reverted = self._deduct(proposal_id, False)
        self.assertEqual(reverted.status_code, 200, reverted.text)
        self.assertFalse(reverted.json()["stock_deducted"])
        self.assertIsNone(reverted.json()["stock_deducted_at"])
        row = self._row(proposal_id)
        self.assertIsNone(row.warehouse_stock_deducted_at)
        self.assertIsNone(row.warehouse_stock_deducted_by_user_id)
        self.assertEqual(self._warehouse_list()["pending_stock_deduction"], 1)
        self.assertEqual([event[0] for event in self._stock_events(proposal_id)], ["WAREHOUSE_STOCK_DEDUCTED", "WAREHOUSE_STOCK_DEDUCTION_REVERTED"])

    def test_entregue_sai_da_aba_com_baixa_e_volta_ao_desfazer(self):
        proposal_id = self._make("B-ENT", warehouse_status="ALMOXARIFADO_ENTREGUE")
        self.assertEqual(self._warehouse_numbers(), {"B-ENT"})
        self.assertEqual(self._deduct(proposal_id).status_code, 200)
        self.assertEqual(self._warehouse_numbers(), set())
        self.assertEqual(self._deduct(proposal_id, False).status_code, 200)
        self.assertEqual(self._warehouse_numbers(), {"B-ENT"})

    def test_so_confirma_de_separado_em_diante(self):
        for index, status in enumerate(("SEPARADO", "ALMOXARIFADO_ENTREGUE_PARCIAL", "ALMOXARIFADO_ENTREGUE")):
            with self.subTest(status=status):
                proposal_id = self._make(f"B-OK-{index}", warehouse_status=status)
                self.assertEqual(self._deduct(proposal_id).status_code, 200)
        for index, status in enumerate((None, "AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO", "SEM_PARAFUSOS")):
            with self.subTest(status=status):
                proposal_id = self._make(f"B-NO-{index}", **({"warehouse_status": status} if status else {}))
                response = self._deduct(proposal_id)
                self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "PROPOSAL_INVALID_STATE"))
                self.assertIsNone(self._row(proposal_id).warehouse_stock_deducted_at)

    def test_versao_velha_da_409_e_nao_grava(self):
        proposal_id = self._make("B-VER", warehouse_status="SEPARADO")
        self._set(proposal_id, version=3)  # outro usuario ja mexeu na proposta
        stale = 2
        response = self._deduct(proposal_id, version=stale)
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "PROPOSAL_VERSION_CONFLICT"))
        self.assertIsNone(self._row(proposal_id).warehouse_stock_deducted_at)
        self.assertEqual(self._stock_events(proposal_id), [])

    def test_idempotente_sem_evento_novo_nem_nova_versao(self):
        proposal_id = self._make("B-IDEM", warehouse_status="SEPARADO")
        # desfazer baixa que ja esta pendente
        pending = self._deduct(proposal_id, False)
        self.assertEqual(pending.status_code, 200, pending.text)
        self.assertEqual(self._stock_events(proposal_id), [])
        version = self._version(proposal_id)
        first = self._deduct(proposal_id)
        self.assertEqual(first.status_code, 200)
        after_first = self._version(proposal_id)
        self.assertEqual(after_first, version + 1)
        # repetir a confirmacao (ate com versao velha, como um retry) nao duplica
        again = self._deduct(proposal_id, version=version)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertTrue(again.json()["stock_deducted"])
        self.assertEqual(self._version(proposal_id), after_first)
        self.assertEqual(len(self._stock_events(proposal_id)), 1)

    def test_proposta_inexistente_e_cancelada(self):
        self.assertEqual(self._deduct(99999, version=1).status_code, 404)
        proposal_id = self._make("B-CANC", warehouse_status="SEPARADO", is_cancelled=True)
        response = self._deduct(proposal_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "PROPOSAL_CANCELLED_TERMINAL")

    def test_permissao_exige_alterar_status(self):
        proposal_id = self._make("B-PERM", warehouse_status="SEPARADO")
        viewer = self._seed_user("so_ver", ["proposals.view"])
        self.assertEqual(self._deduct(proposal_id, headers=viewer).status_code, 403)
        operator = self._seed_user("operador", ["proposals.view", "proposals.change_status"])
        self.assertEqual(self._deduct(proposal_id, headers=operator).status_code, 200)
        self.assertEqual(self._row(proposal_id).warehouse_stock_deducted_by_user_id, 3)  # admin=1, so_ver=2, operador=3

    def test_corpo_invalido_da_422(self):
        proposal_id = self._make("B-422", warehouse_status="SEPARADO")
        url = f"{API}/warehouse/proposals/{proposal_id}/stock-deduction"
        self.assertEqual(self.client.post(url, json={"version": 1}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post(url, json={"version": 1, "deducted": True, "x": 1}, headers=self.headers).status_code, 422)

    # ---- transicoes (D11) ---------------------------------------------------
    def test_em_separacao_pode_ir_para_sem_parafusos_mas_separado_nao(self):
        a = self._make("T-A", warehouse_status="EM_SEPARACAO")
        self.assertEqual(self._status(a, "SEM_PARAFUSOS").status_code, 200)
        self.assertEqual(self._row(a).warehouse_status, "SEM_PARAFUSOS")
        b = self._make("T-B", warehouse_status="SEPARADO")
        denied = self._status(b, "SEM_PARAFUSOS")
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (409, "PROPOSAL_INVALID_STATE"))
        self.assertEqual(self._row(b).warehouse_status, "SEPARADO")

    # ---- pista do desfazer --------------------------------------------------
    def test_baixa_nao_trava_o_desfazer_geral(self):
        proposal_id = self._make("L-GERAL", warehouse_status="SEPARADO")
        self.assertEqual(self._deduct(proposal_id, rid="rid-baixa").status_code, 200)
        geral = self._candidate(proposal_id, "GERAL")
        self.assertEqual(geral["action"]["event_type"], "PROPOSAL_CREATED")
        self.assertNotEqual(geral["action"]["request_id"], "rid-baixa")
        self.assertEqual(geral["lane"], "GERAL")

    def test_desfazer_status_continua_oferecido_com_baixa_e_zera_a_baixa(self):
        self.assertEqual(self._enter_with_number("D-1"), "ENTROU")
        proposal_id = self._id("D-1")
        self.assertEqual(self._status(proposal_id, "SEPARADO", rid="rid-sep").status_code, 200)
        self.assertEqual(self._status(proposal_id, "ALMOXARIFADO_ENTREGUE", rid="rid-ent").status_code, 200)
        self.assertEqual(self._deduct(proposal_id, rid="rid-baixa").status_code, 200)
        self.assertEqual(self._warehouse_numbers(), set())  # entregue com baixa sai da aba

        candidate = self._candidate(proposal_id, "ALMOXARIFADO")
        self.assertEqual((candidate["handler"], candidate["lane"], candidate["can_undo"]), ("WAREHOUSE_STATUS", "ALMOXARIFADO", True), candidate)
        self.assertEqual(candidate["action"]["request_id"], "rid-ent")
        self.assertEqual(candidate["blockers"], [])
        changes = {change["field"]: change for change in candidate["changes"]}
        self.assertEqual(set(changes), {"warehouse_status", "warehouse_stock_deducted_at"})
        self.assertEqual(changes["warehouse_stock_deducted_at"]["label"], "Baixa no estoque")
        self.assertEqual((changes["warehouse_stock_deducted_at"]["current_value"], changes["warehouse_stock_deducted_at"]["restored_value"]), ("Confirmada", "Pendente"))

        response = self._undo(proposal_id, "rid-ent", "key-d1-a")
        self.assertEqual(response.status_code, 200, response.text)
        row = self._row(proposal_id)
        self.assertEqual(row.warehouse_status, "SEPARADO")
        self.assertIsNone(row.warehouse_stock_deducted_at)
        self.assertIsNone(row.warehouse_stock_deducted_by_user_id)
        # voltou para a aba e o contador volta a contar
        listed = self._warehouse_list()
        self.assertEqual(listed["pending_stock_deduction"], 1)
        self.assertEqual({r["proposal_number"] for r in listed["items"]}, {"D-1"})
        self.assertFalse(listed["items"][0]["stock_deducted"])

        # novo topo da pista: o SEPARADO (a baixa continua fora da pilha)
        again = self._candidate(proposal_id, "ALMOXARIFADO")
        self.assertEqual(again["action"]["request_id"], "rid-sep")

    def test_desfazer_ate_o_status_nulo_some_da_aba(self):
        self._enter_with_number("D-2")
        proposal_id = self._id("D-2")
        entry_rid = self._candidate(proposal_id, "ALMOXARIFADO")["action"]["request_id"]
        self.assertEqual(self._status(proposal_id, "SEPARADO", rid="rid-sep2").status_code, 200)
        self.assertEqual(self._deduct(proposal_id, rid="rid-baixa2").status_code, 200)
        self.assertEqual(self._warehouse_list()["pending_stock_deduction"], 0)

        self.assertEqual(self._undo(proposal_id, "rid-sep2", "key-d2-a").status_code, 200)
        row = self._row(proposal_id)
        self.assertEqual((row.warehouse_status, row.warehouse_stock_deducted_at), ("EM_SEPARACAO", None))
        self.assertEqual(self._undo(proposal_id, entry_rid, "key-d2-b").status_code, 200)
        row = self._row(proposal_id)
        self.assertEqual((row.warehouse_status, row.warehouse_stock_deducted_at, row.warehouse_stock_deducted_by_user_id), (None, None, None))
        self.assertEqual(self._warehouse_numbers(), set())
        self.assertEqual(self._warehouse_list()["pending_stock_deduction"], 0)

    def test_nao_desfaz_a_baixa_pelo_desfazer_da_fase_14(self):
        self._enter_with_number("D-3")
        proposal_id = self._id("D-3")
        self.assertEqual(self._status(proposal_id, "SEPARADO").status_code, 200)
        self.assertEqual(self._deduct(proposal_id, rid="rid-baixa3").status_code, 200)
        refused = self._undo(proposal_id, "rid-baixa3", "key-d3-baixa")
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (409, "UNDO_NOT_SUPPORTED"))
        self.assertIsNotNone(self._row(proposal_id).warehouse_stock_deducted_at)

    # ---- sem notificacao (decisao 2026-11-07) --------------------------------
    def _notifications(self):
        async def go():
            async with get_engine().begin() as conn:
                return (await conn.execute(text("SELECT (SELECT count(*) FROM notifications), (SELECT count(*) FROM notification_deliveries)"))).one()

        return tuple(asyncio.run(go()))

    def _watched(self, number, creator_id, participant_id, **fields):
        """Proposta que normalmente notificaria: criador e participante do chat sao outros usuarios (nao o ator)."""
        proposal_id = self._make(number, created_by=creator_id, **fields)

        async def go():
            async with get_engine().begin() as conn:
                conversation_id = (await conn.execute(text("INSERT INTO chat_conversations (kind, proposal_id) VALUES ('PROPOSTA', :p) RETURNING id"), {"p": proposal_id})).scalar_one()
                await conn.execute(text("INSERT INTO chat_messages (conversation_id, author_user_id, body) VALUES (:c, :u, 'oi')"), {"c": conversation_id, "u": participant_id})

        asyncio.run(go())
        return proposal_id

    def test_baixa_nao_cria_notificacao_ao_confirmar_nem_ao_desfazer_inclusive_em_lote(self):
        self._seed_user("criador", ["proposals.view"])  # id 2
        self._seed_user("participante", ["proposals.view"])  # id 3
        ids = [self._watched(f"N-{i}", 2, 3, warehouse_status="SEPARADO") for i in range(3)]
        control = self._watched("N-CTRL", 2, 3, warehouse_status="EM_SEPARACAO")

        # controle: o avanco de status continua notificando criador e participante
        self.assertEqual(self._status(control, "SEPARADO").status_code, 200)
        notified = self._notifications()
        self.assertGreater(notified[0], 0, "o controle precisa notificar, senao o teste nao prova nada")

        for deducted in (True, False):  # "em lote" = o Desktop chama a rota uma vez por proposta
            for proposal_id in ids:
                self.assertEqual(self._deduct(proposal_id, deducted).status_code, 200)
            self.assertEqual(self._notifications(), notified)
        for proposal_id in ids:
            self.assertEqual([event[0] for event in self._stock_events(proposal_id)], ["WAREHOUSE_STOCK_DEDUCTED", "WAREHOUSE_STOCK_DEDUCTION_REVERTED"])
            history = self.client.get(f"{API}/proposals/{proposal_id}/history", headers=self.headers)
            self.assertEqual(history.status_code, 200, history.text)
            self.assertTrue({"WAREHOUSE_STOCK_DEDUCTED", "WAREHOUSE_STOCK_DEDUCTION_REVERTED"} <= {row["event_type"] for row in history.json()})
            activities = self.client.get(f"{API}/proposals/{proposal_id}/activities", headers=self.headers)
            self.assertEqual(activities.status_code, 200, activities.text)
            headlines = [row["headline"] for row in activities.json() if row["event_type"].startswith("WAREHOUSE_STOCK_")]
            self.assertEqual(len(headlines), 2, headlines)
            self.assertTrue(all("baixa no estoque" in headline for headline in headlines), headlines)

    def test_avancar_o_status_pelo_fluxo_normal_mantem_a_baixa(self):
        proposal_id = self._make("KEEP-1", warehouse_status="SEPARADO")
        self.assertEqual(self._deduct(proposal_id).status_code, 200)
        self.assertEqual(self._status(proposal_id, "ALMOXARIFADO_ENTREGUE").status_code, 200)
        row = self._row(proposal_id)
        self.assertEqual(row.warehouse_status, "ALMOXARIFADO_ENTREGUE")
        self.assertIsNotNone(row.warehouse_stock_deducted_at)
        self.assertEqual(self._warehouse_numbers(), set())  # entregue com baixa nao reaparece na aba

    # ---- sync legado: status do Almoxarifado mudou por fora zera a baixa -----------------------------
    def _sync(self, warehouse_status, seed):
        proposal = {
            "legacy_id": 900, "proposal_number": "SYNC-1", "customer_name": "Cliente Legado", "current_area": "EXPEDICAO", "current_status": "SEPARADO",
            "warehouse_status": warehouse_status, "source": "sqlite", "source_hash": f"{seed:064d}",
            "items": [{"legacy_id": 9001, "item_number": "1", "description": "Item", "quantity": "1.0000", "unit_weight": "1.0000", "total_weight": "1.0000", "produce_internally": "sim", "requires_galvanization": "nao", "source_hash": f"{9001:064d}"}],
        }
        batch = {"source_identifier": "legacy.db", "dry_run": False, "batch_number": 1, "batch_total": 1, "proposals": [proposal]}
        response = self.client.post(f"{API}/admin/sync/proposals", json=batch, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated"] + response.json()["created"], 1, response.text)

    def test_sync_legado_zera_a_baixa_so_quando_o_status_do_almoxarifado_muda(self):
        self._sync("SEPARADO", 1)
        proposal_id = self._id("SYNC-1")
        self.assertEqual(self._deduct(proposal_id).status_code, 200)
        self._sync("SEPARADO", 2)  # hash novo, mesmo status: a baixa fica
        row = self._row(proposal_id)
        self.assertEqual((row.warehouse_status, row.warehouse_stock_deducted_by_user_id), ("SEPARADO", 1))
        self.assertIsNotNone(row.warehouse_stock_deducted_at)
        self._sync("ALMOXARIFADO_ENTREGUE", 3)  # status mudou: a baixa zera no mesmo passo
        row = self._row(proposal_id)
        self.assertEqual(row.warehouse_status, "ALMOXARIFADO_ENTREGUE")
        self.assertIsNone(row.warehouse_stock_deducted_at)
        self.assertIsNone(row.warehouse_stock_deducted_by_user_id)

    # ---- util ---------------------------------------------------------------
    def _enter_with_number(self, number):
        self._make(number)
        return self._enter(number)

    def _id(self, number):
        response = self.client.get(f"{API}/proposals", params={"search": number}, headers=self.headers)
        return int(response.json()["items"][0]["id"])


if __name__ == "__main__":
    unittest.main()
