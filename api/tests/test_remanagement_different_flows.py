"""Remanejamento entre propostas com fluxos diferentes (plano de logistica, "fluxos diferentes").

O remanejamento acontece mesmo que o fluxo de cada proposta seja outro: as pecas que trocam de
dono seguem o caminho que ja seguiam, o destino pode ainda estar sem fluxo definido (e continua
assim) e a origem que nao fabrica passa a ficar devendo a reposicao. Em todos os passos a conta de
cada item fecha e o total das duas propostas nao muda.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from api.tests import test_expedition_fiscal_read_path as read_path
from api.tests.test_proposals_integration import _integration_enabled, _item_payload, _proposal_payload

CODE = "450.400"


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class DifferentFlowsRemanagementTests(unittest.TestCase):
    setUpClass = read_path.ExpeditionFiscalReadPathTests.setUpClass
    tearDownClass = read_path.ExpeditionFiscalReadPathTests.tearDownClass
    setUp = read_path.ExpeditionFiscalReadPathTests.setUp
    _seed_admin = read_path.ExpeditionFiscalReadPathTests._seed_admin
    _headers = read_path.ExpeditionFiscalReadPathTests._headers
    _post = read_path.ExpeditionFiscalReadPathTests._post

    # ---- cenario -----------------------------------------------------------------------------------
    def _get(self, url, **params):
        response = self.client.get(url, params=params or None, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _proposal(self, number, *, quantity="10.0000", produce=True, galvanize=True):
        payload = _proposal_payload(number, [_item_payload("1", product_code=CODE, quantity=quantity, produce_internally=produce, requires_galvanization=galvanize)])
        return self._post("/api/v1/proposals", payload)

    def _release(self, proposal):
        return self._post(f"/api/v1/proposals/{proposal['id']}/status", {"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"})

    def _produce(self, proposal):
        released = self._release(proposal)
        started = self._post(f"/api/v1/production/proposals/{proposal['id']}/start", {"version": released["version"]})
        return self._post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", {"version": started["version"]})

    def _send(self, item_id, quantity):
        load = self._post("/api/v1/galvanization/loads", {"driver_name": "Motorista", "items": [{"proposal_item_id": item_id, "sent_quantity": quantity}]})
        return self._post(f"/api/v1/galvanization/loads/{load['id']}/release", {"version": load["version"]})

    def _return(self, load_id, *proposal_ids):
        current = self._get(f"/api/v1/galvanization/loads/{load_id}")
        return self._post(f"/api/v1/galvanization/loads/{load_id}/returns", {"version": current["version"], "proposal_ids": list(proposal_ids), "observation": "Retorno"})

    def _galvanize_only_source(self, number, quantity="10.0000"):
        """Proposta que NAO fabrica (so galvaniza): ja nasce "produzida" e vai direto para a galvanizacao."""
        proposal = self._release(self._proposal(number, quantity=quantity, produce=False, galvanize=True))
        item_id = proposal["items"][0]["id"]
        load = self._send(item_id, quantity)
        self._return(load["id"], proposal["id"])
        self.assertEqual(self._get(f"/api/v1/shipping/proposals/{proposal['id']}")["items"][0]["available_quantity"], quantity)
        return proposal, item_id

    def _simple_source(self, number, quantity="10.0000"):
        """Proposta que fabrica e nao galvaniza, com tudo pronto na Expedicao."""
        proposal = self._produce(self._proposal(number, quantity=quantity, produce=True, galvanize=False))
        self.assertEqual(self._get(f"/api/v1/shipping/proposals/{proposal['id']}")["items"][0]["available_quantity"], quantity)
        return proposal, proposal["items"][0]["id"]

    def _undefined_destination(self, number, quantity="10.0000"):
        payload = _proposal_payload(number, [_item_payload("1", product_code=CODE, quantity=quantity, produce_internally=None, requires_galvanization=None)])
        return self._post("/api/v1/proposals", payload)

    def _stages(self, proposal_id):
        body = self._get("/api/v1/shipping/remanagements/stage-ledger", proposal_id=proposal_id)
        self.assertEqual([a for a in body["anomalies"] if a["severity"] == "ERROR"], [], body["anomalies"])
        item = body["items"][0]
        self.assertEqual(item["gap"], "0.0000", item)
        return item

    @staticmethod
    def _numbers(item):
        return tuple(item[key] for key in ("to_produce", "awaiting_galvanization", "in_galvanization", "ready", "delivered"))

    def _payload(self, destination, destination_item_id, source, source_item_id, quantity, operation_id, requested="10.0000"):
        return {
            "destination_proposal_id": destination["id"],
            "items": [{"destination_item_id": destination_item_id, "requested_quantity": requested}],
            "allocations": [{"destination_item_id": destination_item_id, "source_proposal_id": source["id"], "source_item_id": source_item_id, "allocated_quantity": quantity}],
            "reason": "Entrega antecipada",
            "operation_id": operation_id,
        }

    def _total(self, *proposal_ids):
        total = Decimal("0")
        for proposal_id in proposal_ids:
            item = self._stages(proposal_id)
            total += sum((Decimal(item[key]) for key in ("to_produce", "awaiting_galvanization", "in_galvanization", "ready", "delivered", "undefined_flow")), Decimal("0"))
        return total

    def _availability(self, destination, destination_item_id, quantity):
        return self._post("/api/v1/shipping/remanagements/availability", {"destination_proposal_id": destination["id"], "items": [{"destination_item_id": destination_item_id, "requested_quantity": quantity}]})

    # ---- origem que so galvaniza -> destino que fabrica e galvaniza -------------------------------------------
    def test_a_source_that_only_galvanizes_gives_ready_pieces_to_a_destination_that_also_produces(self):
        source, source_item_id = self._galvanize_only_source("FLX-A1")
        destination = self._proposal("FLX-B1")
        destination_item_id = destination["items"][0]["id"]
        before = self._total(source["id"], destination["id"])

        # Antes: "fluxo de producao diferente" escondia a origem. Agora ela e candidata.
        availability = self._availability(destination, destination_item_id, "4.0000")
        self.assertEqual([c["source_proposal_id"] for c in availability["items"][0]["candidates"]], [source["id"]])
        payload = self._payload(destination, destination_item_id, source, source_item_id, "4.0000", "flx-op-0001")
        review = self._post("/api/v1/shipping/remanagements/review", payload)
        self.assertTrue(review["valid"], review)
        self.assertEqual(review["items"][0]["sources"][0]["stage_transfers"], [{"stage": "TO_PRODUCE", "quantity": "4.0000"}])
        self._post("/api/v1/shipping/remanagements/confirm", payload)

        # A cedeu 4 prontas e passou a dever 4 a fabricar; B recebeu 4 prontas e tem 6 a fabricar.
        self.assertEqual(self._numbers(self._stages(source["id"])), ("4.0000", "0.0000", "0.0000", "6.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("6.0000", "0.0000", "0.0000", "4.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)
        # Cada item continua com o fluxo que tinha.
        source_item = self._get(f"/api/v1/proposals/{source['id']}")["items"][0]
        self.assertEqual((source_item["produce_internally"], source_item["requires_galvanization"]), ("NAO", "SIM"))

        # A origem nao fabrica, mas agora deve pecas: a producao dessas pecas aparece nela.
        rows = self._get("/api/v1/production/items", pending="true", limit=200)["items"]
        hosted = next((row for row in rows if row["item_id"] == source_item_id), None)
        self.assertIsNotNone(hosted, "a reposicao devida pela origem precisa aparecer na Producao")
        self.assertEqual(hosted["production_pending_quantity"], "4.0000")

        current = self._get(f"/api/v1/proposals/{source['id']}")
        started = self._post(f"/api/v1/production/proposals/{source['id']}/start", {"version": current["version"]})
        self._post(f"/api/v1/production/proposals/{source['id']}/complete-items", {"version": started["version"], "item_ids": [source_item_id]})
        # Fabricada: segue o fluxo da PROPRIA origem (galvanizacao), nao entra pronta direto.
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "4.0000", "0.0000", "6.0000", "0.0000"))
        load = self._send(source_item_id, "4.0000")
        self._return(load["id"], source["id"])
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)

    # ---- destino sem fluxo definido ------------------------------------------------------------------------------
    def test_a_destination_without_a_defined_flow_receives_the_pieces_and_keeps_the_flow_undefined(self):
        source, source_item_id = self._simple_source("FLX-A2")
        destination = self._undefined_destination("FLX-B2")
        destination_item_id = destination["items"][0]["id"]
        before = self._total(source["id"], destination["id"])
        destination_before = self._get(f"/api/v1/proposals/{destination['id']}")

        availability = self._availability(destination, destination_item_id, "4.0000")
        self.assertEqual([c["source_proposal_id"] for c in availability["items"][0]["candidates"]], [source["id"]])
        payload = self._payload(destination, destination_item_id, source, source_item_id, "4.0000", "flx-op-0002")
        review = self._post("/api/v1/shipping/remanagements/review", payload)
        self.assertTrue(review["valid"], review)
        self.assertEqual(review["items"][0]["sources"][0]["stage_transfers"], [{"stage": "UNDEFINED_FLOW", "quantity": "4.0000"}])
        self._post("/api/v1/shipping/remanagements/confirm", payload)

        # A cedeu 4 e fica devendo 4 a fabricar (fluxo dela); B recebeu 4 prontas e as outras 6 continuam sem fluxo.
        self.assertEqual(self._numbers(self._stages(source["id"])), ("4.0000", "0.0000", "0.0000", "6.0000", "0.0000"))
        destination_stages = self._stages(destination["id"])
        self.assertEqual((destination_stages["ready"], destination_stages["undefined_flow"], destination_stages["to_produce"]), ("4.0000", "6.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)

        # O destino segue exatamente como estava: fluxo indefinido, mesma area; so ganhou as 4 prontas.
        destination_after = self._get(f"/api/v1/proposals/{destination['id']}")
        item = destination_after["items"][0]
        self.assertEqual((item["produce_internally"], item["requires_galvanization"], item["flow_defined"]), ("INDEFINIDO", "INDEFINIDO", False))
        self.assertEqual(destination_after["current_area"], destination_before["current_area"])
        self.assertEqual(self._get(f"/api/v1/shipping/proposals/{destination['id']}")["items"][0]["available_quantity"], "4.0000")

        # A conferencia periodica (que reconcilia a Expedicao) nao desfaz o que o destino recebeu.
        self._availability(destination, destination_item_id, "4.0000")
        self.assertEqual(self._get(f"/api/v1/shipping/proposals/{destination['id']}")["items"][0]["available_quantity"], "4.0000")
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "0.0000", "0.0000", "4.0000", "0.0000"))

    def test_an_item_without_flow_cannot_pass_on_the_pieces_it_received(self):
        """A origem precisa ter fluxo definido: a reposicao dela segue o fluxo da propria origem."""
        source, source_item_id = self._simple_source("FLX-A3")
        undefined = self._undefined_destination("FLX-B3")
        undefined_item_id = undefined["items"][0]["id"]
        self._post("/api/v1/shipping/remanagements/confirm", self._payload(undefined, undefined_item_id, source, source_item_id, "4.0000", "flx-op-0003"))
        self.assertEqual(self._get(f"/api/v1/shipping/proposals/{undefined['id']}")["items"][0]["available_quantity"], "4.0000")

        another = self._proposal("FLX-C3")
        availability = self._availability(another, another["items"][0]["id"], "4.0000")
        self.assertEqual([c["source_proposal_id"] for c in availability["items"][0]["candidates"]], [source["id"]])

    # ---- pecas ja fabricadas so cabem em quem galvaniza ------------------------------------------------------
    def test_made_pieces_of_a_galvanized_destination_cannot_go_to_a_source_that_does_not_galvanize(self):
        source, source_item_id = self._simple_source("FLX-A4")
        destination = self._produce(self._proposal("FLX-B4"))
        destination_item_id = destination["items"][0]["id"]
        self._send(destination_item_id, "4.0000")  # 4 na galvanizacao, 6 fabricadas aguardando carga: nada "a fabricar"
        before = self._total(source["id"], destination["id"])

        payload = self._payload(destination, destination_item_id, source, source_item_id, "4.0000", "flx-op-0004")
        review = self._post("/api/v1/shipping/remanagements/review", payload)
        self.assertFalse(review["valid"])
        self.assertTrue(any(error["code"] == "DESTINATION_IN_FLIGHT_INSUFFICIENT" and "não passa pela galvanização" in error["message"] for error in review["errors"]), review["errors"])
        response = self.client.post("/api/v1/shipping/remanagements/confirm", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 409, response.text)
        # Nada foi gravado.
        self.assertEqual(self._total(source["id"], destination["id"]), before)
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))

    def test_a_galvanized_destination_that_has_not_been_produced_can_receive_from_a_source_that_does_not_galvanize(self):
        source, source_item_id = self._simple_source("FLX-A5")
        destination = self._proposal("FLX-B5")
        destination_item_id = destination["items"][0]["id"]
        before = self._total(source["id"], destination["id"])
        payload = self._payload(destination, destination_item_id, source, source_item_id, "4.0000", "flx-op-0005")
        review = self._post("/api/v1/shipping/remanagements/review", payload)
        self.assertTrue(review["valid"], review)
        self.assertEqual(review["items"][0]["sources"][0]["stage_transfers"], [{"stage": "TO_PRODUCE", "quantity": "4.0000"}])
        self._post("/api/v1/shipping/remanagements/confirm", payload)
        self.assertEqual(self._numbers(self._stages(source["id"])), ("4.0000", "0.0000", "0.0000", "6.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("6.0000", "0.0000", "0.0000", "4.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)

        # A fabrica a reposicao e ela entra pronta na Expedicao (o fluxo de A nao galvaniza).
        current = self._get(f"/api/v1/proposals/{source['id']}")
        started = self._post(f"/api/v1/production/proposals/{source['id']}/start", {"version": current["version"]})
        self._post(f"/api/v1/production/proposals/{source['id']}/complete-items", {"version": started["version"], "item_ids": [source_item_id]})
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)


if __name__ == "__main__":
    unittest.main()
