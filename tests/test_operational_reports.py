from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.migration_runner import apply_migrations
from app.services.operational_reports import OperationalReportsService
from app.services.production_repository import initialize_database


class OperationalReportsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_operational_reports_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        initialize_database(self.conn)
        self.service = OperationalReportsService(self.conn)
        self.seed_data()

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_reports_are_readonly_and_have_standard_shape(self):
        before_changes = self.conn.total_changes
        statements: list[str] = []
        self.conn.set_trace_callback(statements.append)

        reports = [
            self.service.gerar_relatorio_producao(),
            self.service.gerar_relatorio_galvanizacao(),
            self.service.gerar_relatorio_expedicao(),
            self.service.gerar_relatorio_almoxarifado(),
            self.service.gerar_relatorio_remanejamentos(),
            self.service.resumo_operacional_por_area(),
            self.service.detalhar_itens_relatorio(self.ids["prod_complete"]),
        ]

        self.conn.set_trace_callback(None)
        self.assertEqual(self.conn.total_changes, before_changes)
        forbidden = ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "REPLACE")
        traced = "\n".join(statements).upper()
        self.assertFalse(any(word in traced for word in forbidden), traced)
        for report in reports:
            self.assertIn("cards", report)
            self.assertIn("linhas", report)
            self.assertIn("avisos", report)
            self.assertIn(report["confiabilidade"], ("alta", "media", "baixa"))

    def test_production_report_uses_statuses_items_and_filters(self):
        report = self.service.gerar_relatorio_producao({"cliente": "MNS", "periodo_inicial": "2026-06-01", "periodo_final": "2026-06-30"})

        proposals = {row["proposta"] for row in report["linhas"]}
        cards = {card["titulo"]: card["valor"] for card in report["cards"]}
        self.assertIn("CP10000", proposals)
        self.assertIn("CP10001", proposals)
        self.assertEqual(cards["Producao completa"], 1)
        self.assertEqual(cards["Producao parcial"], 1)
        self.assertEqual(cards["Pend. remanejamento"], 1)
        self.assertGreater(cards["Peso produzido atual"], 0)

    def test_galvanization_report_uses_load_items_without_duplicating_weight(self):
        report = self.service.gerar_relatorio_galvanizacao({"lote": "L1"})
        cards = {card["titulo"]: card["valor"] for card in report["cards"]}

        self.assertEqual(cards["Cargas abertas"], 1)
        self.assertEqual(cards["Cargas finalizadas"], 1)
        self.assertEqual(cards["Kg enviados"], 150)
        self.assertEqual(cards["Kg retornados"], 100)
        self.assertEqual(cards["Kg pendentes"], 50)
        self.assertEqual(cards["Pendentes de retorno"], 1)

    def test_expedition_report_separates_complete_partial_pending_and_weight(self):
        report = self.service.gerar_relatorio_expedicao({"cliente": "MNS"})
        cards = {card["titulo"]: card["valor"] for card in report["cards"]}

        self.assertEqual(cards["Entregues completas"], 1)
        self.assertEqual(cards["Entregues parciais"], 1)
        self.assertEqual(cards["Pendentes entrega"], 1)
        self.assertGreater(cards["Itens pendentes"], 0)
        self.assertGreater(cards["Kg entregue atual"], 0)

    def test_stockroom_report_returns_existing_statuses(self):
        report = self.service.gerar_relatorio_almoxarifado({"status": "SEM_PARAFUSOS"})
        cards = {card["titulo"]: card["valor"] for card in report["cards"]}

        self.assertEqual(len(report["linhas"]), 1)
        self.assertEqual(report["linhas"][0]["proposta"], "CP10005")
        self.assertEqual(cards["Sem parafusos"], 1)

    def test_remanagement_report_returns_origin_destination_items_user_and_weight(self):
        report = self.service.gerar_relatorio_remanejamentos({"proposta": "CP10006"})
        cards = {card["titulo"]: card["valor"] for card in report["cards"]}

        self.assertEqual(len(report["linhas"]), 1)
        row = report["linhas"][0]
        self.assertEqual(row["proposta_origem"], "CP10006")
        self.assertEqual(row["proposta_destino"], "CP10007")
        self.assertEqual(row["numero_item"], "1")
        self.assertEqual(row["usuario"], "admin")
        self.assertEqual(row["peso_remanejado"], 24)
        self.assertEqual(cards["Remanejamentos"], 1)
        self.assertEqual(cards["Pendencias geradas"], 1)

    def test_filters_by_proposal_client_lot_and_period(self):
        production = self.service.gerar_relatorio_producao({"proposta": "CP10001", "lote": "L1"})
        galvanization = self.service.gerar_relatorio_galvanizacao({"periodo_inicial": "01/06/2026", "periodo_final": "30/06/2026"})
        expedition = self.service.gerar_relatorio_expedicao({"obra_site": "Obra A"})

        self.assertEqual({row["proposta"] for row in production["linhas"]}, {"CP10001"})
        self.assertGreaterEqual(len(galvanization["linhas"]), 2)
        self.assertTrue(all("Obra A" in row["obra_site"] for row in expedition["linhas"]))

    def test_detail_items_report_scopes_partial_process(self):
        report = self.service.detalhar_itens_relatorio(self.ids["partial_child"])

        self.assertEqual(report["area"], "ITENS")
        self.assertEqual(len(report["linhas"]), 1)
        self.assertEqual(report["linhas"][0]["proposta_atual"], "CP10008-P1")

    def seed_data(self):
        self.ids: dict[str, int] = {}
        self.ids["prod_complete"] = self.create_process(
            "CP10000",
            status_geral="EM_GALVANIZACAO",
            status_producao="FINALIZADO",
            status_galvanizacao="AGUARDANDO_ENVIO",
            data_final_producao="10/06/2026",
            cliente="MNS",
            obra_site="Obra A",
            lote="L1",
            peso=100,
        )
        self.create_item(self.ids["prod_complete"], "1", 5, 10, produzido=1)
        self.create_item(self.ids["prod_complete"], "2", 5, 10, produzido=1)

        self.ids["prod_partial"] = self.create_process(
            "CP10001",
            status_geral="EM_PRODUCAO",
            status_producao="FINALIZADO_PARCIAL",
            data_final_producao="11/06/2026",
            cliente="MNS",
            obra_site="Obra A",
            lote="L1",
            peso=120,
        )
        self.create_item(self.ids["prod_partial"], "1", 3, 10, produzido=1)
        self.create_item(self.ids["prod_partial"], "2", 9, 10, produzido=0)

        self.ids["prod_pending"] = self.create_process(
            "CP10002",
            status_geral="EM_PRODUCAO",
            status_producao="ITEM_PENDENTE_FABRICACAO",
            data_final_producao="12/06/2026",
            cliente="MNS",
            obra_site="Obra B",
            lote="L2",
            origem_remanejamento="CP10007",
        )

        self.ids["exp_delivered"] = self.create_process(
            "CP10003",
            status_geral="ENTREGUE",
            status_producao="FINALIZADO",
            status_expedicao="ENTREGUE",
            data_retirada="13/06/2026",
            cliente="MNS",
            obra_site="Obra A",
            lote="L3",
        )
        self.create_item(self.ids["exp_delivered"], "1", 2, 20, produzido=1, entregue=1)

        self.ids["exp_partial"] = self.create_process(
            "CP10004",
            status_geral="EM_EXPEDICAO",
            status_producao="FINALIZADO",
            status_expedicao="ENTREGUE_PARCIAL",
            data_retirada="14/06/2026",
            cliente="MNS",
            obra_site="Obra A",
            lote="L3",
        )
        self.create_item(self.ids["exp_partial"], "1", 1, 10, produzido=1, entregue=1)
        self.create_item(self.ids["exp_partial"], "2", 2, 10, produzido=1, entregue=0)

        self.ids["stock_no"] = self.create_process(
            "CP10005",
            status_almoxarifado="SEM_PARAFUSOS",
            necessita_almoxarifado="NAO",
            data_separacao="15/06/2026",
            cliente="Cliente Almox",
            obra_site="Obra Almox",
            lote="L4",
        )
        self.create_process(
            "CP10009",
            status_almoxarifado="EM_SEPARACAO",
            necessita_almoxarifado="SIM",
            data_separacao="15/06/2026",
            cliente="Cliente Almox",
            obra_site="Obra Almox",
            lote="L4",
        )

        self.create_load(self.ids["prod_complete"], "CP10000", "RETORNADA_GALVANIZACAO", 100, data_retorno="16/06/2026")
        self.create_load(self.ids["prod_partial"], "CP10001", "LIBERADA_PARA_ENVIO", 50)

        self.ids["source"] = self.create_process(
            "CP10006",
            status_geral="EM_EXPEDICAO",
            status_producao="FINALIZADO",
            status_expedicao="SEPARADO",
            cliente="Origem",
            obra_site="Obra Rem",
            lote="LR",
        )
        source_item = self.create_item(self.ids["source"], "1", 2, 12, produzido=1, entregue=0)
        self.ids["destination"] = self.create_process(
            "CP10007",
            status_geral="ENTREGUE",
            status_producao="FINALIZADO",
            status_expedicao="ENTREGUE",
            cliente="Destino",
            obra_site="Obra Rem",
            lote="LR",
        )
        self.conn.execute(
            """
            INSERT INTO remanejamentos_itens(
                processo_destino_id, processo_origem_id, item_id, data_hora, usuario, observacao
            ) VALUES (?, ?, ?, '16/06/2026 10:00:00', 'admin', 'Teste de remanejamento')
            """,
            (self.ids["destination"], self.ids["source"], source_item),
        )
        self.create_process(
            "CP10006-P1",
            status_geral="EM_PRODUCAO",
            status_producao="ITEM_PENDENTE_FABRICACAO",
            processo_pai_id=self.ids["source"],
            tipo_processo="PARCIAL",
            numero_parcial=1,
            observacao_remanejamento="Reposicao gerada",
        )

        parent = self.create_process("CP10008", status_producao="FINALIZADO_PARCIAL", tipo_processo="PRINCIPAL")
        self.ids["partial_child"] = self.create_process(
            "CP10008-P1",
            status_producao="FINALIZADO",
            processo_pai_id=parent,
            tipo_processo="PARCIAL",
            numero_parcial=1,
        )
        self.create_item(parent, "1", 1, 8, produzido=1, processo_atual_id=self.ids["partial_child"])
        self.create_item(parent, "2", 1, 8, produzido=0, processo_atual_id=parent)
        self.conn.commit()

    def create_process(self, proposal: str, **overrides) -> int:
        values = {
            "cliente": overrides.pop("cliente", "MNS"),
            "proposta": proposal,
            "pedido_compra": overrides.pop("pedido_compra", ""),
            "obra_site": overrides.pop("obra_site", "Obra A"),
            "peso": overrides.pop("peso", 0),
            "lote": overrides.pop("lote", ""),
            "data_entrada": overrides.pop("data_entrada", "01/06/2026"),
            "data_cadastro": overrides.pop("data_cadastro", "01/06/2026 08:00:00"),
            "prazo_entrega": overrides.pop("prazo_entrega", "30/06/2026"),
            "status_geral": overrides.pop("status_geral", "EM_PRODUCAO"),
            "status_producao": overrides.pop("status_producao", ""),
            "data_final_producao": overrides.pop("data_final_producao", ""),
            "status_galvanizacao": overrides.pop("status_galvanizacao", ""),
            "data_envio_galv": overrides.pop("data_envio_galv", "10/06/2026"),
            "data_prevista_retorno_galv": overrides.pop("data_prevista_retorno_galv", "20/06/2026"),
            "data_retorno_galv": overrides.pop("data_retorno_galv", ""),
            "status_expedicao": overrides.pop("status_expedicao", ""),
            "data_separacao": overrides.pop("data_separacao", ""),
            "data_retirada": overrides.pop("data_retirada", ""),
            "status_almoxarifado": overrides.pop("status_almoxarifado", ""),
            "necessita_almoxarifado": overrides.pop("necessita_almoxarifado", "NAO_DEFINIDO"),
            "situacao_fluxo": overrides.pop("situacao_fluxo", "NORMAL"),
            "tem_pendencia_producao": overrides.pop("tem_pendencia_producao", 0),
            "origem_remanejamento": overrides.pop("origem_remanejamento", ""),
            "observacao_remanejamento": overrides.pop("observacao_remanejamento", ""),
            "processo_pai_id": overrides.pop("processo_pai_id", None),
            "tipo_processo": overrides.pop("tipo_processo", "PRINCIPAL"),
            "numero_parcial": overrides.pop("numero_parcial", 0),
        }
        self.assertFalse(overrides)
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        return self.conn.execute(
            f"INSERT INTO processos({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        ).lastrowid

    def create_item(
        self,
        process_id: int,
        number: str,
        quantity: int,
        weight: float,
        produzido: int = 0,
        galvanizado: int = 0,
        entregue: int = 0,
        processo_atual_id: int | None = None,
    ) -> int:
        return self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item, descricao,
                quantidade, peso, produzido, galvanizado, entregue
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                process_id,
                processo_atual_id or process_id,
                number,
                f"Item {number}",
                quantity,
                weight,
                produzido,
                galvanizado,
                entregue,
            ),
        ).lastrowid

    def create_load(self, process_id: int, proposal: str, status: str, weight: float, data_retorno: str = "") -> int:
        load_id = self.conn.execute(
            """
            INSERT INTO cargas_galvanizacao(
                motorista, peso_maximo, peso_total, status, data_prevista_retorno,
                data_retorno, criado_em, criado_por, computador
            ) VALUES ('Motorista', 1000, ?, ?, '20/06/2026', ?, '10/06/2026 08:00:00', 'admin', 'TESTE')
            """,
            (weight, status, data_retorno),
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO cargas_galvanizacao_itens(
                carga_id, processo_id, proposta, cliente, peso_total_proposta, peso_enviado, parcial
            ) VALUES (?, ?, ?, 'MNS', ?, ?, 0)
            """,
            (load_id, process_id, proposal, weight, weight),
        )
        return load_id


if __name__ == "__main__":
    unittest.main()
