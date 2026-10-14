from __future__ import annotations

import os
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
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

    def fiscal_status_label(self, status):
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

    def setUp(self):
        self._dialogs: list[ProcessDetailDialog] = []

    def tearDown(self):
        # ProcessDetailDialog.load() dispara start_worker (QThread real
        # parentada ao dialog). Sem parar/esperar essas threads, o dialog local
        # e coletado pelo GC com a QThread ainda viva ("QThread: Destroyed
        # while thread is still running") -> corrompe o heap e derruba a suite
        # mais tarde, num teste posterior qualquer.
        for dialog in self._dialogs:
            for thread in dialog.findChildren(QThread):
                thread.quit()
                thread.wait(2000)
            dialog.deleteLater()
        self._dialogs.clear()
        self.app.processEvents()

    def _wait_loaded(self, dialog: ProcessDetailDialog) -> None:
        # Poll com processEvents em vez de QEventLoop.exec() aninhado: um event
        # loop aninhado aqui reentra o processamento de DeferredDelete/sinais
        # cross-thread de objetos vazados por testes anteriores no meio de uma
        # coleta de lixo, o que aborta o processo.
        done = {"loaded": False}
        dialog.loaded.connect(lambda *_: done.__setitem__("loaded", True))
        deadline = time.monotonic() + 5.0
        while not done["loaded"] and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)

    def _dialog(self, service=None) -> ProcessDetailDialog:
        service = service or FakeDetailService()
        dialog = ProcessDetailDialog(service, service.process["id"], None)
        self._dialogs.append(dialog)
        self._wait_loaded(dialog)
        return dialog

    def test_header_uses_shared_proposal_formatting_and_shows_stage_and_deadline(self):
        dialog = self._dialog()
        self.assertEqual(dialog.title.text(), "CP 05389 | MNS ENGENHARIA")
        self.assertEqual(dialog.subtitle.text(), "MSNVL006_A")
        self.assertIn("EXPEDIÇÃO", dialog.status_badge.text().upper())
        self.assertIn("Prazo: 03/09/2026", dialog.deadline_label.text())

    def test_all_six_tabs_are_present_in_order(self):
        dialog = self._dialog()
        titles = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
        self.assertEqual(titles, ["Resumo", "Itens", "Fluxo", "Cargas", "Fiscal/Entrega", "Histórico"])

    def test_items_tab_merges_grouped_processes_without_duplicating_shared_items(self):
        service = FakeDetailService()
        service.items = [
            {"id": 1, "numero_item": "1", "descricao": "Item A", "quantidade": "2", "peso": "5", "produzir_internamente": "sim", "precisa_galvanizacao": "sim", "produzido": True, "galvanizado": True, "entregue": False},
            {"id": 3, "numero_item": "3", "descricao": "Item C", "quantidade": "1", "peso": "", "produzir_internamente": "sim", "precisa_galvanizacao": "sim", "produzido": True, "galvanizado": False, "enviado_galvanizacao": True, "entregue": False},
            {"id": 2, "numero_item": "2", "descricao": "Item B", "quantidade": "1", "peso": "", "produzir_internamente": "sim", "precisa_galvanizacao": "nao", "produzido": False, "galvanizado": False, "entregue": False},
        ]
        dialog = self._dialog(service)
        self.assertEqual(dialog.itens_tab.table.rowCount(), 3)
        self.assertIn("Galvanizado - aguardando expedição", dialog.itens_tab.table.item(0, 5).text())
        self.assertIn("Enviado para galvanização", dialog.itens_tab.table.item(1, 5).text())
        self.assertIn("Não informado", dialog.itens_tab.table.item(2, 4).text())

    def test_fluxo_tab_hides_almoxarifado_when_not_needed_and_shows_when_needed(self):
        service = FakeDetailService()
        dialog = self._dialog(service)
        areas_shown = len(dialog.fluxo_tab.area_panels)
        self.assertEqual(areas_shown, 4)  # sem Almoxarifado: necessita=NAO e sem status

        service2 = FakeDetailService()
        service2.process["necessita_almoxarifado"] = "SIM"
        service2.process["status_almoxarifado"] = "EM_SEPARACAO"
        dialog2 = self._dialog(service2)
        self.assertEqual(len(dialog2.fluxo_tab.area_panels), 5)

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
        self.assertEqual(fiscal_text, "Nenhuma movimentação fiscal registrada.")
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
        self._dialogs.append(dialog)
        self._wait_loaded(dialog)

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
        self._wait_loaded(dialog)
        dialog.load()
        self._wait_loaded(dialog)
        self.assertEqual(dialog.tabs.count(), 6)
        self.assertEqual(dialog.itens_tab.table.rowCount(), 1)


