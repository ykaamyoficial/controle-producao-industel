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

    def test_search_clause_looks_at_invoices_only_when_asked(self):
        from sqlalchemy.dialects import postgresql

        def sql(clause):
            return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

        plain = sql(service._proposal_search_clause("1001"))
        self.assertNotIn("fiscal_invoices", plain)
        with_invoices = sql(service._proposal_search_clause("1001", include_invoices=True))
        self.assertIn("fiscal_invoices.invoice_number", with_invoices)
        self.assertIn("fiscal_invoices.active IS true", with_invoices)
        # A NF sem numero informado ("REGISTRO-...") nao entra na busca.
        self.assertRegex(with_invoices, r"NOT LIKE 'REGISTRO-%+'")
        self.assertIsNone(service._proposal_search_clause("  ", include_invoices=True))

    def test_summary_schemas_expose_invoice_numbers_with_an_empty_default(self):
        self.assertEqual(schemas.FiscalRecordSummary.model_fields["invoice_numbers"].default_factory(), [])
        self.assertEqual(schemas.ExpeditionProposalSummary.model_fields["invoice_numbers"].default_factory(), [])
        # O detalhe herda o campo do resumo.
        self.assertIn("invoice_numbers", schemas.FiscalRecordDetail.model_fields)
        self.assertIn("invoice_numbers", schemas.ExpeditionProposalDetail.model_fields)


if __name__ == "__main__":
    unittest.main()
