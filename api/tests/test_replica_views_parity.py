"""Paridade entre a API e as leituras locais do Desktop (app/replica/*_view.py).

O Desktop lista o Controle Geral a partir da replica SQLite. Este teste monta
um cenario real pela API, carrega a replica pelos endpoints /sync e exige que
a resposta local seja IDENTICA a de `GET /proposals`. So listagens sem regra
de negocio sao lidas da replica; o resto continua na API.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.replica import proposals_view
from app.replica.replica_db import ReplicaDatabase
from app.replica.sync_engine import MODE_INCREMENTAL, ReplicaSyncEngine, SyncApiClient
from api.tests import test_expedition_fiscal_read_path as read_path
from api.tests.test_proposals_integration import _integration_enabled, _item_payload

PROPOSAL_CASES = (
    {},
    {"limit": 200, "offset": 0},
    {"limit": 2, "offset": 1},
    {"sort_by": "updated_at", "sort_dir": "asc", "limit": 200},
    {"sort_by": "proposal_date", "sort_dir": "desc", "limit": 200},
    {"sort_by": "deadline_date", "sort_dir": "asc", "limit": 200},
    {"sort_by": "synced_at", "sort_dir": "desc", "limit": 200},
    {"sort_by": "legacy_updated_at", "sort_dir": "asc", "limit": 200},
    {"customer": "beta", "limit": 200},
    {"customer": "a_fa", "limit": 200},
    {"customer": "%ltda", "limit": 200},
    {"proposal_number": "exp-", "limit": 200},
    {"project": "site", "limit": 200},
    {"current_area": "EXPEDICAO", "limit": 200},
    {"current_status": "CANCELADA", "limit": 200},
    {"is_cancelled": True, "limit": 200},
    {"is_cancelled": False, "is_completed": False, "limit": 200},
    {"is_partial": False, "limit": 200},
    {"date_from": "2026-07-20", "date_to": "2026-07-20", "limit": 200},
    {"date_from": "2026-07-21", "limit": 200},
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

    def assertProposalsParity(self, database):
        for params in PROPOSAL_CASES:
            with self.subTest(params=params):
                self.assertTrue(proposals_view.can_serve(params))
                response = self.client.get("/api/v1/proposals", params=params, headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(proposals_view.list_proposals(database, **params), response.json())

    def test_general_control_list_from_replica_matches_the_api(self):
        self._build_scenario()
        database, engine = self._replica()
        engine.sync_once()
        self.assertGreater(self.client.get("/api/v1/proposals", headers=self.headers).json()["total"], 0)
        self.assertProposalsParity(database)

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
        self.assertProposalsParity(database)


if __name__ == "__main__":
    unittest.main()
