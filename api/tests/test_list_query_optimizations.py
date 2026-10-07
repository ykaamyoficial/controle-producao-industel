"""Listas otimizadas (Producao, Galvanizacao, Almoxarifado, Parciais): mesmo resultado de antes.

As listas passaram a carregar so o que usam e a filtrar no banco o que antes era
descartado em Python. Cada filtro SQL novo e comparado, proposta por proposta,
com a regra Python original, e cada tela e comparada com o algoritmo antigo
reimplementado aqui como referencia (carrega tudo, filtra em Python).
"""

from __future__ import annotations

import asyncio
import unittest
from decimal import Decimal

from sqlalchemy import exists, select

from api.app.database.session import get_sessionmaker
from api.app.modules.proposals import service
from api.app.modules.proposals.models import GalvanizationLoad, GalvanizationLoadItem, Proposal, ProposalItem
from api.tests import test_expedition_fiscal_read_path as read_path
from api.tests.test_proposals_integration import _integration_enabled, _item_payload


def run(coro_fn):
    async def runner():
        async with get_sessionmaker()() as session:
            return await coro_fn(session)

    return asyncio.run(runner())


async def _all_proposals(session):
    return (await session.execute(select(Proposal))).scalars().unique().all()


async def _ids(session, *conditions):
    return {int(value) for value in (await session.execute(select(Proposal.id).where(*conditions))).scalars()}


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class ListQueryOptimizationTests(unittest.TestCase):
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

    # ---- cenario ------------------------------------------------------------
    def _produce(self, number, customer, items, *, complete_ids=None, stop_after=None):
        proposal = self._create(number, items, customer)
        released = self._post(f"/api/v1/proposals/{proposal['id']}/status", {"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"})
        if stop_after == "released":
            return proposal["id"], released
        started = self._post(f"/api/v1/production/proposals/{proposal['id']}/start", {"version": released["version"]})
        if stop_after == "started":
            return proposal["id"], started
        if stop_after == "paused":
            return proposal["id"], self._post(f"/api/v1/production/proposals/{proposal['id']}/pause", {"version": started["version"], "reason": "Parada para o teste"})
        body = {"version": started["version"]}
        if complete_ids is not None:
            body.update({"item_ids": [started["items"][complete_ids]["id"]], "observation": "Parcial"})
        return proposal["id"], self._post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", body)

    def _scenario(self):
        ids = self._build_scenario()
        galv = lambda n: _item_payload(n, requires_galvanization=True)  # noqa: E731
        plain = lambda n: _item_payload(n, requires_galvanization=False)  # noqa: E731
        ids["PARCIAL1"], _ = self._produce("OPT-P1", "Parcial Alfa Ltda", [plain("1"), plain("2")], complete_ids=0)
        ids["PARCIAL2"], _ = self._produce("OPT-P2", "Parcial Beta", [plain("1"), plain("2"), plain("3")], complete_ids=1)
        ids["LIBERADA"], _ = self._produce("OPT-L", "Cliente Liberado", [plain("1")], stop_after="released")
        ids["INICIADA"], _ = self._produce("OPT-I", "Cliente Iniciado", [plain("1"), plain("2")], stop_after="started")
        ids["PAUSADA"], _ = self._produce("OPT-PA", "Cliente Pausado", [plain("1")], stop_after="paused")
        # Galvanizacao: itens produzidos que exigem galvanizacao; uma carga parcial e uma total.
        ids["GALV1"], galv1 = self._produce("OPT-G1", "Galv Um Ltda", [galv("1"), galv("2")])
        ids["GALV2"], galv2 = self._produce("OPT-G2", "Galv Dois", [galv("1")])
        ids["GALV3"], _ = self._produce("OPT-G3", "Galv Tres", [galv("1")])
        self._post("/api/v1/galvanization/loads", {"driver_name": "Motorista Um", "items": [{"proposal_item_id": galv1["items"][0]["id"], "sent_quantity": "1.0000"}]})
        self._post("/api/v1/galvanization/loads", {"driver_name": "Motorista Dois", "items": [{"proposal_item_id": galv2["items"][0]["id"], "version": galv2["items"][0]["version"]}]})
        return ids

    # ---- filtros SQL x regra Python ----------------------------------------
    def test_sql_filters_match_the_python_rules_for_every_proposal(self):
        self._scenario()

        async def check(session):
            proposals = await _all_proposals(session)
            python_partial = {int(p.id) for p in proposals if service._proposal_has_partial_movement(p)}
            python_active = {
                int(p.id) for p in proposals
                if service._production_status_value(p.production_status or p.current_status) in service.PRODUCTION_ACTIVE_STATUSES
            }
            python_eligible = {int(p.id) for p in proposals if service._eligible_galvanization_items(p)}
            has_eligible = exists().where(
                ProposalItem.proposal_id == Proposal.id, ProposalItem.active.is_(True), ProposalItem.produced.is_(True),
                ProposalItem.requires_galvanization == "SIM", ProposalItem.flow_defined.is_(True), ProposalItem.galvanized.is_(False),
            )
            return {
                "total": len(proposals),
                "partial": (python_partial, await _ids(session, service._partial_movement_clause())),
                "active": (python_active, await _ids(session, service._production_active_status_clause())),
                "eligible": (python_eligible, await _ids(session, has_eligible)),
            }

        result = run(check)
        partial_python, partial_sql = result["partial"]
        self.assertGreaterEqual(len(partial_python), 3, "o cenario precisa ter varias propostas com movimento parcial")
        self.assertEqual(partial_sql, partial_python)
        active_python, active_sql = result["active"]
        self.assertGreaterEqual(len(active_python), 5)
        self.assertLess(len(active_python), result["total"], "o cenario precisa ter propostas fora da producao")
        self.assertTrue(active_python <= active_sql)
        self.assertEqual(active_sql, active_python)
        eligible_python, eligible_sql = result["eligible"]
        self.assertGreaterEqual(len(eligible_python), 2)
        self.assertEqual(eligible_sql, eligible_python)

    # ---- telas x algoritmo antigo ------------------------------------------
    def _get(self, url, **params):
        response = self.client.get(url, params=params, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_partials_list_matches_the_load_everything_algorithm(self):
        self._scenario()

        async def oracle(session):
            rows = (await session.execute(select(Proposal).where(Proposal.active.is_(True)).where(service._proposal_operational_clause()))).scalars().unique().all()
            rows = [p for p in rows if service._proposal_has_partial_movement(p)]
            rows.sort(key=lambda p: (-(p.updated_at.timestamp() if p.updated_at else 0), p.proposal_number, p.id))
            return [int(p.id) for p in rows]

        expected = run(oracle)
        self.assertGreaterEqual(len(expected), 3)
        page = self._get("/api/v1/partials/proposals", limit=200)
        self.assertEqual([row["id"] for row in page["items"]], expected)
        self.assertEqual(page["total"], len(expected))
        self.assertEqual([row["id"] for row in self._get("/api/v1/partials/proposals", limit=2, offset=1)["items"]], expected[1:3])

    def test_production_lists_match_the_load_everything_algorithm(self):
        self._scenario()

        async def oracle(session):
            rows = (await session.execute(select(Proposal).where(service._proposal_operational_clause()).where(Proposal.active.is_(True)))).scalars().unique().all()
            active = [
                p for p in rows
                if any(service._production_item_requires_attention(item) for item in service._active_items(p))
                and service._production_status_value(p.production_status or p.current_status) in service.PRODUCTION_ACTIVE_STATUSES
            ]
            active.sort(key=lambda p: (service._production_sort_key(p), -(p.updated_at.timestamp() if p.updated_at else 0), p.id))
            items = []
            for p in rows:
                if p.current_area != "PRODUCAO" and not any(service._loaded_item_balance(i).production_reallocated_in_pending > 0 for i in service._active_items(p)):
                    continue
                status_value = service._production_status_value(p.production_status or p.current_status)
                if status_value not in service.PRODUCTION_ACTIVE_STATUSES:
                    continue
                items.extend((p.proposal_number, i.item_number, int(i.id)) for i in service._production_queue_items(p))
            return [int(p.id) for p in active], sorted(items)

        expected_ids, expected_items = run(oracle)
        self.assertGreaterEqual(len(expected_ids), 4)
        page = self._get("/api/v1/production/proposals", limit=200)
        self.assertEqual([row["id"] for row in page["items"]], expected_ids)
        self.assertEqual(page["total"], len(expected_ids))
        for status in ("NAO_INICIADO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL", "LIBERADO_PRODUCAO"):
            with self.subTest(status=status):
                filtered = self._get("/api/v1/production/proposals", status=status, limit=200)
                self.assertTrue(set(row["id"] for row in filtered["items"]) <= set(expected_ids))
                self.assertEqual(filtered["total"], len(filtered["items"]))
        listed = self._get("/api/v1/production/items", limit=200)
        self.assertEqual(sorted((row["proposal_number"], row["item_number"], row["item_id"]) for row in listed["items"]), expected_items)

    def test_galvanization_candidates_match_the_per_item_algorithm(self):
        self._scenario()

        async def oracle(session):
            rows = (await session.execute(select(Proposal).where(Proposal.active.is_(True)).where(service._proposal_operational_clause()))).scalars().unique().all()
            expected = {}
            for proposal in rows:
                for item in service._eligible_galvanization_items(proposal):
                    available = await service._galvanization_available_quantity(session, item)
                    pending = await service._galvanization_pending_quantity(session, item)
                    expected[int(item.id)] = (available, pending)
            return expected

        expected = run(oracle)
        self.assertGreaterEqual(len(expected), 3)
        self.assertTrue(any(pending > 0 for _available, pending in expected.values()), "o cenario precisa ter item ja enviado")
        self.assertTrue(any(available == 0 for available, _pending in expected.values()), "o cenario precisa ter item totalmente enviado")
        self.assertTrue(any(available > 0 and pending == 0 for available, pending in expected.values()))
        page = self._get("/api/v1/galvanization/candidates", include_unavailable="true", limit=200)
        got = {row["item_id"]: (Decimal(row["available_quantity"]), Decimal(row["sent_quantity"])) for row in page["items"]}
        self.assertEqual(got, {item_id: (available.quantize(Decimal("0.0001")), pending.quantize(Decimal("0.0001"))) for item_id, (available, pending) in expected.items()})
        visible = self._get("/api/v1/galvanization/candidates", limit=200)
        self.assertEqual({row["item_id"] for row in visible["items"]}, {item_id for item_id, (available, _p) in expected.items() if available > 0})
        self.assertEqual(visible["total"], len(visible["items"]))

    def test_galvanization_loads_paginate_in_the_database_without_changing_the_result(self):
        self._scenario()

        async def oracle(session):
            loads = (await session.execute(select(GalvanizationLoad).where(GalvanizationLoad.active.is_(True)).order_by(GalvanizationLoad.created_at.desc(), GalvanizationLoad.id.desc()))).scalars().unique().all()
            return [int(load.id) for load in loads]

        expected = run(oracle)
        self.assertGreaterEqual(len(expected), 2)
        everything = self._get("/api/v1/galvanization/loads", limit=200)
        self.assertEqual([row["id"] for row in everything["items"]], expected)
        self.assertEqual(everything["total"], len(expected))
        for limit, offset in ((1, 0), (1, 1), (2, 1), (1, 50)):
            with self.subTest(limit=limit, offset=offset):
                page = self._get("/api/v1/galvanization/loads", limit=limit, offset=offset)
                self.assertEqual([row["id"] for row in page["items"]], expected[offset : offset + limit])
                self.assertEqual((page["total"], page["limit"], page["offset"]), (len(expected), limit, offset))
        searched = self._get("/api/v1/galvanization/loads", search="motorista um", limit=200)
        self.assertEqual(searched["total"], 1)
        self.assertEqual(self._get("/api/v1/galvanization/loads", search="galv dois", limit=200)["total"], 1)
        self.assertEqual(self._get("/api/v1/galvanization/loads", search="nao-existe", limit=200)["items"], [])
        first = everything["items"][0]
        self.assertEqual(self._get("/api/v1/galvanization/loads", status=first["status"], limit=200)["total"], sum(1 for row in everything["items"] if row["status"] == first["status"]))

    def test_warehouse_list_keeps_order_search_and_item_totals(self):
        ids = self._scenario()
        full = self._get("/api/v1/warehouse/proposals", limit=200)
        self.assertEqual(full["total"], len(full["items"]))
        self.assertTrue(all(row["total_items"] >= 1 for row in full["items"]))
        by_id = {row["id"]: row for row in full["items"]}

        async def oracle(session):
            rows = (await session.execute(
                select(Proposal).where(Proposal.active.is_(True)).where(service._proposal_operational_clause()).where(Proposal.parent_proposal_id.is_(None))
            )).scalars().unique().all()
            return {int(p.id): (len(service._active_items(p)), str(service.calculate_weight_coverage(i.total_weight for i in service._active_items(p)).known_weight)) for p in rows}

        expected = run(oracle)
        self.assertEqual(set(by_id), set(expected))
        for proposal_id, (count, known_weight) in expected.items():
            with self.subTest(proposal_id=proposal_id):
                self.assertEqual(by_id[proposal_id]["total_items"], count)
                self.assertEqual(by_id[proposal_id]["weight_total_items"], count)
                self.assertEqual(Decimal(by_id[proposal_id]["total_weight"]), Decimal(known_weight))
        # Registrar a producao de 1 item de 3 move esse item para uma filha: a mae fica com 2.
        self.assertEqual(by_id[ids["PARCIAL2"]]["total_items"], 2)
        self.assertEqual(by_id[ids["INICIADA"]]["total_items"], 2)
        order = [(read_order(row), -row_updated(row), row["id"]) for row in full["items"]]
        self.assertEqual(order, sorted(order))
        searched = self._get("/api/v1/warehouse/proposals", search="galv", limit=200)
        self.assertEqual({row["id"] for row in searched["items"]}, {ids["GALV1"], ids["GALV2"], ids["GALV3"]})


def read_order(row):
    order = {"NAO_DEFINIDO": 0, "AGUARDANDO_CONFIRMACAO": 1, "EM_SEPARACAO": 2, "SEPARADO": 3, "ALMOXARIFADO_ENTREGUE_PARCIAL": 4, "SEM_PARAFUSOS": 5, "ALMOXARIFADO_ENTREGUE": 6}
    return order.get(row["warehouse_status"], 99)


def row_updated(row):
    from datetime import datetime

    return datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")).timestamp() if row.get("updated_at") else 0


if __name__ == "__main__":
    unittest.main()
