from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.services.remanagement_flow_state import RemanagementFlowState
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent


class RemanagementDestinationStepDialog(QDialog):
    """Etapa 1 do novo fluxo de Remanejamento Compensado: escolhe somente a
    proposta destino ("quem precisa receber material pronto?"). A origem e os
    itens sao descobertos nas fases seguintes.

    Reaproveita `service.early_delivery_destination_candidates`, a mesma
    consulta/regra de elegibilidade ja usada pela tela legada
    (`EarlyRemanagementDeliveryDialog`) - esta fase nao cria nenhuma regra de
    negocio nova, apenas uma apresentacao mais simples do mesmo dado.
    """

    def __init__(
        self, service, parent=None, initial_destination_id: int | None = None,
        state: RemanagementFlowState | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.state = state if state is not None else RemanagementFlowState()
        if initial_destination_id is not None:
            self.state.destination_proposal_id = initial_destination_id
        self._candidates_by_id: dict[int, dict] = {}
        self.setWindowTitle("Remanejamento de materiais")
        self.setMinimumSize(640, 520)
        style_dialog_from_parent(self, parent)
        self._build()
        self._load_candidates()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("1. Proposta destino")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        caption = QLabel(
            "Escolha a proposta que recebera o material pronto. Depois de avancar, o sistema "
            "descobre automaticamente quais propostas podem fornecer esse material."
        )
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(caption)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar proposta, cliente ou obra/site...")
        self.search.textChanged.connect(self._load_candidates)
        root.addWidget(self.search)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Obra/Site", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.table, 1)

        self.summary = QFrame()
        self.summary.setObjectName("Card")
        summary_layout = QVBoxLayout(self.summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        self.summary_label = QLabel("Nenhuma proposta selecionada.")
        self.summary_label.setObjectName("Caption")
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        root.addWidget(self.summary)

        footer = QHBoxLayout()
        cancel = ModernButton("Cancelar", "clear")
        self.advance_button = ModernButton("Avancar para selecionar itens", "status", accent=True)
        self.advance_button.setEnabled(False)
        cancel.clicked.connect(self.reject)
        self.advance_button.clicked.connect(self._advance)
        footer.addStretch()
        footer.addWidget(cancel)
        footer.addWidget(self.advance_button)
        root.addLayout(footer)

    def _load_candidates(self):
        selected_id = self._selected_id()
        if selected_id is None:
            selected_id = self.state.destination_proposal_id
        try:
            rows = self.service.early_delivery_destination_candidates(self.search.text())
        except Exception as exc:
            QMessageBox.warning(self, "Remanejamento", str(exc))
            rows = []
        self._candidates_by_id = {int(row["id"]): row for row in rows}

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        restore_row = None
        for row_data in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                row_data.get("proposta"),
                row_data.get("cliente"),
                row_data.get("obra_site"),
                row_data.get("status_expedicao") or row_data.get("status_producao") or row_data.get("status_geral"),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setData(Qt.UserRole, int(row_data["id"]))
                self.table.setItem(row, col, cell)
            if selected_id is not None and int(row_data["id"]) == selected_id:
                restore_row = row
        self.table.blockSignals(False)

        if restore_row is not None:
            self.table.selectRow(restore_row)
        else:
            self._selection_changed()

    def _selected_id(self) -> int | None:
        model = self.table.selectionModel()
        rows = model.selectedRows() if model else []
        return int(self.table.item(rows[0].row(), 0).data(Qt.UserRole)) if rows else None

    def _selection_changed(self):
        selected_id = self._selected_id()
        data = self._candidates_by_id.get(selected_id) if selected_id is not None else None
        if data is None:
            # Nada visivel na tabela agora - pode ser filtro de busca escondendo a
            # linha, nao uma desselecao real. So limpa o destino do estado
            # compartilhado se nenhum jamais foi escolhido; caso contrario preserva
            # a selecao (e a de itens da Fase 2 que dependa dela) ate o usuario
            # escolher outra linha de fato.
            if self.state.destination_proposal_id is None:
                self.summary_label.setText("Nenhuma proposta selecionada.")
                self.advance_button.setEnabled(False)
            else:
                self.advance_button.setEnabled(True)
            return
        self.state.set_destination(selected_id, data.get("api_version"))
        status = data.get("status_expedicao") or data.get("status_producao") or data.get("status_geral") or "-"
        self.summary_label.setText(
            f"{data.get('proposta') or ''} - {data.get('cliente') or ''}\n"
            f"Obra/Site: {data.get('obra_site') or '-'}\n"
            f"Status atual: {status}"
        )
        self.advance_button.setEnabled(True)

    def _advance(self):
        selected_id = self.state.destination_proposal_id
        if selected_id is None:
            return
        try:
            candidates = self.service.early_delivery_destination_candidates("")
        except Exception as exc:
            QMessageBox.warning(self, "Remanejamento", str(exc))
            return
        if not any(int(row["id"]) == selected_id for row in candidates):
            QMessageBox.warning(
                self, "Remanejamento",
                "A proposta selecionada nao esta mais disponivel como destino. Escolha novamente.",
            )
            self._load_candidates()
            return
        self.accept()
