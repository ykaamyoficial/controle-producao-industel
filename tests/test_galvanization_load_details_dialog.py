from __future__ import annotations

import os
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import BackendService, OFFICIAL_COLOR_PALETTES
from app.ui.galvanization_items_page import GalvanizationLoadsPage
from app.ui.galvanization_load_details_dialog import GalvanizationLoadDetailsDialog


def _details(status: str = "RETORNO_PARCIAL") -> dict:
    return {
        "load": {
            "id": 4,
            "codigo": "CG00004",
            "status": status,
            "motorista": "Maria",
            "peso_informado_carga": "1500.0000",
            "peso_conhecido_itens": "370.0000",
            "proposal_count": 2,
            "item_count": 3,
            "criado_em": "11/08/2026 19:13:00",
            "criado_por": "João",
            "data_prevista_retorno": "15/08/2026",
            "data_retorno": "",
            "observacao": "Carga prioritária",
        },
        "proposals": [
            {
                "processo_id": 101,
                "proposta": "CP00101",
                "cliente": "Cliente A",
                "peso_enviado": "320.0000",
                "status_retorno": "RETORNO_PARCIAL",
            },
            {
                "processo_id": 102,
                "proposta": "CP00102",
                "cliente": "Cliente B",
                "peso_enviado": "50.0000",
                "status_retorno": "AGUARDANDO_RETORNO",
            },
        ],
        "items": [
            {
                "id": 1,
                "processo_id": 101,
                "proposta": "CP00101",
                "codigo_produto": "COD-A",
                "descricao": "Viga principal",
                "quantidade_enviada": "4.0000",
                "peso_enviado": "200.0000",
                "quantidade_retornada": "2.0000",
                "peso_retornado": "100.0000",
                "quantidade_pendente": "2.0000",
                "peso_pendente": "100.0000",
            },
            {
                "id": 2,
                "processo_id": 101,
                "proposta": "CP00101",
                "codigo_produto": "COD-B",
                "descricao": "Coluna lateral",
                "quantidade_enviada": "2.0000",
                "peso_enviado": "120.0000",
                "quantidade_retornada": "2.0000",
                "peso_retornado": "120.0000",
                "quantidade_pendente": "-0.0001",
                "peso_pendente": "-0.0050",
            },
            {
                "id": 3,
                "processo_id": 102,
                "proposta": "CP00102",
                "codigo_produto": "COD-C",
                "descricao": "Chapa de base",
                "quantidade_enviada": "1.0000",
                "peso_enviado": "50.0000",
                "quantidade_retornada": "0.0000",
                "peso_retornado": "0.0000",
                "quantidade_pendente": "1.0000",
                "peso_pendente": "50.0000",
            },
        ],
        "returns": [
            {
                "id": 21,
                "numero_retorno": 1,
                "data": "12/08/2026 09:42:00",
                "usuario": "Maria",
                "peso_retornado": "100.0000",
                "itens_com_peso": 1,
                "itens_total_peso": 1,
                "tipo_retorno": "PARCIAL",
                "observacao": "Primeira viagem",
                "itens": [
                    {
                        "proposta": "CP00101",
                        "codigo_produto": "COD-A",
                        "descricao": "Viga principal",
                        "quantidade_retornada": "2.0000",
                        "peso_retornado": "100.0000",
                    }
                ],
            },
            {
                "id": 22,
                "numero_retorno": 2,
                "data": "13/08/2026 10:30:00",
                "usuario": "Pedro",
                "peso_retornado": "120.0000",
                "itens_com_peso": 1,
                "itens_total_peso": 1,
                "tipo_retorno": "PARCIAL",
                "observacao": "Segunda viagem",
                "itens": [
                    {
                        "proposta": "CP00101",
                        "codigo_produto": "COD-B",
                        "descricao": "Coluna lateral",
                        "quantidade_retornada": "2.0000",
                        "peso_retornado": "120.0000",
                    }
                ],
            },
        ],
        "history": [
            {
                "id": 31,
                "data": "12/08/2026 09:42:00",
                "usuario": "Maria",
                "evento": "GALVANIZATION_RETURN_REGISTERED",
                "status_anterior": "LIBERADA_PARA_ENVIO",
                "status_novo": "RETORNO_PARCIAL",
                "metadata": {"observation": "Primeira viagem"},
            },
            {
                "id": 30,
                "data": "11/08/2026 19:13:00",
                "usuario": "João",
                "evento": "GALVANIZATION_LOAD_CREATED",
                "status_anterior": "",
                "status_novo": "",
                "metadata": {},
            },
        ],
    }


