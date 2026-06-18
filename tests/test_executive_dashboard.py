from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app.services.executive_dashboard import ExecutiveDashboardService
from app.services.migration_runner import apply_migrations
from app.services.production_repository import initialize_database


class ExecutiveDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_executive_dashboard_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        initialize_database(self.conn)
        self.service = ExecutiveDashboardService(self.conn)
        self.seed_data()

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_dashboard_is_readonly_and_has_standard_shape(self):
        before = self.conn.total_changes
        statements: list[str] = []
        self.conn.set_trace_callback(statements.append)

        result = self.service.gerar_dashboard_executivo({"cliente": "MNS"})

        self.conn.set_trace_callback(None)
        self.assertEqual(self.conn.total_changes, before)
        traced = "\n".join(statements).upper()
        for forbidden in ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "REPLACE"):
            self.assertNotIn(forbidden, traced)
        self.assertEqual(result["titulo"], "Dashboard Executivo")
        self.assertIn("cards_operacionais", result)
        self.assertIn("cards_fiscais", result)
        self.assertIn("graficos", result)
        self.assertIn("rankings", result)
        self.assertIn("alertas", result)
        self.assertIn("avisos", result)
        self.assertIn(result["confiabilidade"], ("alta", "media", "baixa"))

    def test_weight_indicators_use_items_and_loads(self):
        result = self.service.indicadores_pesos({"cliente": "MNS"})

        self.assertEqual(result["peso_produzido"], 230)
        self.assertEqual(result["peso_enviado_galv"], 150)
        self.assertEqual(result["peso_retornado_galv"], 100)
        self.assertEqual(result["peso_expedido"], 50)
        self.assertEqual(result["confiabilidade"]["peso_enviado_galv"], "alta")

    def test_fiscal_indicators_are_separate_from_operational_cards(self):
        dashboard = self.service.gerar_dashboard_executivo({"cliente": "MNS"})

        operational_titles = {card["titulo"] for card in dashboard["cards_operacionais"]}
        fiscal_titles = {card["titulo"] for card in dashboard["cards_fiscais"]}
        self.assertIn("Falta emitir NF", fiscal_titles)
        self.assertIn("NF parcial", fiscal_titles)
        self.assertIn("NF emitida", fiscal_titles)
        self.assertNotIn("Falta emitir NF", operational_titles)
        fiscal = self.service.indicadores_fiscais_executivos({"cliente": "MNS"})
        self.assertEqual(fiscal["falta_emitir_nf"], 1)
        self.assertEqual(fiscal["nf_parcial"], 1)
        self.assertEqual(fiscal["nf_emitida"], 1)
        self.assertEqual(fiscal["entregue_sem_nf"], 1)
        self.assertEqual(fiscal["peso_fiscal_pendente"], 90)
        self.assertEqual(fiscal["peso_fiscal_faturado"], 90)
        self.assertEqual(fiscal["mais_7_dias_sem_emissao"], 1)

    def test_result_has_no_financial_fields_or_content(self):
        result = self.service.gerar_dashboard_executivo({})
        text = str(result).lower()

        for forbidden in ("preco", "preço", "subtotal", "imposto", "pagamento", "frete", "financeiro", "currency", "r$"):
            self.assertNotIn(forbidden, text)

    def test_filters_by_period_client_and_proposal(self):
        start = (date.today() - timedelta(days=2)).isoformat()
        end = (date.today() + timedelta(days=10)).isoformat()
        filtered = self.service.indicadores_pesos(
            {"cliente": "MNS", "proposta": "CP30001", "data_inicial": start, "data_final": end}
        )
        outside = self.service.indicadores_pesos(
            {"cliente": "Outro", "data_inicial": start, "data_final": end}
        )

        self.assertEqual(filtered["peso_produzido"], 100)
        self.assertEqual(filtered["peso_enviado_galv"], 100)
        self.assertEqual(outside["peso_produzido"], 0)

    def test_ranking_gargalos_and_alerts_work(self):
        ranking = self.service.ranking_clientes({})
        gargalos = self.service.gargalos_por_area({})
        alerts = self.service.alertas_executivos({})

        self.assertEqual(ranking[0]["cliente"], "MNS")
        self.assertGreater(ranking[0]["peso_operacional"], 0)
        areas = {row["area"]: row["quantidade"] for row in gargalos}
        self.assertGreaterEqual(areas["Producao"], 1)
        self.assertGreaterEqual(areas["Galvanizacao"], 1)
        self.assertTrue(any(alert["tipo"] == "PROPOSTA_ATRASADA" for alert in alerts))
        self.assertTrue(any(alert["tipo"] == "PROPOSTA_VENCENDO" for alert in alerts))

    def test_evolution_and_comparison_have_expected_groups(self):
        evolution = self.service.evolucao_operacional({})
        comparison = self.service.comparativo_areas({})

        self.assertEqual(evolution["agrupamento"], "semanal")
        self.assertIn("producao", evolution)
        self.assertIn("galvanizacao_envio", evolution)
        self.assertIn("expedicao", evolution)
        self.assertEqual({row["area"] for row in comparison}, {"Producao", "Galv. enviada", "Galv. retornada", "Expedicao"})

    def seed_data(self):
        today = date.today()
        self.ids: dict[str, int] = {}
        self.ids["prod_complete"] = self.create_process(
            "CP30001",
            cliente="MNS",
            status_geral="EM_GALVANIZACAO",
            status_producao="FINALIZADO",
            status_galvanizacao="ENVIADO_GALVANIZACAO",
            data_final_producao=today.strftime("%d/%m/%Y"),
            prazo_entrega=(today + timedelta(days=5)).strftime("%d/%m/%Y"),
            lote="L1",
        )
        self.create_item(self.ids["prod_complete"], "1", 5, 10, produzido=1)
        self.create_item(self.ids["prod_complete"], "2", 5, 10, produzido=1)

        self.ids["prod_partial"] = self.create_process(
            "CP30002",
            cliente="MNS",
            status_geral="EM_PRODUCAO",
            status_producao="FINALIZADO_PARCIAL",
            data_final_producao=today.strftime("%d/%m/%Y"),
            prazo_entrega=(today - timedelta(days=1)).strftime("%d/%m/%Y"),
            lote="L1",
        )
        self.create_item(self.ids["prod_partial"], "1", 4, 20, produzido=1)
        self.create_item(self.ids["prod_partial"], "2", 2, 20, produzido=0)

        self.ids["exp_delivered"] = self.create_process(
            "CP30003",
            cliente="MNS",
            status_geral="ENTREGUE",
            status_expedicao="ENTREGUE",
            data_retirada=today.strftime("%d/%m/%Y"),
            prazo_entrega=(today - timedelta(days=10)).strftime("%d/%m/%Y"),
            lote="L2",
        )
        self.create_item(self.ids["exp_delivered"], "1", 2, 20, produzido=1, entregue=1)

        self.ids["stock"] = self.create_process(
            "CP30004",
            cliente="MNS",
            status_almoxarifado="EM_SEPARACAO",
            prazo_entrega=(today + timedelta(days=20)).strftime("%d/%m/%Y"),
            lote="L3",
        )

        self.ids["source"] = self.create_process("CP30005", cliente="Origem", status_expedicao="SEPARADO", lote="LR")
        source_item = self.create_item(self.ids["source"], "1", 2, 15, produzido=1)
        self.ids["destination"] = self.create_process("CP30006", cliente="MNS", status_geral="ENTREGUE", lote="LR")
        self.conn.execute(
            """
            INSERT INTO remanejamentos_itens(
                processo_destino_id, processo_origem_id, item_id, data_hora, usuario, observacao
            ) VALUES (?, ?, ?, ?, 'admin', 'Remanejamento teste')
            """,
            (self.ids["destination"], self.ids["source"], source_item, f"{today.strftime('%d/%m/%Y')} 10:00:00"),
        )
        self.ids["delivered_no_nf"] = self.create_process(
            "CP30007",
            cliente="MNS",
            status_geral="ENTREGUE",
            status_expedicao="ENTREGUE",
            data_retirada=today.strftime("%d/%m/%Y"),
            lote="LF",
        )
        self.create_item(self.ids["delivered_no_nf"], "1", 1, 10, produzido=1, entregue=1)

        self.create_load(self.ids["prod_complete"], "CP30001", "RETORNADA_GALVANIZACAO", 100, today.strftime("%d/%m/%Y"))
        self.create_load(self.ids["prod_partial"], "CP30002", "LIBERADA_PARA_ENVIO", 50, "")

        self.create_fiscal(self.ids["delivered_no_nf"], "FALTA_EMITIR_NOTA_FISCAL", 20, 0, old=True)
        self.create_fiscal(self.ids["prod_partial"], "NOTA_FISCAL_PARCIAL", 120, 50)
        self.create_fiscal(self.ids["exp_delivered"], "NOTA_FISCAL_EMITIDA", 40, 40)
        self.conn.commit()

    def create_process(self, proposal: str, **overrides) -> int:
        values = {
            "cliente": overrides.pop("cliente", "MNS"),
            "proposta": proposal,
            "pedido_compra": "",
            "obra_site": overrides.pop("obra_site", "Obra A"),
            "peso": overrides.pop("peso", 0),
            "lote": overrides.pop("lote", ""),
            "data_entrada": overrides.pop("data_entrada", date.today().strftime("%d/%m/%Y")),
            "data_cadastro": overrides.pop("data_cadastro", f"{date.today().strftime('%d/%m/%Y')} 08:00:00"),
            "prazo_entrega": overrides.pop("prazo_entrega", (date.today() + timedelta(days=15)).strftime("%d/%m/%Y")),
            "status_geral": overrides.pop("status_geral", "EM_PRODUCAO"),
            "status_producao": overrides.pop("status_producao", ""),
            "data_final_producao": overrides.pop("data_final_producao", ""),
            "status_galvanizacao": overrides.pop("status_galvanizacao", ""),
            "data_envio_galv": overrides.pop("data_envio_galv", date.today().strftime("%d/%m/%Y")),
            "data_prevista_retorno_galv": overrides.pop("data_prevista_retorno_galv", (date.today() + timedelta(days=7)).strftime("%d/%m/%Y")),
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

    def create_item(self, process_id: int, number: str, quantity: int, weight: float, produzido: int = 0, entregue: int = 0) -> int:
        return self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item, descricao,
                quantidade, peso, produzido, galvanizado, entregue
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (process_id, process_id, number, f"Item {number}", quantity, weight, produzido, produzido, entregue),
        ).lastrowid

    def create_load(self, process_id: int, proposal: str, status: str, weight: float, return_date: str) -> int:
        load_id = self.conn.execute(
            """
            INSERT INTO cargas_galvanizacao(
                motorista, peso_maximo, peso_total, status, data_prevista_retorno,
                data_retorno, criado_em, criado_por, computador
            ) VALUES ('Motorista', 1000, ?, ?, ?, ?, ?, 'admin', 'TESTE')
            """,
            (
                weight,
                status,
                (date.today() + timedelta(days=3)).strftime("%d/%m/%Y"),
                return_date,
                f"{date.today().strftime('%d/%m/%Y')} 08:00:00",
            ),
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

    def create_fiscal(self, process_id: int, status: str, total_weight: float, billed_weight: float, old: bool = False) -> None:
        process = self.conn.execute("SELECT proposta FROM processos WHERE id = ?", (process_id,)).fetchone()
        entry_date = (date.today() - timedelta(days=10) if old else date.today()).strftime("%d/%m/%Y")
        fiscal_id = self.conn.execute(
            """
            INSERT INTO fiscal_processos(
                processo_id, proposta, status_fiscal, data_entrada_fiscal,
                data_ultima_emissao, emitido_por, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '', '', ?, ?)
            """,
            (process_id, process["proposta"], status, entry_date, entry_date, entry_date),
        ).lastrowid
        item = self.conn.execute(
            "SELECT id, numero_item, descricao, quantidade FROM proposta_itens WHERE processo_atual_id = ? LIMIT 1",
            (process_id,),
        ).fetchone()
        if not item:
            item_id = self.create_item(process_id, "F1", 1, total_weight, produzido=1)
            item = self.conn.execute("SELECT id, numero_item, descricao, quantidade FROM proposta_itens WHERE id = ?", (item_id,)).fetchone()
        item_status = "FATURADO" if billed_weight >= total_weight else ("PARCIAL" if billed_weight else "PENDENTE")
        self.conn.execute(
            """
            INSERT INTO fiscal_itens(
                fiscal_processo_id, processo_id, item_id, numero_item, descricao,
                quantidade_total, quantidade_faturada, peso_total, peso_faturado,
                status_item_fiscal, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fiscal_id,
                process_id,
                item["id"],
                item["numero_item"],
                item["descricao"],
                item["quantidade"],
                item["quantidade"] if billed_weight >= total_weight else 0,
                total_weight,
                billed_weight,
                item_status,
                entry_date,
                entry_date,
            ),
        )


if __name__ == "__main__":
    unittest.main()
