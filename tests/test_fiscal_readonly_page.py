from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from app.services.migration_runner import apply_migrations
from app.services.production_repository import Repository, initialize_database
from app.ui.dashboard_page import DashboardPage
from app.ui.fiscal_page import FiscalPage
from app.ui.sidebar import Sidebar


PALETTE = {
    "bg": "#ffffff",
    "surface": "#f8fafc",
    "surface_alt": "#eef2ff",
    "text": "#0f172a",
    "muted": "#94a3b8",
    "border": "#cbd5e1",
    "accent": "#0078d4",
    "accent_hover": "#106ebe",
    "accent_text": "#ffffff",
    "secondary": "#7c3aed",
    "success": "#16a34a",
    "warning": "#f59e0b",
    "danger": "#dc2626",
}


class FiscalUiService:
    company = "Industel"
    palette = PALETTE

    def __init__(self, repo):
        self.repo = repo

    def fiscal_rows(self, filters=None):
        return [dict(row) for row in self.repo.list_fiscal_processes(filters)]

    def fiscal_items(self, fiscal_processo_id):
        return [dict(row) for row in self.repo.list_fiscal_items(fiscal_processo_id)]

    def fiscal_indicators(self):
        return self.repo.fiscal_indicators()

    def fiscal_indicator_rows(self, indicator):
        return [dict(row) for row in self.repo.fiscal_indicator_rows(indicator)]

    def can_register_fiscal_emission(self):
        return True

    def register_fiscal_emission(self, fiscal_processo_id, emissions, numero_controle="", observacao=""):
        return self.repo.register_fiscal_emission(
            fiscal_processo_id,
            emissions,
            {"login": "admin", "perfil": "admin", "areas_acesso": ""},
            numero_controle,
            observacao,
        )

    def visible_areas(self):
        return ["CONTROLE GERAL", "PRODUCAO", "GALVANIZACAO", "EXPEDICAO", "ALMOXARIFADO"]

    def user_profile(self):
        return "Administrador"

    def dashboard(self):
        return dict(self.repo.dashboard())

    def dashboard_charts(self):
        return self.repo.dashboard_charts()

    def dashboard_metric_rows(self, metric):
        return [dict(row) for row in self.repo.dashboard_metric_rows(metric)]

    def dashboard_chart_rows(self, chart_key, label):
        return [dict(row) for row in self.repo.dashboard_chart_rows(chart_key, label)]

    def current_location(self, process):
        return ("CONTROLE GERAL", "Controle geral", process.get("status_geral") or "")

    def area_status_label(self, _area, status):
        return status or "-"

    def fiscal_status_label(self, status):
        return status or "-"


class FiscalReadOnlyPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_fiscal_page_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        initialize_database(self.conn)
        self.repo = Repository(self.conn)
        self.service = FiscalUiService(self.repo)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_fiscal_list_returns_process_with_totals(self):
        fiscal_id = self.create_fiscal_process("CP02000", status_fiscal="FALTA_EMITIR_NOTA_FISCAL")

        rows = [dict(row) for row in self.repo.list_fiscal_processes()]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fiscal_processo_id"], fiscal_id)
        self.assertEqual(rows[0]["proposta"], "CP02000")
        self.assertEqual(rows[0]["quantidade_itens"], 2)
        self.assertEqual(rows[0]["itens_pendentes"], 2)
        self.assertEqual(rows[0]["itens_faturados"], 0)
        self.assertEqual(rows[0]["peso_total"], 40)
        self.assertEqual(rows[0]["peso_pendente"], 40)

    def test_fiscal_items_are_returned_for_selected_process(self):
        fiscal_id = self.create_fiscal_process("CP02001")

        items = [dict(row) for row in self.repo.list_fiscal_items(fiscal_id)]

        self.assertEqual([row["numero_item"] for row in items], ["1", "2"])
        self.assertEqual(items[0]["descricao"], "Fiscal item A")
        self.assertEqual(items[0]["quantidade_pendente"], 10)
        self.assertEqual(items[0]["peso_pendente"], 25)

    def test_indicators_count_statuses_and_critical_pending(self):
        self.create_fiscal_process("CP02002", status_fiscal="FALTA_EMITIR_NOTA_FISCAL", expedition_status="ENTREGUE")
        self.create_fiscal_process("CP02003", status_fiscal="NOTA_FISCAL_PARCIAL")
        self.create_fiscal_process("CP02004", status_fiscal="NOTA_FISCAL_EMITIDA", expedition_status="ENTREGUE")

        indicators = self.repo.fiscal_indicators()

        self.assertEqual(indicators["falta_emitir"], 1)
        self.assertEqual(indicators["nf_parcial"], 1)
        self.assertEqual(indicators["nf_emitida"], 1)
        self.assertEqual(indicators["pendencia_critica"], 1)

    def test_fiscal_indicators_include_weights_delivered_without_nf_and_old_entries(self):
        fiscal_id = self.create_fiscal_process(
            "CP02009",
            status_fiscal="NOTA_FISCAL_PARCIAL",
            expedition_status="ENTREGUE",
            entry_date="2020-01-01",
        )
        self.conn.execute(
            "UPDATE fiscal_itens SET quantidade_faturada = 5, peso_faturado = 12.5, status_item_fiscal = 'PARCIAL' WHERE fiscal_processo_id = ? AND numero_item = '1'",
            (fiscal_id,),
        )
        self.conn.commit()

        indicators = self.repo.fiscal_indicators()

        self.assertEqual(indicators["entregues_sem_nf"], 1)
        self.assertEqual(indicators["mais_7_dias_sem_emissao"], 1)
        self.assertAlmostEqual(indicators["peso_faturado"], 12.5)
        self.assertAlmostEqual(indicators["peso_pendente"], 27.5)

    def test_fiscal_indicator_rows_return_related_processes(self):
        self.create_fiscal_process("CP02010", status_fiscal="FALTA_EMITIR_NOTA_FISCAL")
        self.create_fiscal_process("CP02011", status_fiscal="NOTA_FISCAL_EMITIDA")

        rows = [dict(row) for row in self.repo.fiscal_indicator_rows("falta_emitir")]

        self.assertEqual([row["proposta"] for row in rows], ["CP02010"])

    def test_critical_pending_is_identified_by_process(self):
        process_id = self.create_fiscal_process("CP02005", expedition_status="ENTREGUE", return_process_id=True)

        self.assertTrue(self.repo.identificar_pendencia_fiscal_critica(process_id))

    def test_fiscal_page_refresh_does_not_write_to_database(self):
        self.create_fiscal_process("CP02006")
        before = self.fiscal_table_counts()

        page = FiscalPage(self.service)
        page.refresh()
        after = self.fiscal_table_counts()

        self.assertEqual(before, after)

    def test_fiscal_page_refreshes_phase_five_alerts_without_writing(self):
        self.create_fiscal_process(
            "CP02012",
            status_fiscal="FALTA_EMITIR_NOTA_FISCAL",
            expedition_status="ENTREGUE",
            entry_date="2020-01-01",
        )
        before = self.fiscal_table_counts()

        page = FiscalPage(self.service)
        page.refresh()
        after = self.fiscal_table_counts()

        self.assertEqual(page.card_critical.number.text(), "1")
        self.assertEqual(page.card_delivered_without_nf.number.text(), "1")
        self.assertEqual(page.card_older_than_7.number.text(), "1")
        self.assertEqual(before, after)

    def test_dashboard_loads_fiscal_cards_without_writing(self):
        self.create_fiscal_process(
            "CP02013",
            status_fiscal="FALTA_EMITIR_NOTA_FISCAL",
            expedition_status="ENTREGUE",
            entry_date="2020-01-01",
        )
        before = self.fiscal_table_counts()

        page = DashboardPage(self.service)
        page.refresh()
        after = self.fiscal_table_counts()

        card_titles = [card.metric_key for card in page.cards]
        self.assertIn("falta_emitir", card_titles)
        self.assertIn("peso_pendente", card_titles)
        self.assertIn("mais_7_dias_sem_emissao", card_titles)
        self.assertEqual(before, after)

    def test_fiscal_page_loads_items_for_selected_row(self):
        self.create_fiscal_process("CP02007")

        page = FiscalPage(self.service)
        page.refresh()

        self.assertGreater(page.model.rowCount(), 0)
        self.assertEqual(page.items_model.rowCount(), 2)

    def test_fiscal_page_exposes_manual_emission_button_for_allowed_user(self):
        self.create_fiscal_process("CP02008A")
        page = FiscalPage(self.service)
        page.refresh()

        buttons = {button.text().lower(): button for button in page.findChildren(QPushButton)}

        self.assertIn("registrar emissao fiscal", buttons)
        self.assertTrue(buttons["registrar emissao fiscal"].isEnabled())

    @unittest.skip("Fase 4 habilita registro fiscal manual controlado por permissao.")
    def test_fiscal_page_has_no_active_emission_buttons(self):
        self.create_fiscal_process("CP02008")
        page = FiscalPage(self.service)
        page.refresh()

        forbidden = ("emitir", "emissao", "emissão", "nota", "faturar")
        button_texts = [button.text().lower() for button in page.findChildren(QPushButton)]

        self.assertTrue(button_texts)
        self.assertFalse(any(any(word in text for word in forbidden) for text in button_texts))

    def test_sidebar_exposes_fiscal_page(self):
        sidebar = Sidebar(self.service)
        received = []
        sidebar.page_selected.connect(received.append)

        self.assertIn("FISCAL", sidebar.buttons)
        sidebar.buttons["FISCAL"].click()

        self.assertEqual(received, ["FISCAL"])

    def create_fiscal_process(
        self,
        proposal: str,
        status_fiscal: str = "FALTA_EMITIR_NOTA_FISCAL",
        expedition_status: str = "EM_SEPARACAO",
        entry_date: str = "2026-06-15",
        return_process_id: bool = False,
    ):
        process_id = self.conn.execute(
            """
            INSERT INTO processos(
                cliente, proposta, obra_site, data_cadastro, status_geral,
                status_producao, status_galvanizacao, status_expedicao
            ) VALUES ('Cliente Fiscal', ?, 'Obra Fiscal', '2026-06-15 10:00:00',
                      'EM_EXPEDICAO', 'FINALIZADO', 'RETORNOU_GALVANIZACAO', ?)
            """,
            (proposal, expedition_status),
        ).lastrowid
        item_a = self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item,
                descricao, quantidade, peso, produzido
            ) VALUES (?, ?, '1', 'Fiscal item A', 10, 2.5, 1)
            """,
            (process_id, process_id),
        ).lastrowid
        item_b = self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item,
                descricao, quantidade, peso, produzido
            ) VALUES (?, ?, '2', 'Fiscal item B', 5, 3, 1)
            """,
            (process_id, process_id),
        ).lastrowid
        fiscal_id = self.conn.execute(
            """
            INSERT INTO fiscal_processos(
                processo_id, proposta, status_fiscal, data_entrada_fiscal,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, '2026-06-15 10:00:00',
                      '2026-06-15 10:00:00')
            """,
            (process_id, proposal, status_fiscal, entry_date),
        ).lastrowid
        for item_id, numero, descricao, quantity, weight in (
            (item_a, "1", "Fiscal item A", 10, 25),
            (item_b, "2", "Fiscal item B", 5, 15),
        ):
            self.conn.execute(
                """
                INSERT INTO fiscal_itens(
                    fiscal_processo_id, processo_id, item_id, numero_item,
                    descricao, quantidade_total, quantidade_faturada, peso_total,
                    peso_faturado, status_item_fiscal, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, 'PENDENTE',
                          '2026-06-15 10:00:00', '2026-06-15 10:00:00')
                """,
                (fiscal_id, process_id, item_id, numero, descricao, quantity, weight),
            )
        self.conn.commit()
        return process_id if return_process_id else fiscal_id

    def fiscal_table_counts(self):
        tables = [
            "fiscal_processos",
            "fiscal_itens",
            "fiscal_movimentacoes",
            "fiscal_emissoes",
            "fiscal_emissao_itens",
        ]
        return {
            table: self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }


if __name__ == "__main__":
    unittest.main()
