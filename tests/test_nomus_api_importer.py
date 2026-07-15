from __future__ import annotations

import json
import unittest
from decimal import Decimal

from app.services.nomus_api_importer import (
    NomusApiAmbiguousOrderError,
    NomusApiImporter,
    NomusApiInvalidResponseError,
    NomusApiItemsNotFoundError,
    NomusApiOrderNotFoundError,
    WARNING_FIELD_IGNORED,
    parse_order_payload,
)


class FakeNomusClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        if not self.responses:
            raise AssertionError("No fake response configured")
        return self.responses.pop(0)


class NomusApiImporterTests(unittest.TestCase):
    def test_fetch_by_internal_id_uses_confirmed_get_endpoint(self):
        client = FakeNomusClient([_order_payload()])
        importer = NomusApiImporter(client)

        result = importer.fetch_proposal("123")

        self.assertEqual(client.calls, [("propostas/123", None)])
        self.assertEqual(result.metadata.source, "nomus_api")
        self.assertEqual(result.metadata.extraction_method, "nomus_api_rest")
        self.assertEqual(result.proposal.proposal_number, "CP 05252")
        self.assertEqual(result.proposal.client, "MNS ENGENHARIA")
        self.assertEqual(result.proposal.site, "MTCMX001 - MTCZN13 - WINITY - CLARO")
        self.assertEqual(result.items[0].product_code, "450.993")
        self.assertEqual(result.items[0].quantity, Decimal("1"))
        self.assertEqual(result.items[0].total_weight, Decimal("63"))

    def test_fetch_by_code_uses_bounded_paginated_list(self):
        client = FakeNomusClient([
            {"pedidos": [_order_payload(codigo="PD 04069"), _order_payload(codigo="CP 05252")]},
        ])
        importer = NomusApiImporter(client, max_search_pages=2)

        result = importer.fetch_proposal("CP05252")

        self.assertEqual(client.calls, [("propostas", {"pagina": 1})])
        self.assertEqual(result.proposal.proposal_number, "CP 05252")

    def test_fetch_by_code_accepts_real_nomus_root_list_envelope(self):
        payload = [
            _order_payload(codigo="PD 04069"),
            _order_payload(codigo="CP 04934", raw_id=4934),
        ]
        payload[1]["itensPedido"][0].update(
            {
                "idProduto": "450993",
                "informacoesAdicionaisProduto": "PERFIL DOBRADO OPERACIONAL",
                "status": "ATIVO",
            }
        )
        client = FakeNomusClient([payload, {"id": 450993}])
        importer = NomusApiImporter(client, max_search_pages=2)

        result = importer.fetch_proposal("CP04934")

        self.assertEqual(client.calls, [("propostas", {"pagina": 1}), ("produtos/450993", None)])
        self.assertEqual(result.proposal.proposal_number, "CP 04934")
        self.assertEqual(result.items[0].product_code, "450.993")

    def test_fetch_by_code_reads_nomus_proposta_envelope_and_items(self):
        payload = [
            _proposal_payload(proposta="CP 04937", raw_id=4934),
            _proposal_payload(proposta="CP 04934", raw_id=4931),
        ]
        client = FakeNomusClient([payload])
        importer = NomusApiImporter(client, max_search_pages=2)

        result = importer.fetch_proposal("CP04934")

        self.assertEqual(client.calls, [("propostas", {"pagina": 1})])
        self.assertEqual(result.proposal.proposal_number, "CP 04934")
        self.assertEqual(result.proposal.client, "CLIENTE TESTE")
        self.assertEqual(result.items[0].product_code, "132310001")
        self.assertEqual(result.items[0].description, "VIGA OPERACIONAL")
        self.assertEqual(result.items[0].unit, "UNIDADE")
        self.assertEqual(result.items[0].quantity, Decimal("220"))
        serialized = json.dumps(result.to_dict(), ensure_ascii=False).lower()
        self.assertNotIn("valortotal", serialized)
        self.assertNotIn("valorunitario", serialized)

    def test_fetch_by_code_reads_proposal_attributes_opening_date_and_item_deadline(self):
        payload = [_proposal_payload(proposta="CP 05285", raw_id=5285)]
        payload[0]["dataHoraAbertura"] = "07/07/2026 00:00:00"
        payload[0]["atributosProposta"] = [
            {"nomeAtributo": "OBRA/SITE:", "valorAtributo": "SITE IHS 64060059 - GF CLARO"}
        ]
        payload[0]["itensProposta"][0]["prazoEntregaDias"] = "30"
        client = FakeNomusClient([payload])
        importer = NomusApiImporter(client, max_search_pages=1)

        result = importer.fetch_proposal("CP05285")

        self.assertEqual(result.proposal.site, "SITE IHS 64060059 - GF CLARO")
        self.assertEqual(result.proposal.proposal_date.isoformat(), "2026-07-07")
        self.assertEqual(result.proposal.deadline_raw, "2026-08-06")

    def test_fetch_by_code_uses_product_register_unit_weight_to_calculate_item_total(self):
        payload = [_proposal_payload(proposta="CP 04934", raw_id=4931)]
        payload[0]["itensProposta"][0]["idProduto"] = 17517
        product_payload = {
            "id": 17517,
            "codigo": "132310001",
            "pesoLiquidoUnitario": "12,5",
            "valorUnitario": "999.99",
        }
        client = FakeNomusClient([payload, product_payload])
        importer = NomusApiImporter(client, max_search_pages=1)

        result = importer.fetch_proposal("CP04934")

        self.assertEqual(client.calls, [("propostas", {"pagina": 1}), ("produtos/17517", None)])
        self.assertEqual(result.items[0].unit_weight, Decimal("12.5"))
        self.assertEqual(result.items[0].total_weight, Decimal("2750.0"))
        self.assertEqual(result.items[0].source_method, "nomus_product_net_weight")
        self.assertFalse(result.items[0].weight_needs_confirmation)
        serialized = json.dumps(result.to_dict(), ensure_ascii=False).lower()
        self.assertNotIn("valorunitario", serialized)

    def test_fetch_by_code_uses_gross_weight_as_product_fallback(self):
        payload = [_proposal_payload(proposta="CP 04934", raw_id=4931)]
        payload[0]["itensProposta"][0]["idProduto"] = 17517
        product_payload = {"id": 17517, "pesoBrutoUnitario": "2"}
        client = FakeNomusClient([payload, product_payload])
        importer = NomusApiImporter(client, max_search_pages=1)

        result = importer.fetch_proposal("CP04934")

        self.assertEqual(result.items[0].unit_weight, Decimal("2"))
        self.assertEqual(result.items[0].total_weight, Decimal("440"))
        self.assertIn("NOMUS_PRODUCT_GROSS_WEIGHT_USED", {warning.code for warning in result.warnings})

    def test_fetch_by_code_preserves_order_item_weight_when_product_has_no_weight(self):
        payload = [_proposal_payload(proposta="CP 04934", raw_id=4931)]
        payload[0]["itensProposta"][0]["idProduto"] = 17517
        payload[0]["itensProposta"][0]["pesoTotal"] = "123"
        client = FakeNomusClient([payload, {"id": 17517}])
        importer = NomusApiImporter(client, max_search_pages=1)

        result = importer.fetch_proposal("CP04934")

        self.assertEqual(result.items[0].total_weight, Decimal("123"))
        self.assertEqual(result.items[0].source_method, "nomus_order_item_weight")

    def test_fetch_by_code_uses_product_cache_for_repeated_items(self):
        payload = [_proposal_payload(proposta="CP 04934", raw_id=4931)]
        payload[0]["itensProposta"].append(dict(payload[0]["itensProposta"][0]))
        payload[0]["itensProposta"][0]["idProduto"] = 17517
        payload[0]["itensProposta"][1]["idProduto"] = 17517
        payload[0]["itensProposta"][1]["item"] = "2"
        client = FakeNomusClient([payload, {"id": 17517, "pesoLiquidoUnitario": "1"}])
        importer = NomusApiImporter(client, max_search_pages=1)

        result = importer.fetch_proposal("CP04934")

        self.assertEqual(client.calls, [("propostas", {"pagina": 1}), ("produtos/17517", None)])
        self.assertEqual(result.items[0].total_weight, Decimal("220"))
        self.assertEqual(result.items[1].total_weight, Decimal("220"))

    def test_product_lookup_failure_keeps_item_pending_without_canceling_proposal(self):
        payload = [_proposal_payload(proposta="CP 04934", raw_id=4931)]
        payload[0]["itensProposta"][0]["idProduto"] = 17517
        client = FakeNomusClient([payload, []])
        importer = NomusApiImporter(client, max_search_pages=1)

        result = importer.fetch_proposal("CP04934")

        self.assertIsNone(result.items[0].total_weight)
        self.assertTrue(result.items[0].weight_needs_confirmation)
        self.assertIn("NOMUS_PRODUCT_RESPONSE_INVALID", {warning.code for warning in result.warnings})

    def test_fetch_by_code_does_not_match_different_prefix(self):
        client = FakeNomusClient([
            {"pedidos": [_order_payload(codigo="PD 05252")]},
            {"pedidos": []},
        ])
        importer = NomusApiImporter(client, max_search_pages=1)

        with self.assertRaises(NomusApiOrderNotFoundError):
            importer.fetch_proposal("CP05252")

    def test_fetch_by_code_blocks_ambiguous_matches(self):
        client = FakeNomusClient([
            {"pedidos": [_order_payload(codigo="CP 05252", raw_id=1), _order_payload(codigo="CP05252", raw_id=2)]},
        ])
        importer = NomusApiImporter(client, max_search_pages=1)

        with self.assertRaises(NomusApiAmbiguousOrderError):
            importer.fetch_proposal("CP05252")

    def test_raises_when_items_are_missing(self):
        client = FakeNomusClient([_order_payload(items=[])])
        importer = NomusApiImporter(client)

        with self.assertRaises(NomusApiItemsNotFoundError):
            importer.fetch_proposal("123")

    def test_financial_fields_are_ignored_and_never_returned(self):
        payload = _order_payload()
        payload.update(
            {
                "condicaoPagamentoTexto": "30 dias",
                "valorTotalFrete": "999,00",
                "parcelas": [{"valorParcela": "123,00"}],
                "nfes": [{"numero": "999"}],
            }
        )
        payload["itensPedido"][0].update(
            {
                "valorUnitario": "1,65",
                "percentualDesconto": "10",
                "valorAcrescimo": "5",
            }
        )
        importer = NomusApiImporter(FakeNomusClient([]))

        result = importer.convert_order_payload(payload, requested_identifier="CP05252")
        serialized = json.dumps(result.to_dict(), ensure_ascii=False).lower()

        self.assertIn(WARNING_FIELD_IGNORED, {warning.code for warning in result.warnings})
        for forbidden in (
            "valorunitario",
            "valortotalfrete",
            "valorparcela",
            "percentualdesconto",
            "valoracrescimo",
            "condicaopagamentotexto",
            "parcelas",
            "nfes",
            "r$",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_missing_weight_is_pending_confirmation(self):
        payload = _order_payload(items=[{"item": "1", "descricao": "Viga metalica", "quantidade": "2"}])
        importer = NomusApiImporter(FakeNomusClient([]))

        result = importer.convert_order_payload(payload, requested_identifier="CP05252")

        self.assertIsNone(result.items[0].total_weight)
        self.assertTrue(result.items[0].weight_needs_confirmation)
        self.assertIn("NOMUS_API_WEIGHT_MISSING", {warning.code for warning in result.warnings})

    def test_invalid_quantity_generates_error_without_guessing_value(self):
        payload = _order_payload(items=[{"item": "1", "descricao": "Viga metalica", "quantidade": "abc"}])
        importer = NomusApiImporter(FakeNomusClient([]))

        result = importer.convert_order_payload(payload, requested_identifier="CP05252")

        self.assertIsNone(result.items[0].quantity)
        self.assertIn("NOMUS_API_ITEM_QUANTITY_INVALID", {warning.code for warning in result.warnings})
        self.assertTrue(result.errors)

    def test_description_rule_preserves_full_description(self):
        payload = _order_payload(
            items=[
                {
                    "item": "1",
                    "descricaoCompleta": "COMPRA - CLIENTE PERFIL U DOBRADO #4.8X70X200X70X1000MM PARA FIX. DE SKID EM CAMPO GALV. A FOGO.",
                    "descricao": "resumida",
                    "quantidade": "1",
                }
            ]
        )
        importer = NomusApiImporter(FakeNomusClient([]))

        result = importer.convert_order_payload(payload, requested_identifier="CP05252")

        self.assertEqual(
            result.items[0].description,
            "PERFIL U DOBRADO #4.8X70X200X70X1000MM PARA FIX. DE SKID EM CAMPO GALV. A FOGO.",
        )

    def test_incompatible_list_response_is_blocked(self):
        importer = NomusApiImporter(FakeNomusClient([]))

        with self.assertRaises(NomusApiInvalidResponseError):
            importer.convert_order_payload([], requested_identifier="CP05252")  # type: ignore[arg-type]

    def test_parse_order_payload_uses_allowlisted_fields_only(self):
        order = parse_order_payload(_order_payload())

        self.assertEqual(order.codigo_pedido, "CP 05252")
        self.assertEqual(order.pedido_compra, "OC-123")
        self.assertEqual(len(order.items), 2)
        self.assertTrue(order.ignored_non_operational_fields)


def _order_payload(codigo="CP 05252", raw_id=123, items=None):
    return {
        "id": raw_id,
        "codigoPedido": codigo,
        "idExterno": "ETCP 05252",
        "dataEmissao": "08/06/2026",
        "dataEntregaPadrao": "18/06/2026",
        "cliente": {"nome": "MNS ENGENHARIA"},
        "obraSite": "MTCMX001 - MTCZN13 - WINITY - CLARO",
        "pedidoCompraCliente": "OC-123",
        "valorTotalSeguro": "10.00",
        "itensPedido": items
        if items is not None
        else [
            {
                "item": "1",
                "codigoProduto": "450.993",
                "descricaoCompleta": "Viga metalica W200x15",
                "unidade": "UNIDADE",
                "quantidade": "1",
                "pesoTotal": "63",
                "valorUnitario": "100.00",
            },
            {
                "item": "2",
                "codigoProduto": "450.994",
                "descricao": "Tubo 76 x 3,75 x 3000 mm",
                "unidade": "UNIDADE",
                "quantidade": "6",
            },
        ],
    }


def _proposal_payload(proposta="CP 04934", raw_id=4931):
    return {
        "id": raw_id,
        "proposta": proposta,
        "dataHoraAbertura": "2026-06-19T10:00:00",
        "nomeCliente": "CLIENTE TESTE",
        "valorTotal": "99999.99",
        "valorTotalNfe": "99999.99",
        "itensProposta": [
            {
                "item": "1",
                "codigoProduto": "132310001",
                "idProduto": None,
                "descricaoProduto": "VIGA OPERACIONAL",
                "nomeUnidadeMedida": "UNIDADE",
                "qtde": "220",
                "valorUnitario": "10.00",
                "valorTotalProdutos": "2200.00",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
