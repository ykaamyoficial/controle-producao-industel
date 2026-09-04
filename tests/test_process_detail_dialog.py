from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES, legacy
from app.ui.process_detail_dialog import ProcessDetailDialog


class FakeDetailService:
    """Fake minimo o bastante para exercitar as 6 abas de ProcessDetailDialog
    sem falar com a API real - segue a mesma forma de dados que
    `BackendService`/`OfficialProposalApiStorage` ja devolvem hoje (mesmos
    nomes de campo vistos em `app/services/api_proposal_storage.py`)."""

    def __init__(self, process: dict | None = None):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.process = process or {
            "id": 10,
            "proposta": "CP 05389",
            "cliente": "MNS ENGENHARIA",
            "obra_site": "MSNVL006_A",
            "pedido_compra": "PD-100",
            "lote": "L1",
            "tipo_processo": "PRINCIPAL",
            "prazo_entrega": "03/09/2026",
            "situacao_fluxo": "EM_EXPEDICAO",
            "status_geral": "EM_EXPEDICAO",
            "status_producao": "FINALIZADO",
            "status_galvanizacao": "RETORNOU_GALVANIZACAO",
            "status_expedicao": "EM_SEPARACAO",
            "status_almoxarifado": "",
            "necessita_almoxarifado": "NAO",
            "peso": "120.0000",
            "peso_parcial": "0",
            "saldo_pendente": "0",
            "quantidade_itens": 3,
            "quantidade_entregue": "0",
            "atualizado_por": "usuario.teste",
            "atualizado_em": "01/08/2026 10:00:00",
        }
        self.history: list[dict] = []
        self.partials: list[dict] = []
        self.loads: list[dict] = []
        self.items: list[dict] = []
        self.fiscal_rows_data: list[dict] = []
        self.fiscal_emissions_data: dict[int, list[dict]] = {}

    def get_process_dict(self, process_id):
        return dict(self.process) if process_id == self.process["id"] else None

    def current_location(self, process):
        return ("EXPEDICAO", "Expedicao", process.get("status_expedicao") or "")

    def area_status_label(self, area, status):
        return legacy.area_status_label(area, status)

    def status_label(self, status):
        return legacy.status_label(status)

    def load_status_label(self, status):
        return legacy.load_status_label(status)

    def weight_progress_text(self, process_id):
        return "120/120 kg"

    def process_history_rows(self, process_id):
        return list(self.history)

    def process_partials(self, process_id):
        return list(self.partials)

    def process_loads(self, process_id):
        return list(self.loads)

    def proposal_items(self, process_id):
        return list(self.items)

    def fiscal_rows(self, filters):
        return list(self.fiscal_rows_data)

    def fiscal_emissions(self, fiscal_processo_id):
        return list(self.fiscal_emissions_data.get(fiscal_processo_id, []))

    def can_edit_process(self):
        return True


class ProcessDetailDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, service=None) -> ProcessDetailDialog:
        service = service or FakeDetailService()
        return ProcessDetailDialog(service, service.process["id"], None)

    def test_header_uses_shared_proposal_formatting_and_shows_stage_and_deadline(self):
        dialog = self._dialog()
        self.assertEqual(dialog.title.text(), "CP 05389 | MNS ENGENHARIA")
        self.assertEqual(dialog.subtitle.text(), "MSNVL006_A")
        self.assertIn("EXPEDICAO", dialog.status_badge.text().upper())
        self.assertIn("Prazo: 03/09/2026", dialog.deadline_label.text())

    def test_all_six_tabs_are_present_in_order(self):
        dialog = self._dialog()
        titles = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
        self.assertEqual(titles, ["Resumo", "Itens", "Fluxo", "Cargas", "Fiscal/Entrega", "Historico"])

    def test_items_tab_merges_grouped_processes_without_duplicating_shared_items(self):
        service = FakeDetailService()
        service.items = [
            {"id": 1, "numero_item": "1", "descricao": "Item A", "quantidade": "2", "peso": "5", "produzir_internamente": "sim", "precisa_galvanizacao": "sim", "produzido": True, "galvanizado": True, "entregue": False},
            {"id": 3, "numero_item": "3", "descricao": "Item C", "quantidade": "1", "peso": "", "produzir_internamente": "sim", "precisa_galvanizacao": "sim", "produzido": True, "galvanizado": False, "enviado_galvanizacao": True, "entregue": False},
            {"id": 2, "numero_item": "2", "descricao": "Item B", "quantidade": "1", "peso": "", "produzir_internamente": "sim", "precisa_galvanizacao": "nao", "produzido": False, "galvanizado": False, "entregue": False},
        ]
        dialog = self._dialog(service)
        self.assertEqual(dialog.itens_tab.table.rowCount(), 3)
        self.assertIn("Galvanizado - aguardando expedicao", dialog.itens_tab.table.item(0, 5).text())
        self.assertIn("Enviado para galvanizacao", dialog.itens_tab.table.item(1, 5).text())
        self.assertIn("Nao informado", dialog.itens_tab.table.item(2, 4).text())

    def test_fluxo_tab_hides_almoxarifado_when_not_needed_and_shows_when_needed(self):
        service = FakeDetailService()
        dialog = self._dialog(service)
        areas_shown = dialog.fluxo_tab.content_layout.count() - 1
        self.assertEqual(areas_shown, 4)  # sem Almoxarifado: necessita=NAO e sem status

        service2 = FakeDetailService()
        service2.process["necessita_almoxarifado"] = "SIM"
        service2.process["status_almoxarifado"] = "EM_SEPARACAO"
        dialog2 = self._dialog(service2)
        self.assertEqual(dialog2.fluxo_tab.content_layout.count() - 1, 5)

    def test_cargas_tab_shows_empty_state_and_opens_official_dialog_on_double_click(self):
        service = FakeDetailService()
        service.loads = [{"id": 55, "codigo": "C55", "status": "LIBERADA_PARA_ENVIO", "motorista": "Joao", "item_count": 4, "proposal_count": 1}]
        dialog = self._dialog(service)
        self.assertEqual(dialog.cargas_tab.table.rowCount(), 1)

        with patch("app.ui.galvanization_load_details_dialog.GalvanizationLoadDetailsDialog") as details:
            details.return_value.exec.return_value = 0
            dialog.cargas_tab.table.selectRow(0)
            dialog.cargas_tab._open_selected()
        details.assert_called_once_with(service, 55, dialog.cargas_tab)

    def test_cargas_tab_empty_state_message(self):
        dialog = self._dialog()
        self.assertEqual(dialog.cargas_tab.summary.text(), "Nenhuma carga vinculada.")

    def test_fiscal_entrega_tab_empty_messages_when_no_data(self):
        service = FakeDetailService()
        service.process["quantidade_entregue"] = ""
        service.process["saldo_pendente"] = ""
        service.process["status_expedicao"] = ""
        dialog = self._dialog(service)
        fiscal_layout = dialog.fiscal_entrega_tab.fiscal_panel.layout()
        entrega_layout = dialog.fiscal_entrega_tab.entrega_panel.layout()
        fiscal_text = fiscal_layout.itemAt(1).widget().text()
        entrega_text = entrega_layout.itemAt(1).widget().text()
        self.assertEqual(fiscal_text, "Nenhuma movimentacao fiscal registrada.")
        self.assertEqual(entrega_text, "Nenhuma entrega registrada.")

    def test_fiscal_entrega_tab_shows_delivery_fields_but_no_carrier_data(self):
        # Ponto em aberto do mapeamento (FASE A): confirma que a aba mostra
        # apenas os campos que realmente existem para entrega ao cliente
        # (quantidade/saldo/status) e nao inventa transportadora/motorista/
        # placa - esses so existem para o transporte de galvanizacao.
        service = FakeDetailService()
        service.process["quantidade_entregue"] = "10"
        service.process["saldo_pendente"] = "2"
        service.process["status_expedicao"] = "ENTREGUE_PARCIAL"
        dialog = self._dialog(service)
        entrega_layout = dialog.fiscal_entrega_tab.entrega_panel.layout()
        # O grid de campos (item 1, logo apos o titulo do painel) e o unico
        # lugar que representaria um DADO de entrega - a nota explicativa
        # (item seguinte) pode mencionar os termos ao dizer que eles nao
        # existem para entrega ao cliente, isso e esperado.
        fields_grid = entrega_layout.itemAt(1).layout()
        rendered_fields = " ".join(
            fields_grid.itemAtPosition(row, col).widget().text()
            for row in range(fields_grid.rowCount())
            for col in range(2)
            if fields_grid.itemAtPosition(row, col) is not None
        )
        self.assertNotIn("motorista", rendered_fields.lower())
        self.assertNotIn("placa", rendered_fields.lower())
        self.assertNotIn("transportadora", rendered_fields.lower())
        self.assertIn("10", rendered_fields)
        self.assertIn("2", rendered_fields)

    def test_proposal_id_is_preserved_across_edit_and_actions(self):
        service = FakeDetailService()
        dialog = self._dialog(service)
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = True
        with patch("app.ui.process_detail_dialog.open_proposal_action_center", return_value=fake_dialog) as opener:
            dialog.change_status()
        opener.assert_called_once_with(service, 10, dialog)
        self.assertTrue(dialog.changed)

    def test_items_tab_uses_already_fetched_process_names_without_extra_network_calls(self):
        # Regressao: ItensTab.load() chamava service.process_partials(process_id) uma
        # vez por process_id parcial so para montar o rotulo "Processo: X" - uma
        # chamada de rede completa (busca + get_proposal) redundante com os dados que
        # ProcessDetailDialog.load() ja buscou via get_process_dict para cada id.
        # Isso deixava a abertura do dialogo lenta em propostas com muitas parciais.
        service = FakeDetailService()
        service.process = {**service.process, "id": 10, "proposta": "CP 05389"}
        second_process = {**service.process, "id": 11, "proposta": "CP 05389-P2"}
        processes_by_id = {10: dict(service.process), 11: dict(second_process)}
        service.get_process_dict = lambda process_id: dict(processes_by_id.get(process_id) or {}) or None
        service.items = [
            {
                "id": 1,
                "numero_item": "1",
                "descricao": "Item A",
                "quantidade": "1",
                "peso": "1",
                "processo_atual_id": 11,
                "produzido": True,
                "galvanizado": True,
                "entregue": False,
            }
        ]
        call_count = {"n": 0}
        original_partials = service.process_partials

        def counting_partials(process_id):
            call_count["n"] += 1
            return original_partials(process_id)

        service.process_partials = counting_partials

        dialog = ProcessDetailDialog(service, 10, None, process_ids=[10, 11])

        # ProcessDetailDialog.load() ainda faz sua propria chamada unica a
        # process_partials(self.process_id) (usada pela aba Fluxo); o que a
        # regressao evita e ItensTab.load() somar mais uma chamada por
        # process_id parcial so para montar os rotulos "Processo: X".
        self.assertEqual(call_count["n"], 1)
        self.assertIn("Processo: CP 05389-P2", dialog.itens_tab.table.item(0, 5).text())

    def test_reload_does_not_duplicate_tabs_or_rows(self):
        service = FakeDetailService()
        service.items = [{"id": 1, "numero_item": "1", "descricao": "Item A", "quantidade": "1", "peso": "1", "produzido": True, "galvanizado": True, "entregue": True}]
        dialog = self._dialog(service)
        dialog.load()
        dialog.load()
        self.assertEqual(dialog.tabs.count(), 6)
        self.assertEqual(dialog.itens_tab.table.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