def _family_payload() -> dict:
    """CP 05493 (mae sem itens): P1 pronta na Expedicao (2 itens) e P2 com 1 item em Producao."""
    zero = "0.0000"

    def quantities(**values):
        base = {"to_produce": zero, "awaiting_galvanization": zero, "in_galvanization": zero, "ready": zero, "delivered": zero, "undefined_flow": zero, "given_away": zero}
        base.update(values)
        return base

    def item(item_id, proposal_id, label, number, qty, **stage):
        return {
            "item_id": item_id, "proposal_id": proposal_id, "proposal_number": f"CP 05389-{label}", "partial_label": label,
            "item_number": number, "product_code": f"COD{number}", "description": f"Item {number}", "quantity": qty,
            "unit_weight": "2.0000", "quantities": quantities(**stage),
        }

    member = {"consolidated": {"kind": "SINGLE", "parts": []}, "quantities": quantities()}
    return {
        "has_partials": True, "partial_count": 2, "proposal_id": 10, "root_id": 10,
        "consolidated": {
            "kind": "MIXED", "label": "Parcial", "area": None, "status": None,
            "parts": [{"place": "EXPEDICAO", "label": "Expedição", "quantity": "5.0000"}, {"place": "PRODUCAO", "label": "Produção", "quantity": "2.0000"}],
        },
        "totals": {"total_units": "7.0000", "delivered_units": "0.0000", "progress_percent": 0, "known_weight": "14.0000", "pending_weight": "14.0000",
                   "weight_complete": True, "weight_known_items": 3, "weight_total_items": 3, "fiscal_status": "FALTA_EMITIR_NOTA_FISCAL"},
        "members": [
            {**member, "proposal_id": 10, "proposal_number": "CP 05389", "label": "Mãe", "role": "MAE", "is_reference": True, "current_area": "CONTROLE_GERAL", "current_status": "EM_PRODUCAO", "total_units": "0.0000"},
            {**member, "proposal_id": 11, "proposal_number": "CP 05389-1", "label": "P1", "role": "PARCIAL", "current_area": "EXPEDICAO", "current_status": "EM_SEPARACAO", "total_units": "5.0000"},
            {**member, "proposal_id": 12, "proposal_number": "CP 05389-2", "label": "P2", "role": "PARCIAL", "current_area": "PRODUCAO", "current_status": "ITEM_PENDENTE_FABRICACAO", "total_units": "2.0000"},
        ],
        "items": [
            item(1, 11, "P1", "1", "3.0000", ready="3.0000"),
            item(2, 11, "P1", "2", "2.0000", ready="2.0000"),
            item(3, 12, "P2", "3", "2.0000", to_produce="2.0000"),
        ],
        "remanagement_labels": ["Recebeu remanejamento"],
    }


def _lot_family_payload() -> dict:
    """CP 05511 (sem proposta-filha): 10 un. prontas na Expedicao (P1) e 1 un. ainda na Galvanizacao (P2)."""
    zero = "0.0000"

    def quantities(**values):
        base = {"to_produce": zero, "awaiting_galvanization": zero, "in_galvanization": zero, "ready": zero, "delivered": zero, "undefined_flow": zero, "given_away": zero}
        base.update(values)
        return base

    def item(item_id, number, qty, keys, **stage):
        return {
            "item_id": item_id, "proposal_id": 10, "proposal_number": "CP 05389", "partial_label": "Proposta",
            "item_number": number, "product_code": f"COD{number}", "description": f"Item {number}", "quantity": qty,
            "unit_weight": None, "quantities": quantities(**stage), "partial_keys": keys,
        }

    return {
        "has_partials": False, "partial_count": 0, "proposal_id": 10, "root_id": 10, "root_proposal_number": "CP 05389",
        "consolidated": {
            "kind": "MIXED", "label": "Parcial", "area": None, "status": None,
            "parts": [{"place": "EXPEDICAO", "label": "Expedição", "quantity": "10.0000"}, {"place": "GALVANIZACAO", "label": "Galvanização", "quantity": "1.0000"}],
        },
        "totals": {"total_units": "11.0000", "delivered_units": "0.0000", "progress_percent": 0, "known_weight": "0.0000", "pending_weight": "0.0000",
                   "weight_complete": False, "weight_known_items": 0, "weight_total_items": 3, "fiscal_status": None},
        "members": [],
        "partials": [
            {"key": "L:EXPEDICAO", "kind": "LOTE", "label": "P1", "proposal_id": 10, "proposal_number": None, "place": "EXPEDICAO",
             "current_area": "EXPEDICAO", "current_status": "EM_SEPARACAO", "item_count": 2, "total_units": "10.0000", "quantities": quantities(ready="10.0000")},
            {"key": "L:GALVANIZACAO", "kind": "LOTE", "label": "P2", "proposal_id": 10, "proposal_number": None, "place": "GALVANIZACAO",
             "current_area": "GALVANIZACAO", "current_status": "RETORNOU_PARCIAL", "item_count": 1, "total_units": "1.0000", "quantities": quantities(in_galvanization="1.0000")},
        ],
        "items": [
            item(1, "1", "6.0000", ["L:EXPEDICAO"], ready="6.0000"),
            item(2, "2", "4.0000", ["L:EXPEDICAO"], ready="4.0000"),
            item(3, "3", "1.0000", ["L:GALVANIZACAO"], in_galvanization="1.0000"),
        ],
        "remanagement_labels": [],
    }


