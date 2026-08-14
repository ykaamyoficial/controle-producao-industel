from __future__ import annotations

import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.galvanization_load_dialog import GalvanizationLoadManagerDialog, GalvanizationReturnDialog


class FakeGalvanizationLoadService:
    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.loads = [
            {
                "id": 1,
                "status": "AGUARDANDO_LIBERACAO",
                "motorista": "Ana",
                "peso_total": 1200,
                "item_count": 2,
                "data_prevista_retorno": "20/07/2026",
                "data_retorno": "",
                "criado_em": "10/07/2026 08:00:00",
                "criado_por": "admin",
            },
            {
                "id": 2,
                "status": "LIBERADA_PARA_ENVIO",
                "motorista": "Bruno",
                "peso_total": 800,
                "item_count": 1,
                "data_prevista_retorno": "20/07/2026",
                "data_retorno": "",
                "criado_em": "10/07/2026 09:00:00",
                "criado_por": "admin",
            },
            {
                "id": 3,
                "status": "RETORNADA_GALVANIZACAO",
                "motorista": "Carla",
                "peso_total": 500,
                "item_count": 1,
                "data_prevista_retorno": "18/07/2026",
                "data_retorno": "19/07/2026",
                "criado_em": "10/07/2026 10:00:00",
                "criado_por": "admin",
            },
        ]
        self.proposals = {
            1: [
                {
                    "processo_id": 101,
                    "proposta": "CP00101",
                    "cliente": "MNS",
                    "obra_site": "SITE A",
                    "peso_total_proposta": 1000,
                    "peso_enviado": 700,
                    "parcial": 1,
                },
                {
                    "processo_id": 102,
                    "proposta": "CP00102",
                    "cliente": "ABC",
                    "obra_site": "SITE B",
                    "peso_total_proposta": 500,
                    "peso_enviado": 500,
                    "parcial": 0,
                },
            ],
            2: [
                {
                    "processo_id": 201,
                    "proposta": "CP00201",
                    "cliente": "MNS",
                    "peso_enviado": 0,
                    "peso_retornado": 0,
                    "peso_pendente": 0,
                },
            ],
            3: [],
            4: [
                {
                    "processo_id": 401,
                    "proposta": "CP00401",
                    "cliente": "MNS",
                    "peso_enviado": 0,
                    "peso_retornado": 0,
                    "peso_pendente": 0,
                },
            ],
        }
        self.items = {
            (1, 101): [
                {
                    "numero_item": "1",
                    "codigo_produto": "COD-A",
                    "descricao": "Descricao longa do item para testar quebra de linha",
                    "quantidade": 2,
                    "peso": 10,
                    "produzido": 1,
                    "galvanizado": 0,
                    "precisa_galvanizacao": "sim",
                },
                {
                    "numero_item": "2",
                    "codigo_produto": "COD-B",
                    "descricao": "Outro item",
                    "quantidade": 1,
                    "peso": 5,
                    "produzido": 1,
                    "galvanizado": 0,
                    "precisa_galvanizacao": "sim",
                },
            ],
            (1, 102): [
                {
                    "numero_item": "1",
                    "codigo_produto": "COD-C",
                    "descricao": "Item completo",
                    "quantidade": 1,
                    "peso": 8,
                    "produzido": 1,
                    "galvanizado": 1,
                    "precisa_galvanizacao": "sim",
                }
            ],
        }
        self.return_proposals = {
            2: [
                {
                    "carga_item_id": 201,
                    "processo_id": 201,
                    "proposta": "CP00201",
                    "cliente": "MNS",
                    "peso_enviado": 100,
                    "peso_retornado": 0,
                    "peso_pendente": 100,
                    "itens_pendentes": 0,
                    "observacao": "",
                }
            ],
            4: [
                {
                    "carga_item_id": 401,
                    "processo_id": 401,
                    "proposta": "CP00401",
                    "cliente": "MNS",
                    "peso_enviado": 30,
                    "peso_retornado": 0,
                    "peso_pendente": 30,
                    "itens_pendentes": 2,
                    "observacao": "",
                }
            ],
        }
        self.return_items = {
            (2, 201): [
                {
                    "detail_id": 2011,
                    "id": 2011,
                    "processo_id": 201,
                    "proposta_item_id": 20011,
                    "proposta": "CP00201",
                    "cliente": "MNS",
                    "numero_item": "1",
                    "codigo_produto": "COD-Z",
                    "descricao": "Item unico da proposta",
                    "peso_unitario": None,
                    "quantidade_enviada": 100,
                    "quantidade_retornada": 0,
                    "quantidade_pendente": 100,
                    "peso_pendente": 100,
                    "status_retorno": "AGUARDANDO_RETORNO",
                },
            ],
            (4, 401): [
                {
                    "id": 9001,
                    "processo_id": 401,
                    "proposta": "CP00401",
                    "cliente": "MNS",
                    "numero_item": "1",
                    "codigo_produto": "COD-A",
                    "descricao": "Item A",
                    "quantidade_enviada": 2,
                    "quantidade_retornada": 0,
                    "quantidade_pendente": 2,
                    "peso_pendente": 20,
                    "status_retorno": "AGUARDANDO_RETORNO",
                },
                {
                    "id": 9002,
                    "processo_id": 401,
                    "proposta": "CP00401",
                    "cliente": "MNS",
                    "numero_item": "2",
                    "codigo_produto": "COD-B",
                    "descricao": "Item B",
                    "quantidade_enviada": 1,
                    "quantidade_retornada": 0,
                    "quantidade_pendente": 1,
                    "peso_pendente": 10,
                    "status_retorno": "AGUARDANDO_RETORNO",
                },
            ]
        }
        self.registered_returns = []

    def galvanization_loads(self):
        return self.loads

    def load_status_label(self, status):
        return {
            "AGUARDANDO_LIBERACAO": "Aguardando liberacao",
            "LIBERADA_PARA_ENVIO": "Liberada para envio",
            "RETORNADA_GALVANIZACAO": "Retornada da galvanizacao",
        }.get(status, status)

    def get_galvanization_load_dict(self, load_id):
        return next((row for row in self.loads if row["id"] == load_id), {})

    def galvanization_load_items(self, load_id):
        return self.proposals.get(load_id, [])

    def galvanization_load_proposal_items(self, load_id, process_id):
        return self.items.get((load_id, process_id), [])

    def galvanization_return_proposals(self, load_id):
        return self.return_proposals.get(load_id, [])

    def galvanization_return_items(self, load_id, process_id):
        return self.return_items.get((load_id, process_id), [])

    def register_galvanization_partial_return(self, load_id, items, observation):
        self.registered_returns.append((load_id, items, observation))


class GalvanizationLoadManagerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = FakeGalvanizationLoadService()

    def test_main_table_is_load_only_with_action_column(self):
        with patch("app.ui.galvanization_load_dialog.current_date", return_value=date(2026, 7, 19)):
            dialog = GalvanizationLoadManagerDialog(self.service)

        self.assertEqual(dialog.table.horizontalHeaderItem(0).text(), "Acao")
        self.assertEqual(dialog.table.horizontalHeaderItem(1).text(), "Carga")
        self.assertEqual(dialog.table.rowCount(), 3)
        self.assertFalse(hasattr(dialog, "load_proposals"))
        self.assertFalse(hasattr(dialog, "proposal_items"))
        self.assertFalse(dialog.table.item(0, 0).icon().isNull())
        self.assertIn("aguardando", dialog.table.item(0, 0).toolTip().lower())
        self.assertIsNotNone(dialog.table.cellWidget(0, 2))
        self.assertIn("border-radius", dialog.table.cellWidget(0, 2).styleSheet())

    def test_overdue_load_uses_current_date_rule(self):
        with patch("app.ui.galvanization_load_dialog.current_date", return_value=date(2026, 7, 21)):
            dialog = GalvanizationLoadManagerDialog(self.service)

        self.assertIn("atrasada", dialog.table.item(0, 0).toolTip().lower())
        self.assertEqual(dialog.table.item(0, 2).text(), "Atrasada")

    def test_action_menu_respects_load_status(self):
        dialog = GalvanizationLoadManagerDialog(self.service)

        waiting_actions = [action.text() for action in dialog.action_menu_for_load(1).actions() if action.text()]
        sent_actions = [action.text() for action in dialog.action_menu_for_load(2).actions() if action.text()]
        returned_actions = [action.text() for action in dialog.action_menu_for_load(3).actions() if action.text()]

        self.assertIn("Editar carga", waiting_actions)
        self.assertIn("Liberar carga", waiting_actions)
        self.assertNotIn("Registrar retorno", waiting_actions)
        self.assertIn("Registrar retorno", sent_actions)
        self.assertNotIn("Editar carga", sent_actions)
        self.assertEqual(returned_actions, ["Detalhes da carga", "Atualizar"])

    def test_action_column_click_opens_menu_and_double_click_opens_details(self):
        dialog = GalvanizationLoadManagerDialog(self.service)
        opened_menu = []
        opened_details = []
        dialog.open_actions_menu_for_row = lambda row: opened_menu.append(row)
        dialog.show_load_details = lambda load_id=None: opened_details.append(load_id or dialog.selected_load_id())

        dialog.handle_table_click(0, 0)
        dialog.open_load_details_from_row(1, 3)

        self.assertEqual(opened_menu, [0])
        self.assertEqual(opened_details, [2])

    def test_return_dialog_defaults_to_full_pending_balance_of_the_whole_load(self):
        dialog = GalvanizationReturnDialog(self.service, 2)

        # Sem nenhum ajuste manual, "carga completa" ja vem com o saldo
        # pendente integral pronto para retornar - nao existe mais um passo
        # de selecao por checkbox.
        with patch.object(QMessageBox, "information"):
            dialog._confirm()

        self.assertEqual(len(self.service.registered_returns), 1)
        _load_id, items, _observation = self.service.registered_returns[0]
        self.assertEqual(items, [{"detail_id": 2011, "quantidade_retornada": 100.0}])

    def test_editing_one_item_down_to_zero_excludes_it_from_the_payload(self):
        dialog = GalvanizationReturnDialog(self.service, 4)

        # Duas unidades pendentes do item 9001, mas so o item 9002 deve
        # retornar agora - equivalente ao antigo "selecionar so um item",
        # so que via edicao de quantidade (0 = nao retorna desta vez).
        dialog.cart[9001]["return_quantity"] = 0
        dialog.refresh()
        with patch.object(QMessageBox, "information"):
            dialog._confirm()

        _load_id, items, _observation = self.service.registered_returns[0]
        self.assertEqual(items, [{"detail_id": 9002, "quantidade_retornada": 1.0}])


