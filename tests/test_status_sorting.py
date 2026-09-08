from __future__ import annotations

import unittest

from app.services.status_sorting import sort_fiscal_rows, sort_process_rows, status_date_value, status_priority


class StatusSortingTest(unittest.TestCase):
    def test_control_general_prioritizes_waiting_release_and_newest_first(self):
        rows = [
            {"id": 1, "proposta": "CP001", "status_geral": "LIBERADO_PRODUCAO", "atualizado_em": "10/07/2026 09:00:00"},
            {"id": 2, "proposta": "CP002", "status_geral": "NAO_LIBERADO", "atualizado_em": "09/07/2026 09:00:00"},
            {"id": 3, "proposta": "CP003", "status_geral": "NAO_LIBERADO", "atualizado_em": "11/07/2026 09:00:00"},
        ]

        ordered = sort_process_rows("CONTROLE GERAL", rows)

        self.assertEqual([row["id"] for row in ordered], [3, 2, 1])

    def test_production_prioritizes_waiting_start(self):
        rows = [
            {"id": 1, "proposta": "CP001", "status_producao": "FINALIZADO", "data_final_producao": "11/07/2026"},
            {"id": 2, "proposta": "CP002", "status_producao": "INICIADO", "atualizado_em": "11/07/2026 10:00:00"},
            {"id": 3, "proposta": "CP003", "status_producao": "NAO_INICIADO", "atualizado_em": "10/07/2026 10:00:00"},
        ]

        ordered = sort_process_rows("PRODUCAO", rows)

        self.assertEqual([row["id"] for row in ordered], [3, 2, 1])

    def test_galvanization_prioritizes_load_mounting_and_newest_same_status(self):
        rows = [
            {"id": 1, "proposta": "CP001", "status_galvanizacao": "ENVIADO_GALVANIZACAO", "data_envio_galv": "11/07/2026"},
            {"id": 2, "proposta": "CP002", "status_galvanizacao": "AGUARDANDO_ENVIO", "atualizado_em": "10/07/2026 08:00:00"},
            {"id": 3, "proposta": "CP003", "status_galvanizacao": "AGUARDANDO_ENVIO", "atualizado_em": "12/07/2026 08:00:00"},
            {"id": 4, "proposta": "CP004", "status_galvanizacao": "RETORNOU_GALVANIZACAO", "data_retorno_galv": "13/07/2026"},
        ]

        ordered = sort_process_rows("GALVANIZACAO", rows)

        self.assertEqual([row["id"] for row in ordered], [3, 2, 1, 4])

    def test_expedition_prioritizes_waiting_separation(self):
        rows = [
            {"id": 1, "proposta": "CP001", "status_expedicao": "ENTREGUE", "data_retirada": "12/07/2026"},
            {"id": 2, "proposta": "CP002", "status_expedicao": "SEPARADO", "data_separacao": "12/07/2026"},
            {"id": 3, "proposta": "CP003", "status_expedicao": "EM_SEPARACAO", "data_separacao": "10/07/2026"},
        ]

        ordered = sort_process_rows("EXPEDICAO", rows)

        self.assertEqual([row["id"] for row in ordered], [3, 2, 1])

    def test_stockroom_prioritizes_waiting_confirmation(self):
        rows = [
            {"id": 1, "proposta": "CP001", "status_almoxarifado": "SEPARADO", "data_separacao": "12/07/2026"},
            {"id": 2, "proposta": "CP002", "status_almoxarifado": "AGUARDANDO_CONFIRMACAO", "atualizado_em": "10/07/2026"},
            {"id": 3, "proposta": "CP003", "status_almoxarifado": "SEM_PARAFUSOS", "data_retirada": "13/07/2026"},
        ]

        ordered = sort_process_rows("ALMOXARIFADO", rows)

        self.assertEqual([row["id"] for row in ordered], [2, 3, 1])

    def test_fiscal_prioritizes_pending_invoice_and_newest_entry(self):
        rows = [
            {"fiscal_processo_id": 1, "proposta": "CP001", "status_fiscal": "NOTA_FISCAL_PARCIAL", "data_ultima_emissao": "12/07/2026"},
            {"fiscal_processo_id": 2, "proposta": "CP002", "status_fiscal": "FALTA_EMITIR_NOTA_FISCAL", "data_entrada_fiscal": "10/07/2026"},
            {"fiscal_processo_id": 3, "proposta": "CP003", "status_fiscal": "FALTA_EMITIR_NOTA_FISCAL", "data_entrada_fiscal": "13/07/2026"},
        ]

        ordered = sort_fiscal_rows(rows)

        self.assertEqual([row["fiscal_processo_id"] for row in ordered], [3, 2, 1])

    def test_row_moved_to_priority_status_rises_to_top(self):
        rows = [
            {"id": 1, "proposta": "CP001", "status_producao": "INICIADO", "atualizado_em": "13/07/2026 10:00:00"},
            {"id": 2, "proposta": "CP002", "status_producao": "FINALIZADO", "data_final_producao": "14/07/2026"},
        ]
        self.assertEqual([row["id"] for row in sort_process_rows("PRODUCAO", rows)], [1, 2])

        rows[1]["status_producao"] = "NAO_INICIADO"
        rows[1]["atualizado_em"] = "14/07/2026 12:00:00"

        self.assertEqual([row["id"] for row in sort_process_rows("PRODUCAO", rows)], [2, 1])

    def test_priority_and_date_helpers_are_stable_for_unknown_values(self):
        row = {"id": 1, "status_producao": "STATUS_NOVO", "atualizado_em": ""}

        self.assertGreater(status_priority("PRODUCAO", "STATUS_NOVO"), status_priority("PRODUCAO", "NAO_INICIADO"))
        self.assertIsNone(status_date_value("PRODUCAO", row))


if __name__ == "__main__":
    unittest.main()
