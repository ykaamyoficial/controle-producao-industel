from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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

from app.services.app_logging import get_logger
from app.services.backend_adapter import VersionConflictError
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.table_utils import configure_wrapping_table, resize_rows_to_contents

log = get_logger("item_flow_dialog")


FLOW_OPTIONS = (
    ("indefinido", "Indefinido"),
    ("sim", "Sim"),
    ("nao", "Nao"),
)


class ItemFlowDialog(QDialog):
    """Define the operational route of proposal items before production advances."""

    def __init__(self, service, process_id: int, parent=None, origin: str = "Producao"):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.origin = origin
        self.items = service.proposal_items(process_id)
        log.debug(
            "Abrindo fluxo: process_id=%r versoes_itens=%r",
            process_id,
            {item.get("id"): item.get("api_version") for item in self.items},
        )
        self.reason_options = [("", "-")] + service.item_no_production_reasons()
        self.setWindowTitle("Definir fluxo dos itens")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        title = QLabel("Definir fluxo dos itens")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        caption = QLabel(
            "Informe se cada item sera produzido internamente e se precisa passar pela galvanizacao."
        )
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(caption)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Item", "Codigo", "Descricao", "Qtd.", "Produzir", "Motivo", "Galvanizar", "Obs. fluxo"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        configure_wrapping_table(self.table, description_columns=(2,), code_columns=(1,), min_row_height=46)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        root.addWidget(self.table, 1)
        self._load_items()

        footer = QHBoxLayout()
        footer.addStretch()
        cancel = ModernButton("Cancelar", "clear")
        save = ModernButton("Salvar fluxo", "status", accent=True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

    def _flow_combo(self, value: str) -> QComboBox:
        combo = QComboBox()
        for data, label in FLOW_OPTIONS:
            combo.addItem(label, data)
        idx = combo.findData(value or "indefinido")
        combo.setCurrentIndex(max(0, idx))
        return combo

    def _reason_combo(self, value: str) -> QComboBox:
        combo = QComboBox()
        for data, label in self.reason_options:
            combo.addItem(label, data)
        idx = combo.findData(value or "")
        combo.setCurrentIndex(max(0, idx))
        return combo

    def _load_items(self):
        self.table.setRowCount(0)
        for item in self.items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            id_cell = QTableWidgetItem(str(item.get("numero_item") or row + 1))
            id_cell.setData(Qt.UserRole, int(item["id"]))
            id_cell.setData(Qt.UserRole + 1, int(item.get("api_version") or item.get("version") or 0) or None)
            self.table.setItem(row, 0, id_cell)
            code = QTableWidgetItem(str(item.get("codigo_produto") or item.get("product_code") or "-"))
            code.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, code)
            desc = QTableWidgetItem(str(item.get("descricao") or ""))
            desc.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
            self.table.setItem(row, 2, desc)
            quantity = QTableWidgetItem(str(item.get("quantidade") or 1))
            quantity.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, quantity)
            self.table.setCellWidget(row, 4, self._flow_combo(str(item.get("produzir_internamente") or "indefinido")))
            self.table.setCellWidget(row, 5, self._reason_combo(str(item.get("motivo_nao_produzir") or "")))
            self.table.setCellWidget(row, 6, self._flow_combo(str(item.get("precisa_galvanizacao") or "indefinido")))
            note = QLineEdit(str(item.get("observacao_fluxo_item") or ""))
            note.setPlaceholderText("Opcional")
            self.table.setCellWidget(row, 7, note)
        resize_rows_to_contents(self.table)

    def definitions(self) -> list[dict]:
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            produce = self.table.cellWidget(row, 4)
            reason = self.table.cellWidget(row, 5)
            galvanize = self.table.cellWidget(row, 6)
            note = self.table.cellWidget(row, 7)
            result.append(
                {
                    "id": int(item.data(Qt.UserRole)),
                    "api_version": item.data(Qt.UserRole + 1),
                    "produzir_internamente": produce.currentData() if isinstance(produce, QComboBox) else "indefinido",
                    "motivo_nao_produzir": reason.currentData() if isinstance(reason, QComboBox) else "",
                    "precisa_galvanizacao": galvanize.currentData() if isinstance(galvanize, QComboBox) else "indefinido",
                    "observacao_fluxo_item": note.text().strip() if isinstance(note, QLineEdit) else "",
                }
            )
        return result

    def save(self):
        definitions = self.definitions()
        log.debug(
            "Salvando fluxo: process_id=%r versoes_itens_enviadas=%r itens=%d",
            self.process_id,
            {definition["id"]: definition.get("api_version") for definition in definitions},
            len(definitions),
        )
        try:
            changed = self.service.update_item_flow(self.process_id, definitions, self.origin)
            if changed:
                QMessageBox.information(self, "Fluxo dos itens", f"{changed} item(ns) atualizado(s).")
            else:
                QMessageBox.information(self, "Fluxo dos itens", "Nenhuma alteracao para salvar.")
            self.accept()
        except VersionConflictError:
            self._handle_version_conflict(definitions)
        except Exception as exc:
            QMessageBox.warning(self, "Fluxo dos itens", str(exc))

    def _handle_version_conflict(self, pending_definitions: list[dict]) -> None:
        answer = QMessageBox.question(
            self,
            "Fluxo dos itens",
            "Os dados desta proposta foram atualizados desde que esta janela foi aberta.\n\n"
            "Deseja recarregar os dados mais recentes?\n"
            "As alteracoes ainda nao salvas serao revisadas antes de continuar.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        previous_by_id = {item.get("id"): item for item in self.items}
        pending_by_id = {definition["id"]: definition for definition in pending_definitions}
        self.items = self.service.proposal_items(self.process_id)
        log.debug(
            "Fluxo recarregado apos conflito: process_id=%r versoes_itens=%r",
            self.process_id,
            {item.get("id"): item.get("api_version") for item in self.items},
        )
        conflicted_fields = ("produzir_internamente", "motivo_nao_produzir", "precisa_galvanizacao", "observacao_fluxo_item")
        conflicted_items = []
        for item in self.items:
            item_id = item.get("id")
            previous = previous_by_id.get(item_id)
            pending = pending_by_id.get(item_id)
            if previous is None or pending is None:
                continue
            server_changed = any(str(item.get(field) or "") != str(previous.get(field) or "") for field in conflicted_fields)
            if server_changed:
                conflicted_items.append(item.get("numero_item") or item_id)
                continue
            item["produzir_internamente"] = pending.get("produzir_internamente")
            item["motivo_nao_produzir"] = pending.get("motivo_nao_produzir")
            item["precisa_galvanizacao"] = pending.get("precisa_galvanizacao")
            item["observacao_fluxo_item"] = pending.get("observacao_fluxo_item")
        self._load_items()
        if conflicted_items:
            QMessageBox.information(
                self,
                "Fluxo dos itens",
                "Os seguintes itens foram alterados no servidor e mantiveram o valor atualizado, "
                "revise-os antes de salvar novamente: " + ", ".join(str(value) for value in conflicted_items),
            )
