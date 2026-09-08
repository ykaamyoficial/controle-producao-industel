from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QTabWidget

from tools.legacy_sqlite_runtime.migration_runner import apply_migrations
from tools.legacy_sqlite_runtime.production_repository import Repository, initialize_database
from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.models.fiscal_table_model import FiscalProcessTableModel, fiscal_status_label
from app.ui.dashboard_page import DashboardPage
from app.ui.fiscal_emission_dialog import FiscalEmissionDialog
from app.ui.fiscal_page import FiscalPage, FiscalProposalDetailDialog
from app.ui.sidebar import Sidebar
from app.ui.styles import app_stylesheet


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

    def ensure_global_fiscal_entries(self):
        return self.repo.ensure_fiscal_entries_for_all_processes(
            {"login": "admin", "perfil": "admin", "areas_acesso": ""},
            "Entrada fiscal global de teste.",
        )

    def fiscal_items(self, fiscal_processo_id):
        return [dict(row) for row in self.repo.list_fiscal_items(fiscal_processo_id)]

    def fiscal_indicators(self):
        return self.repo.fiscal_indicators()

    def fiscal_indicator_rows(self, indicator):
        return [dict(row) for row in self.repo.fiscal_indicator_rows(indicator)]

    def fiscal_report_rows(self, report_type, filters=None):
        return [dict(row) for row in self.repo.fiscal_report_rows(report_type, filters)]

    def fiscal_movements(self, fiscal_processo_id):
        return [dict(row) for row in self.repo.list_fiscal_movements(fiscal_processo_id)]

    def fiscal_emissions(self, fiscal_processo_id):
        return [dict(row) for row in self.repo.list_fiscal_emissions(fiscal_processo_id)]

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

    def mark_fiscal_invoice_withdrawn(self, fiscal_processo_id, observacao=""):
        return self.repo.mark_fiscal_invoice_withdrawn(
            fiscal_processo_id,
            {"login": "admin", "perfil": "admin", "areas_acesso": ""},
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
        return fiscal_status_label(status)


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

    def test_fiscal_page_refreshes_alert_rows_without_writing(self):
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

        self.assertEqual(page.model.rows[0]["pendencia_critica"], 1)
        self.assertEqual(page.model.rows[0]["mais_7_dias_sem_emissao"], 1)
        self.assertEqual(before, after)

    def test_dashboard_keeps_fiscal_indicators_out_of_operational_panel(self):
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
        self.assertNotIn("falta_emitir", card_titles)
        self.assertNotIn("peso_pendente", card_titles)
        self.assertNotIn("mais_7_dias_sem_emissao", card_titles)
        self.assertIn("Producao", card_titles)
        self.assertEqual(before, after)

    def test_fiscal_reports_return_pending_partial_emitted_and_critical_rows(self):
        self.create_fiscal_process("CP02100", status_fiscal="FALTA_EMITIR_NOTA_FISCAL")
        self.create_fiscal_process("CP02101", status_fiscal="NOTA_FISCAL_PARCIAL")
        self.create_fiscal_process("CP02102", status_fiscal="NOTA_FISCAL_EMITIDA")
        self.create_fiscal_process("CP02103", status_fiscal="FALTA_EMITIR_NOTA_FISCAL", expedition_status="ENTREGUE")

        self.assertCountEqual([dict(row)["proposta"] for row in self.repo.fiscal_report_rows("PENDENTES")], ["CP02103", "CP02100"])
        self.assertEqual([dict(row)["proposta"] for row in self.repo.fiscal_report_rows("PARCIAIS")], ["CP02101"])
        self.assertEqual([dict(row)["proposta"] for row in self.repo.fiscal_report_rows("EMITIDAS")], ["CP02102"])
        self.assertEqual([dict(row)["proposta"] for row in self.repo.fiscal_report_rows("CRITICAS")], ["CP02103"])

    def test_fiscal_reports_items_and_emissions(self):
        fiscal_id = self.create_fiscal_process("CP02104", status_fiscal="NOTA_FISCAL_PARCIAL")
        self.create_fiscal_emission(fiscal_id, "NF-123", "fiscal", "2026-06-10")

        items = [dict(row) for row in self.repo.fiscal_report_rows("ITENS_PENDENTES")]
        emissions = [dict(row) for row in self.repo.fiscal_report_rows("EMISSOES")]

        self.assertTrue(any(row["proposta"] == "CP02104" for row in items))
        self.assertEqual(emissions[0]["numero_controle"], "NF-123")
        self.assertEqual(emissions[0]["usuario"], "fiscal")
        self.assertEqual(emissions[0]["data_emissao"], "2026-06-10")

    def test_fiscal_report_filters_by_period_client_and_status(self):
        self.create_fiscal_process("CP02105", status_fiscal="FALTA_EMITIR_NOTA_FISCAL", entry_date="2026-06-01")
        self.create_fiscal_process("CP02106", status_fiscal="NOTA_FISCAL_EMITIDA", entry_date="2026-07-01")

        rows = [
            dict(row)
            for row in self.repo.fiscal_report_rows(
                "POR_PERIODO",
                {"data_inicio": "2026-06-01", "data_fim": "2026-06-30", "cliente": "Cliente Fiscal"},
            )
        ]
        emitted = [
            dict(row)
            for row in self.repo.fiscal_report_rows("EMITIDAS", {"status_fiscal": "NOTA_FISCAL_EMITIDA"})
        ]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["periodo"], "2026-06-01")
        self.assertEqual([row["proposta"] for row in emitted], ["CP02106"])

    def test_fiscal_report_page_and_csv_are_readonly_and_without_financial_fields(self):
        self.create_fiscal_process("CP02107", status_fiscal="FALTA_EMITIR_NOTA_FISCAL")
        before = self.fiscal_table_counts()
        csv_path = Path(self.temp_dir.name) / "relatorio_fiscal.csv"

        page = FiscalPage(self.service)
        page.report_type.setCurrentIndex(0)
        page.refresh_report()
        with patch("app.ui.fiscal_page.QFileDialog.getSaveFileName", return_value=(str(csv_path), "CSV (*.csv)")):
            with patch("app.ui.fiscal_page.QMessageBox.information"):
                page.export_report_csv()
        after = self.fiscal_table_counts()
        content = csv_path.read_text(encoding="utf-8-sig").lower()
        forbidden = ("price", "valor", "value", "amount", "subtotal", "tax", "discount", "payment", "currency", "r$")

        self.assertEqual(before, after)
        self.assertTrue(csv_path.exists())
        self.assertFalse(any(term in content for term in forbidden))

    def test_fiscal_page_uses_context_actions_instead_of_fixed_items_panel(self):
        self.create_fiscal_process("CP02007")

        page = FiscalPage(self.service)
        page.refresh()

        self.assertGreater(page.model.rowCount(), 0)
        self.assertFalse(hasattr(page, "items_table"))
        self.assertEqual(page.model.columns[0][0], "fiscal_action")
        self.assertEqual(page.model.columns[-1][0], "acoes")

    def test_fiscal_dark_theme_styles_cover_tabs_tables_and_footer(self):
        dark_palette = OFFICIAL_COLOR_PALETTES["escuro"]
        css = app_stylesheet(dark_palette)

        self.assertIn("QTabWidget::pane", css)
        self.assertIn("QTabBar::tab", css)
        self.assertIn("QAbstractScrollArea::viewport", css)
        self.assertIn("QTableView::viewport", css)
        self.assertIn("QLabel#HintLabel", css)
        self.assertIn(dark_palette["bg"], css)
        self.assertIn(dark_palette["surface"], css)

        self.service.palette = dark_palette
        page = FiscalPage(self.service)
        page.setStyleSheet(css)
        tabs = page.findChild(QTabWidget, "ModernTabs")

        self.assertEqual(page.objectName(), "FiscalPage")
        self.assertIsNotNone(tabs)
        self.assertTrue(all(tabs.widget(index).objectName() == "FiscalTabPage" for index in range(tabs.count())))
        self.assertIn("QTabWidget::pane", page.styleSheet())
        self.assertIn("QLabel#HintLabel", page.styleSheet())

    def test_fiscal_details_dialog_groups_summary_items_emissions_history_and_alerts(self):
        fiscal_id = self.create_fiscal_process(
            "CP02007D",
            status_fiscal="NOTA_FISCAL_PARCIAL",
            expedition_status="ENTREGUE",
        )
        self.create_fiscal_emission(fiscal_id, "NF-987", "fiscal", "2026-06-16")
        row = [dict(row) for row in self.repo.list_fiscal_processes({"text": "CP02007D"})][0]

        dialog = FiscalProposalDetailDialog(self.service, row)
        tabs = dialog.findChild(QTabWidget)

        self.assertIsNotNone(tabs)
        self.assertGreaterEqual(dialog.width(), 980)
        self.assertGreaterEqual(dialog.height(), 640)
        self.assertEqual(
            [tabs.tabText(index) for index in range(tabs.count())],
            ["Resumo", "Itens", "Emissoes", "Historico Fiscal", "Alertas"],
        )
        self.assertTrue(dialog.items)
        self.assertTrue(dialog.emissions)
        self.assertIsInstance(dialog.movements, list)

    def test_fiscal_context_menu_uses_single_proposal_details_entry(self):
        self.create_fiscal_process("CP02007M")
        page = FiscalPage(self.service)
        page.refresh()
        row = page.model.rows[0]
        menu = page.build_actions_menu(row)

        self.assertEqual(
            [action.text() for action in menu.actions()],
            ["Detalhes da Proposta", "Registrar emissao fiscal"],
        )

    def test_fiscal_emission_dialog_selects_items_instead_of_manual_values(self):
        fiscal_id = self.create_fiscal_process("CP02007S")
        row = self.service.fiscal_rows({"text": "CP02007S"})[0]
        dialog = FiscalEmissionDialog(self.service, row)
        headers = [dialog.table.horizontalHeaderItem(index).text() for index in range(dialog.table.columnCount())]

        self.assertEqual(headers[0], "Emitir")
        self.assertNotIn("Qtd. agora", headers)
        self.assertNotIn("Peso agora", headers)

        first_item_id = int(self.service.fiscal_items(fiscal_id)[0]["id"])
        dialog.selection_items[first_item_id].setCheckState(Qt.Checked)

        self.assertEqual(
            dialog.prepared_emissions(),
            [{"fiscal_item_id": first_item_id, "quantidade_emitida": 10.0, "peso_emitido": 25.0}],
        )

    def test_fiscal_emission_dialog_allows_process_without_items(self):
        fiscal_id = self.create_fiscal_process("CP02007W")
        self.repo.conn.execute("DELETE FROM fiscal_itens WHERE fiscal_processo_id = ?", (fiscal_id,))
        self.repo.conn.commit()
        row = self.service.fiscal_rows({"text": "CP02007W"})[0]

        dialog = FiscalEmissionDialog(self.service, row)

        self.assertEqual(dialog.prepared_emissions(), [])
        self.assertIn("Sem itens cadastrados", dialog.table.item(0, 0).text())

    def test_fiscal_page_has_withdrawn_invoices_tab(self):
        self.create_fiscal_process("CP02007R", status_fiscal="NOTA_FISCAL_EMITIDA")
        fiscal_id = [dict(row) for row in self.repo.list_fiscal_processes({"text": "CP02007R"})][0]["fiscal_processo_id"]
        self.repo.mark_fiscal_invoice_withdrawn(
            fiscal_id,
            {"login": "admin", "perfil": "admin", "areas_acesso": ""},
            "Retirada teste",
        )

        page = FiscalPage(self.service)
        page.refresh()
        tabs = page.findChild(QTabWidget, "ModernTabs")

        self.assertEqual(tabs.tabText(1), "Notas fiscais retiradas")
        self.assertEqual([row["proposta"] for row in page.withdrawn_model.rows], ["CP02007R"])

    def test_fiscal_action_column_uses_specific_icons_and_tooltips(self):
        self.create_fiscal_process("CP02007I", status_fiscal="FALTA_EMITIR_NOTA_FISCAL")
        self.create_fiscal_process("CP02007P", status_fiscal="NOTA_FISCAL_PARCIAL")
        self.create_fiscal_process("CP02007E", status_fiscal="NOTA_FISCAL_EMITIDA")
        self.create_fiscal_process("CP02007C", status_fiscal="FALTA_EMITIR_NOTA_FISCAL", expedition_status="ENTREGUE")
        model = FiscalProcessTableModel([dict(row) for row in self.repo.list_fiscal_processes()])
        action_column = [key for key, _label in model.columns].index("fiscal_action")
        by_proposal = {row["proposta"]: row_index for row_index, row in enumerate(model.rows)}

        self.assertEqual(model.data(model.index(by_proposal["CP02007I"], action_column), Qt.UserRole + 2), "fiscal_pending")
        self.assertEqual(model.data(model.index(by_proposal["CP02007P"], action_column), Qt.UserRole + 2), "fiscal_partial")
        self.assertEqual(model.data(model.index(by_proposal["CP02007E"], action_column), Qt.UserRole + 2), "fiscal_done")
        self.assertEqual(model.data(model.index(by_proposal["CP02007C"], action_column), Qt.UserRole + 2), "fiscal_critical")
        self.assertEqual(
            model.data(model.index(by_proposal["CP02007C"], action_column), Qt.ToolTipRole),
            "Pendencia fiscal critica: retirado sem NF emitida",
        )

    def test_clicking_fiscal_action_column_opens_actions_menu(self):
        self.create_fiscal_process("CP02007A")
        page = FiscalPage(self.service)
        page.refresh()
        opened = []
        page.open_actions_menu = lambda row, _pos: opened.append(row["proposta"])

        action_index = page.proxy.index(0, 0)
        page.handle_tracking_click(action_index)

        self.assertEqual(opened, [page.model.rows[0]["proposta"]])

    def test_fiscal_action_menu_hides_emission_for_emitted_status(self):
        self.create_fiscal_process("CP02007F", status_fiscal="NOTA_FISCAL_EMITIDA")
        page = FiscalPage(self.service)
        page.refresh()
        row = page.model.rows[0]
        menu = page.build_actions_menu(row)

        self.assertEqual([action.text() for action in menu.actions()], ["Detalhes da Proposta"])

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

        forbidden = ("emitir", "emissao", "emissÃ£o", "nota", "faturar")
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
        situation = {
            "FALTA_EMITIR_NOTA_FISCAL": "AGUARDANDO_NF",
            "NOTA_FISCAL_PARCIAL": "NF_PARCIAL",
            "NOTA_FISCAL_EMITIDA": "NF_EMITIDA",
            "FISCAL_CANCELADO": "FISCAL_CANCELADO",
        }.get(status_fiscal, "AGUARDANDO_NF")
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
                processo_id, proposta, status_fiscal, situacao_fiscal, data_entrada_fiscal,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '2026-06-15 10:00:00',
                      '2026-06-15 10:00:00')
            """,
            (process_id, proposal, status_fiscal, situation, entry_date),
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

    def create_fiscal_emission(self, fiscal_id: int, number: str, user: str, emission_date: str):
        emission_id = self.conn.execute(
            """
            INSERT INTO fiscal_emissoes(
                fiscal_processo_id, numero_controle, tipo_emissao,
                data_emissao, usuario, observacao, created_at
            ) VALUES (?, ?, 'PARCIAL', ?, ?, 'Teste fiscal', ?)
            """,
            (fiscal_id, number, emission_date, user, emission_date),
        ).lastrowid
        item = self.conn.execute(
            "SELECT id FROM fiscal_itens WHERE fiscal_processo_id = ? ORDER BY id LIMIT 1",
            (fiscal_id,),
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO fiscal_emissao_itens(
                fiscal_emissao_id, item_id, quantidade_emitida, peso_emitido, created_at
            ) VALUES (?, ?, 1, 2, ?)
            """,
            (emission_id, item["id"], emission_date),
        )
        self.conn.commit()


if __name__ == "__main__":
    unittest.main()


