"""Remanejamento por linhas e parciais (plano REMANEJAMENTO_PARCIAIS_PLANO.md), de ponta a ponta.

A chave `REMANAGEMENT_BY_ROWS_ENABLED` e ligada por patch. Em todos os passos a conta de cada linha fecha e as
pecas por produto e por estagio nao mudam.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from api.tests import test_expedition_fiscal_read_path as read_path
from api.tests.test_proposals_integration import _integration_enabled, _item_payload, _proposal_payload

SWITCH = "api.app.modules.proposals.remanagement.REMANAGEMENT_BY_ROWS_ENABLED"


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class RemanagementByRowsTests(unittest.TestCase):
    setUpClass = read_path.ExpeditionFiscalReadPathTests.setUpClass
    tearDownClass = read_path.ExpeditionFiscalReadPathTests.tearDownClass
    setUp = read_path.ExpeditionFiscalReadPathTests.setUp
    _seed_admin = read_path.ExpeditionFiscalReadPathTests._seed_admin
    _headers = read_path.ExpeditionFiscalReadPathTests._headers
    _post = read_path.ExpeditionFiscalReadPathTests._post

    # ---- cenario ---------------------------------------------------------------------------------------
    def _get(self, url, **params):
        response = self.client.get(url, params=params or None, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _proposal(self, number, items, *, galvanize=True):
        payload = _proposal_payload(number, [
            _item_payload(item_number, product_code=code, quantity=qty, produce_internally=True, requires_galvanization=galvanize)
            for item_number, code, qty in items
        ])
        return self._post("/api/v1/proposals", payload)

    def _release(self, proposal):
        return self._post(f"/api/v1/proposals/{proposal['id']}/status", {"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"})

    def _produce(self, proposal_id):
        current = self._get(f"/api/v1/proposals/{proposal_id}")
        if current["current_area"] != "PRODUCAO" or current["production_status"] in (None, "", "NAO_INICIADO") and current["current_status"] == "RASCUNHO":
            current = self._release(current)
        started = self._post(f"/api/v1/production/proposals/{proposal_id}/start", {"version": current["version"]})
        return self._post(f"/api/v1/production/proposals/{proposal_id}/complete-items", {"version": started["version"]})

    def _send(self, *item_quantities):
        load = self._post("/api/v1/galvanization/loads", {"driver_name": "Motorista", "items": [{"proposal_item_id": item_id, "sent_quantity": qty} for item_id, qty in item_quantities]})
        return self._post(f"/api/v1/galvanization/loads/{load['id']}/release", {"version": load["version"]})

    def _return(self, load_id, *proposal_ids):
        current = self._get(f"/api/v1/galvanization/loads/{load_id}")
        return self._post(f"/api/v1/galvanization/loads/{load_id}/returns", {"version": current["version"], "proposal_ids": list(proposal_ids), "observation": "Retorno"})

    def _ready_source(self, number, items):
        """Proposta galvanizada de varios itens que ja voltou da galvanizacao (tudo pronto na Expedicao)."""
        proposal = self._release(self._proposal(number, items))
        produced = self._produce(proposal["id"])
        rows = [(item["id"], item["quantity"]) for item in produced["items"]]
        load = self._send(*rows)
        self._return(load["id"], proposal["id"])
        return produced

    def _destination(self, number, items):
        return self._release(self._proposal(number, items))

    def _item_ids(self, proposal):
        return {item["item_number"]: item["id"] for item in self._get(f"/api/v1/proposals/{proposal['id']}")["items"]}

    def _family(self, number):
        """Propostas ativas cujo numero comeca com `number` (a mae e as filhas), por numero."""
        rows = self._get("/api/v1/proposals", search=number, limit=50)["items"]
        rows += self._get("/api/v1/partials/proposals", search=number, limit=50)["items"]
        return {row["proposal_number"]: row for row in rows if row["proposal_number"].startswith(number)}

    def _stages(self, proposal_id):
        """Linhas que a proposta tem de fato (a mae mostra tambem as das filhas), do controle de pecas."""
        body = self._get("/api/v1/shipping/remanagements/stage-ledger", proposal_id=proposal_id)
        self.assertEqual([a for a in body["anomalies"] if a["severity"] == "ERROR"], [], body["anomalies"])
        for item in body["items"]:
            self.assertEqual(item["gap"], "0.0000", item)
        return [item for item in body["items"] if item["proposal_id"] == proposal_id]

    def _codes(self, proposal_id):
        return sorted(item["product_code"] for item in self._stages(proposal_id))

    def _payload(self, destination, lines, operation_id):
        return {
            "destination_proposal_id": destination["id"],
            "items": [{"destination_item_id": d, "requested_quantity": str(sum(Decimal(q) for dd, _s, _sp, q in lines if dd == d))} for d in sorted({line[0] for line in lines})],
            "allocations": [{"destination_item_id": d, "source_proposal_id": sp, "source_item_id": s, "allocated_quantity": q} for d, s, sp, q in lines],
            "reason": "Entrega antecipada",
            "operation_id": operation_id,
        }

    # ---- itens inteiros: o caso da base de teste (CP 05493 cede o item 3 para a CP 05640) ---------------------
    def test_whole_item_splits_the_source_into_p1_and_p2_and_the_destination_keeps_the_rest(self):
        items = [("1", "450.400", "2.0000"), ("2", "450.398", "1.0000"), ("3", "450.830", "1.0000"), ("4", "450.3", "1.0000")]
        source = self._ready_source("ROW-A1", items)
        destination = self._destination("ROW-B1", items)
        source_items, destination_items = self._item_ids(source), self._item_ids(destination)
        payload = self._payload(destination, [(destination_items["3"], source_items["3"], source["id"], "1.0000")], "row-op-0001")
        with patch(SWITCH, True):
            review = self._post("/api/v1/shipping/remanagements/review", payload)
            self.assertTrue(review["valid"], review)
            self._post("/api/v1/shipping/remanagements/confirm", payload)

        origin = self._family("ROW-A1")
        self.assertEqual(sorted(origin), ["ROW-A1", "ROW-A1-1", "ROW-A1-2"])
        self.assertEqual(origin["ROW-A1"]["current_area"], "CONTROLE_GERAL")
        ready, produce = origin["ROW-A1-1"], origin["ROW-A1-2"]
        self.assertEqual(ready["current_area"], "EXPEDICAO")
        self.assertEqual(produce["current_area"], "PRODUCAO")
        self.assertEqual(self._codes(ready["id"]), ["450.3", "450.398", "450.400"])
        self.assertEqual(self._codes(produce["id"]), ["450.830"])

        target = self._family("ROW-B1")
        self.assertEqual(sorted(target), ["ROW-B1", "ROW-B1-1"])
        self.assertEqual(target["ROW-B1"]["current_area"], "PRODUCAO")
        self.assertEqual(target["ROW-B1-1"]["current_area"], "EXPEDICAO")
        self.assertEqual(self._codes(target["ROW-B1-1"]["id"]), ["450.830"])
        self.assertEqual(self._codes(target["ROW-B1"]["id"]), ["450.3", "450.398", "450.400"])

        # O historico das duas propostas conta o remanejamento (mesmas frases do motor antigo).
        origin_history = [row["event_type"] for row in self._get(f"/api/v1/proposals/{source['id']}/history", limit=100)]
        destination_history = [row["event_type"] for row in self._get(f"/api/v1/proposals/{destination['id']}/history", limit=100)]
        self.assertIn("COMPENSATED_REMANAGEMENT_APPLIED", origin_history)
        self.assertIn("COMPENSATED_REMANAGEMENT_RECEIVED", destination_history)

    def test_the_replacement_comes_back_the_parts_join_and_the_mother_is_reborn(self):
        items = [("1", "450.400", "2.0000"), ("2", "450.398", "1.0000"), ("3", "450.830", "1.0000"), ("4", "450.3", "1.0000")]
        source = self._ready_source("ROW-A2", items)
        destination = self._destination("ROW-B2", items)
        source_items, destination_items = self._item_ids(source), self._item_ids(destination)
        payload = self._payload(destination, [(destination_items["3"], source_items["3"], source["id"], "1.0000")], "row-op-0002")
        with patch(SWITCH, True):
            self._post("/api/v1/shipping/remanagements/confirm", payload)

        # A CP ROW-A2-2 (o item 3, que veio a fabricar) e fabricada, vai para a galvanizacao e volta.
        replacement = self._family("ROW-A2")["ROW-A2-2"]
        self._produce(replacement["id"])
        self.assertEqual(self._family("ROW-A2")["ROW-A2-2"]["current_area"], "GALVANIZACAO")
        lot = self._stages(replacement["id"])[0]
        load = self._send((lot["item_id"], "1.0000"))
        self._return(load["id"], replacement["id"])

        family = self._family("ROW-A2")
        active = {number: row for number, row in family.items() if number != "ROW-A2" or row["current_area"] != "CONTROLE_GERAL"}
        self.assertEqual(sorted(active), ["ROW-A2"], active)
        self.assertEqual(family["ROW-A2"]["current_area"], "EXPEDICAO")
        self.assertEqual(self._codes(family["ROW-A2"]["id"]), ["450.3", "450.398", "450.400", "450.830"])
        self.assertEqual(sorted((item["item_id"], item["ready"]) for item in self._stages(family["ROW-A2"]["id"]))[0][1], "2.0000")

        # O destino fabrica os 3 itens que restavam, galvaniza e tambem volta a ser uma proposta so.
        target = self._family("ROW-B2")
        self._produce(target["ROW-B2"]["id"])
        pending = [(row["item_id"], row["quantity"] if "quantity" in row else row["requested"]) for row in self._stages(self._family("ROW-B2")["ROW-B2"]["id"])]
        self.assertEqual(pending, [])  # a mae entregou as linhas a uma filha em galvanizacao

    # ---- parte da quantidade, pecas em lugares diferentes ---------------------------------------------------------
    def test_part_of_the_quantity_takes_the_most_advanced_pieces_and_splits_the_item_in_lots(self):
        source = self._ready_source("ROW-A3", [("1", "450.400", "10.0000")])
        destination = self._release(self._proposal("ROW-B3", [("1", "450.400", "10.0000")]))
        produced = self._produce(destination["id"])
        y_id = produced["items"][0]["id"]
        load = self._send((y_id, "4.0000"))  # 4 na galvanizacao, 6 fabricadas aguardando carga
        x_id = self._item_ids(source)["1"]
        payload = self._payload(destination, [(y_id, x_id, source["id"], "5.0000")], "row-op-0003")
        with patch(SWITCH, True):
            review = self._post("/api/v1/shipping/remanagements/review", payload)
            self.assertTrue(review["valid"], review)
            self._post("/api/v1/shipping/remanagements/confirm", payload)

        origin = self._family("ROW-A3")
        self.assertEqual(sorted(origin), ["ROW-A3", "ROW-A3-1", "ROW-A3-2", "ROW-A3-3"])
        areas = {number: row["current_area"] for number, row in origin.items()}
        self.assertEqual(areas, {"ROW-A3": "CONTROLE_GERAL", "ROW-A3-1": "EXPEDICAO", "ROW-A3-2": "GALVANIZACAO", "ROW-A3-3": "GALVANIZACAO"})
        ready, in_load, awaiting = (self._stages(origin[number]["id"])[0] for number in ("ROW-A3-1", "ROW-A3-2", "ROW-A3-3"))
        self.assertEqual((ready["requested"], ready["ready"]), ("5.0000", "5.0000"))
        self.assertEqual((in_load["requested"], in_load["in_galvanization"]), ("4.0000", "4.0000"))
        self.assertEqual((awaiting["requested"], awaiting["awaiting_galvanization"]), ("1.0000", "1.0000"))

        target = self._family("ROW-B3")
        self.assertEqual(sorted(target), ["ROW-B3", "ROW-B3-1"])
        received = self._stages(target["ROW-B3-1"]["id"])[0]
        rest = self._stages(target["ROW-B3"]["id"])[0]
        self.assertEqual((received["requested"], received["ready"]), ("5.0000", "5.0000"))
        self.assertEqual((rest["requested"], rest["awaiting_galvanization"]), ("5.0000", "5.0000"))

        # A carga volta: as 4 pecas que estavam nela (agora da origem) se juntam as 5 prontas.
        self._return(load["id"], origin["ROW-A3-2"]["id"])
        family = self._family("ROW-A3")
        owners = {number: row for number, row in family.items() if row["current_area"] != "CONTROLE_GERAL"}
        self.assertEqual(sorted(owners), ["ROW-A3-1", "ROW-A3-3"])
        joined = self._stages(owners["ROW-A3-1"]["id"])[0]
        self.assertEqual((joined["requested"], joined["ready"]), ("9.0000", "9.0000"))

    # ---- cedeu tudo: nao ha o que dividir ---------------------------------------------------------------------------
    def test_giving_everything_in_one_batch_does_not_split_anyone(self):
        items = [("1", "450.7", "3.0000"), ("2", "450.32", "2.0000")]
        source = self._ready_source("ROW-A4", items)
        destination = self._destination("ROW-B4", items)
        source_items, destination_items = self._item_ids(source), self._item_ids(destination)
        payload = self._payload(destination, [
            (destination_items["1"], source_items["1"], source["id"], "3.0000"),
            (destination_items["2"], source_items["2"], source["id"], "2.0000"),
        ], "row-op-0004")
        with patch(SWITCH, True):
            self._post("/api/v1/shipping/remanagements/confirm", payload)
        origin, target = self._family("ROW-A4"), self._family("ROW-B4")
        self.assertEqual(sorted(origin), ["ROW-A4"])
        self.assertEqual(sorted(target), ["ROW-B4"])
        # A origem inteira voltou para o lugar das pecas que recebeu; o destino foi atendido por completo.
        self.assertEqual(origin["ROW-A4"]["current_area"], "PRODUCAO")
        self.assertEqual(target["ROW-B4"]["current_area"], "EXPEDICAO")
        self.assertEqual([item["to_produce"] for item in self._stages(origin["ROW-A4"]["id"])], ["3.0000", "2.0000"])
        self.assertEqual([item["ready"] for item in self._stages(target["ROW-B4"]["id"])], ["3.0000", "2.0000"])
        # Mesmo sem dividir: a origem espera as pecas de troca ("Substituida"); o destino ja esta todo pronto (sem marca).
        marks = {badge["proposal_number"]: badge for badge in self._get("/api/v1/shipping/remanagements/badges")["items"]}
        self.assertEqual(marks["ROW-A4"]["status"], "SUBSTITUIDA")
        self.assertEqual([(e["direction"], e["counterpart_proposal_number"]) for e in marks["ROW-A4"]["entries"]], [("CEDEU", "ROW-B4")])
        self.assertNotIn("ROW-B4", marks)

    # ---- fluxos diferentes: o que veio pronto de origem simples fica separado do resto galvanizado ------------------------
    def test_ready_pieces_from_a_simple_source_stay_as_a_separate_part_of_a_galvanized_destination(self):
        source = self._release(self._proposal("ROW-A5", [("1", "450.400", "10.0000")], galvanize=False))
        self._produce(source["id"])
        destination = self._release(self._proposal("ROW-B5", [("1", "450.400", "10.0000")]))
        x_id, y_id = self._item_ids(source)["1"], self._item_ids(destination)["1"]
        payload = self._payload(destination, [(y_id, x_id, source["id"], "4.0000")], "row-op-0005")
        with patch(SWITCH, True):
            self._post("/api/v1/shipping/remanagements/confirm", payload)
        origin = self._family("ROW-A5")
        self.assertEqual(sorted(origin), ["ROW-A5", "ROW-A5-1", "ROW-A5-2"])
        ready, produce = self._stages(origin["ROW-A5-1"]["id"])[0], self._stages(origin["ROW-A5-2"]["id"])[0]
        self.assertEqual((ready["requested"], ready["ready"]), ("6.0000", "6.0000"))
        self.assertEqual((produce["requested"], produce["to_produce"]), ("4.0000", "4.0000"))
        # A reposicao da origem (simples) e fabricada e volta direto para a Expedicao: junta com a parte pronta e a mae renasce.
        self._produce(origin["ROW-A5-2"]["id"])
        after = self._family("ROW-A5")
        self.assertEqual(sorted(number for number, row in after.items() if row["current_area"] != "CONTROLE_GERAL" or number == "ROW-A5"), ["ROW-A5"])
        self.assertEqual(after["ROW-A5"]["current_area"], "EXPEDICAO")
        self.assertEqual(self._stages(after["ROW-A5"]["id"])[0]["ready"], "10.0000")
        # O destino galvanizado recebeu 4 prontas sem passar pela galvanizacao: ficam numa parte propria na Expedicao.
        target = self._family("ROW-B5")
        self.assertEqual(sorted(target), ["ROW-B5", "ROW-B5-1"])
        received = self._stages(target["ROW-B5-1"]["id"])[0]
        self.assertEqual((received["requested"], received["ready"]), ("4.0000", "4.0000"))
        rest = self._stages(target["ROW-B5"]["id"])[0]
        self.assertEqual((rest["requested"], rest["to_produce"]), ("6.0000", "6.0000"))

    def test_the_destination_rest_is_produced_galvanized_and_the_mother_is_reborn_when_all_parts_can_join(self):
        items = [("1", "450.400", "2.0000"), ("2", "450.398", "1.0000"), ("3", "450.830", "1.0000")]
        source = self._ready_source("ROW-A6", items)
        destination = self._destination("ROW-B6", items)
        source_items, destination_items = self._item_ids(source), self._item_ids(destination)
        payload = self._payload(destination, [(destination_items["3"], source_items["3"], source["id"], "1.0000")], "row-op-0006")
        with patch(SWITCH, True):
            self._post("/api/v1/shipping/remanagements/confirm", payload)
        mother = self._family("ROW-B6")["ROW-B6"]
        self._produce(mother["id"])
        family = self._family("ROW-B6")
        pending = [row for number, row in family.items() if number != "ROW-B6" and row["current_area"] == "GALVANIZACAO"]
        self.assertTrue(pending, family)
        rows = [(item["item_id"], item["requested"]) for row in pending for item in self._stages(row["id"])]
        load = self._send(*rows)
        self._return(load["id"], *[row["id"] for row in pending])
        after = self._family("ROW-B6")
        self.assertEqual(after["ROW-B6"]["current_area"], "EXPEDICAO")
        self.assertEqual(sorted(number for number in after if number != "ROW-B6" and after[number]["current_area"] != "CONTROLE_GERAL"), [])
        self.assertEqual(self._codes(after["ROW-B6"]["id"]), ["450.398", "450.400", "450.830"])

    # ---- revisao, marca, idempotencia ----------------------------------------------------------------------------------
    def test_review_announces_the_parts_that_the_confirmation_creates(self):
        items = [("1", "450.400", "2.0000"), ("2", "450.398", "1.0000"), ("3", "450.830", "1.0000")]
        source = self._ready_source("ROW-A7", items)
        destination = self._destination("ROW-B7", items)
        source_items, destination_items = self._item_ids(source), self._item_ids(destination)
        payload = self._payload(destination, [(destination_items["3"], source_items["3"], source["id"], "1.0000")], "row-op-0007")
        with patch(SWITCH, True):
            review = self._post("/api/v1/shipping/remanagements/review", payload)
            self.assertTrue(review["valid"], review)
            self.assertEqual(review["engine"], "ROWS")
            predicted = {part["proposal_number"]: (part["role"], part["place"], part["item_numbers"], part["is_part"]) for part in review["parts"]}
            self.assertEqual(predicted, {
                "ROW-A7": ("ORIGEM", "REFERENCIA", [], False),
                "ROW-A7-1": ("ORIGEM", "EXPEDICAO", ["1", "2"], True),
                "ROW-A7-2": ("ORIGEM", "PRODUCAO", ["3"], True),
                "ROW-B7": ("DESTINO", "PRODUCAO", ["1", "2"], False),
                "ROW-B7-1": ("DESTINO", "EXPEDICAO", ["3"], True),
            })
            # A revisao e so uma previa: nada foi gravado.
            self.assertEqual(sorted(self._family("ROW-A7")), ["ROW-A7"])
            self._post("/api/v1/shipping/remanagements/confirm", payload)
            again = self._post("/api/v1/shipping/remanagements/confirm", payload)
        self.assertEqual(again["status"], "CONFIRMED")
        self.assertEqual(sorted(self._family("ROW-A7")), ["ROW-A7", "ROW-A7-1", "ROW-A7-2"])
        self.assertEqual(sorted(self._family("ROW-B7")), ["ROW-B7", "ROW-B7-1"])

    def test_badges_follow_the_families_and_go_away_when_the_parts_join(self):
        items = [("1", "450.400", "2.0000"), ("2", "450.398", "1.0000")]
        source = self._ready_source("ROW-A8", items)
        destination = self._destination("ROW-B8", items)
        source_items, destination_items = self._item_ids(source), self._item_ids(destination)
        payload = self._payload(destination, [(destination_items["2"], source_items["2"], source["id"], "1.0000")], "row-op-0008")
        with patch(SWITCH, True):
            self._post("/api/v1/shipping/remanagements/confirm", payload)
        marks = {badge["proposal_number"]: badge for badge in self._get("/api/v1/shipping/remanagements/badges")["items"]}
        self.assertEqual(marks["ROW-A8-1"]["status"], "PARCIALMENTE_SUBSTITUIDA")
        self.assertEqual(marks["ROW-A8-2"]["status"], "SUBSTITUIDA")
        self.assertEqual(marks["ROW-B8"]["status"], "RECEBEU")
        self.assertEqual(marks["ROW-B8-1"]["status"], "RECEBEU")
        self.assertEqual([(e["direction"], e["counterpart_proposal_number"]) for e in marks["ROW-A8-2"]["entries"]], [("CEDEU", "ROW-B8")])
        self.assertNotIn("ROW-A8", marks)
        # A reposicao volta e a origem fica inteira de novo: a marca da origem some.
        replacement = self._family("ROW-A8")["ROW-A8-2"]
        self._produce(replacement["id"])
        lot = self._stages(replacement["id"])[0]
        load = self._send((lot["item_id"], "1.0000"))
        self._return(load["id"], replacement["id"])
        marks = {badge["proposal_number"] for badge in self._get("/api/v1/shipping/remanagements/badges")["items"]}
        self.assertFalse({"ROW-A8", "ROW-A8-1", "ROW-A8-2"} & marks, marks)
        self.assertIn("ROW-B8", marks)

    # ---- varias origens, origem que ja e parte, motor antigo ----------------------------------------------------------------
    def test_two_sources_for_one_destination_in_the_same_confirmation(self):
        first = self._ready_source("ROW-A9", [("1", "450.400", "4.0000")])
        second = self._ready_source("ROW-C9", [("1", "450.400", "5.0000")])
        destination = self._destination("ROW-B9", [("1", "450.400", "6.0000")])
        y_id = self._item_ids(destination)["1"]
        payload = self._payload(destination, [
            (y_id, self._item_ids(first)["1"], first["id"], "4.0000"),
            (y_id, self._item_ids(second)["1"], second["id"], "2.0000"),
        ], "row-op-0009")
        with patch(SWITCH, True):
            self._post("/api/v1/shipping/remanagements/confirm", payload)
        # A primeira cedeu tudo (nao se divide, volta para a producao); a segunda cedeu 2 de 5 (se divide).
        self.assertEqual(sorted(self._family("ROW-A9")), ["ROW-A9"])
        self.assertEqual(self._family("ROW-A9")["ROW-A9"]["current_area"], "PRODUCAO")
        second_family = self._family("ROW-C9")
        self.assertEqual(sorted(second_family), ["ROW-C9", "ROW-C9-1", "ROW-C9-2"])
        # O destino recebeu as 6 pecas prontas (4 + 2): vai inteiro para a Expedicao.
        self.assertEqual(sorted(self._family("ROW-B9")), ["ROW-B9"])
        received = self._stages(self._family("ROW-B9")["ROW-B9"]["id"])
        self.assertEqual(sum(Decimal(item["ready"]) for item in received), Decimal("6.0000"))

    def test_a_part_can_be_the_source_of_another_remanagement(self):
        items = [("1", "450.400", "2.0000"), ("2", "450.398", "1.0000"), ("3", "450.830", "1.0000")]
        source = self._ready_source("ROW-A10", items)
        first = self._destination("ROW-B10", items)
        second = self._destination("ROW-D10", [("1", "450.400", "2.0000")])
        source_items = self._item_ids(source)
        with patch(SWITCH, True):
            self._post("/api/v1/shipping/remanagements/confirm", self._payload(first, [(self._item_ids(first)["3"], source_items["3"], source["id"], "1.0000")], "row-op-0010a"))
            part = self._family("ROW-A10")["ROW-A10-1"]
            lot = next(item for item in self._stages(part["id"]) if item["product_code"] == "450.400")
            self._post("/api/v1/shipping/remanagements/confirm", self._payload(second, [(self._item_ids(second)["1"], lot["item_id"], part["id"], "2.0000")], "row-op-0010b"))
        family = self._family("ROW-A10")
        active = sorted(number for number, row in family.items() if row["current_area"] != "CONTROLE_GERAL")
        # As duas reposicoes (itens 3 e 1) estao no mesmo lugar (producao) e se juntaram numa parte so.
        self.assertEqual(active, ["ROW-A10-1", "ROW-A10-2"])
        self.assertEqual(self._codes(family["ROW-A10-1"]["id"]), ["450.398"])
        self.assertEqual(self._codes(family["ROW-A10-2"]["id"]), ["450.400", "450.830"])

    def test_a_row_with_history_of_the_old_engine_falls_back_to_the_old_engine(self):
        first = self._ready_source("ROW-A11", [("1", "450.400", "10.0000")])
        second = self._ready_source("ROW-C11", [("1", "450.400", "10.0000")])
        destination = self._destination("ROW-B11", [("1", "450.400", "10.0000")])
        y_id = self._item_ids(destination)["1"]
        # 1) motor antigo (chave desligada): a proposta destino fica com historico de transferencias.
        self._post("/api/v1/shipping/remanagements/confirm", self._payload(destination, [(y_id, self._item_ids(first)["1"], first["id"], "4.0000")], "row-op-0011a"))
        self.assertEqual(sorted(self._family("ROW-A11")), ["ROW-A11"])
        # 2) chave ligada, mas o destino tem historico antigo: cai no motor antigo e funciona (sem partes novas).
        with patch(SWITCH, True):
            payload = self._payload(destination, [(y_id, self._item_ids(second)["1"], second["id"], "3.0000")], "row-op-0011b")
            review = self._post("/api/v1/shipping/remanagements/review", payload)
            self.assertEqual(review["engine"], "TRANSFER")
            self._post("/api/v1/shipping/remanagements/confirm", payload)
        self.assertEqual(sorted(self._family("ROW-C11")), ["ROW-C11"])


if __name__ == "__main__":
    unittest.main()
