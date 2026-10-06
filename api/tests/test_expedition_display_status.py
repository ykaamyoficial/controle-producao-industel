from __future__ import annotations

import unittest
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from api.app.modules.proposals import service


def _proposal(shipping_status, current_status):
    return SimpleNamespace(shipping_status=shipping_status, current_status=current_status)


class ExpeditionDisplayStatusTests(unittest.TestCase):
    def test_shipping_status_wins(self):
        self.assertEqual(service._expedition_display_status(_proposal("SEPARADO", "EM_GALVANIZACAO")), "SEPARADO")

    def test_expedition_current_status_is_used_when_shipping_status_is_empty(self):
        self.assertEqual(service._expedition_display_status(_proposal("", "SEPARACAO_INICIADA")), "SEPARACAO_INICIADA")

    def test_mixed_proposal_in_other_area_is_waiting_separation(self):
        # Itens liberados para Expedicao, proposta ainda em outra area: a
        # Expedicao enxerga "EM_SEPARACAO" (topo da lista, acao de iniciar).
        for current_status in ("EM_GALVANIZACAO", "EM_PRODUCAO", None, ""):
            proposal = _proposal(None, current_status)
            self.assertEqual(service._expedition_display_status(proposal), "EM_SEPARACAO")
            self.assertEqual(service._expedition_sort_key(proposal), 0)

    def test_sql_sort_key_mirrors_python_fallback(self):
        sql = str(service._expedition_sort_key_sql().compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("nullif(proposals.shipping_status", sql)
        self.assertIn("proposals.current_status IN ('EM_SEPARACAO'", sql)
        self.assertIn("'EM_SEPARACAO')", sql)


if __name__ == "__main__":
    unittest.main()
