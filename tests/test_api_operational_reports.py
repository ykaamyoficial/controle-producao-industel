from __future__ import annotations

import unittest

from app.services.api_reports import ApiOperationalReportsService


class FakeOperationalStorage:
    def __init__(self, *, production=None, expedition=None, proposals=None, loads=None, load_items=None, audit=None):
        self._production = production or []
        self._expedition = expedition or []
        self._proposals = proposals or []
        self._loads = loads or []
        self._load_items = load_items or {}
        self._audit = audit or []

    def list_production_proposals(self, **_kwargs):
        return list(self._production)

    def list_expedition_proposals(self, **_kwargs):
        return list(self._expedition)

    def list_proposals(self, **_kwargs):
        return list(self._proposals)

    def galvanization_loads(self):
        return list(self._loads)

    def galvanization_load_items(self, load_id):
        return list(self._load_items.get(int(load_id), []))

    def audit_rows(self):
        return list(self._audit)


def _cards(report):
    return {card["titulo"]: card["valor"] for card in report["cards"]}


class ProductionReportTests(unittest.TestCase):
    def setUp(self):
        self.storage = FakeOperationalStorage(
            production=[
                {"status_producao": "NAO_INICIADO", "quantidade_itens": 2, "peso": 20, "peso_produzido": 0, "proposta": "CP1", "cliente": "X"},
                {"status_producao": "FINALIZADO", "quantidade_itens": 3, "peso": 30, "peso_produzido": 30, "proposta": "CP2", "cliente": "X"},
                {"status_producao": "FINALIZADO_PARCIAL", "quantidade_itens": 1, "peso": 10, "peso_produzido": 5, "proposta": "CP3", "cliente": "Y"},
                {"status_producao": "ITEM_PENDENTE_FABRICACAO", "quantidade_itens": 1, "peso": 5, "peso_produzido": 2, "proposta": "CP4", "cliente": "Y"},
            ]
        )
        self.service = ApiOperationalReportsService(self.storage)

    def test_cards_count_by_status_bucket(self):
        report = self.service.production({})
        cards = _cards(report)
        self.assertEqual(cards["Propostas em producao"], 3)
        self.assertEqual(cards["Producao completa"], 1)
        self.assertEqual(cards["Producao parcial"], 1)
        self.assertEqual(cards["Peso produzido atual"], 37)
        self.assertEqual(cards["Pend. remanejamento"], 1)

    def test_client_text_filter_narrows_rows_before_counting(self):
        report = self.service.production({"cliente": "Y"})
        cards = _cards(report)
        self.assertEqual(len(report["linhas"]), 2)
        self.assertEqual(cards["Propostas em producao"], 2)
        self.assertEqual(cards["Producao completa"], 0)

    def test_status_filter_matches_by_substring(self):
        report = self.service.production({"status": "FINALIZADO"})
        statuses = {row["status_producao"] for row in report["linhas"]}
        self.assertEqual(statuses, {"FINALIZADO", "FINALIZADO_PARCIAL"})


class GalvanizationReportTests(unittest.TestCase):
    def setUp(self):
        self.storage = FakeOperationalStorage(
            loads=[
                {"id": 10, "status": "LIBERADA_PARA_ENVIO", "motorista": "Joao"},
                {"id": 20, "status": "RETORNADA_GALVANIZACAO", "motorista": "Maria"},
            ],
            load_items={
                10: [{"proposta": "CP1", "cliente": "Cliente A", "peso_enviado": 100, "peso_retornado": 0, "peso_pendente": 100, "status_retorno": "PENDENTE"}],
                20: [{"proposta": "CP2", "cliente": "Cliente B", "peso_enviado": 50, "peso_retornado": 50, "peso_pendente": 0, "status_retorno": "RETORNADO"}],
            },
        )
        self.service = ApiOperationalReportsService(self.storage)

    def test_open_and_finished_load_counts_are_distinct_by_status(self):
        report = self.service.galvanization({})
        cards = _cards(report)
        self.assertEqual(cards["Cargas abertas"], 1)
        self.assertEqual(cards["Cargas finalizadas"], 1)

    def test_weight_cards_sum_across_load_items(self):
        report = self.service.galvanization({})
        cards = _cards(report)
        self.assertEqual(cards["Kg enviados"], 150)
        self.assertEqual(cards["Kg retornados"], 50)
        self.assertEqual(cards["Kg pendentes"], 100)
        self.assertEqual(cards["Pendentes de retorno"], 1)


