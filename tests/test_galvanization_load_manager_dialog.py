from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.galvanization_load_dialog import GalvanizationLoadDetailsDialog, GalvanizationLoadManagerDialog


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
            2: [],
            3: [],
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


class GalvanizationLoadManagerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = FakeGalvanizationLoadService()

    def test_main_table_is_load_only_with_action_column(self):
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

    def test_details_dialog_has_tabs_proposals_and_consolidated_items(self):
        dialog = GalvanizationLoadDetailsDialog(self.service, 1)
        tabs = dialog.findChild(QTabWidget)

        self.assertEqual([tabs.tabText(index) for index in range(tabs.count())], ["Resumo", "Propostas", "Itens da carga"])
        self.assertEqual(dialog.proposals_table.rowCount(), 2)
        self.assertEqual(dialog.proposal_items_table.rowCount(), 2)
        dialog.proposals_table.selectRow(1)
        dialog._fill_selected_proposal_items()
        self.assertEqual(dialog.proposal_items_table.rowCount(), 1)
        self.assertEqual(dialog.all_items_table.rowCount(), 3)


if __name__ == "__main__":
    unittest.main()
