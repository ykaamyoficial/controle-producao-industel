"""Paridade entre a API e as leituras locais do Desktop (app/replica/*_view.py).

O Desktop recalcula a lista de Expedicao e a lista/indicadores do Fiscal sobre
a replica SQLite. Este teste monta um cenario real pela API, carrega a replica
pelos endpoints /sync e exige que a resposta local seja IDENTICA a de
`GET /shipping/proposals`, `GET /fiscal/records` e `GET /fiscal/indicators`.
Se alguem mudar a regra na API e esquecer o espelho no Desktop, falha aqui.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.replica import expedition_view, fiscal_view
from app.replica.replica_db import ReplicaDatabase
from app.replica.sync_engine import MODE_INCREMENTAL, ReplicaSyncEngine, SyncApiClient
from api.tests import test_expedition_fiscal_read_path as read_path
from api.tests.test_proposals_integration import _integration_enabled, _item_payload

EXPEDITION_CASES = (
    {"limit": 50, "offset": 0},
    {"limit": 200, "offset": 0},
    {"limit": 2, "offset": 0},
    {"limit": 2, "offset": 2},
    {"limit": 2, "offset": 40},
    {"search": "beta", "limit": 50, "offset": 0},
    {"search": "  EXP-", "limit": 50, "offset": 0},
    {"search": "Ltda", "limit": 50, "offset": 0},
    {"search": "nao-existe", "limit": 50, "offset": 0},
    {"search": "%", "limit": 50, "offset": 0},
)

FISCAL_CASES = (
    {"limit": 50, "offset": 0},
    {"limit": 200, "offset": 0},
    {"limit": 2, "offset": 0},
    {"limit": 2, "offset": 3},
    {"limit": 2, "offset": 40},
    {"search": "beta", "limit": 50, "offset": 0},
    {"search": "nao-existe", "limit": 50, "offset": 0},
    {"status": "FALTA_EMITIR_NOTA_FISCAL", "limit": 50, "offset": 0},
    {"status": "NOTA_FISCAL_PARCIAL", "limit": 50, "offset": 0},
    {"status": "NOTA_FISCAL_EMITIDA", "limit": 50, "offset": 0},
    {"situation": "PENDENCIA_FISCAL_CRITICA", "limit": 50, "offset": 0},
    {"situation": "DISPONIVEL_PARA_EMISSAO", "limit": 50, "offset": 0},
    {"situation": "NF_PARCIAL", "limit": 50, "offset": 0},
    {"situation": "CP_EM_PROCESSAMENTO", "limit": 50, "offset": 0},
    {"situation": "NF_EMITIDA", "limit": 50, "offset": 0},
    {"situation": "NF_RETIRADA_CLIENTE", "limit": 50, "offset": 0},
    {"status": "FALTA_EMITIR_NOTA_FISCAL", "situation": "DISPONIVEL_PARA_EMISSAO", "search": "beta", "limit": 50, "offset": 0},
)


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class ReplicaViewsParityTests(unittest.TestCase):
    # Mesmo banco, usuario e cenario do teste de leitura de Expedicao/Fiscal.
    setUpClass = read_path.ExpeditionFiscalReadPathTests.setUpClass
    tearDownClass = read_path.ExpeditionFiscalReadPathTests.tearDownClass
    setUp = read_path.ExpeditionFiscalReadPathTests.setUp
    _seed_admin = read_path.ExpeditionFiscalReadPathTests._seed_admin
    _headers = read_path.ExpeditionFiscalReadPathTests._headers
    _post = read_path.ExpeditionFiscalReadPathTests._post
    _create = read_path.ExpeditionFiscalReadPathTests._create
    _ready = read_path.ExpeditionFiscalReadPathTests._ready
    _build_scenario = read_path.ExpeditionFiscalReadPathTests._build_scenario
    _shipping_list = read_path.ExpeditionFiscalReadPathTests._shipping_list
    _fiscal_list = read_path.ExpeditionFiscalReadPathTests._fiscal_list

    def _replica(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        database = ReplicaDatabase(Path(tmp.name) / "replica.db")

        def get_json(path):
            response = self.client.get(path, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        return database, ReplicaSyncEngine(database, SyncApiClient(get_json), identity="teste|admin")

    def assertExpeditionParity(self, database):
        for params in EXPEDITION_CASES:
            with self.subTest(params=params):
                self.assertEqual(expedition_view.list_expedition_proposals(database, **params), self._shipping_list(**params))

    def assertFiscalParity(self, database):
        for params in FISCAL_CASES:
            with self.subTest(params=params):
                local_params = {("situation_filter" if key == "situation" else key): value for key, value in params.items()}
                self.assertEqual(fiscal_view.list_fiscal_records(database, **local_params), self._fiscal_list(**params))
        indicators = self.client.get("/api/v1/fiscal/indicators", headers=self.headers)
        self.assertEqual(indicators.status_code, 200, indicators.text)
        self.assertEqual(fiscal_view.fiscal_indicators(database), indicators.json())

    def test_fiscal_list_and_indicators_from_replica_match_the_api(self):
        self._build_scenario()
        database, engine = self._replica()
        engine.sync_once()
        api = self.client.get("/api/v1/fiscal/indicators", headers=self.headers).json()
        # O cenario precisa exercitar pesos e os tres status, senao a paridade nao prova nada.
        self.assertNotEqual(api["peso_pendente"], "0.0000")
        self.assertNotEqual(api["peso_faturado"], "0.0000")
        self.assertTrue(api["falta_emitir"] and api["nf_parcial"] and api["nf_emitida"] and api["pendencia_critica"])
        self.assertFiscalParity(database)

    def test_expedition_list_from_replica_matches_the_api(self):
        self._build_scenario()
        database, engine = self._replica()
        engine.sync_once()
        self.assertGreater(self._shipping_list(limit=200)["total"], 0)
        self.assertExpeditionParity(database)

    def test_parity_holds_after_incremental_changes(self):
        ids = self._build_scenario()
        database, engine = self._replica()
        engine.sync_once()
        # Depois da carga inicial: separacao em E, cancelamento de A e uma proposta nova pronta.
        detail = self.client.get(f"/api/v1/shipping/proposals/{ids['E']}", headers=self.headers).json()
        started = self._post(f"/api/v1/shipping/proposals/{ids['E']}/start-separation", {"version": detail["version"]})
        self._post(f"/api/v1/shipping/proposals/{ids['E']}/separate-items", {"version": started["version"]})
        proposal_a = self.client.get(f"/api/v1/proposals/{ids['A']}", headers=self.headers).json()
        self._post(f"/api/v1/proposals/{ids['A']}/cancel", {"version": proposal_a["version"], "reason": "Cancelada no teste de paridade"})
        self._ready("EXP-NOVA", [_item_payload("1", requires_galvanization=False)], "Novo Cliente Ltda")
        result = engine.sync_once()
        self.assertEqual(result.mode, MODE_INCREMENTAL)
        self.assertExpeditionParity(database)
        self.assertFiscalParity(database)

    def test_fiscal_parity_after_invoice_and_withdrawal(self):
        self._build_scenario()
        database, engine = self._replica()
        engine.sync_once()
        records = {row["proposal_number"]: row for row in self._fiscal_list(limit=200)["items"]}
        # NF total em A (ate entao sem nota) e retirada da NF ja emitida de C.
        self._post(f"/api/v1/fiscal/records/{records['EXP-A']['id']}/invoices", {"version": records["EXP-A"]["version"], "invoice_number": "2001", "series": "1"})
        self._post(f"/api/v1/fiscal/records/{records['EXP-C']['id']}/withdrawal", {"version": records["EXP-C"]["version"]})
        self.assertEqual(engine.sync_once().mode, MODE_INCREMENTAL)
        after = {row["proposal_number"]: row for row in self._fiscal_list(limit=200)["items"]}
        self.assertEqual(after["EXP-A"]["status_fiscal"], "NOTA_FISCAL_EMITIDA")
        self.assertEqual(after["EXP-C"]["fiscal_situation"], "NF_RETIRADA_CLIENTE")
        self.assertIsNotNone(after["EXP-A"]["last_emission_at"])
        self.assertFiscalParity(database)


if __name__ == "__main__":
    unittest.main()
