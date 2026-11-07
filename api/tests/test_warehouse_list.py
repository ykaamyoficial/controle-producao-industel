"""Almoxarifado: quem aparece na aba Propostas, campos de baixa e contador de baixas pendentes."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from api.tests._warehouse_support import WarehouseApiTestCase, _integration_enabled

DONE = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class WarehouseListTests(WarehouseApiTestCase):
    def test_visibilidade_por_status(self):
        visiveis = {
            "W-EMSEP": {"warehouse_status": "EM_SEPARACAO"},
            "W-SEP": {"warehouse_status": "SEPARADO"},
            "W-PARC": {"warehouse_status": "ALMOXARIFADO_ENTREGUE_PARCIAL"},
            "W-SEMP": {"warehouse_status": "SEM_PARAFUSOS"},
            "W-ENT-PEND": {"warehouse_status": "ALMOXARIFADO_ENTREGUE"},
        }
        ocultas = {
            "W-NULL": {},
            "W-AGU": {"warehouse_status": "AGUARDANDO_CONFIRMACAO"},
            "W-ENT-BAIXA": {"warehouse_status": "ALMOXARIFADO_ENTREGUE", "warehouse_stock_deducted_at": DONE},
        }
        for number, fields in {**visiveis, **ocultas}.items():
            self._make(number, **fields)

        listed = self._warehouse_list()
        self.assertEqual({row["proposal_number"] for row in listed["items"]}, set(visiveis))
        self.assertEqual(listed["total"], len(visiveis))
        # nenhuma linha foi apagada: as ocultas continuam no banco
        self.assertEqual(self._client_total_proposals(), len(visiveis) + len(ocultas))

    def _client_total_proposals(self):
        response = self.client.get("/api/v1/proposals", params={"limit": 200}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["total"]

    def test_entregue_parcial_com_baixa_continua_na_aba(self):
        self._make("W-PARC-BX", warehouse_status="ALMOXARIFADO_ENTREGUE_PARCIAL", warehouse_stock_deducted_at=DONE)
        listed = self._warehouse_list()
        self.assertEqual([row["proposal_number"] for row in listed["items"]], ["W-PARC-BX"])
        self.assertTrue(listed["items"][0]["stock_deducted"])
        self.assertEqual(listed["pending_stock_deduction"], 0)

    def test_filha_e_cancelada_nunca_aparecem_nem_contam(self):
        mae = self._make("W-MAE", warehouse_status="SEPARADO")
        self._make("W-FILHA", warehouse_status="SEPARADO", parent_proposal_id=mae)
        self._make("W-CANC", warehouse_status="SEPARADO", is_cancelled=True)
        self._make("W-CANC2", warehouse_status="SEPARADO", current_status="CANCELADA")
        self._make("W-INATIVA", warehouse_status="SEPARADO", active=False)
        listed = self._warehouse_list()
        self.assertEqual([row["proposal_number"] for row in listed["items"]], ["W-MAE"])
        self.assertEqual(listed["pending_stock_deduction"], 1)

    def test_campos_de_baixa_na_linha(self):
        self._make("W-PEND", warehouse_status="SEPARADO")
        self._make("W-FEITA", warehouse_status="SEPARADO", warehouse_stock_deducted_at=DONE)
        rows = {row["proposal_number"]: row for row in self._warehouse_list()["items"]}
        self.assertFalse(rows["W-PEND"]["stock_deducted"])
        self.assertIsNone(rows["W-PEND"]["stock_deducted_at"])
        self.assertTrue(rows["W-FEITA"]["stock_deducted"])
        self.assertTrue(rows["W-FEITA"]["stock_deducted_at"].startswith("2026-11-01"))

    def test_contador_so_conta_pendentes_dos_tres_status_e_ignora_pagina_e_busca(self):
        for number in ("C-SEP-1", "C-SEP-2", "C-SEP-3"):
            self._make(number, warehouse_status="SEPARADO")
        self._make("C-PARC", warehouse_status="ALMOXARIFADO_ENTREGUE_PARCIAL")
        self._make("C-ENT", warehouse_status="ALMOXARIFADO_ENTREGUE")
        # nao contam: ja baixada, em separacao, sem parafusos
        self._make("C-SEP-BX", warehouse_status="SEPARADO", warehouse_stock_deducted_at=DONE)
        self._make("C-EMSEP", warehouse_status="EM_SEPARACAO")
        self._make("C-SEMP", warehouse_status="SEM_PARAFUSOS")

        full = self._warehouse_list()
        self.assertEqual(full["pending_stock_deduction"], 5)
        self.assertEqual(full["total"], 8)
        paged = self._warehouse_list(limit=2, offset=2)
        self.assertEqual(len(paged["items"]), 2)
        self.assertEqual(paged["total"], 8)
        self.assertEqual(paged["pending_stock_deduction"], 5)
        searched = self._warehouse_list(search="C-SEP-1")
        self.assertEqual(searched["total"], 1)
        self.assertEqual(searched["pending_stock_deduction"], 5)
        self.assertEqual(self._warehouse_list(status="SEPARADO")["pending_stock_deduction"], 5)

    def test_contador_zera_sem_pendencia(self):
        self._make("Z-EMSEP", warehouse_status="EM_SEPARACAO")
        self.assertEqual(self._warehouse_list()["pending_stock_deduction"], 0)

    def test_filtro_de_status(self):
        self._make("F-SEP", warehouse_status="SEPARADO")
        self._make("F-EMSEP", warehouse_status="EM_SEPARACAO")
        self._make("F-NULL")
        self._make("F-AGU", warehouse_status="AGUARDANDO_CONFIRMACAO")
        self.assertEqual(self._warehouse_numbers(status="separado"), {"F-SEP"})
        # NAO_DEFINIDO e AGUARDANDO_CONFIRMACAO nao sao mais da aba: 200 com lista vazia, sem erro
        self.assertEqual(self._warehouse_list(status="NAO_DEFINIDO")["items"], [])
        self.assertEqual(self._warehouse_list(status="AGUARDANDO_CONFIRMACAO")["items"], [])

    def test_ordem_por_status_depois_mais_recente(self):
        self._make("O-ENT", warehouse_status="ALMOXARIFADO_ENTREGUE")
        self._make("O-SEMP", warehouse_status="SEM_PARAFUSOS")
        self._make("O-SEP", warehouse_status="SEPARADO")
        self._make("O-EMSEP", warehouse_status="EM_SEPARACAO")
        order = [row["proposal_number"] for row in self._warehouse_list()["items"]]
        self.assertEqual(order, ["O-EMSEP", "O-SEP", "O-SEMP", "O-ENT"])


if __name__ == "__main__":
    unittest.main()
