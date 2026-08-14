from __future__ import annotations

import inspect
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.action_center.descriptor import ActionCategory
from app.ui.process_page import ProcessPage
from app.ui.status_dialog import StatusDialog, open_proposal_action_center
from tests.test_action_center import FakeControlGeneralService, FakeExpeditionService, FakeWarehouseService
from tests.test_galvanization_action_center import FakeGalvanizationService
from tests.test_status_dialog import FakeService

# Fase 8, secao 67-68: uma fabrica por area, todas exercitando exatamente o
# mesmo par (StatusDialog, ProposalActionCenter) - nao ha implementacao
# paralela por area, apenas services diferentes.
_AREA_FACTORIES = {
    "PRODUCAO": lambda: (FakeService("INICIADO"), "INICIADO"),
    "CONTROLE GERAL": lambda: (FakeControlGeneralService("AGUARDANDO_LIBERACAO"), "AGUARDANDO_LIBERACAO"),
    "ALMOXARIFADO": lambda: (FakeWarehouseService("EM_SEPARACAO"), "EM_SEPARACAO"),
    "EXPEDICAO": lambda: (FakeExpeditionService("EM_SEPARACAO"), "EM_SEPARACAO"),
    "GALVANIZACAO": lambda: (FakeGalvanizationService("AGUARDANDO_ENVIO"), "AGUARDANDO_ENVIO"),
}


class CrossAreaContractTests(unittest.TestCase):
    """Secoes 67-70: as cinco areas migradas abrem a MESMA
    ProposalActionCenter (via StatusDialog), com contexto correto e todo
    Action ID resolvendo para exatamente um handler."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_area_opens_the_same_class_with_correct_identity(self):
        for area, factory in _AREA_FACTORIES.items():
            with self.subTest(area=area):
                service, status = factory()
                dialog = StatusDialog(service, 314, area)
                self.assertIsInstance(dialog, StatusDialog)
                self.assertEqual(dialog.context.proposal_id, 314)
                self.assertEqual(dialog.context.area, area)
                self.assertEqual(dialog.context.current_status, status)
                self.assertEqual(dialog.context.proposal_number, "CP05266" if area != "PRODUCAO" else "CP05385")
                self.assertTrue(dialog.context.client_name)

    def test_every_descriptor_across_every_area_has_exactly_one_handler(self):
        registry = StatusDialog._build_registry()
        for area, factory in _AREA_FACTORIES.items():
            service, _status = factory()
            dialog = StatusDialog(service, 1, area)
            with self.subTest(area=area):
                for descriptor in dialog.context.available_actions:
                    handler = registry.resolve(descriptor.id, descriptor.area)
                    self.assertIsNotNone(handler, f"{area}: sem handler para {descriptor.id!r}")
                    self.assertIsInstance(descriptor.category, ActionCategory)
                    self.assertTrue(descriptor.label)

    def test_unknown_action_id_is_a_controlled_error_in_every_area(self):
        from app.ui.action_center.descriptor import ActionDescriptor

        for area, factory in _AREA_FACTORIES.items():
            with self.subTest(area=area):
                service, _status = factory()
                dialog = StatusDialog(service, 1, area)
                bogus = ActionDescriptor(
                    id="TOTALLY_UNKNOWN_ACTION", label="X", description="", icon=None,
                    category=ActionCategory.NORMAL, area=area,
                )
                with patch("app.ui.action_center.proposal_action_center.QMessageBox.warning") as warning:
                    dialog.run_action(bogus)
                warning.assert_called_once()

    def test_opening_and_closing_writes_nothing_in_any_area(self):
        writers = {"update_status", "administrative_correction", "save_galvanization_load"}
        for area, factory in _AREA_FACTORIES.items():
            with self.subTest(area=area):
                service, _status = factory()
                dialog = StatusDialog(service, 1, area)
                dialog.observation.setPlainText("rascunho que nao deve ser gravado")
                dialog.reject()
                calls = getattr(service, "calls", [])
                self.assertFalse(any(call[0] in writers for call in calls))


class OpenProposalActionCenterTests(unittest.TestCase):
    """Secao 6: ponto unico de abertura - resolve a area preferida contra
    `visible_areas()` e delega o auto-detect (area=None) para o proprio
    ProposalActionCenter, sem duplicar a logica em cada chamador."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preferred_area_is_used_when_visible(self):
        service = FakeService("INICIADO")
        service.visible_areas = lambda: ["PRODUCAO", "CONTROLE GERAL"]
        dialog = open_proposal_action_center(service, 1, None, area="PRODUCAO")
        self.assertEqual(dialog.area, "PRODUCAO")

    def test_preferred_area_outside_visible_areas_falls_back_to_auto_detect(self):
        # Reproduz o caso real de Parciais: "PARCIAIS" nunca esta em
        # visible_areas() (secao 54 - Parciais nao muda, mas nao deve
        # regredir), entao a area real da proposta deve ser resolvida via
        # current_location(), exatamente como antes desta fase.
        service = FakeService("INICIADO")
        service.visible_areas = lambda: ["PRODUCAO"]
        dialog = open_proposal_action_center(service, 1, None, area="PARCIAIS")
        self.assertEqual(dialog.area, "PRODUCAO")  # current_location() do FakeService

    def test_no_preferred_area_auto_detects(self):
        service = FakeService("INICIADO")
        service.visible_areas = lambda: ["PRODUCAO"]
        dialog = open_proposal_action_center(service, 1, None)
        self.assertEqual(dialog.area, "PRODUCAO")

    def test_returns_a_status_dialog_instance(self):
        service = FakeService("INICIADO")
        service.visible_areas = lambda: ["PRODUCAO"]
        dialog = open_proposal_action_center(service, 1, None, area="PRODUCAO")
        self.assertIsInstance(dialog, StatusDialog)


