from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.migration_runner import apply_migrations
from app.services.production_repository import initialize_database
from app.ui.operational_reports_page import OperationalReportsPage
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


class OperationalUiService:
    company = "Industel"
    palette = PALETTE

    def __init__(self, conn):
        self.conn = conn

    def visible_areas(self):
        return ["CONTROLE GERAL", "PRODUCAO", "GALVANIZACAO", "EXPEDICAO", "ALMOXARIFADO"]

    def user_profile(self):
        return "Administrador"

    def close(self):
        pass


class OperationalReportsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_operational_reports_page_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        initialize_database(self.conn)
        self.seed_data()
        self.service = OperationalUiService(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_page_opens_and_generates_each_area_without_writing(self):
        page = OperationalReportsPage(self.service)
        before = self.conn.total_changes

        area_options = [(page.area.itemText(index), page.area.itemData(index)) for index in range(page.area.count())]
        for index, (_label, area) in enumerate(area_options):
            page.area.setCurrentIndex(index)
            page.refresh()
            self.assertEqual(page.current_report["area"], area)
            self.assertGreater(len(page.current_report["cards"]), 0)
            self.assertIn(page.current_report["confiabilidade"], ("alta", "media", "baixa"))

        self.assertEqual(self.conn.total_changes, before)

    def test_filters_are_sent_to_operational_reports(self):
        page = OperationalReportsPage(self.service)
        page.area.setCurrentIndex(0)
        page.client.setText("MNS")
        page.proposal.setText("CP20001")
        page.lot.setText("L1")
        page.start.setText("2026-06-01")
        page.end.setText("2026-06-30")
        page.refresh()

        self.assertEqual(page.current_report["filtros"]["cliente"], "MNS")
        self.assertEqual(page.current_report["filtros"]["proposta"], "CP20001")
        self.assertEqual(page.current_report["filtros"]["lote"], "L1")
        self.assertEqual({row["proposta"] for row in page.model.rows}, {"CP20001"})

    def test_cards_warnings_and_reliability_badge_are_rendered(self):
        page = OperationalReportsPage(self.service)
        page.refresh()

        self.assertGreater(len(page._card_widgets), 0)
        self.assertIn("Confiabilidade:", page.reliability_badge.text())
        self.assertNotIn("Gere um relatorio", page.warning_text.text())

    def test_csv_export_does_not_include_financial_terms_or_write_database(self):
        page = OperationalReportsPage(self.service)
        page.refresh()
        before = self.conn.total_changes
        csv_path = Path(self.temp_dir.name) / "relatorio.csv"

        page.write_csv(csv_path)

        content = csv_path.read_text(encoding="utf-8-sig").lower()
        self.assertIn("proposta", content)
        for forbidden in ("valor", "preco", "preço", "subtotal", "imposto", "pagamento", "frete"):
            self.assertNotIn(forbidden, content)
        self.assertEqual(self.conn.total_changes, before)

    def test_export_button_uses_csv_dialog_without_writing_database(self):
        page = OperationalReportsPage(self.service)
        page.refresh()
        csv_path = Path(self.temp_dir.name) / "relatorio_dialog.csv"
        before = self.conn.total_changes

        with patch("app.ui.operational_reports_page.QFileDialog.getSaveFileName", return_value=(str(csv_path), "CSV (*.csv)")):
            with patch("app.ui.operational_reports_page.QMessageBox.information"):
                page.export_csv()

        self.assertTrue(csv_path.exists())
        self.assertEqual(self.conn.total_changes, before)

    def test_sidebar_exposes_operational_reports_page(self):
        sidebar = Sidebar(self.service)
        received = []
        sidebar.page_selected.connect(received.append)

        self.assertIn("RELATORIOS OPERACIONAIS", sidebar.buttons)
        sidebar.buttons["RELATORIOS OPERACIONAIS"].click()
        self.assertEqual(received, ["RELATORIOS OPERACIONAIS"])

    def seed_data(self):
        prod = self.create_process(
            "CP20001",
            status_producao="FINALIZADO",
            data_final_producao="10/06/2026",
            cliente="MNS",
            lote="L1",
        )
        self.create_item(prod, "1", 2, 10, produzido=1)
        exp = self.create_process(
            "CP20002",
            status_geral="ENTREGUE",
            status_expedicao="ENTREGUE",
            data_retirada="11/06/2026",
            cliente="MNS",
            lote="L2",
        )
        self.create_item(exp, "1", 1, 15, produzido=1, entregue=1)
        stock = self.create_process(
            "CP20003",
            status_almoxarifado="EM_SEPARACAO",
            data_separacao="12/06/2026",
            cliente="Cliente Almox",
            lote="L3",
        )
        load = self.conn.execute(
            """
            INSERT INTO cargas_galvanizacao(
                motorista, peso_maximo, peso_total, status, data_prevista_retorno,
                data_retorno, criado_em, criado_por, computador
            ) VALUES ('Motorista', 1000, 20, 'LIBERADA_PARA_ENVIO', '20/06/2026', '', '10/06/2026 08:00:00', 'admin', 'TESTE')
            """
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO cargas_galvanizacao_itens(
                carga_id, processo_id, proposta, cliente, peso_total_proposta, peso_enviado, parcial
            ) VALUES (?, ?, 'CP20001', 'MNS', 20, 20, 0)
            """,
            (load, prod),
        )
        item = self.create_item(stock, "1", 1, 5, produzido=1)
        self.conn.execute(
            """
            INSERT INTO remanejamentos_itens(
                processo_destino_id, processo_origem_id, item_id, data_hora, usuario, observacao
            ) VALUES (?, ?, ?, '13/06/2026 10:00:00', 'admin', 'Teste')
            """,
            (exp, stock, item),
        )
        self.conn.commit()

    def create_process(self, proposal: str, **overrides) -> int:
        values = {
            "cliente": overrides.pop("cliente", "MNS"),
            "proposta": proposal,
            "pedido_compra": "",
            "obra_site": overrides.pop("obra_site", "Obra A"),
            "peso": overrides.pop("peso", 0),
            "lote": overrides.pop("lote", ""),
            "data_entrada": "01/06/2026",
            "data_cadastro": "01/06/2026 08:00:00",
            "prazo_entrega": "30/06/2026",
            "status_geral": overrides.pop("status_geral", "EM_PRODUCAO"),
            "status_producao": overrides.pop("status_producao", ""),
            "data_final_producao": overrides.pop("data_final_producao", ""),
            "status_galvanizacao": overrides.pop("status_galvanizacao", ""),
            "data_envio_galv": "10/06/2026",
            "data_prevista_retorno_galv": "20/06/2026",
            "data_retorno_galv": "",
            "status_expedicao": overrides.pop("status_expedicao", ""),
            "data_separacao": overrides.pop("data_separacao", ""),
            "data_retirada": overrides.pop("data_retirada", ""),
            "status_almoxarifado": overrides.pop("status_almoxarifado", ""),
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
    ) -> int:
        return self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item, descricao,
                quantidade, peso, produzido, galvanizado, entregue
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (process_id, process_id, number, f"Item {number}", quantity, weight, produzido, galvanizado, entregue),
        ).lastrowid
if __name__ == "__main__":
    unittest.main()
