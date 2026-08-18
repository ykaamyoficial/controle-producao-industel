from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent


class PlannedLoadBuildSummaryDialog(QDialog):
    """Resumo exibido quando `POST /planned-loads/{id}/build` volta com
    `fully_available=False` (FASE_PL7) -- mostra planejado/disponivel/faltante
    e a lista de itens pendentes, com duas opcoes:

    - "Aguardar" (`reject()`): fecha sem fazer nada, o usuario decide montar
      a carga depois.
    - "Montar carga parcial com o disponivel" (`accept()`): so habilitado
      quando ha ao menos um item pronto (`ready_items` nao vazio) -- segue
      para `GalvanizationLoadDialog` pre-preenchido so com os itens prontos.

    `PlannedLoadDialog._handle_build_result` decide o que fazer a partir do
    `result()` deste dialogo; este dialogo em si nao chama nenhum endpoint."""

    def __init__(self, build_result: dict[str, Any], parent=None):
        super().__init__(parent)
        self.build_result = build_result or {}
        self.setWindowTitle("Montar carga - disponibilidade parcial")
        apply_large_dialog_geometry(self, parent, minimum_width=560, minimum_height=420)
        style_dialog_from_parent(self, parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        planned = self.build_result.get("total_planned_quantity", 0)
        available = self.build_result.get("total_available_quantity", 0)
        missing = self.build_result.get("total_missing_quantity", 0)
        summary_label = QLabel(f"Planejado: {planned} | Disponivel: {available} | Faltante: {missing}")
        summary_label.setObjectName("FieldLabel")
        root.addWidget(summary_label)

        hint = QLabel(
            "Nem todos os itens deste planejamento estao disponiveis agora. "
            "Voce pode aguardar o material ficar disponivel ou montar a carga "
            "so com o que ja esta disponivel hoje."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Caption")
        root.addWidget(hint)

        pending_items = list(self.build_result.get("pending_items") or [])
        root.addWidget(QLabel("Itens pendentes"))
        self.pending_table = QTableWidget(0, 4)
        self.pending_table.setHorizontalHeaderLabels(["Item", "Descricao", "Planejado", "Faltante"])
        self.pending_table.verticalHeader().setVisible(False)
        self.pending_table.setSelectionMode(QTableWidget.NoSelection)
        self.pending_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.pending_table.setAlternatingRowColors(True)
        self.pending_table.horizontalHeader().setStretchLastSection(True)
        self.pending_table.setRowCount(len(pending_items))
        for row, entry in enumerate(pending_items):
            values = [
                entry.get("item_number", ""),
                entry.get("description", ""),
                entry.get("planned_quantity", ""),
                entry.get("missing_quantity", ""),
            ]
            for column, value in enumerate(values):
                self.pending_table.setItem(row, column, QTableWidgetItem(str(value)))
        root.addWidget(self.pending_table, 1)

        footer = QHBoxLayout()
        self.wait_button = QPushButton("Aguardar")
        self.wait_button.clicked.connect(self.reject)
        self.build_partial_button = QPushButton("Montar carga parcial com o disponivel")
        self.build_partial_button.clicked.connect(self.accept)
        ready_items = list(self.build_result.get("ready_items") or [])
        self.build_partial_button.setEnabled(bool(ready_items))
        footer.addStretch()
        footer.addWidget(self.wait_button)
        footer.addWidget(self.build_partial_button)
        root.addLayout(footer)
