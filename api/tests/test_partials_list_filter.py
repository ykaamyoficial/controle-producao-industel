"""`GET /partials/proposals`: busca e `proposal_id` filtram no SQL sem mudar o resultado.

O Detalhe de uma proposta chama este endpoint so para achar a propria linha.
Antes a API carregava todas as propostas ativas com cinco relacoes e filtrava
em Python; agora filtra antes de carregar. O contrato tem de ser o mesmo: a
resposta filtrada e exatamente a lista completa filtrada pelo mesmo criterio.
"""

from __future__ import annotations

import unittest

from api.tests import test_expedition_fiscal_read_path as read_path
from api.tests.test_proposals_integration import _integration_enabled, _item_payload


def _text(row: dict) -> str:
    return " ".join([row["proposal_number"], row["customer_name"], row.get("project_name") or "", row.get("lot") or ""]).lower()


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class PartialsListFilterTests(unittest.TestCase):
    setUpClass = read_path.ExpeditionFiscalReadPathTests.setUpClass
    tearDownClass = read_path.ExpeditionFiscalReadPathTests.tearDownClass
    setUp = read_path.ExpeditionFiscalReadPathTests.setUp
    _seed_admin = read_path.ExpeditionFiscalReadPathTests._seed_admin
    _headers = read_path.ExpeditionFiscalReadPathTests._headers
    _post = read_path.ExpeditionFiscalReadPathTests._post
    _create = read_path.ExpeditionFiscalReadPathTests._create
    _ready = read_path.ExpeditionFiscalReadPathTests._ready
    _build_scenario = read_path.ExpeditionFiscalReadPathTests._build_scenario
    _fiscal_list = read_path.ExpeditionFiscalReadPathTests._fiscal_list

    def _partial_production(self, number, customer):
        """Proposta com dois itens e so o primeiro produzido: movimento parcial."""
        items = [_item_payload("1", requires_galvanization=False), _item_payload("2", requires_galvanization=False)]
        proposal = self._create(number, items, customer)
        released = self._post(f"/api/v1/proposals/{proposal['id']}/status", {"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"})
        started = self._post(f"/api/v1/production/proposals/{proposal['id']}/start", {"version": released["version"]})
        self._post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", {"version": started["version"], "item_ids": [started["items"][0]["id"]], "observation": "Parcial"})
        return proposal["id"]

    def _scenario(self):
        ids = self._build_scenario()
        ids["P1"] = self._partial_production("EXP-P1", "Parcial Alfa Ltda")
        ids["P2"] = self._partial_production("EXP-P2", "Parcial Beta")
        ids["P3"] = self._partial_production("PAR-P3", "Outro Cliente")
        return ids

    def _partials(self, **params):
        response = self.client.get("/api/v1/partials/proposals", params=params, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_search_returns_exactly_the_full_list_filtered(self):
        self._scenario()
        full = self._partials(limit=200)
        self.assertGreater(full["total"], 3, "o cenario precisa ter propostas com movimento parcial")
        self.assertEqual(full["total"], len(full["items"]))
        for needle in ("exp-", "EXP-B", "  beta ", "ltda", "parcial", "par-", "site", "l1", "nao-existe", "%", "_"):
            with self.subTest(needle=needle):
                expected = [row for row in full["items"] if needle.strip().lower() in _text(row)]
                page = self._partials(search=needle, limit=200)
                self.assertEqual(page["items"], expected)
                self.assertEqual(page["total"], len(expected))

    def test_search_keeps_pagination(self):
        self._scenario()
        expected = self._partials(search="exp-", limit=200)["items"]
        self.assertGreater(len(expected), 2)
        page = self._partials(search="exp-", limit=2, offset=1)
        self.assertEqual(page["items"], expected[1:3])
        self.assertEqual((page["total"], page["limit"], page["offset"]), (len(expected), 2, 1))

    def test_proposal_id_returns_only_that_row_unchanged(self):
        self._scenario()
        full = self._partials(limit=200)["items"]
        target = full[len(full) // 2]
        self.assertEqual(self._partials(proposal_id=target["id"], limit=20), {"items": [target], "total": 1, "limit": 20, "offset": 0})
        # Como o Desktop chama: numero da proposta + id.
        self.assertEqual(self._partials(search=target["proposal_number"], proposal_id=target["id"], limit=20)["items"], [target])

    def test_proposal_id_without_partial_movement_or_unknown_is_empty(self):
        ids = self._scenario()
        listed = {row["id"] for row in self._partials(limit=200)["items"]}
        absent = [proposal_id for proposal_id in ids.values() if proposal_id not in listed]
        for proposal_id in absent + [99999999]:
            with self.subTest(proposal_id=proposal_id):
                self.assertEqual(self._partials(proposal_id=proposal_id, limit=20)["items"], [])
        self.assertEqual(self.client.get("/api/v1/partials/proposals", params={"proposal_id": 0}, headers=self.headers).status_code, 422)


if __name__ == "__main__":
    unittest.main()
