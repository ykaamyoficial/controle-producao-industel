from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QTableWidget, QTreeWidget, QVBoxLayout, QWidget

from app.ui.components.dialog_shell import (
    StepIndicator,
    dialog_footer,
    dialog_header,
    set_notice_kind,
    set_validation_state,
    standardize_tables,
)
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent


class DialogShellPartsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_header_accepts_text_or_existing_label_and_orders_actions(self):
        title = QLabel("Carregando...")
        edit = ModernButton("Editar", "edit")
        primary = ModernButton("Ações", "status", accent=True)
        close = ModernButton("Fechar", "clear", variant="ghost")
        header = dialog_header(title, "Subtítulo", status=[QLabel("selo")], actions=[edit, primary, close])

        self.assertEqual(header.objectName(), "DetailPanel")
        self.assertIs(header.title_label, title)
        self.assertEqual(title.objectName(), "DetailTitle")
        title.setText("CP 1 | Cliente")
        self.assertEqual(header.title_label.text(), "CP 1 | Cliente")
        self.assertEqual(header.subtitle_label.text(), "Subtítulo")
        buttons = [b.text() for b in header.findChildren(ModernButton)]
        self.assertEqual(buttons, ["Editar", "Ações", "Fechar"])

        plain = dialog_header("Só texto")
        self.assertIsNone(plain.subtitle_label)
        self.assertEqual(plain.title_label.text(), "Só texto")

    def test_footer_puts_left_items_first_and_buttons_in_given_order(self):
        step = StepIndicator(2, 5)
        summary = QLabel("3 item(ns) selecionado(s) com um texto bem longo que precisa quebrar linha")
        cancel = ModernButton("Cancelar", "clear", variant="ghost")
        confirm = ModernButton("Confirmar", "save", accent=True)
        footer = dialog_footer(left=[step, summary], right=[cancel, confirm])

        self.assertEqual(footer.objectName(), "DialogFooter")
        self.assertTrue(summary.wordWrap())
        layout = footer.layout()
        order = [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget()]
        self.assertEqual(order, [step, summary, cancel, confirm])
        footer.resize(900, footer.sizeHint().height())
        self.assertFalse(footer.grab().isNull())

    def test_step_indicator_text_and_bounds(self):
        self.assertEqual(StepIndicator(2, 5).text(), "Passo 2 de 5")
        # Passo acima do total nao quebra: o total acompanha.
        self.assertEqual(StepIndicator(7, 5).text(), "Passo 7 de 7")
        self.assertEqual(StepIndicator(0, 3).text(), "Passo 1 de 3")
        indicator = StepIndicator(3, 5)
        indicator.resize(indicator.sizeHint())
        self.assertFalse(indicator.grab().isNull())

    def test_notice_and_validation_helpers_set_properties_not_stylesheets(self):
        label = set_notice_kind(QLabel("Erro"), "danger")
        self.assertEqual(label.objectName(), "InlineNotice")
        self.assertEqual(label.property("kind"), "danger")
        self.assertEqual(label.styleSheet(), "")
        field = QWidget()
        set_validation_state(field, "error")
        self.assertEqual(field.property("validationState"), "error")
        set_validation_state(field, "")
        self.assertEqual(field.property("validationState"), "")
        self.assertEqual(field.styleSheet(), "")

    def test_standardize_tables_is_idempotent_and_keeps_model_and_columns(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        table = QTableWidget(2, 3)
        table.setHorizontalHeaderLabels(["A", "B", "C"])
        table.setColumnWidth(1, 222)
        table.verticalHeader().setDefaultSectionSize(20)
        tree = QTreeWidget()
        layout.addWidget(table)
        layout.addWidget(tree)

        standardize_tables(root)
        standardize_tables(root)

        self.assertFalse(table.showGrid())
        self.assertTrue(table.alternatingRowColors())
        self.assertEqual(table.verticalHeader().defaultSectionSize(), 40)
        self.assertEqual(table.columnWidth(1), 222)
        self.assertEqual(table.rowCount(), 2)
        self.assertTrue(table.horizontalHeader().defaultAlignment() & Qt.AlignLeft)
        # Linha ja maior que o padrao nao encolhe.
        tall = QTableWidget(1, 1)
        tall.verticalHeader().setDefaultSectionSize(64)
        layout.addWidget(tall)
        standardize_tables(root)
        self.assertEqual(tall.verticalHeader().defaultSectionSize(), 64)


class DialogShellWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_with_owner_becomes_frameless_and_standardizes_its_tables(self):
        owner = QWidget()
        owner.show()
        dialog = QDialog(owner)
        dialog.setModal(True)
        table = QTableWidget(1, 1)
        layout = QVBoxLayout(dialog)
        layout.addWidget(table)
        style_dialog_from_parent(dialog, owner)
        self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)
        dialog.show()
        self.app.processEvents()
        self.assertFalse(table.showGrid())
        self.assertGreaterEqual(table.verticalHeader().defaultSectionSize(), 40)
        dialog.reject()
        owner.close()

    def test_dialog_without_owner_keeps_its_native_title_bar(self):
        # Dialogo de inicializacao (sem janela principal): a barra nativa e a
        # unica forma garantida de fechar a janela.
        dialog = QDialog()
        style_dialog_from_parent(dialog, None)
        self.assertFalse(dialog.windowFlags() & Qt.FramelessWindowHint)
        dialog.close()

    def test_installing_twice_is_harmless(self):
        owner = QWidget()
        owner.show()
        dialog = QDialog(owner)
        QHBoxLayout(dialog)
        style_dialog_from_parent(dialog, owner)
        controller = dialog._dialog_shell_controller
        style_dialog_from_parent(dialog, owner)
        self.assertIs(dialog._dialog_shell_controller, controller)
        owner.close()


if __name__ == "__main__":
    unittest.main()