class FakeDetailsService:
    def __init__(self, *, theme: str = "claro", details: dict | None = None, can_edit: bool = True):
        self.palette = OFFICIAL_COLOR_PALETTES[theme]
        self.payload = deepcopy(details if details is not None else _details())
        self.can_edit_value = can_edit
        self.reads = 0
        self.writes = 0

    def galvanization_load_details(self, load_id: int):
        self.reads += 1
        assert load_id == 4
        return deepcopy(self.payload)

    def load_status_label(self, status: str):
        return {
            "AGUARDANDO_LIBERACAO": "Aguardando liberação",
            "LIBERADA_PARA_ENVIO": "Liberada para envio",
            "RETORNO_PARCIAL": "Retorno parcial",
            "RETORNADA_GALVANIZACAO": "Retornada da galvanização",
        }.get(status, status)

    def status_label(self, status: str):
        return self.load_status_label(status) or "—"

    def galvanization_load_actions(self, load: dict):
        if not self.can_edit_value:
            return []
        if load.get("status") == "AGUARDANDO_LIBERACAO":
            return ["EDIT", "RELEASE"]
        if load.get("status") in {"LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL"}:
            return ["RETURN"]
        return []


def _run_synchronously(_owner, operation, on_success, on_error):
    try:
        on_success(operation())
    except Exception as exc:
        on_error(exc)
    return None


class GalvanizationLoadDetailsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, service: FakeDetailsService) -> GalvanizationLoadDetailsDialog:
        with (
            patch("app.ui.galvanization_load_details_dialog.start_worker", side_effect=_run_synchronously),
            patch("app.ui.galvanization_load_details_dialog.QTimer.singleShot", side_effect=lambda _delay, callback: callback()),
        ):
            return GalvanizationLoadDetailsDialog(service, 4)

    def test_loads_once_and_builds_complete_header_and_five_tabs(self):
        service = FakeDetailsService()
        dialog = self._dialog(service)

        self.assertEqual(service.reads, 1)
        self.assertEqual(dialog.title_label.text(), "Carga #4")
        self.assertEqual(dialog.status_badge.text(), "Retorno parcial")
        self.assertEqual(dialog.header_values["motorista"].text(), "Maria")
        self.assertEqual(dialog.header_values["usuario"].text(), "João")
        self.assertEqual(
            [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())],
            ["Resumo", "Propostas", "Itens da carga", "Retornos", "Histórico"],
        )

    def test_proposals_and_selected_items_are_strictly_scoped_to_load_and_proposal(self):
        dialog = self._dialog(FakeDetailsService())

        self.assertEqual(dialog.proposals_tab.proposals_table.rowCount(), 2)
        self.assertEqual(dialog.proposals_tab.items_table.rowCount(), 2)
        dialog.proposals_tab.proposals_table.selectRow(1)
        dialog.proposals_tab._update_selected_items()
        self.assertEqual(dialog.proposals_tab.items_table.rowCount(), 1)
        self.assertEqual(dialog.proposals_tab.items_table.item(0, 0).text(), "COD-C")
        self.assertEqual(dialog.items_tab.table.rowCount(), 3)

    def test_local_item_search_and_nonnegative_balance(self):
        dialog = self._dialog(FakeDetailsService())

        dialog.items_tab.search.setText("cod-b")
        self.assertEqual(dialog.items_tab.table.rowCount(), 1)
        self.assertEqual(dialog.items_tab.table.item(0, 1).text(), "COD-B")
        self.assertEqual(dialog.items_tab.table.item(0, 7).text(), "0")
        self.assertEqual(dialog.items_tab.table.item(0, 8).text(), "0 kg")
        dialog.items_tab.search.setText("CP00102")
        self.assertEqual(dialog.items_tab.table.rowCount(), 1)
        dialog.items_tab.search.setText("inexistente")
        self.assertEqual(dialog.items_tab.table.rowCount(), 0)
        self.assertFalse(dialog.items_tab.empty.isHidden())

    def test_multiple_returns_remain_separate_and_show_their_own_items(self):
        dialog = self._dialog(FakeDetailsService())

        self.assertEqual(dialog.returns_tab.returns_table.rowCount(), 2)
        self.assertEqual(dialog.returns_tab.items_table.item(0, 1).text(), "COD-A")
        dialog.returns_tab.returns_table.selectRow(1)
        dialog.returns_tab._update_selected_return()
        self.assertEqual(dialog.returns_tab.items_table.rowCount(), 1)
        self.assertEqual(dialog.returns_tab.items_table.item(0, 1).text(), "COD-B")

    def test_empty_returns_and_history_have_explanatory_states(self):
        payload = _details()
        payload["returns"] = []
        payload["history"] = []
        dialog = self._dialog(FakeDetailsService(details=payload))

        self.assertEqual(dialog.returns_tab.returns_table.rowCount(), 0)
        self.assertFalse(dialog.returns_tab.returns_empty.isHidden())
        self.assertEqual(dialog.history_tab.table.rowCount(), 0)
        self.assertFalse(dialog.history_tab.empty.isHidden())

    def test_open_refresh_and_close_are_read_only(self):
        service = FakeDetailsService()
        dialog = self._dialog(service)

        with patch("app.ui.galvanization_load_details_dialog.start_worker", side_effect=_run_synchronously):
            dialog.refresh()
        dialog.reject()
        self.assertEqual(service.reads, 2)
        self.assertEqual(service.writes, 0)

    def test_actions_respect_status_permissions_and_both_themes(self):
        waiting = _details("AGUARDANDO_LIBERACAO")
        waiting_dialog = self._dialog(FakeDetailsService(theme="claro", details=waiting))
        waiting_actions = [action.text() for action in waiting_dialog.actions_button.menu().actions()]
        self.assertEqual(waiting_actions, ["Editar carga", "Liberar carga"])

        denied_dialog = self._dialog(FakeDetailsService(theme="escuro", details=waiting, can_edit=False))
        self.assertFalse(denied_dialog.actions_button.isEnabled())
        self.assertIsNone(denied_dialog.actions_button.menu())
        self.assertIn("background:", waiting_dialog.status_badge.styleSheet())
        self.assertIn("background:", denied_dialog.status_badge.styleSheet())

    def test_official_adapter_centralizes_available_load_actions(self):
        service = BackendService.__new__(BackendService)
        service.can_edit = lambda _area: True
        self.assertEqual(
            service.galvanization_load_actions({"status": "AGUARDANDO_LIBERACAO"}),
            ["EDIT", "RELEASE"],
        )
        self.assertEqual(
            service.galvanization_load_actions({"status": "RETORNO_PARCIAL"}),
            ["RETURN"],
        )
        self.assertEqual(
            service.galvanization_load_actions({"status": "RETORNADA_GALVANIZACAO"}),
            [],
        )
        service.can_edit = lambda _area: False
        self.assertEqual(
            service.galvanization_load_actions({"status": "AGUARDANDO_LIBERACAO"}),
            [],
        )

    def test_query_error_is_shown_without_closing_the_dialog(self):
        service = FakeDetailsService()
        service.galvanization_load_details = lambda _load_id: (_ for _ in ()).throw(RuntimeError("servidor indisponível"))

        dialog = self._dialog(service)

        self.assertFalse(dialog.error_label.isHidden())
        self.assertIn("servidor indisponível", dialog.error_label.text())
        self.assertFalse(dialog.tabs.isEnabled())
        self.assertEqual(dialog.result(), 0)


class _FakeLoadsPageService:
    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]

    def can_mount_galvanization_load(self):
        return True

    def can_edit(self, _area):
        return True

    def galvanization_load_actions(self, _row):
        return []

    def load_status_label(self, status):
        return status

    def display_cell(self, _key, value, _row):
        return "" if value is None else str(value)


class GalvanizationLoadsNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_double_click_and_context_action_use_same_real_load_id(self):
        page = GalvanizationLoadsPage(_FakeLoadsPageService())
        page.model.set_rows([{"id": 9, "status": "RETORNO_PARCIAL"}, {"id": 4, "status": "RETORNO_PARCIAL"}])
        opened: list[int] = []
        page.open_load_details = opened.append

        page._open_details_from_index(page.model.index(1, 3))
        page._menu_for_load(9).actions()[0].trigger()
        page._open_details_from_index(QModelIndex())

        self.assertEqual(opened, [4, 9])


if __name__ == "__main__":
    unittest.main()
