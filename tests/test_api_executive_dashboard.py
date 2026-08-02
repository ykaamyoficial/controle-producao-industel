from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.services.api_reports import ApiExecutiveDashboardService


def _br_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


class FakeOfficialProposalStorage:
    def __init__(self, *, proposals=None, production=None, expedition=None, loads=None, fiscal=None):
        self._proposals = proposals or []
        self._production = production or []
        self._expedition = expedition or []
        self._loads = loads or []
        self._fiscal = fiscal or {}

    def list_proposals(self, **_kwargs):
        return list(self._proposals)

    def list_production_proposals(self, **_kwargs):
        return list(self._production)

    def list_expedition_proposals(self, **_kwargs):
        return list(self._expedition)

    def galvanization_loads(self):
        return list(self._loads)

    def fiscal_indicators(self):
        return dict(self._fiscal)


class FakeBackendService:
    def __init__(self, storage: FakeOfficialProposalStorage):
        self.official_proposal_storage = storage


def _fixture_service():
    today = date.today()
    overdue_date = _br_date(today - timedelta(days=3))
    soon_date = _br_date(today + timedelta(days=3))
    far_date = _br_date(today + timedelta(days=30))

    proposals = [
        {"proposta": "CP1", "cliente": "Cliente A", "status_geral": "EM_PRODUCAO", "prazo_entrega": overdue_date, "peso": 100},
        {"proposta": "CP2", "cliente": "Cliente A", "status_geral": "EM_PRODUCAO", "prazo_entrega": soon_date, "peso": 200},
        {"proposta": "CP3", "cliente": "Cliente B", "status_geral": "ENTREGUE", "prazo_entrega": overdue_date, "peso": 50},
        {"proposta": "CP4", "cliente": "Cliente B", "status_geral": "EM_PRODUCAO", "prazo_entrega": far_date, "peso": 300},
        {"proposta": "CP5", "cliente": "Cliente C", "status_geral": "EM_PRODUCAO", "prazo_entrega": "", "peso": 10},
    ]
    production = [
        {"proposta": "CP1", "status_producao": "INICIADO", "peso_produzido": 40},
        {"proposta": "CP3", "status_producao": "FINALIZADO", "peso_produzido": 60},
        {"proposta": "CP4", "status_producao": "ITEM_PENDENTE_FABRICACAO", "peso_produzido": 15},
    ]
    expedition = [
        {"proposta": "CP3", "status_expedicao": "ENTREGUE", "quantidade_entregue": 70},
        {"proposta": "CP2", "status_expedicao": "EM_SEPARACAO", "quantidade_entregue": 0},
    ]
    loads = [
        {"id": 1, "status": "LIBERADA_PARA_ENVIO", "peso_total": 500},
        {"id": 2, "status": "RETORNADA_GALVANIZACAO", "peso_total": 300},
    ]
    fiscal = {
        "falta_emitir": 3,
        "nf_parcial": 1,
        "nf_emitida": 5,
        "entregue_sem_nf": 2,
        "peso_pendente": 120.5,
        "peso_faturado": 900.25,
        "mais_7_dias_sem_emissao": 1,
    }
    storage = FakeOfficialProposalStorage(proposals=proposals, production=production, expedition=expedition, loads=loads, fiscal=fiscal)
    return ApiExecutiveDashboardService(FakeBackendService(storage))


class ApiExecutiveDashboardServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = _fixture_service()
        self.report = self.service.generate()

    def test_deadline_counts_ignore_finished_and_undefined_deadlines(self):
        cards = {card["titulo"]: card["numero"] for card in self.report["cards_operacionais"]}
        self.assertEqual(cards["Propostas atrasadas"], 1)
        self.assertEqual(cards["Vencendo em 7 dias"], 1)

    def test_weight_cards_use_correct_sources(self):
        cards = {card["titulo"]: card["numero"] for card in self.report["cards_operacionais"]}
        self.assertEqual(cards["Peso produzido"], 115.0)
        self.assertEqual(cards["Peso enviado galvanizacao"], 800.0)
        self.assertEqual(cards["Peso retornado galvanizacao"], 300.0)
        self.assertEqual(cards["Peso expedido"], 70.0)

    def test_remanagement_card_counts_pending_fabrication_items(self):
        cards = {card["titulo"]: card["numero"] for card in self.report["cards_operacionais"]}
        self.assertEqual(cards["Remanejamentos"], 1)

    def test_critical_pending_combines_overdue_and_delivered_without_invoice(self):
        cards = {card["titulo"]: card["numero"] for card in self.report["cards_operacionais"]}
        self.assertEqual(cards["Pendencias criticas"], 3)

    def test_fiscal_cards_map_directly_from_indicators(self):
        cards = {card["titulo"]: card["numero"] for card in self.report["cards_fiscais"]}
        self.assertEqual(cards["Falta emitir NF"], 3)
        self.assertEqual(cards["NF parcial"], 1)
        self.assertEqual(cards["NF emitida"], 5)
        self.assertEqual(cards["Entregue sem NF"], 2)
        self.assertEqual(cards["Peso fiscal pendente"], 120.5)
        self.assertEqual(cards["Peso fiscal faturado"], 900.25)
        self.assertEqual(cards["+7 dias sem emissao"], 1)

    def test_bottlenecks_quantities_and_percentages(self):
        bottlenecks = {row["area"]: row for row in self.report["graficos"]["gargalos_por_area"]}
        self.assertEqual(bottlenecks["Producao"]["quantidade"], 2)
        self.assertEqual(bottlenecks["Producao"]["percentual"], 40.0)
        self.assertEqual(bottlenecks["Galvanizacao"]["quantidade"], 1)
        self.assertEqual(bottlenecks["Galvanizacao"]["percentual"], 20.0)
        self.assertEqual(bottlenecks["Expedicao"]["quantidade"], 1)
        self.assertEqual(bottlenecks["Expedicao"]["percentual"], 20.0)
        self.assertEqual(bottlenecks["Pend. remanejamento"]["quantidade"], 1)
        self.assertEqual(bottlenecks["Pend. remanejamento"]["percentual"], 20.0)

    def test_bottleneck_percentages_do_not_divide_by_zero_when_empty(self):
        empty_service = ApiExecutiveDashboardService(FakeBackendService(FakeOfficialProposalStorage()))
        report = empty_service.generate()
        for row in report["graficos"]["gargalos_por_area"]:
            self.assertEqual(row["quantidade"], 0)
            self.assertEqual(row["percentual"], 0.0)

    def test_ranking_orders_clients_by_operational_weight_descending(self):
        ranking = self.report["rankings"]["clientes_por_volume"]
        self.assertEqual([row["cliente"] for row in ranking], ["Cliente B", "Cliente A", "Cliente C"])
        self.assertEqual(ranking[0]["peso_operacional"], 350.0)
        self.assertEqual(ranking[0]["propostas"], 2)

    def test_alerts_only_include_overdue_non_finished_proposals(self):
        alerts = self.report["alertas"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["proposta"], "CP1")
        self.assertEqual(alerts[0]["tipo"], "PROPOSTA_ATRASADA")

    def test_filters_narrow_ranking_and_alerts_to_matching_client(self):
        filtered = self.service.generate({"cliente": "Cliente A"})
        ranking = filtered["rankings"]["clientes_por_volume"]
        self.assertEqual([row["cliente"] for row in ranking], ["Cliente A"])
        self.assertEqual(len(filtered["alertas"]), 1)
        self.assertEqual(filtered["alertas"][0]["proposta"], "CP1")


if __name__ == "__main__":
    unittest.main()
