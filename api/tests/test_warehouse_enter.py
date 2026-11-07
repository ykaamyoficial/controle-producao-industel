"""Almoxarifado: entrada de propostas por numero (POST /warehouse/proposals/enter)."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from sqlalchemy import select, update

from api.app.database.session import get_sessionmaker
from api.app.modules.proposals.models import Proposal, ProposalEvent
from api.tests._warehouse_support import WarehouseApiTestCase, _integration_enabled

URL = "/api/v1/warehouse/proposals/enter"


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class WarehouseEnterTests(WarehouseApiTestCase):
    def _enter(self, numbers, headers=None, expected=200):
        response = self.client.post(URL, json={"numbers": numbers}, headers=headers or self.headers)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def _results(self, numbers):
        return {item["number"]: item for item in self._enter(numbers)["items"]}

    def _events(self, proposal_id):
        async def go():
            async with get_sessionmaker()() as session:
                rows = (await session.execute(select(ProposalEvent).where(ProposalEvent.proposal_id == proposal_id, ProposalEvent.event_type == "WAREHOUSE_STATUS_CHANGED"))).scalars().all()
                return [(row.request_id, row.from_status, row.to_status, row.metadata_) for row in rows]

        return asyncio.run(go())

    def test_mistura_de_numeros_com_resultado_por_numero(self):
        nulo = self._make("E-NULO")
        aguardando = self._make("E-AGU", warehouse_status="AGUARDANDO_CONFIRMACAO")
        self._make("E-NA-ABA", warehouse_status="EM_SEPARACAO")
        self._make("E-SEP", warehouse_status="SEPARADO")
        self._make("E-ENT", warehouse_status="ALMOXARIFADO_ENTREGUE", warehouse_stock_deducted_at=datetime(2026, 11, 1, tzinfo=UTC))
        self._make("E-CANC", is_cancelled=True)
        mae = self._make("E-MAE")
        self._make("E-FILHA", parent_proposal_id=mae)
        self._make("E-INATIVA", active=False)

        body = self._enter(["E-NULO", "E-AGU", "E-NA-ABA", "E-SEP", "E-ENT", "E-CANC", "E-FILHA", "E-INATIVA", "E-NAO-EXISTE"])
        result = {item["number"]: item for item in body["items"]}
        self.assertEqual([item["number"] for item in body["items"]], ["E-NULO", "E-AGU", "E-NA-ABA", "E-SEP", "E-ENT", "E-CANC", "E-FILHA", "E-INATIVA", "E-NAO-EXISTE"])
        self.assertEqual(
            {number: item["result"] for number, item in result.items()},
            {
                "E-NULO": "ENTROU",
                "E-AGU": "ENTROU",
                "E-NA-ABA": "JA_NA_ABA",
                "E-SEP": "JA_NA_ABA",
                "E-ENT": "JA_ENTREGUE",
                "E-CANC": "CANCELADA",
                "E-FILHA": "PROPOSTA_PARCIAL",
                "E-INATIVA": "NAO_ENCONTRADA",
                "E-NAO-EXISTE": "NAO_ENCONTRADA",
            },
        )
        self.assertEqual(result["E-NULO"]["proposal_id"], nulo)
        self.assertEqual(result["E-AGU"]["proposal_id"], aguardando)
        self.assertIsNone(result["E-NAO-EXISTE"]["proposal_id"])
        self.assertTrue(all(item["message"] for item in body["items"]))
        self.assertEqual(self._row(nulo).warehouse_status, "EM_SEPARACAO")
        self.assertEqual(self._row(aguardando).warehouse_status, "EM_SEPARACAO")
        # quem ja estava mais adiante nao regride
        self.assertEqual(self._row(self._id_of("E-SEP")).warehouse_status, "SEPARADO")
        self.assertEqual(self._row(self._id_of("E-ENT")).warehouse_status, "ALMOXARIFADO_ENTREGUE")
        self.assertEqual(self._row(mae).warehouse_status, None)
        self.assertEqual(self._warehouse_numbers(), {"E-NULO", "E-AGU", "E-NA-ABA", "E-SEP"})

    def _id_of(self, number):
        async def go():
            async with get_sessionmaker()() as session:
                return (await session.execute(select(Proposal.id).where(Proposal.proposal_number == number))).scalar_one()

        return asyncio.run(go())

    def test_entrada_grava_evento_e_versao(self):
        proposal_id = self._make("E-EVT", warehouse_status="AGUARDANDO_CONFIRMACAO")
        version_before = self._row(proposal_id).version
        self._enter(["E-EVT"])
        row = self._row(proposal_id)
        self.assertEqual(row.version, version_before + 1)
        self.assertEqual(row.updated_by, 1)
        events = self._events(proposal_id)
        self.assertEqual(len(events), 1)
        request_id, from_status, to_status, metadata = events[0]
        self.assertTrue(request_id)
        self.assertEqual((from_status, to_status), ("AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO"))
        self.assertEqual(metadata["source"], "entrada_por_numero")
        self.assertEqual(metadata["previous_warehouse_status"], "AGUARDANDO_CONFIRMACAO")

    def test_entrada_de_status_nulo_guarda_status_anterior_nulo(self):
        proposal_id = self._make("E-EVT-NULO")
        self._enter(["E-EVT-NULO"])
        _, from_status, _, metadata = self._events(proposal_id)[0]
        self.assertEqual(from_status, "AGUARDANDO_CONFIRMACAO")
        self.assertIsNone(metadata["previous_warehouse_status"])

    def test_idempotente_segunda_chamada_nao_duplica_nem_regride(self):
        proposal_id = self._make("E-IDEM")
        first = self._results(["E-IDEM"])
        self.assertEqual(first["E-IDEM"]["result"], "ENTROU")
        version_after_first = self._row(proposal_id).version
        second = self._results(["E-IDEM"])
        self.assertEqual(second["E-IDEM"]["result"], "JA_NA_ABA")
        self.assertEqual(self._row(proposal_id).version, version_after_first)
        self.assertEqual(len(self._events(proposal_id)), 1)

    def test_normaliza_espaco_caixa_nbsp_e_repetidos_preservando_ordem(self):
        self._make("E-NORM-1")
        self._make("E-NORM-2")
        body = self._enter(["  e-norm-2 ", "E-NORM-1 ", "E-NORM-2", "e-norm-1", "   "])
        self.assertEqual([(item["number"], item["result"]) for item in body["items"]], [("e-norm-2", "ENTROU"), ("E-NORM-1", "ENTROU")])

    def test_aspas_e_ponto_final_nao_sao_tratados(self):
        # O normalizador (igual ao da busca) so tira espacos e ignora caixa: aspas/ponto final
        # colados no numero nao casam. O Desktop limpa isso no parser antes de enviar.
        self._make("E-ASPAS")
        results = self._results(['"E-ASPAS"', "E-ASPAS."])
        self.assertEqual({item["result"] for item in results.values()}, {"NAO_ENCONTRADA"})

    def test_limites_do_corpo(self):
        self._enter([], expected=422)
        self._enter(["   ", ""], expected=422)
        self._enter([f"N-{i}" for i in range(201)], expected=422)
        response = self.client.post(URL, json={"numbers": ["X"], "extra": 1}, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(self._enter([f"N-{i}" for i in range(200)])["items"]), 200)

    def test_permissao_exige_alterar_status(self):
        self._make("E-PERM")
        viewer = self._seed_user("so_ver", ["proposals.view"])
        self._enter(["E-PERM"], headers=viewer, expected=403)
        operator = self._seed_user("operador", ["proposals.view", "proposals.change_status"])
        self.assertEqual(self._enter(["E-PERM"], headers=operator)["items"][0]["result"], "ENTROU")

    def test_nao_sobrescreve_status_mais_avancado_gravado_durante_a_chamada(self):
        """A linha e travada: se outra sessao avanca o status antes de a entrada ler, ela ve o novo."""
        proposal_id = self._make("E-CONC", warehouse_status="AGUARDANDO_CONFIRMACAO")

        async def scenario():
            async with get_sessionmaker()() as other:
                await other.execute(select(Proposal.id).where(Proposal.id == proposal_id).with_for_update())
                call = asyncio.create_task(asyncio.to_thread(lambda: self.client.post(URL, json={"numbers": ["E-CONC"]}, headers=self.headers)))
                await asyncio.sleep(2)
                self.assertFalse(call.done(), "a entrada deveria esperar a linha travada")
                await other.execute(update(Proposal).where(Proposal.id == proposal_id).values(warehouse_status="SEPARADO"))
                await other.commit()
                return await call

        response = asyncio.run(scenario())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"][0]["result"], "JA_NA_ABA")
        self.assertEqual(self._row(proposal_id).warehouse_status, "SEPARADO")
        self.assertEqual(self._events(proposal_id), [])


if __name__ == "__main__":
    unittest.main()