class _MultiLoadGalvanizationLoadService(FakeGalvanizationLoadService):
    """Estende o fixture base com uma segunda carga (id 6) cujo item
    compartilha o codigo COD-A com a carga 4, para testar que "Itens do
    retorno" continua agrupando por codigo mesmo quando o retorno abrange
    mais de uma carga."""

    def __init__(self):
        super().__init__()
        self.proposals[6] = [
            {
                "processo_id": 601, "proposta": "CP00601", "cliente": "XPTO",
                "peso_enviado": 0, "peso_retornado": 0, "peso_pendente": 0,
            },
        ]
        self.return_items[(6, 601)] = [
            {
                "id": 9101,
                "processo_id": 601,
                "proposta": "CP00601",
                "cliente": "XPTO",
                "numero_item": "1",
                "codigo_produto": "COD-A",
                "descricao": "Item A",
                "quantidade_enviada": 3,
                "quantidade_retornada": 0,
                "quantidade_pendente": 3,
                "peso_pendente": 30,
                "status_retorno": "AGUARDANDO_RETORNO",
            },
        ]


class GalvanizationReturnDialogMultiLoadTests(unittest.TestCase):
    """O retorno pode abranger mais de uma carga ao mesmo tempo
    (`extra_load_ids`) - uma unica tela, com uma coluna "Carga" na tabela de
    propostas para diferenciar, "Itens do retorno" continua agrupando por
    codigo sem alteracao, e a confirmacao registra o retorno uma vez para
    cada carga envolvida (o endpoint continua sendo por carga)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cart_combines_both_loads_tagged_with_their_load_id(self):
        service = FakeGalvanizationLoadService()
        dialog = GalvanizationReturnDialog(service, 2, extra_load_ids=[4])
        self.assertEqual(dialog.load_ids, [2, 4])
        self.assertEqual({entry["load_id"] for entry in dialog.cart.values()}, {2, 4})
        self.assertEqual(dialog.cart[2011]["load_id"], 2)
        self.assertEqual(dialog.cart[9001]["load_id"], 4)
        self.assertEqual(dialog.cart[9002]["load_id"], 4)

    def test_proposals_table_has_a_carga_column_showing_the_right_load(self):
        service = FakeGalvanizationLoadService()
        dialog = GalvanizationReturnDialog(service, 2, extra_load_ids=[4])
        headers = [
            dialog.proposals_table.horizontalHeaderItem(i).text()
            for i in range(dialog.proposals_table.columnCount())
        ]
        self.assertIn("Carga", headers)
        carga_col = headers.index("Carga")
        proposta_col = headers.index("Proposta")
        rows = {
            dialog.proposals_table.item(row, proposta_col).text(): dialog.proposals_table.item(row, carga_col).text()
            for row in range(dialog.proposals_table.rowCount())
        }
        self.assertEqual(rows, {"CP00201": "#2", "CP00401": "#4"})

    def test_single_load_still_works_without_extra_load_ids(self):
        service = FakeGalvanizationLoadService()
        dialog = GalvanizationReturnDialog(service, 2)
        self.assertEqual(dialog.load_ids, [2])
        headers = [
            dialog.proposals_table.horizontalHeaderItem(i).text()
            for i in range(dialog.proposals_table.columnCount())
        ]
        self.assertIn("Carga", headers)

    def test_items_tab_still_groups_by_product_code_across_loads(self):
        service = _MultiLoadGalvanizationLoadService()
        dialog = GalvanizationReturnDialog(service, 4, extra_load_ids=[6])
        groups = dialog._grouped_items()
        coda_groups = [group for group in groups if group["code"] == "COD-A"]
        self.assertEqual(len(coda_groups), 1)
        self.assertEqual(set(coda_groups[0]["detail_ids"]), {9001, 9101})

    def test_confirm_registers_return_once_per_load_with_its_own_items(self):
        service = FakeGalvanizationLoadService()
        dialog = GalvanizationReturnDialog(service, 2, extra_load_ids=[4])
        with patch.object(QMessageBox, "information"):
            dialog._confirm()
        self.assertEqual(len(service.registered_returns), 2)
        by_load = {load_id: items for load_id, items, _observation in service.registered_returns}
        self.assertEqual(by_load[2], [{"detail_id": 2011, "quantidade_retornada": 100.0}])
        self.assertEqual(
            sorted(by_load[4], key=lambda item: item["detail_id"]),
            [
                {"detail_id": 9001, "quantidade_retornada": 2.0},
                {"detail_id": 9002, "quantidade_retornada": 1.0},
            ],
        )
        self.assertTrue(dialog.result())

    def test_partial_failure_keeps_successful_load_and_does_not_accept(self):
        service = FakeGalvanizationLoadService()
        original_register = service.register_galvanization_partial_return

        def flaky_register(load_id, items, observation):
            if load_id == 4:
                raise RuntimeError("carga fechada por outro usuario")
            return original_register(load_id, items, observation)

        service.register_galvanization_partial_return = flaky_register
        dialog = GalvanizationReturnDialog(service, 2, extra_load_ids=[4])
        with patch.object(QMessageBox, "critical") as critical:
            dialog._confirm()
        critical.assert_called_once()
        self.assertFalse(dialog.result())
        # A carga 2 (bem sucedida) ja foi gravada - nao e desfeita so porque
        # a carga 4 falhou depois, ja que cada carga e uma chamada
        # independente ao backend.
        self.assertEqual(len(service.registered_returns), 1)
        self.assertEqual(service.registered_returns[0][0], 2)


if __name__ == "__main__":
    unittest.main()