class SingleOpeningMethodDelegationTests(unittest.TestCase):
    """Secao 6/71: botao Acoes, atalho de tabela e menu contextual de
    ProcessPage, alem do botao Acoes de ProcessDetailDialog, convergem todos
    para `open_proposal_action_center` - nao existe implementacao paralela
    por ponto de entrada."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _page(self):
        from tests.test_process_batch_selection import ROWS, FakeProductionService

        service = FakeProductionService()
        page = ProcessPage(service, "PRODUCAO", "Producao")
        page._refresh_success((deepcopy(ROWS), {}))
        return page, service

    def test_button_and_context_menu_wire_to_the_same_callback_not_a_duplicate(self):
        # Guarda estrutural (secao 6/9): tanto o botao "Acoes" quanto o item
        # "Acoes da proposta" do menu contextual devem conectar em
        # `self.change_status` - se algum dia um dos dois passar a chamar um
        # metodo diferente (reimplementando a abertura em paralelo), este
        # teste falha em vez de deixar a duplicacao passar despercebida.
        build_source = inspect.getsource(ProcessPage._build)
        menu_source = inspect.getsource(ProcessPage.open_context_menu)
        self.assertIn("status_btn.clicked.connect(self.change_status)", build_source)
        self.assertIn("triggered=self.change_status", menu_source)

    def test_change_status_for_id_delegates_to_the_single_opening_function(self):
        page, _service = self._page()
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        fake_dialog.success_message = "ok"
        with patch("app.ui.process_page.open_proposal_action_center", return_value=fake_dialog) as opener:
            page.change_status_for_id(10)
        opener.assert_called_once_with(page.service, 10, page, area="PRODUCAO")

    def test_process_detail_dialog_delegates_to_the_single_opening_function(self):
        from app.ui.process_detail_dialog import ProcessDetailDialog

        service = MagicMock()
        service.palette = OFFICIAL_COLOR_PALETTES["claro"]
        service.get_process_dict.return_value = {
            "id": 10, "proposta": "CP05266", "cliente": "MNS", "status_geral": "EM_PRODUCAO",
        }
        service.can_edit_process.return_value = False
        service.process_history_rows.return_value = []
        service.loads_for_process = lambda *_a, **_k: []
        with patch.object(ProcessDetailDialog, "load", lambda self: None):
            dialog = ProcessDetailDialog(service, 10, None)
        fake_center = MagicMock()
        fake_center.exec.return_value = 0
        with patch("app.ui.process_detail_dialog.open_proposal_action_center", return_value=fake_center) as opener:
            dialog.change_status()
        opener.assert_called_once_with(service, 10, dialog)


class ClickBehaviorTests(unittest.TestCase):
    """Secoes 72-73: duplo clique abre Detalhes; clique simples so seleciona
    - nenhum dos dois executa uma transicao de status."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _page(self):
        from tests.test_process_batch_selection import ROWS, FakeProductionService

        service = FakeProductionService()
        page = ProcessPage(service, "PRODUCAO", "Producao")
        page._refresh_success((deepcopy(ROWS), {}))
        return page

    def test_double_click_opens_details_not_actions(self):
        page = self._page()
        page.table.selectRow(0)
        with patch("app.ui.process_page.ProcessDetailDialog") as details_ctor, patch(
            "app.ui.process_page.open_proposal_action_center"
        ) as opener:
            details_ctor.return_value.exec.return_value = 0
            details_ctor.return_value.changed = False
            page._handle_table_double_click(page.proxy.index(0, 1))
        details_ctor.assert_called_once()
        opener.assert_not_called()

    def test_single_click_in_normal_mode_does_not_open_anything(self):
        page = self._page()
        self.assertFalse(page.batch_selection.active)
        with patch("app.ui.process_page.ProcessDetailDialog") as details_ctor, patch(
            "app.ui.process_page.open_proposal_action_center"
        ) as opener:
            page.table.selectRow(0)
            page._handle_table_click(page.proxy.index(0, 1))
        details_ctor.assert_not_called()
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
