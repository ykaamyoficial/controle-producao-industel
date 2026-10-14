"""`GET /proposals/{id}/family` e o resumo de parciais da lista geral (leitura apenas).

Cobre o caso CP 05493: mae-referencia sem itens, com as pecas espalhadas em
parciais (uma na Galvanizacao, outra na Expedicao). A familia tem de mostrar
os itens, onde estao, o status consolidado e os totais -- e ser a mesma
quando aberta pela mae ou por uma parcial.
"""

from __future__ import annotations

import asyncio
import unittest
from decimal import Decimal

from api.app.modules.proposals.family import consolidate
from api.app.modules.proposals.schemas import FamilyStageQuantities
from api.tests import test_proposals_integration as base
from api.tests.test_proposals_integration import _integration_enabled, _item_payload, _proposal_payload


def _stages(**values) -> FamilyStageQuantities:
    return FamilyStageQuantities(**{name: Decimal(str(value)) for name, value in values.items()})


class ConsolidateTests(unittest.TestCase):
    def test_single_place_with_one_row_keeps_the_rows_own_status(self):
        result = consolidate(_stages(ready=4), partial_count=0, own_area="EXPEDICAO", own_status="EM_SEPARACAO")
        self.assertEqual((result.kind, result.area, result.status, result.label), ("SINGLE", "EXPEDICAO", "EM_SEPARACAO", "Expedição"))

    def test_single_place_with_many_rows_is_uniform_and_drops_the_row_status(self):
        result = consolidate(_stages(ready=4), partial_count=2, own_area="CONTROLE_GERAL", own_status="EM_PRODUCAO")
        self.assertEqual((result.kind, result.area, result.status), ("UNIFORM", "EXPEDICAO", None))

    def test_mixed_places_list_each_quantity_in_display_order(self):
        result = consolidate(_stages(ready=7, to_produce=1), partial_count=2, own_area="CONTROLE_GERAL", own_status="EM_PRODUCAO")
        self.assertEqual(result.kind, "MIXED")
        self.assertEqual(result.label, "Parcial · 7 un. na Expedição · 1 un. em Produção")
        self.assertEqual([part.place for part in result.parts], ["EXPEDICAO", "PRODUCAO"])

    def test_everything_delivered_is_not_called_partial(self):
        result = consolidate(_stages(delivered=5), partial_count=2, own_area="EXPEDICAO", own_status="ENTREGUE")
        self.assertEqual(result.label, "Entregue")

    def test_delivered_plus_pending_is_partial(self):
        result = consolidate(_stages(delivered=3, ready=2), partial_count=2, own_area=None, own_status=None)
        self.assertEqual(result.label, "Parcial · 2 un. na Expedição · 3 un. entregues")

    def test_galvanization_stages_are_summed(self):
        result = consolidate(_stages(awaiting_galvanization=1, in_galvanization=2), partial_count=2, own_area=None, own_status=None)
        self.assertEqual([(part.place, part.quantity) for part in result.parts], [("GALVANIZACAO", Decimal("3.0000"))])


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class ProposalFamilyApiTests(unittest.TestCase):
    setUpClass = base.ProposalsIntegrationTests.setUpClass
    tearDownClass = base.ProposalsIntegrationTests.tearDownClass
    setUp = base.ProposalsIntegrationTests.setUp
    _seed_admin = base.ProposalsIntegrationTests._seed_admin
    _headers = base.ProposalsIntegrationTests._headers
    _release_to_production = base.ProposalsIntegrationTests._release_to_production
    _active_child_ids = base.ProposalsIntegrationTests._active_child_ids

    def _split_proposal(self, number: str):
        """Mae com 3 itens que viram duas filhas: galvanizacao (itens 1 e 3) e expedicao (item 2)."""
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload(number, [
                _item_payload("1", requires_galvanization=True),
                _item_payload("2", requires_galvanization=False),
                _item_payload("3", requires_galvanization=True),
            ]),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()
        first = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": started["version"], "item_ids": [started["items"][0]["id"]]},
            headers=headers,
        ).json()
        self.client.post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", json={"version": first["version"]}, headers=headers)
        return proposal["id"], headers

    def _family(self, proposal_id: int, headers: dict) -> dict:
        response = self.client.get(f"/api/v1/proposals/{proposal_id}/family", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_mother_without_items_shows_every_item_and_where_it_is(self):
        mother_id, headers = self._split_proposal("CP05493")
        family = self._family(mother_id, headers)
        self.assertEqual((family["root_id"], family["partial_count"], family["has_partials"]), (mother_id, 2, True))
        self.assertEqual([member["role"] for member in family["members"]], ["MAE", "PARCIAL", "PARCIAL"])
        self.assertTrue(family["members"][0]["is_reference"])
        self.assertEqual(family["members"][0]["item_count"], 0)
        self.assertEqual(sorted(row["item_number"] for row in family["items"]), ["1", "2", "3"])
        self.assertEqual({row["partial_label"] for row in family["items"]}, {"P1", "P2"})
        places = {row["item_number"]: row["place"] for row in family["items"]}
        self.assertEqual(places["2"], "EXPEDICAO")
        self.assertIn(places["1"], {"PRODUCAO", "GALVANIZACAO"})
        self.assertEqual(family["consolidated"]["kind"], "MIXED")
        self.assertTrue(family["consolidated"]["label"].startswith("Parcial"))
        # as unidades de cada estagio fecham com o total pedido
        stages = family["stages"]
        placed = sum(Decimal(stages[name]) for name in ("to_produce", "awaiting_galvanization", "in_galvanization", "ready", "delivered", "undefined_flow"))
        self.assertEqual(placed, Decimal(family["totals"]["total_units"]))

    def test_child_partials_are_listed_for_the_selector_with_item_keys(self):
        mother_id, headers = self._split_proposal("CP05497")
        family = self._family(mother_id, headers)
        partials = family["partials"]
        self.assertEqual([p["kind"] for p in partials], ["PROPOSTA", "PROPOSTA"])
        self.assertEqual([p["label"] for p in partials], ["P1", "P2"])
        self.assertEqual({p["proposal_number"] for p in partials}, {"CP05497-1", "CP05497-2"})
        self.assertEqual(sum(p["item_count"] for p in partials), 3)
        keys = {p["key"] for p in partials}
        for row in family["items"]:
            self.assertEqual(len(row["partial_keys"]), 1)
            self.assertIn(row["partial_keys"][0], keys)

    def test_same_proposal_with_pieces_in_two_places_becomes_lot_partials(self):
        """Sem proposta-filha: um item vai para a galvanizacao e outro para a expedicao na mesma conclusao."""
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload("CP05498", [
                _item_payload("1", requires_galvanization=True),
                _item_payload("2", requires_galvanization=False),
            ]),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()
        done = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", json={"version": started["version"]}, headers=headers)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(asyncio.run(self._active_child_ids(proposal["id"])), [], "o cenario nao deve criar filha")
        family = self._family(proposal["id"], headers)
        partials = family["partials"]
        self.assertEqual([p["kind"] for p in partials], ["LOTE", "LOTE"])
        self.assertEqual([p["label"] for p in partials], ["P1", "P2"])
        self.assertEqual({p["place"] for p in partials}, {"EXPEDICAO", "GALVANIZACAO"})
        self.assertTrue(all(p["proposal_id"] == proposal["id"] and p["proposal_number"] is None for p in partials))
        by_place = {p["place"]: p for p in partials}
        self.assertEqual(by_place["EXPEDICAO"]["item_count"], 1)
        self.assertEqual(by_place["GALVANIZACAO"]["item_count"], 1)
        units = sum(Decimal(p["total_units"]) for p in partials)
        self.assertEqual(units, Decimal(family["totals"]["total_units"]))
        for row in family["items"]:
            self.assertEqual(len(row["partial_keys"]), 1)

    def test_single_place_proposal_has_no_partials(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP05499"), headers=headers).json()
        self.assertEqual(self._family(proposal["id"], headers)["partials"], [])

    def test_family_is_the_same_when_opened_from_a_partial(self):
        mother_id, headers = self._split_proposal("CP05494")
        child_ids = asyncio.run(self._active_child_ids(mother_id))
        from_mother = self._family(mother_id, headers)
        from_child = self._family(child_ids[0], headers)
        self.assertEqual(from_child["root_id"], mother_id)
        self.assertEqual(from_child["proposal_id"], child_ids[0])
        self.assertEqual(from_child["items"], from_mother["items"])
        self.assertEqual(from_child["totals"], from_mother["totals"])
        self.assertEqual([m["proposal_id"] for m in from_child["members"]], [m["proposal_id"] for m in from_mother["members"]])
        self.assertEqual([m["is_requested"] for m in from_child["members"]], [m["proposal_id"] == child_ids[0] for m in from_child["members"]])

    def test_proposal_without_partials_is_a_family_of_one(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP05495"), headers=headers).json()
        family = self._family(proposal["id"], headers)
        self.assertEqual((family["partial_count"], family["has_partials"]), (0, False))
        self.assertEqual([member["role"] for member in family["members"]], ["UNICA"])
        self.assertEqual(len(family["items"]), len(proposal["items"]))

    def test_unknown_proposal_is_404(self):
        headers = self._headers()
        self.assertEqual(self.client.get("/api/v1/proposals/999999/family", headers=headers).status_code, 404)

    def test_general_list_carries_partial_badges_only_on_the_mother(self):
        mother_id, headers = self._split_proposal("CP05496")
        listed = self.client.get("/api/v1/proposals", params={"limit": 50}, headers=headers).json()["items"]
        row = next(item for item in listed if item["id"] == mother_id)
        self.assertEqual(row["partials_count"], 2)
        self.assertEqual([badge["label"] for badge in row["partials"]], ["P1", "P2"])
        self.assertEqual({badge["proposal_id"] for badge in row["partials"]}, set(asyncio.run(self._active_child_ids(mother_id))))
        self.assertTrue(all(item["partials_count"] == 0 for item in listed if item["id"] != mother_id))


if __name__ == "__main__":
    unittest.main()
