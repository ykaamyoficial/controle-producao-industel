"""Almoxarifado: aba Itens (GET /warehouse/items) - itens ativos das propostas que estao na aba Propostas."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from sqlalchemy import update

from api.app.database.session import get_sessionmaker
from api.app.modules.proposals.models import ProposalItem
from api.tests._warehouse_support import WarehouseApiTestCase, _integration_enabled

URL = "/api/v1/warehouse/items"
DONE = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class WarehouseItemsTests(WarehouseApiTestCase):
    def _items(self, headers=None, expected=200, **params):
        response = self.client.get(URL, params={"limit": 500, **params}, headers=headers or self.headers)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def _set_item(self, proposal_id, item_number, **fields):
        async def go():
            async with get_sessionmaker()() as session:
                await session.execute(update(ProposalItem).where(ProposalItem.proposal_id == proposal_id, ProposalItem.item_number == item_number).values(**fields))
                await session.commit()

        asyncio.run(go())

    def _keys(self, **params):
        return [(row["proposal_number"], row["item_number"]) for row in self._items(**params)["items"]]

    def test_so_itens_ativos_de_propostas_visiveis(self):
        a = self._make("I-EMSEP", items=3, warehouse_status="EM_SEPARACAO")
        self._set_item(a, "2", active=False)
        self._make("I-SEP", items=1, warehouse_status="SEPARADO")
        self._make("I-ENT-PEND", items=1, warehouse_status="ALMOXARIFADO_ENTREGUE")
        # fora da aba
        self._make("I-NULL", items=2)
        self._make("I-AGU", items=2, warehouse_status="AGUARDANDO_CONFIRMACAO")
        self._make("I-ENT-BX", items=2, warehouse_status="ALMOXARIFADO_ENTREGUE", warehouse_stock_deducted_at=DONE)
        mae = self._make("I-MAE", items=1)
        self._make("I-FILHA", items=2, warehouse_status="SEPARADO", parent_proposal_id=mae)
        self._make("I-CANC", items=2, warehouse_status="SEPARADO", is_cancelled=True)

        body = self._items()
        self.assertEqual(
            [(row["proposal_number"], row["item_number"]) for row in body["items"]],
            [("I-EMSEP", "1"), ("I-EMSEP", "3"), ("I-SEP", "1"), ("I-ENT-PEND", "1")],
        )
        self.assertEqual((body["total"], body["limit"], body["offset"]), (4, 500, 0))

    def test_campos_da_linha(self):
        proposal_id = self._make("I-CAMPOS", warehouse_status="SEPARADO", customer_name="Cliente Campos")
        self._set_item(proposal_id, "1", product_code="PC-9", description="Parafuso sextavado", unit="pc")
        row = self._items()["items"][0]
        self.assertEqual(
            set(row),
            {"proposal_id", "proposal_number", "customer_name", "item_number", "product_code", "description", "quantity", "unit", "total_weight", "warehouse_status"},
        )
        self.assertEqual(row["proposal_id"], proposal_id)
        self.assertEqual((row["proposal_number"], row["customer_name"], row["item_number"]), ("I-CAMPOS", "Cliente Campos", "1"))
        self.assertEqual((row["product_code"], row["description"], row["unit"], row["warehouse_status"]), ("PC-9", "Parafuso sextavado", "pc", "SEPARADO"))
        self.assertEqual(float(row["quantity"]), 2.0)
        self.assertEqual(float(row["total_weight"]), 7.0)

    def test_busca_por_proposta_cliente_codigo_e_descricao(self):
        a = self._make("I-BUSCA-A", warehouse_status="EM_SEPARACAO", customer_name="Alfa Metais")
        b = self._make("I-BUSCA-B", warehouse_status="EM_SEPARACAO", customer_name="Beta Ltda")
        self._set_item(a, "1", product_code="ABC-1", description="Chapa de aco")
        self._set_item(b, "1", product_code="XYZ-2", description="Porca lisa")
        self.assertEqual(self._keys(search="busca-a"), [("I-BUSCA-A", "1")])
        self.assertEqual(self._keys(search="beta"), [("I-BUSCA-B", "1")])
        self.assertEqual(self._keys(search="xyz-2"), [("I-BUSCA-B", "1")])
        self.assertEqual(self._keys(search="chapa"), [("I-BUSCA-A", "1")])
        self.assertEqual(self._keys(search="nao-existe"), [])
        # a busca nunca traz item de proposta fora da aba
        self._make("I-BUSCA-FORA", customer_name="Alfa Metais")
        self.assertEqual(self._items(search="alfa")["total"], 1)

    def test_paginacao_no_sql_ordenada_por_ids(self):
        first = self._make("I-P1", items=3, warehouse_status="EM_SEPARACAO")
        second = self._make("I-P2", items=2, warehouse_status="SEPARADO")
        self.assertLess(first, second)
        everything = self._keys()
        self.assertEqual(everything, [("I-P1", "1"), ("I-P1", "2"), ("I-P1", "3"), ("I-P2", "1"), ("I-P2", "2")])
        for limit, offset in ((2, 0), (2, 2), (2, 4), (10, 3), (3, 99)):
            with self.subTest(limit=limit, offset=offset):
                page = self._items(limit=limit, offset=offset)
                self.assertEqual([(r["proposal_number"], r["item_number"]) for r in page["items"]], everything[offset : offset + limit])
                self.assertEqual((page["total"], page["limit"], page["offset"]), (5, limit, offset))

    def test_entregue_some_quando_a_baixa_e_confirmada(self):
        proposal_id = self._make("I-BAIXA", warehouse_status="ALMOXARIFADO_ENTREGUE")
        self.assertEqual(self._items()["total"], 1)
        response = self.client.post(
            f"/api/v1/warehouse/proposals/{proposal_id}/stock-deduction",
            json={"version": self._row(proposal_id).version, "deducted": True},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._items()["total"], 0)

    def test_limites_e_permissao(self):
        self._items(limit=501, expected=422)
        self._items(limit=0, expected=422)
        self._items(offset=-1, expected=422)
        nobody = self._seed_user("sem_permissao", [])
        self._items(headers=nobody, expected=403)
        viewer = self._seed_user("so_ver", ["proposals.view"])
        self._items(headers=viewer)


if __name__ == "__main__":
    unittest.main()
