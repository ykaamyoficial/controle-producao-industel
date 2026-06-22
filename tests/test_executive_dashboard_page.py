from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.services.migration_runner import apply_migrations
from app.services.production_repository import initialize_database
from app.ui.executive_dashboard_page import ExecutiveDashboardPage
from app.ui.main_window import MainWindow
from app.ui.sidebar import Sidebar


PALETTE = {
    "bg": "#ffffff",
    "surface": "#f8fafc",
    "surface_alt": "#eaf2ff",
    "text": "#0f172a",
    "muted": "#64748b",
    "border": "#cbd5e1",
    "accent": "#0078d4",
    "accent_hover": "#106ebe",
    "accent_text": "#ffffff",
    "secondary": "#7c3aed",
    "success": "#16a34a",
    "warning": "#f59e0b",
    "danger": "#dc2626",
}


class ExecutiveDashboardUiService:
    company = "Industel"
    palette = PALETTE

    def __init__(self, conn):
        self.conn = conn

    def visible_areas(self):
        return ["CONTROLE GERAL", "PRODUCAO", "GALVANIZACAO", "EXPEDICAO", "ALMOXARIFADO"]

    def user_profile(self):
        return "Administrador"

    def history_rows(self):
        return []

    def audit_rows(self):
        return []

    def saved_reports(self):
        return []

    def close(self):
        pass


class ExecutiveDashboardPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_executive_dashboard_page_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        initialize_database(self.conn)
        self.seed_data()
        self.service = ExecutiveDashboardUiService(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_page_opens_and_renders_cards_alerts_ranking_without_writing(self):
        page = ExecutiveDashboardPage(self.service)
        before = self.conn.total_changes

        page.refresh()

        self.assertEqual(page.current_data["titulo"], "Dashboard Executivo")
        self.assertGreater(len(page.operational_cards), 0)
        self.assertGreater(len(page.fiscal_cards), 0)
        self.assertGreaterEqual(page.alert_model.rowCount(), 1)
        self.assertIn("Confiabilidade:", page.reliability_badge.text())
        self.assertIn("Ultima atualizacao:", page.updated_at.text())
        self.assertLessEqual(max(card.height() for card in page.operational_cards), 62)
        self.assertLessEqual(max(card.height() for card in page.fiscal_cards), 62)
        self.assertEqual(page.content.layout().indexOf(page.alerts_panel), 2)
        self.assertEqual(self.conn.total_changes, before)

    def test_filters_are_sent_to_executive_service(self):
        page = ExecutiveDashboardPage(self.service)
        page.client.setText("MNS")
        page.proposal.setText("CP40001")
        page.site.setText("Obra A")
        page.lot.setText("L1")
        page.start.setText((date.today() - timedelta(days=1)).isoformat())
        page.end.setText((date.today() + timedelta(days=10)).isoformat())
        page.more_filters_btn.setChecked(True)
        page.area.setCurrentIndex(1)
        page.status.setText("FINALIZADO")
        page.reliability_filter.setCurrentIndex(1)

        page.refresh()

        filters = page.current_data["filtros"]
        self.assertEqual(filters["cliente"], "MNS")
        self.assertEqual(filters["proposta"], "CP40001")
        self.assertEqual(filters["obra_site"], "Obra A")
        self.assertEqual(filters["lote"], "L1")
        self.assertEqual(filters["area"], "PRODUCAO")
        self.assertEqual(filters["status"], "FINALIZADO")
        self.assertEqual(filters["confiabilidade"], "alta")
        self.assertFalse(page.more_filters.isHidden())

        page.more_filters_btn.setChecked(False)

        self.assertTrue(page.more_filters.isHidden())

    def test_refresh_button_reloads_without_database_change(self):
        page = ExecutiveDashboardPage(self.service)
        before = self.conn.total_changes

        page.refresh_btn.click()
        first_timestamp = page.updated_at.text()
        page.refresh_btn.click()

        self.assertTrue(first_timestamp.startswith("Ultima atualizacao:"))
        self.assertEqual(self.conn.total_changes, before)

    def test_clear_filters_resets_fields_and_refreshes(self):
        page = ExecutiveDashboardPage(self.service)
        page.client.setText("MNS")
        page.proposal.setText("CP40001")
        page.more_filters_btn.setChecked(True)
        page.include_partials.setChecked(False)

        page.clear_filters()

        self.assertEqual(page.client.text(), "")
        self.assertEqual(page.proposal.text(), "")
        self.assertTrue(page.include_partials.isChecked())
        self.assertIn("cards_operacionais", page.current_data)

    def test_interface_text_does_not_show_financial_terms(self):
        page = ExecutiveDashboardPage(self.service)
        page.refresh()
        visible_text = " ".join(label.text().lower() for label in page.findChildren(type(page.focus_label)))

        for forbidden in ("valor", "preco", "preço", "subtotal", "imposto", "pagamento", "frete", "currency", "r$"):
            self.assertNotIn(forbidden, visible_text)

    def test_empty_alerts_show_empty_state_instead_of_table(self):
        page = ExecutiveDashboardPage(self.service)

        page._render_alerts([])

        self.assertFalse(page.alert_empty.isHidden())
        self.assertTrue(page.alert_table.isHidden())
        self.assertIn("Nenhum alerta executivo", page.alert_empty.text())

    def test_dashboard_uses_operational_flow_and_performance_sections(self):
        page = ExecutiveDashboardPage(self.service)

        page.refresh()

        visible_text = self._visible_text(page)
        self.assertIn("Fluxo Operacional", visible_text)
        self.assertIn("Gargalo Atual", visible_text)
        self.assertIn("Indicadores de Performance", visible_text)
        self.assertIn("Producao concluida", visible_text)
        self.assertNotIn("Comparativo por area", visible_text)
        self.assertNotIn("Evolucao operacional", visible_text)

    def test_ranking_handles_zero_one_and_many_clients(self):
        page = ExecutiveDashboardPage(self.service)

        page._render_ranking([])
        self.assertIn("Sem clientes", self._visible_text(page.ranking_panel))

        page._render_ranking([{"cliente": "MNS", "peso_operacional": 120}])
        self.assertIn("1o MNS", self._visible_text(page.ranking_panel))

        page._render_ranking([
            {"cliente": "MNS", "peso_operacional": 120},
            {"cliente": "ABC", "peso_operacional": 80},
            {"cliente": "XYZ", "peso_operacional": 40},
        ])
        text = self._visible_text(page.ranking_panel)
        self.assertIn("1o MNS", text)
        self.assertIn("2o ABC", text)
        self.assertIn("3o XYZ", text)

    def test_sidebar_exposes_executive_dashboard_page(self):
        sidebar = Sidebar(self.service)
        received = []
        sidebar.page_selected.connect(received.append)

        self.assertIn("DASHBOARD EXECUTIVO", sidebar.buttons)
        sidebar.buttons["DASHBOARD EXECUTIVO"].click()
        self.assertEqual(received, ["DASHBOARD EXECUTIVO"])

    def test_sidebar_groups_menu_and_hides_legacy_reports(self):
        sidebar = Sidebar(self.service)
        expected_order = [
            "PAINEL GERAL",
            "DASHBOARD EXECUTIVO",
            "CONTROLE GERAL",
            "PRODUCAO",
            "GALVANIZACAO",
            "EXPEDICAO",
            "FISCAL",
            "PARCIAIS",
            "ALMOXARIFADO",
            "RELATORIOS OPERACIONAIS",
            "HISTORICO",
            "CONFIGURACOES",
        ]

        self.assertEqual(list(sidebar.buttons), expected_order)
        self.assertNotIn("RELATORIOS", sidebar.buttons)
        self.assertEqual([label.text() for label in sidebar.group_labels], ["PAINEIS", "OPERACAO", "ANALISE", "SISTEMA"])

        sidebar.set_collapsed(True)

        self.assertTrue(all(label.isHidden() for label in sidebar.group_labels))
        self.assertTrue(all(button.toolTip() for button in sidebar.buttons.values()))

    def test_main_window_registers_executive_dashboard_page(self):
        with patch("app.ui.main_window.BackendService", return_value=self.service):
            window = MainWindow()

        with patch("app.ui.main_window.DashboardPage", side_effect=lambda service: QWidget()):
            with patch("app.ui.main_window.ProcessPage", side_effect=lambda service, area, title: QWidget()):
                with patch("app.ui.main_window.FiscalPage", side_effect=lambda service: QWidget()):
                    with patch("app.ui.main_window.OperationalReportsPage", side_effect=lambda service: QWidget()):
                        with patch("app.ui.main_window.DataPage", side_effect=lambda *args, **kwargs: QWidget()):
                            with patch("app.ui.main_window.SettingsPage", side_effect=lambda *args, **kwargs: QWidget()):
                                window._build()

        self.assertIn("DASHBOARD EXECUTIVO", window.pages)
        self.assertIsInstance(window.pages["DASHBOARD EXECUTIVO"], ExecutiveDashboardPage)
        self.assertNotIn("RELATORIOS", window.sidebar.buttons)
        self.assertIn("RELATORIOS", window.pages)
        for key in window.sidebar.buttons:
            self.assertIn(key, window.pages)

    def _visible_text(self, widget) -> str:
        return " ".join(label.text() for label in widget.findChildren(QLabel))

    def seed_data(self):
        today = date.today()
        produced = self.create_process(
            "CP40001",
            cliente="MNS",
            obra_site="Obra A",
            lote="L1",
            status_geral="EM_GALVANIZACAO",
            status_producao="FINALIZADO",
            status_galvanizacao="ENVIADO_GALVANIZACAO",
            data_final_producao=today.strftime("%d/%m/%Y"),
            prazo_entrega=(today + timedelta(days=5)).strftime("%d/%m/%Y"),
        )
        self.create_item(produced, "1", 5, 10, produzido=1)
        self.create_load(produced, "CP40001", "LIBERADA_PARA_ENVIO", 50, "")

        delivered = self.create_process(
            "CP40002",
            cliente="MNS",
            status_geral="ENTREGUE",
            status_expedicao="ENTREGUE",
            data_retirada=today.strftime("%d/%m/%Y"),
            prazo_entrega=(today - timedelta(days=2)).strftime("%d/%m/%Y"),
        )
        self.create_item(delivered, "1", 2, 20, produzido=1, entregue=1)
        self.create_fiscal(delivered, "FALTA_EMITIR_NOTA_FISCAL", 40, 0)
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
            "data_cadastro": f"{date.today().strftime('%d/%m/%Y')} 08:00:00",
            "prazo_entrega": overrides.pop("prazo_entrega", (date.today() + timedelta(days=15)).strftime("%d/%m/%Y")),
            "status_geral": overrides.pop("status_geral", "EM_PRODUCAO"),
            "status_producao": overrides.pop("status_producao", ""),
            "data_final_producao": overrides.pop("data_final_producao", ""),
            "status_galvanizacao": overrides.pop("status_galvanizacao", ""),
            "data_envio_galv": overrides.pop("data_envio_galv", date.today().strftime("%d/%m/%Y")),
            "data_prevista_retorno_galv": overrides.pop("data_prevista_retorno_galv", (date.today() + timedelta(days=7)).strftime("%d/%m/%Y")),
            "data_retorno_galv": overrides.pop("data_retorno_galv", ""),
            "status_expedicao": overrides.pop("status_expedicao", ""),
            "data_separacao": "",
            "data_retirada": overrides.pop("data_retirada", ""),
            "status_almoxarifado": "",
            "necessita_almoxarifado": "NAO_DEFINIDO",
            "situacao_fluxo": "NORMAL",
            "tem_pendencia_producao": 0,
            "origem_remanejamento": "",
            "observacao_remanejamento": "",
            "processo_pai_id": None,
            "tipo_processo": "PRINCIPAL",
            "numero_parcial": 0,
        }
        self.assertFalse(overrides)
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        return self.conn.execute(f"INSERT INTO processos({columns}) VALUES ({placeholders})", tuple(values.values())).lastrowid

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
            (weight, status, (date.today() + timedelta(days=3)).strftime("%d/%m/%Y"), return_date, f"{date.today().strftime('%d/%m/%Y')} 08:00:00"),
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

    def create_fiscal(self, process_id: int, status: str, total_weight: float, billed_weight: float) -> None:
        process = self.conn.execute("SELECT proposta FROM processos WHERE id = ?", (process_id,)).fetchone()
        entry_date = date.today().strftime("%d/%m/%Y")
        fiscal_id = self.conn.execute(
            """
            INSERT INTO fiscal_processos(
                processo_id, proposta, status_fiscal, data_entrada_fiscal,
                data_ultima_emissao, emitido_por, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '', '', ?, ?)
            """,
            (process_id, process["proposta"], status, entry_date, entry_date, entry_date),
        ).lastrowid
        item = self.conn.execute("SELECT id, numero_item, descricao, quantidade FROM proposta_itens WHERE processo_atual_id = ? LIMIT 1", (process_id,)).fetchone()
        self.conn.execute(
            """
            INSERT INTO fiscal_itens(
                fiscal_processo_id, processo_id, item_id, numero_item, descricao,
                quantidade_total, quantidade_faturada, peso_total, peso_faturado,
                status_item_fiscal, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDENTE', ?, ?)
            """,
            (fiscal_id, process_id, item["id"], item["numero_item"], item["descricao"], item["quantidade"], 0, total_weight, billed_weight, entry_date, entry_date),
        )


if __name__ == "__main__":
    unittest.main()
