from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QAbstractItemView, QApplication

from app.ui.user_dialog import UserManagerDialog


class FakeUserService:
    def user_rows(self):
        return [
            {
                "id": 1,
                "nome": "Administrador",
                "login": "admin",
                "perfil_label": "Administrador",
                "areas_label": "Todas",
                "ativo_label": "Sim",
            },
            {
                "id": 2,
                "nome": "Operador",
                "login": "operador",
                "perfil_label": "Operador",
                "areas_label": "Producao",
                "ativo_label": "Sim",
            },
        ]


class UserManagerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_dialog(self):
        return UserManagerDialog(FakeUserService())

    def test_user_table_shows_only_main_columns_and_uses_row_selection(self):
        dialog = self.make_dialog()

        headers = [label for _key, label in dialog.model.columns]
        self.assertEqual(headers, ["ID", "Nome", "Login", "Perfil", "Ativo"])
        self.assertNotIn("Resumo de permissoes", headers)
        self.assertEqual(dialog.table.selectionBehavior(), QAbstractItemView.SelectRows)
        self.assertEqual(dialog.table.selectionMode(), QAbstractItemView.SingleSelection)
        self.assertEqual(dialog.table.editTriggers(), QAbstractItemView.NoEditTriggers)

    def test_edit_button_stays_disabled_until_user_is_selected(self):
        dialog = self.make_dialog()
        self.assertFalse(dialog.edit_btn.isEnabled())

        dialog.table.selectRow(0)
        self.assertTrue(dialog.edit_btn.isEnabled())

        dialog.table.clearSelection()
        self.assertFalse(dialog.edit_btn.isEnabled())

    def test_double_click_any_cell_opens_selected_user_editor(self):
        dialog = self.make_dialog()
        opened: list[int | None] = []

        class FakeEditor:
            def __init__(self, _service, user_id=None, _parent=None):
                opened.append(user_id)

            def exec(self):
                return False

        with patch("app.ui.user_dialog.UserEditorDialog", FakeEditor):
            dialog.table.selectRow(1)
            selected_id = dialog.selected_user_id()
            index = dialog.proxy.index(1, 2)
            dialog.table.doubleClicked.emit(index)

        self.assertEqual(opened, [selected_id])

    def test_edit_button_opens_selected_user_editor(self):
        dialog = self.make_dialog()
        opened: list[int | None] = []

        class FakeEditor:
            def __init__(self, _service, user_id=None, _parent=None):
                opened.append(user_id)

            def exec(self):
                return False

        with patch("app.ui.user_dialog.UserEditorDialog", FakeEditor):
            dialog.table.selectRow(0)
            selected_id = dialog.selected_user_id()
            dialog.edit_btn.click()

        self.assertEqual(opened, [selected_id])


if __name__ == "__main__":
    unittest.main()
