from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents


class ItemWeightDialog(QDialog):
    def __init__(self, service, process_id: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.items = service.proposal_items(process_id)
        self.weight_fields: dict[int, QLineEdit] = {}
        self.saved_count = 0
        self.setWindowTitle("Informar pesos dos itens")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        process = self.service.get_process_dict(self.process_id)
        title = QLabel(f"{process.get('proposta') or '-'} | {process.get('cliente') or '-'}")
        title.setStyleSheet("font-size: 19px; font-weight: 800;")
        subtitle = QLabel("Informe o peso unitario dos itens. Descricao e quantidade permanecem inalteradas.")
        subtitle.setObjectName("Caption")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Item", "Codigo", "Descricao", "Quantidade", "Peso atual (kg)", "Novo peso (kg)"])
        configure_wrapping_table(
            self.table,
            description_columns=(2,),
            code_columns=(1,),
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setRowCount(len(self.items))
        validator = QRegularExpressionValidator(QRegularExpression(r"^\d*(?:[\.,]\d*)?$"), self)
        for row, item in enumerate(self.items):
            values = [
                item.get("numero_item") or "-",
                item_product_code(item),
                item.get("descricao") or "-",
                item.get("quantidade") or 1,
                f"{float(item.get('peso') or 0):g}",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                cell.setTextAlignment(Qt.AlignTop | Qt.AlignLeft if column == 2 else Qt.AlignCenter)
                self.table.setItem(row, column, cell)
            field = QLineEdit()
            field.setValidator(validator)
            current = float(item.get("peso") or 0)
            field.setText(f"{current:g}" if current else "")
            field.setPlaceholderText("0,00")
            field.setAlignment(Qt.AlignRight)
            self.table.setCellWidget(row, 5, field)
            self.weight_fields[int(item["id"])] = field
        resize_rows_to_contents(self.table)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel = ModernButton("Cancelar", "clear")
        save = ModernButton("Salvar pesos", "save", accent=True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

    @staticmethod
    def parse_weight(text: str) -> float | None:
        clean = (text or "").strip()
        if not clean:
            return None
        try:
            value = float(clean.replace(",", "."))
        except ValueError as exc:
            raise ValueError("Informe um peso numerico valido.") from exc
        if value < 0:
            raise ValueError("O peso nao pode ser negativo.")
        return value

    def changed_weights(self) -> dict[int, float]:
        originals = {int(item["id"]): float(item.get("peso") or 0) for item in self.items}
        changed = {}
        for item_id, field in self.weight_fields.items():
            value = self.parse_weight(field.text())
            if value is not None and abs(value - originals[item_id]) > 0.000001:
                changed[item_id] = value
        return changed

    def save(self):
        try:
            changed = self.changed_weights()
            if not changed:
                QMessageBox.information(self, "Pesos dos itens", "Nenhum peso foi alterado.")
                return
            self.saved_count = self.service.update_item_weights(self.process_id, changed)
        except Exception as exc:
            QMessageBox.warning(self, "Pesos dos itens", str(exc))
            return
        QMessageBox.information(self, "Pesos dos itens", f"Pesos atualizados em {self.saved_count} item(ns).")
        self.accept()
