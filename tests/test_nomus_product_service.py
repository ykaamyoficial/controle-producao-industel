from __future__ import annotations

import unittest
from decimal import Decimal

from app.services.nomus_api_client import NomusApiClientError
from app.services.nomus_product_service import (
    NomusProductService,
    WARNING_PRODUCT_GROSS_WEIGHT_USED,
    WARNING_PRODUCT_LOOKUP_FAILED,
    WARNING_PRODUCT_RESPONSE_INVALID,
    WARNING_PRODUCT_WEIGHT_INVALID,
    WARNING_PRODUCT_WEIGHT_MISSING,
)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class NomusProductServiceTests(unittest.TestCase):
    def test_uses_net_unit_weight_first(self):
        service = NomusProductService(FakeClient({
            "id": 26913,
            "pesoLiquidoUnitario": "12,50",
            "pesoBrutoUnitario": "13,90",
            "valorUnitario": "9999",
        }))

        result = service.fetch_product_weight(26913)

        self.assertEqual(result.selected_unit_weight, Decimal("12.50"))
        self.assertEqual(result.net_unit_weight, Decimal("12.50"))
        self.assertEqual(result.gross_unit_weight, Decimal("13.90"))
        self.assertEqual(result.source, "nomus_product_net_weight")
        self.assertIsNone(result.warning)

    def test_uses_gross_when_net_is_missing(self):
        service = NomusProductService(FakeClient({"id": 26913, "pesoBrutoUnitario": "7.25"}))

        result = service.fetch_product_weight("26913")

        self.assertEqual(result.selected_unit_weight, Decimal("7.25"))
        self.assertEqual(result.source, "nomus_product_gross_weight")
        self.assertEqual(result.warning, WARNING_PRODUCT_GROSS_WEIGHT_USED)

    def test_missing_weight_is_not_blocking(self):
        service = NomusProductService(FakeClient({"id": 26913, "nome": "Produto"}))

        result = service.fetch_product_weight(26913)

        self.assertIsNone(result.selected_unit_weight)
        self.assertEqual(result.warning, WARNING_PRODUCT_WEIGHT_MISSING)

    def test_negative_weight_is_invalid(self):
        service = NomusProductService(FakeClient({"id": 26913, "pesoLiquidoUnitario": "-1"}))

        result = service.fetch_product_weight(26913)

        self.assertIsNone(result.selected_unit_weight)
        self.assertEqual(result.warning, WARNING_PRODUCT_WEIGHT_INVALID)

    def test_invalid_response_is_reported(self):
        service = NomusProductService(FakeClient([]))

        result = service.fetch_product_weight(26913)

        self.assertIsNone(result.selected_unit_weight)
        self.assertEqual(result.warning, WARNING_PRODUCT_RESPONSE_INVALID)

    def test_lookup_failure_is_not_blocking(self):
        exc = NomusApiClientError("timeout", "timeout", status_code=None)
        service = NomusProductService(FakeClient(exc))

        result = service.fetch_product_weight(26913)

        self.assertIsNone(result.selected_unit_weight)
        self.assertEqual(result.warning, WARNING_PRODUCT_LOOKUP_FAILED)

    def test_invalid_product_id_is_not_called(self):
        client = FakeClient({"id": 26913, "pesoLiquidoUnitario": "1"})
        service = NomusProductService(client)

        result = service.fetch_product_weight("abc")

        self.assertEqual(client.calls, [])
        self.assertIsNone(result.selected_unit_weight)
        self.assertEqual(result.warning, WARNING_PRODUCT_LOOKUP_FAILED)


if __name__ == "__main__":
    unittest.main()
