from __future__ import annotations

import unittest

from api.app.modules.proposals import schemas
from api.app.modules.proposals.models import Proposal, ProposalItem


FORBIDDEN_TERMS = {"preco", "preço", "price", "valor", "value", "amount", "desconto", "discount", "imposto", "tax", "margem", "margin", "custo", "cost", "financeiro", "financial"}


class ProposalsNoFinancialFieldsTests(unittest.TestCase):
    def test_public_schemas_do_not_expose_financial_fields(self):
        schema_classes = [
            schemas.ProposalListItem,
            schemas.ProposalDetail,
            schemas.ProposalItemSummary,
            schemas.ProposalItemDetail,
            schemas.ProposalSyncPayload,
            schemas.ProposalItemSyncPayload,
        ]
        field_names = {field for schema_class in schema_classes for field in schema_class.model_fields}
        self.assertEqual(_financial_names(field_names), set())

    def test_postgresql_models_do_not_include_financial_columns(self):
        column_names = {column.name for column in Proposal.__table__.columns} | {column.name for column in ProposalItem.__table__.columns}
        self.assertEqual(_financial_names(column_names), set())


def _financial_names(names: set[str]) -> set[str]:
    found: set[str] = set()
    for name in names:
        parts = {part for part in name.lower().replace("-", "_").split("_") if part}
        if parts & FORBIDDEN_TERMS:
            found.add(name)
    return found


if __name__ == "__main__":
    unittest.main()