class ExpeditionReportTests(unittest.TestCase):
    def setUp(self):
        self.storage = FakeOperationalStorage(
            expedition=[
                {"status_expedicao": "ENTREGUE", "status_geral": "ENTREGUE", "quantidade_entregue": 40, "saldo_pendente": 0, "proposta": "CP1"},
                {"status_expedicao": "ENTREGUE_PARCIAL", "status_geral": "EM_EXPEDICAO", "quantidade_entregue": 10, "saldo_pendente": 5, "proposta": "CP2"},
                {"status_expedicao": "EM_SEPARACAO", "status_geral": "EM_EXPEDICAO", "quantidade_entregue": 0, "saldo_pendente": 8, "proposta": "CP3"},
            ]
        )
        self.service = ApiOperationalReportsService(self.storage)

    def test_delivery_status_cards_and_pending_totals(self):
        report = self.service.expedition({})
        cards = _cards(report)
        self.assertEqual(cards["Entregues completas"], 1)
        self.assertEqual(cards["Entregues parciais"], 1)
        self.assertEqual(cards["Pendentes entrega"], 2)
        self.assertEqual(cards["Itens pendentes"], 13)
        self.assertEqual(cards["Kg entregue atual"], 50)


class StockroomReportTests(unittest.TestCase):
    def test_rows_without_stockroom_status_are_excluded_and_cards_count_each_bucket(self):
        storage = FakeOperationalStorage(
            proposals=[
                {"status_almoxarifado": "AGUARDANDO_CONFIRMACAO", "proposta": "CP1"},
                {"status_almoxarifado": "EM_SEPARACAO", "proposta": "CP2"},
                {"status_almoxarifado": "SEPARADO", "proposta": "CP3"},
                {"status_almoxarifado": "SEM_PARAFUSOS", "proposta": "CP4"},
                {"status_almoxarifado": "ALMOXARIFADO_ENTREGUE", "proposta": "CP5"},
                {"status_almoxarifado": "", "proposta": "CP6"},
                {"proposta": "CP7"},
            ]
        )
        report = ApiOperationalReportsService(storage).stockroom({})
        cards = _cards(report)
        self.assertEqual(len(report["linhas"]), 5)
        self.assertEqual(cards["Pendentes almox."], 2)
        self.assertEqual(cards["Em separacao"], 1)
        self.assertEqual(cards["Separadas"], 1)
        self.assertEqual(cards["Sem parafusos"], 1)
        self.assertEqual(cards["Almox. entregue"], 1)


class RemanagementReportTests(unittest.TestCase):
    def test_only_remanagement_actions_are_counted_with_distinct_origin_and_destination(self):
        storage = FakeOperationalStorage(
            audit=[
                {"acao": "REMANEJAMENTO_ITEM", "processo_origem_id": 1, "processo_destino_id": 2, "quantidade": 3, "peso_remanejado": 15},
                {"acao": "REMANEJAMENTO_ITEM", "processo_origem_id": 1, "processo_destino_id": 3, "quantidade": 2, "peso_remanejado": 10},
                {"acao": "STATUS_ALTERADO", "processo_origem_id": 5, "processo_destino_id": 5, "quantidade": 1, "peso_remanejado": 0},
            ]
        )
        report = ApiOperationalReportsService(storage).remanagements({})
        cards = _cards(report)
        self.assertEqual(cards["Remanejamentos"], 2)
        self.assertEqual(cards["Origem distintas"], 1)
        self.assertEqual(cards["Destino distintos"], 2)
        self.assertEqual(cards["Itens remanejados"], 5)
        self.assertEqual(cards["Peso remanejado"], 25)


class GenerateDispatchTests(unittest.TestCase):
    def test_generate_routes_to_area_specific_report(self):
        storage = FakeOperationalStorage(loads=[{"id": 1, "status": "AGUARDANDO_LIBERACAO"}], load_items={1: []})
        service = ApiOperationalReportsService(storage)
        self.assertEqual(service.generate("GALVANIZACAO", {})["area"], "GALVANIZACAO")

    def test_generate_defaults_to_production_for_unknown_area(self):
        service = ApiOperationalReportsService(FakeOperationalStorage())
        self.assertEqual(service.generate("AREA_QUE_NAO_EXISTE", {})["area"], "PRODUCAO")


if __name__ == "__main__":
    unittest.main()