class ProcessDetailFamilyTests(unittest.TestCase):
    """Proposta com parciais: cabecalho com as fichas e aba Itens por lugar."""

    setUpClass = ProcessDetailDialogTests.__dict__["setUpClass"]
    setUp = ProcessDetailDialogTests.setUp
    tearDown = ProcessDetailDialogTests.tearDown
    _wait_loaded = ProcessDetailDialogTests._wait_loaded
    _dialog = ProcessDetailDialogTests._dialog

    def _family_dialog(self, family=None):
        service = FakeDetailService()
        payload = _family_payload() if family is None else family
        service.proposal_family = lambda process_id: payload
        return self._dialog(service)

    def test_header_lists_every_partial_with_number_place_status_and_units(self):
        dialog = self._family_dialog()
        texts = [chip.text() for chip in dialog.family_strip.chips]
        self.assertEqual(len(texts), 3)
        self.assertIn("referência", texts[0])
        self.assertTrue(texts[1].startswith("CP 05389-1 · "))
        self.assertIn("5 un.", texts[1])
        self.assertIn("2 un.", texts[2])
        self.assertFalse(dialog.family_strip.isHidden())

    def test_main_badge_shows_where_the_pieces_are_not_the_open_rows_status(self):
        dialog = self._family_dialog()
        text = dialog.status_badge.text()
        self.assertTrue(text.startswith("PARCIAL"), text)
        self.assertIn("5 un. expedição", text)
        self.assertIn("2 un. produção", text)

    def test_items_tab_groups_by_place_with_one_row_per_item_and_place(self):
        dialog = self._family_dialog()
        table = dialog.itens_tab.table
        first_column = [table.item(row, 0).text() for row in range(table.rowCount())]
        self.assertTrue(first_column[0].startswith("Expedição · 5 un."))
        self.assertTrue(any(text.startswith("Produção · 2 un.") for text in first_column))
        self.assertEqual(sum(1 for text in first_column if text in {"1", "2", "3"}), 3)
        self.assertIn("P1 | Pronto - na Expedição", table.item(1, 5).text())

    def test_clicking_a_partial_filters_items_and_clicking_again_clears(self):
        dialog = self._family_dialog()
        table = dialog.itens_tab.table
        dialog.family_strip.chips[2].clicked.emit(12)
        visible_items = [table.item(row, 0).text() for row in range(table.rowCount()) if not table.isRowHidden(row) and table.item(row, 0).text() in {"1", "2", "3"}]
        self.assertEqual(visible_items, ["3"])
        self.assertFalse(dialog.itens_tab.filter_note.isHidden())
        dialog.family_strip.chips[2].clicked.emit(12)
        visible_items = [table.item(row, 0).text() for row in range(table.rowCount()) if not table.isRowHidden(row) and table.item(row, 0).text() in {"1", "2", "3"}]
        self.assertEqual(visible_items, ["1", "2", "3"])

    def _lot_dialog(self):
        return self._family_dialog(_lot_family_payload())

    def _visible_items(self, dialog):
        table = dialog.itens_tab.table
        return [table.item(row, 0).text() for row in range(table.rowCount())
                if not table.isRowHidden(row) and table.item(row, 0).text() in {"1", "2", "3"}]

    def test_cards_show_principal_and_each_lot_with_place_status_and_counts(self):
        dialog = self._lot_dialog()
        cards = dialog.family_strip.cards
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0].title_label.text(), "CP 05389 · Principal")
        self.assertEqual(cards[1].title_label.text(), "P1")  # lote fisico: sem numero de CP proprio
        self.assertIn("Expedição", cards[1].badge.text())
        self.assertIn("10 un.", cards[1].counts_label.text())
        self.assertIn("1 item", cards[2].counts_label.text())
        self.assertTrue(cards[0].property("selected"))
        self.assertFalse(cards[1].property("selected"))
        self.assertEqual(len(dialog.family_strip.chips), 0)

    def test_cards_for_child_proposals_show_the_cp_number(self):
        payload = _lot_family_payload()
        payload["partials"][0].update({"key": "P:11", "kind": "PROPOSTA", "proposal_number": "CP 05389-1", "proposal_id": 11})
        dialog = self._family_dialog(payload)
        self.assertEqual(dialog.family_strip.cards[1].title_label.text(), "P1 · CP 05389-1")

    def test_choosing_a_card_filters_items_and_principal_restores_all(self):
        dialog = self._lot_dialog()
        strip = dialog.family_strip
        emitted = []
        strip.selection_changed.connect(emitted.append)
        self.assertEqual(self._visible_items(dialog), ["1", "2", "3"])
        strip.cards[2].clicked.emit(strip.cards[2].key)
        self.assertEqual(self._visible_items(dialog), ["3"])
        self.assertTrue(strip.cards[2].property("selected"))
        self.assertFalse(strip.cards[0].property("selected"))
        strip.cards[1].clicked.emit(strip.cards[1].key)
        self.assertEqual(self._visible_items(dialog), ["1", "2"])
        strip.cards[0].clicked.emit(None)
        self.assertEqual(self._visible_items(dialog), ["1", "2", "3"])
        self.assertEqual(emitted, ["L:GALVANIZACAO", "L:EXPEDICAO", None])

    def test_choosing_the_same_card_again_does_not_emit_again(self):
        dialog = self._lot_dialog()
        strip = dialog.family_strip
        emitted = []
        strip.selection_changed.connect(emitted.append)
        strip.cards[1].clicked.emit(strip.cards[1].key)
        strip.cards[1].clicked.emit(strip.cards[1].key)
        self.assertEqual(emitted, ["L:EXPEDICAO"])

    def test_lots_without_child_proposal_still_override_the_main_badge(self):
        dialog = self._lot_dialog()
        # has_partials=False (sem filhas) mas ha lotes: o selo principal ainda deve mostrar onde as pecas estao
        self.assertFalse(dialog.family_strip.isHidden())
        self.assertTrue(dialog.status_badge.text().startswith("PARCIAL"), dialog.status_badge.text())

    def _child_dialog(self):
        """Familia com filhas (P:11 e P:12) e servico que responde por cada proposta-filha."""
        service = FakeDetailService()
        payload = _family_payload()
        payload["partials"] = [
            {"key": "P:11", "kind": "PROPOSTA", "label": "P1", "proposal_id": 11, "proposal_number": "CP 05389-1", "place": "EXPEDICAO",
             "current_area": "EXPEDICAO", "current_status": "EM_SEPARACAO", "item_count": 2, "total_units": "5.0000", "quantities": {}},
            {"key": "P:12", "kind": "PROPOSTA", "label": "P2", "proposal_id": 12, "proposal_number": "CP 05389-2", "place": "PRODUCAO",
             "current_area": "PRODUCAO", "current_status": "ITEM_PENDENTE_FABRICACAO", "item_count": 1, "total_units": "2.0000", "quantities": {}},
        ]
        for row in payload["items"]:
            row["partial_keys"] = [f"P:{row['proposal_id']}"]
        service.proposal_family = lambda process_id: payload
        base_get = service.get_process_dict
        children = {
            11: {**service.process, "id": 11, "proposta": "CP 05389-1", "status_expedicao": "EM_SEPARACAO"},
            12: {**service.process, "id": 12, "proposta": "CP 05389-2", "status_expedicao": ""},
        }
        service.get_process_dict = lambda pid: dict(children[pid]) if pid in children else base_get(pid)
        service.child_loads = {11: [], 12: [{"id": 9, "codigo": "C9", "status": "ENVIADA"}]}
        service.child_history = {11: [{"data_hora": "2026-08-02 10:00", "area": "EXPEDICAO", "acao": "Separacao"}], 12: []}
        service.process_loads = lambda pid: list(service.child_loads.get(pid, [{"id": 1, "codigo": "C1"}, {"id": 2, "codigo": "C2"}]))
        service.process_history_rows = lambda pid: list(service.child_history.get(pid, [
            {"data_hora": "2026-08-01 09:00", "area": "CONTROLE GERAL", "acao": "Criada"},
            {"data_hora": "2026-08-01 10:00", "area": "PRODUCAO", "acao": "Liberada"},
        ]))
        return self._dialog(service), service

    def _wait_scope(self, dialog):
        deadline = time.monotonic() + 5.0
        while not dialog.tabs.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)

    def test_choosing_a_child_partial_loads_its_own_data_in_every_tab(self):
        dialog, service = self._child_dialog()
        strip = dialog.family_strip
        self.assertEqual(dialog.cargas_tab.table.rowCount(), 2)
        self.assertEqual(dialog.historico_tab._history.__len__(), 2)
        strip.cards[1].clicked.emit("P:11")
        self._wait_scope(dialog)
        self.assertEqual(dialog.cargas_tab.table.rowCount(), 0)
        self.assertEqual(len(dialog.historico_tab._history), 1)
        self.assertFalse(dialog.scope_note.isHidden())
        self.assertIn("CP 05389-1", dialog.scope_note.text())
        strip.cards[2].clicked.emit("P:12")
        self._wait_scope(dialog)
        self.assertEqual(dialog.cargas_tab.table.rowCount(), 1)
        self.assertEqual(len(dialog.historico_tab._history), 0)

    def test_going_back_to_principal_restores_the_whole_proposal(self):
        dialog, service = self._child_dialog()
        strip = dialog.family_strip
        strip.cards[1].clicked.emit("P:11")
        self._wait_scope(dialog)
        strip.cards[0].clicked.emit(None)
        self._wait_scope(dialog)
        self.assertEqual(dialog.cargas_tab.table.rowCount(), 2)
        self.assertEqual(len(dialog.historico_tab._history), 2)
        self.assertTrue(dialog.scope_note.isHidden())

    def test_a_lot_keeps_the_proposals_data_and_explains_it(self):
        service = FakeDetailService()
        payload = _lot_family_payload()
        service.proposal_family = lambda process_id: payload
        service.loads = [{"id": 1, "codigo": "C1"}]
        dialog = self._dialog(service)
        dialog.family_strip.cards[1].clicked.emit("L:EXPEDICAO")
        self.assertEqual(dialog.cargas_tab.table.rowCount(), 1)
        self.assertFalse(dialog.scope_note.isHidden())
        self.assertIn("lote P1", dialog.scope_note.text())
        self.assertIn("proposta inteira", dialog.scope_note.text())

    def test_summary_links_count_the_lots_and_child_partials_of_the_family(self):
        from PySide6.QtWidgets import QLabel

        dialog = self._lot_dialog()
        numbers = [label.text() for label in dialog.resumo_tab.links_panel.findChildren(QLabel) if label.objectName() == "StatNumber"]
        self.assertEqual(numbers[0], "2")  # P1 e P2 (lotes), como nos cartoes do cabecalho
        plain = self._dialog(FakeDetailService())
        numbers = [label.text() for label in plain.resumo_tab.links_panel.findChildren(QLabel) if label.objectName() == "StatNumber"]
        self.assertEqual(numbers[0], "0")

    def test_items_tab_count_follows_the_selected_partial(self):
        dialog = self._family_dialog(_lot_family_payload())
        self.assertEqual(dialog.itens_tab.visible_item_count(), 3)
        dialog.family_strip.cards[2].clicked.emit("L:GALVANIZACAO")
        self.assertEqual(dialog.itens_tab.visible_item_count(), 1)

    def test_without_family_the_header_stays_as_before(self):
        for family in ({}, {"has_partials": False, "members": [], "items": []}):
            dialog = self._family_dialog(family)
            self.assertTrue(dialog.family_strip.isHidden())
            self.assertIn("EXPEDIÇÃO", dialog.status_badge.text().upper())
            self.assertFalse(dialog.status_badge.text().startswith("PARCIAL"))

    def test_service_without_family_method_keeps_working(self):
        dialog = self._dialog(FakeDetailService())
        self.assertTrue(dialog.family_strip.isHidden())


if __name__ == "__main__":
    unittest.main()
