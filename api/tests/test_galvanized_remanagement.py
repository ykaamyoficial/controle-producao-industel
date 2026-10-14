"""Remanejamento de itens galvanizados (Fase C do plano de logistica), de ponta a ponta.

A chave `GALVANIZED_REMANAGEMENT_ENABLED` fica desligada em producao ate a Fase E; aqui ela e
ligada por patch so nas chamadas que precisam, para provar a troca de dono das pecas em cada
estagio (a fabricar, aguardando galvanizacao, dentro de carga) e que, em todos os passos, a
conta de cada item fecha e o total das duas propostas nao muda.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

from api.tests import test_expedition_fiscal_read_path as read_path
from api.tests.test_proposals_integration import _integration_enabled, _item_payload, _proposal_payload

SWITCH = "api.app.modules.proposals.remanagement.GALVANIZED_REMANAGEMENT_ENABLED"
CODE = "450.400"


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class GalvanizedRemanagementTests(unittest.TestCase):
    setUpClass = read_path.ExpeditionFiscalReadPathTests.setUpClass
    tearDownClass = read_path.ExpeditionFiscalReadPathTests.tearDownClass
    setUp = read_path.ExpeditionFiscalReadPathTests.setUp
    _seed_admin = read_path.ExpeditionFiscalReadPathTests._seed_admin
    _headers = read_path.ExpeditionFiscalReadPathTests._headers
    _post = read_path.ExpeditionFiscalReadPathTests._post

    # ---- cenario -----------------------------------------------------------------------------------
    @contextmanager
    def switch_on(self):
        with patch(SWITCH, True):
            yield

    @contextmanager
    def switch_off(self):
        with patch(SWITCH, False):
            yield

    def _get(self, url, **params):
        response = self.client.get(url, params=params or None, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _proposal(self, number, quantity="10.0000"):
        payload = _proposal_payload(number, [_item_payload("1", product_code=CODE, quantity=quantity, requires_galvanization=True)])
        return self._post("/api/v1/proposals", payload)

    def _produce(self, proposal):
        released = self._post(f"/api/v1/proposals/{proposal['id']}/status", {"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"})
        started = self._post(f"/api/v1/production/proposals/{proposal['id']}/start", {"version": released["version"]})
        return self._post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", {"version": started["version"]})

    def _send(self, item_id, quantity):
        load = self._post("/api/v1/galvanization/loads", {"driver_name": "Motorista", "items": [{"proposal_item_id": item_id, "sent_quantity": quantity}]})
        return self._post(f"/api/v1/galvanization/loads/{load['id']}/release", {"version": load["version"]})

    def _return(self, load_id, *proposal_ids):
        current = self._get(f"/api/v1/galvanization/loads/{load_id}")
        return self._post(f"/api/v1/galvanization/loads/{load_id}/returns", {"version": current["version"], "proposal_ids": list(proposal_ids), "observation": "Retorno"})

    def _item_id(self, proposal_id):
        return self._get(f"/api/v1/proposals/{proposal_id}")["items"][0]["id"]

    def _ready_source(self, number, quantity="10.0000"):
        """Proposta galvanizada que ja voltou da galvanizacao: todas as pecas prontas na Expedicao."""
        proposal = self._produce(self._proposal(number, quantity))
        item_id = proposal["items"][0]["id"]
        load = self._send(item_id, quantity)
        self._return(load["id"], proposal["id"])
        detail = self._get(f"/api/v1/shipping/proposals/{proposal['id']}")
        self.assertEqual(detail["items"][0]["available_quantity"], quantity)
        return proposal, item_id

    def _stages(self, proposal_id):
        body = self._get("/api/v1/shipping/remanagements/stage-ledger", proposal_id=proposal_id)
        self.assertEqual([a for a in body["anomalies"] if a["severity"] == "ERROR"], [], body["anomalies"])
        item = body["items"][0]
        self.assertEqual(item["gap"], "0.0000", item)
        return item

    @staticmethod
    def _numbers(item):
        return tuple(item[key] for key in ("to_produce", "awaiting_galvanization", "in_galvanization", "ready", "delivered"))

    def _payload(self, destination, destination_item_id, source, source_item_id, quantity, operation_id=None, requested="10.0000"):
        payload = {
            "destination_proposal_id": destination["id"],
            "items": [{"destination_item_id": destination_item_id, "requested_quantity": requested}],
            "allocations": [{"destination_item_id": destination_item_id, "source_proposal_id": source["id"], "source_item_id": source_item_id, "allocated_quantity": quantity}],
            "reason": "Entrega antecipada",
        }
        if operation_id:
            payload["operation_id"] = operation_id
        return payload

    def _total(self, *proposal_ids):
        total = Decimal("0")
        for proposal_id in proposal_ids:
            item = self._stages(proposal_id)
            total += sum((Decimal(item[key]) for key in ("to_produce", "awaiting_galvanization", "in_galvanization", "ready", "delivered")), Decimal("0"))
        return total

    def _candidate_available(self, item_id):
        rows = self._get("/api/v1/galvanization/candidates", limit=200, include_unavailable="true")["items"]
        return next((Decimal(row["available_quantity"]) for row in rows if row["item_id"] == item_id), None)

    # ---- a chave desligada ------------------------------------------------------------------------------
    def test_galvanized_items_stay_blocked_while_the_switch_is_off(self):
        source, source_item_id = self._ready_source("GALV-OFF-A")
        destination = self._proposal("GALV-OFF-B")
        destination_item_id = destination["items"][0]["id"]
        with self.switch_off():
            review = self._post("/api/v1/shipping/remanagements/review", self._payload(destination, destination_item_id, source, source_item_id, "4.0000"))
            availability = self._post("/api/v1/shipping/remanagements/availability", {"destination_proposal_id": destination["id"], "items": [{"destination_item_id": destination_item_id, "requested_quantity": "4.0000"}]})
        self.assertFalse(review["valid"])
        self.assertTrue(any(error["code"] in {"OPERATIONAL_STATE_NOT_SUPPORTED", "SOURCE_ITEM_UNKNOWN"} for error in review["errors"]), review["errors"])
        self.assertEqual(availability["items"][0]["candidates"], [])

    def test_galvanized_items_are_found_as_sources_by_default(self):
        """O que fazia o remanejamento nao achar nada: sem nenhuma chave, o galvanizado pronto na Expedicao e candidato."""
        source, source_item_id = self._ready_source("GALV-ON-A")
        destination = self._proposal("GALV-ON-B")
        destination_item_id = destination["items"][0]["id"]
        availability = self._post("/api/v1/shipping/remanagements/availability", {"destination_proposal_id": destination["id"], "items": [{"destination_item_id": destination_item_id, "requested_quantity": "4.0000"}]})
        candidates = availability["items"][0]["candidates"]
        self.assertEqual([(c["source_proposal_id"], c["source_item_id"], c["available_quantity"]) for c in candidates], [(source["id"], source_item_id, "10.0000")])
        self.assertEqual(availability["items"][0]["coverage_status"], "SUFICIENTE")

    # ---- destino ainda nao fabricado: a obrigacao de fabricar muda de mao --------------------------------------
    def test_destination_not_produced_the_replacement_goes_through_galvanization_and_joins_the_ready_pieces(self):
        source, source_item_id = self._ready_source("GALV-A1")
        destination = self._proposal("GALV-B1")
        destination_item_id = destination["items"][0]["id"]
        before = self._total(source["id"], destination["id"])

        with self.switch_on():
            availability = self._post("/api/v1/shipping/remanagements/availability", {"destination_proposal_id": destination["id"], "items": [{"destination_item_id": destination_item_id, "requested_quantity": "4.0000"}]})
            self.assertEqual([c["source_proposal_id"] for c in availability["items"][0]["candidates"]], [source["id"]])
            payload = self._payload(destination, destination_item_id, source, source_item_id, "4.0000", "galv-op-0001")
            review = self._post("/api/v1/shipping/remanagements/review", payload)
            self.assertTrue(review["valid"], review)
            self.assertEqual(review["items"][0]["sources"][0]["stage_transfers"], [{"stage": "TO_PRODUCE", "quantity": "4.0000"}])
            self._post("/api/v1/shipping/remanagements/confirm", payload)

        # A cedeu 4 prontas e deve 4 a fabricar; B recebeu 4 prontas e tem 6 a fabricar.
        self.assertEqual(self._numbers(self._stages(source["id"])), ("4.0000", "0.0000", "0.0000", "6.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("6.0000", "0.0000", "0.0000", "4.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)

        # A fabrica a reposicao: ela vai para a fila da galvanizacao (nao entra pronta na Expedicao).
        current = self._get(f"/api/v1/proposals/{source['id']}")
        started = self._post(f"/api/v1/production/proposals/{source['id']}/start", {"version": current["version"]})
        self._post(f"/api/v1/production/proposals/{source['id']}/complete-items", {"version": started["version"], "item_ids": [source_item_id]})
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "4.0000", "0.0000", "6.0000", "0.0000"))
        self.assertEqual(self._candidate_available(source_item_id), Decimal("4.0000"))

        # A reposicao vai e volta da galvanizacao: junta-se as 6 prontas e A fica de novo com as 10.
        load = self._send(source_item_id, "4.0000")
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "4.0000", "6.0000", "0.0000"))
        self._return(load["id"], source["id"])
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._get(f"/api/v1/shipping/proposals/{source['id']}")["items"][0]["available_quantity"], "14.0000")
        self.assertTrue(self._get(f"/api/v1/proposals/{source['id']}")["items"][0]["galvanized"])

        # B fabrica e galvaniza as 6 que lhe restam e, ao voltarem, fica com 4 recebidas + 6 = 10 prontas.
        produced = self._produce(self._get(f"/api/v1/proposals/{destination['id']}"))
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "6.0000", "0.0000", "4.0000", "0.0000"))
        self.assertEqual(self._candidate_available(produced["items"][0]["id"]), Decimal("6.0000"))
        destination_load = self._send(produced["items"][0]["id"], "6.0000")
        self._return(destination_load["id"], destination["id"])
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._get(f"/api/v1/shipping/proposals/{destination['id']}")["items"][0]["available_quantity"], "10.0000")
        self.assertEqual(self._total(source["id"], destination["id"]), before)

    # ---- destino com pecas dentro de uma carga: a peca troca de dono dentro da carga ---------------------------
    def test_pieces_inside_a_load_change_owner_inside_the_load(self):
        source, source_item_id = self._ready_source("GALV-A2")
        destination = self._produce(self._proposal("GALV-B2"))
        destination_item_id = destination["items"][0]["id"]
        load = self._send(destination_item_id, "4.0000")  # 4 na galvanizacao, 6 fabricadas aguardando
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "6.0000", "4.0000", "0.0000", "0.0000"))
        before = self._total(source["id"], destination["id"])

        with self.switch_on():
            payload = self._payload(destination, destination_item_id, source, source_item_id, "4.0000", "galv-op-0002")
            review = self._post("/api/v1/shipping/remanagements/review", payload)
            self.assertTrue(review["valid"], review)
            # Decisao D1: as mais adiantadas primeiro - as 4 que estao na carga.
            self.assertEqual(review["items"][0]["sources"][0]["stage_transfers"], [{"stage": "IN_GALVANIZATION", "quantity": "4.0000"}])
            self._post("/api/v1/shipping/remanagements/confirm", payload)

        # A: 6 prontas + 4 na galvanizacao (a carga continua a mesma). B: 4 prontas + 6 aguardando carga.
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "4.0000", "6.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "6.0000", "0.0000", "4.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)
        detail = self._get(f"/api/v1/galvanization/loads/{load['id']}")
        rows = {row["proposal_item_id"]: row for row in detail["items"] if row.get("active", True)}
        self.assertEqual(rows[source_item_id]["sent_quantity"], "4.0000")
        self.assertNotIn(destination_item_id, rows)
        # A origem aparece em Galvanizacao enquanto as 4 nao voltam, e continua na Expedicao com as 6 prontas.
        self.assertEqual(self._get(f"/api/v1/proposals/{source['id']}")["current_area"], "GALVANIZACAO")
        self.assertEqual(self._get(f"/api/v1/shipping/proposals/{source['id']}")["items"][0]["pending_quantity"], "6.0000")

        # O retorno da carga vale para a origem: as 4 voltam e juntam-se as 6 prontas.
        self._return(load["id"], source["id"])
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._get(f"/api/v1/proposals/{source['id']}")["current_area"], "EXPEDICAO")

        # B manda as 6 que tem e, ao voltarem, fica com as 10.
        second = self._send(destination_item_id, "6.0000")
        self._return(second["id"], destination["id"])
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)

    def test_most_advanced_pieces_go_first_across_stages(self):
        source, source_item_id = self._ready_source("GALV-A3")
        destination = self._produce(self._proposal("GALV-B3"))
        destination_item_id = destination["items"][0]["id"]
        load = self._send(destination_item_id, "4.0000")
        before = self._total(source["id"], destination["id"])

        with self.switch_on():
            payload = self._payload(destination, destination_item_id, source, source_item_id, "7.0000", "galv-op-0003")
            review = self._post("/api/v1/shipping/remanagements/review", payload)
            self.assertTrue(review["valid"], review)
            self.assertEqual(
                review["items"][0]["sources"][0]["stage_transfers"],
                [{"stage": "IN_GALVANIZATION", "quantity": "4.0000"}, {"stage": "AWAITING_GALVANIZATION", "quantity": "3.0000"}],
            )
            self._post("/api/v1/shipping/remanagements/confirm", payload)

        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "3.0000", "4.0000", "3.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "3.0000", "0.0000", "7.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)
        # As 3 fabricadas que a origem recebeu ja podem ir em carga.
        self.assertEqual(self._candidate_available(source_item_id), Decimal("3.0000"))
        self.assertEqual(self._candidate_available(destination_item_id), Decimal("3.0000"))
        # Cada uma manda o que tem e, ao voltar tudo, a conta fecha nas duas.
        self._return(load["id"], source["id"])
        own = self._send(source_item_id, "3.0000")
        self._return(own["id"], source["id"])
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        theirs = self._send(destination_item_id, "3.0000")
        self._return(theirs["id"], destination["id"])
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))

    def test_the_conservation_check_also_covers_galvanized_swaps(self):
        source, source_item_id = self._ready_source("GALV-A4")
        destination = self._produce(self._proposal("GALV-B4"))
        destination_item_id = destination["items"][0]["id"]
        load = self._send(destination_item_id, "4.0000")
        with self.switch_on(), patch("api.app.modules.proposals.service.verify_swap_conservation", return_value=["falha simulada"]):
            response = self.client.post("/api/v1/shipping/remanagements/confirm", json=self._payload(destination, destination_item_id, source, source_item_id, "4.0000", "galv-op-0004"), headers=self.headers)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["error"]["code"], "REMANAGEMENT_CONSERVATION_VIOLATION")
        # Nada mudou: a carga segue com as 4 do destino e a origem com as 10 prontas.
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "6.0000", "4.0000", "0.0000", "0.0000"))
        rows = {row["proposal_item_id"]: row for row in self._get(f"/api/v1/galvanization/loads/{load['id']}")["items"]}
        self.assertEqual(rows[destination_item_id]["sent_quantity"], "4.0000")
        self.assertNotIn(source_item_id, rows)

    # ---- cenarios maiores ----------------------------------------------------------------------------------
    def test_source_gives_everything_leaves_the_expedition_and_comes_back_when_the_pieces_return(self):
        source, source_item_id = self._ready_source("GALV-A5")
        destination = self._produce(self._proposal("GALV-B5"))
        destination_item_id = destination["items"][0]["id"]
        load = self._send(destination_item_id, "4.0000")  # 4 na galvanizacao e 6 aguardando carga
        before = self._total(source["id"], destination["id"])
        self.assertEqual(self._get("/api/v1/shipping/proposals", search="GALV-A5")["total"], 1)

        with self.switch_on():
            payload = self._payload(destination, destination_item_id, source, source_item_id, "10.0000", "galv-op-0005")
            first = self._post("/api/v1/shipping/remanagements/confirm", payload)
            again = self._post("/api/v1/shipping/remanagements/confirm", payload)  # mesmo pedido: nada se repete
        self.assertEqual(first["operation_id"], again["operation_id"])

        # R4: a origem cedeu tudo e sai sozinha da lista da Expedicao; as pecas que recebeu seguem seus processos.
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "6.0000", "4.0000", "0.0000", "0.0000"))
        self.assertEqual(self._get("/api/v1/shipping/proposals", search="GALV-A5")["total"], 0)
        self.assertEqual(self._get(f"/api/v1/proposals/{source['id']}")["current_area"], "GALVANIZACAO")
        # R6: o destino recebeu as 10 prontas e ja pode ser separado.
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._get("/api/v1/shipping/proposals", search="GALV-B5")["total"], 1)
        self.assertEqual(self._total(source["id"], destination["id"]), before)
        # A historia: um unico remanejamento gravado (o segundo pedido foi so a repeticao do primeiro).
        self.assertEqual(self._get("/api/v1/shipping/remanagements", proposal_id=source["id"])["total"], 1)

        # As 4 voltam da carga; depois as 6 vao em outra carga e voltam: a origem volta a ter as 10 prontas.
        self._return(load["id"], source["id"])
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "6.0000", "0.0000", "4.0000", "0.0000"))
        self.assertEqual(self._get("/api/v1/shipping/proposals", search="GALV-A5")["total"], 1)
        second = self._send(source_item_id, "6.0000")
        self._return(second["id"], source["id"])
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], destination["id"]), before)

    def test_two_sources_into_one_destination(self):
        first, first_item_id = self._ready_source("GALV-A6", "6.0000")
        second, second_item_id = self._ready_source("GALV-A7", "6.0000")
        destination = self._proposal("GALV-B6")
        destination_item_id = destination["items"][0]["id"]
        before = self._total(first["id"], second["id"], destination["id"])
        payload = {
            "operation_id": "galv-op-0006",
            "destination_proposal_id": destination["id"],
            "items": [{"destination_item_id": destination_item_id, "requested_quantity": "10.0000"}],
            "allocations": [
                {"destination_item_id": destination_item_id, "source_proposal_id": first["id"], "source_item_id": first_item_id, "allocated_quantity": "6.0000"},
                {"destination_item_id": destination_item_id, "source_proposal_id": second["id"], "source_item_id": second_item_id, "allocated_quantity": "4.0000"},
            ],
            "reason": "Duas origens",
        }
        with self.switch_on():
            self._post("/api/v1/shipping/remanagements/confirm", payload)
        self.assertEqual(self._numbers(self._stages(destination["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(first["id"])), ("6.0000", "0.0000", "0.0000", "0.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(second["id"])), ("4.0000", "0.0000", "0.0000", "2.0000", "0.0000"))
        self.assertEqual(self._total(first["id"], second["id"], destination["id"]), before)

    def test_one_source_serves_two_destinations_in_sequence_and_replaces_everything_through_galvanization(self):
        source, source_item_id = self._ready_source("GALV-A8")
        first = self._proposal("GALV-B7", "6.0000")
        second = self._proposal("GALV-B8", "4.0000")
        first_item_id, second_item_id = first["items"][0]["id"], second["items"][0]["id"]
        before = self._total(source["id"], first["id"], second["id"])
        with self.switch_on():
            self._post("/api/v1/shipping/remanagements/confirm", self._payload(first, first_item_id, source, source_item_id, "6.0000", "galv-op-0007", requested="6.0000"))
            self._post("/api/v1/shipping/remanagements/confirm", self._payload(second, second_item_id, source, source_item_id, "4.0000", "galv-op-0008", requested="4.0000"))
        self.assertEqual(self._numbers(self._stages(source["id"])), ("10.0000", "0.0000", "0.0000", "0.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(first["id"])), ("0.0000", "0.0000", "0.0000", "6.0000", "0.0000"))
        self.assertEqual(self._numbers(self._stages(second["id"])), ("0.0000", "0.0000", "0.0000", "4.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], first["id"], second["id"]), before)

        # A fabrica as 10 de reposicao (as duas obrigacoes), galvaniza e volta com as 10 prontas.
        current = self._get(f"/api/v1/proposals/{source['id']}")
        started = self._post(f"/api/v1/production/proposals/{source['id']}/start", {"version": current["version"]})
        self._post(f"/api/v1/production/proposals/{source['id']}/complete-items", {"version": started["version"], "item_ids": [source_item_id]})
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "10.0000", "0.0000", "0.0000", "0.0000"))
        load = self._send(source_item_id, "10.0000")
        self._return(load["id"], source["id"])
        self.assertEqual(self._numbers(self._stages(source["id"])), ("0.0000", "0.0000", "0.0000", "10.0000", "0.0000"))
        self.assertEqual(self._total(source["id"], first["id"], second["id"]), before)


if __name__ == "__main__":
    unittest.main()
