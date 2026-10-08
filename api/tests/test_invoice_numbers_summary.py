"""Numero da NF nas listas de Fiscal e Expedicao: so a regra de montagem (sem banco)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from api.app.modules.proposals import schemas, service


def _invoice(number, day, *, active=True, row_id=1):
    return SimpleNamespace(invoice_number=number, active=active, issued_at=datetime(2026, 10, day, tzinfo=UTC), id=row_id)


class InvoiceNumbersTests(unittest.TestCase):
    def test_numbers_follow_the_emission_order_and_do_not_repeat(self):
        invoices = [_invoice("1002", 5, row_id=2), _invoice("1001", 3, row_id=1), _invoice("1002", 6, row_id=3)]
        self.assertEqual(service._invoice_numbers(invoices), ["1001", "1002"])

    def test_cancelled_invoices_and_blank_numbers_are_left_out(self):
        invoices = [_invoice("1001", 3, row_id=1), _invoice("1002", 4, active=False, row_id=2), _invoice("  ", 5, row_id=3)]
        self.assertEqual(service._invoice_numbers(invoices), ["1001"])

    def test_placeholder_registry_numbers_are_not_shown_as_a_nota_fiscal(self):
        # Sem numero informado a API grava "REGISTRO-<id>-<data>": e um marcador.
        invoices = [_invoice("REGISTRO-7-20261003101500", 3, row_id=1), _invoice("1001", 4, row_id=2)]
        self.assertEqual(service._invoice_numbers(invoices), ["1001"])

    def test_no_invoices_means_an_empty_list(self):
        self.assertEqual(service._invoice_numbers([]), [])

    def test_summary_schemas_expose_invoice_numbers_with_an_empty_default(self):
        self.assertEqual(schemas.FiscalRecordSummary.model_fields["invoice_numbers"].default_factory(), [])
        self.assertEqual(schemas.ExpeditionProposalSummary.model_fields["invoice_numbers"].default_factory(), [])
        # O detalhe herda o campo do resumo.
        self.assertIn("invoice_numbers", schemas.FiscalRecordDetail.model_fields)
        self.assertIn("invoice_numbers", schemas.ExpeditionProposalDetail.model_fields)


if __name__ == "__main__":
    unittest.main()
