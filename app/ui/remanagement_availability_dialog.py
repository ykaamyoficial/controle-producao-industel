from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.remanagement_flow_state import RemanagementFlowState, availability_from_api
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.numeric_utils import format_decimal

COVERAGE_LABELS = {
    "SUFICIENTE": "Material disponivel suficiente",
    "PARCIAL": "Disponibilidade parcial",
    "SEM_DISPONIBILIDADE": "Nenhum material disponivel",
}


class RemanagementAvailabilityStepDialog(QDialog):
    """Etapa 3 do novo fluxo de Remanejamento Compensado: busca automatica,
    somente leitura, de material pronto compativel na Expedicao para os itens
    e quantidades escolhidos na Etapa 2.

    A busca inicia sozinha ao abrir a tela (nenhuma origem e pedida ao
    usuario) e delega toda a matematica de saldo e compatibilidade ao
    servico/API (`service.remanagement_availability`, que reaproveita
    `_item_allocation_balance`/`items_are_compatible` no backend) - esta
    classe apenas apresenta os grupos por item e o estado de cobertura.
    Nenhuma origem e escolhida e nenhuma escrita acontece aqui.
    """

    RESULT_BACK = 2

    def __init__(self, service, parent, state: RemanagementFlowState):
        super().__init__(parent)
        self.service = service
        self.state = state
        self.destination_summary: dict | None = None
        self._groups: list[dict] = []
        self.setWindowTitle("Remanejamento de materiais")
        self.setMinimumSize(960, 660)
        style_dialog_from_parent(self, parent)
        self._build()
        self.load_error = self._load_availability()
        self._render_groups()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("3. Materiais prontos encontrados na Expedicao")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        root.addWidget(title)

        self.destination_frame = QFrame()
        self.destination_frame.setObjectName("Card")
        destination_layout = QVBoxLayout(self.destination_frame)
        destination_layout.setContentsMargins(14, 12, 14, 12)
        self.destination_label = QLabel("Destino")
        self.destination_label.setWordWrap(True)
        destination_layout.addWidget(self.destination_label)
        root.addWidget(self.destination_frame)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(0, 0, 0, 0)
        self.groups_layout.setSpacing(10)
        self.groups_layout.addStretch()
        scroll.setWidget(self.groups_container)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        refresh = ModernButton("Atualizar", "status")
        back = ModernButton("Voltar", "clear")
        self.advance_button = ModernButton("Avancar para alocacao", "status", accent=True)
        self.advance_button.setEnabled(False)
        refresh.clicked.connect(self._refresh_clicked)
        back.clicked.connect(lambda: self.done(self.RESULT_BACK))
        self.advance_button.clicked.connect(self.accept)
        footer.addWidget(refresh)
        footer.addStretch()
        footer.addWidget(back)
        footer.addWidget(self.advance_button)
        root.addLayout(footer)

    def _load_availability(self) -> str | None:
        try:
            candidates = self.service.early_delivery_destination_candidates("")
        except Exception as exc:
            return str(exc)
        self.destination_summary = next(
            (row for row in candidates if int(row["id"]) == self.state.destination_proposal_id), None
        )
        if self.destination_summary is None:
            return "A proposta destino nao esta mais disponivel para remanejamento. Escolha o destino novamente."
        status = (
            self.destination_summary.get("status_expedicao")
            or self.destination_summary.get("status_producao")
            or self.destination_summary.get("status_geral") or "-"
        )
        self.destination_label.setText(
            f"Destino\n{self.destination_summary.get('proposta') or ''} - {self.destination_summary.get('cliente') or ''}\n"
            f"Obra/Site: {self.destination_summary.get('obra_site') or '-'} | Status: {status}"
        )
        if not self.state.item_selections:
            return "Nenhum item foi selecionado na etapa anterior. Volte e selecione ao menos um item."

        items_payload = [
            {"destination_item_id": selection.destination_item_id, "requested_quantity": selection.remanage_quantity}
            for selection in self.state.item_selections
        ]
        try:
            response = self.service.remanagement_availability(self.state.destination_proposal_id, items_payload)
        except Exception as exc:
            return str(exc)
        self._groups = response.get("items") or []
        self.state.set_availability(availability_from_api(self._groups))
        return None

    def _clear_groups(self):
        while self.groups_layout.count() > 1:
            item = self.groups_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_groups(self):
        self._clear_groups()
        any_candidate = False
        for group in self._groups:
            frame = self._build_group_frame(group)
            self.groups_layout.insertWidget(self.groups_layout.count() - 1, frame)
            if group.get("candidates"):
                any_candidate = True
        self.advance_button.setEnabled(bool(self._groups) and any_candidate)

    def _build_group_frame(self, group: dict) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        unit = group.get("unit") or ""
        requested = format_decimal(group.get("requested_quantity"))
        heading = QLabel(f"Produto {group.get('product_code') or ''} - {group.get('description') or ''}")
        heading.setStyleSheet("font-weight: 700;")
        heading.setWordWrap(True)
        subtitle = QLabel(f"Solicitado no destino: {requested} {unit}".strip())
        subtitle.setObjectName("Caption")
        layout.addWidget(heading)
        layout.addWidget(subtitle)

        candidates = group.get("candidates") or []
        if not candidates:
            empty = QLabel("Nenhum material pronto disponivel na Expedicao para este codigo.")
            empty.setObjectName("Caption")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            return frame

        table = QTableWidget(len(candidates), 5)
        table.setHorizontalHeaderLabels(["Proposta origem", "Cliente", "Obra/Site", "Disponivel", "Status"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.horizontalHeader().setStretchLastSection(True)
        for row, candidate in enumerate(candidates):
            values = [
                candidate.get("source_proposal_number"),
                candidate.get("client"),
                candidate.get("site"),
                f"{format_decimal(candidate.get('available_quantity'))} {candidate.get('unit') or ''}".strip(),
                candidate.get("operational_status"),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                table.setItem(row, col, cell)
        table.resizeRowsToContents()
        table.setMinimumHeight(min(28 * (len(candidates) + 1) + 12, 220))
        layout.addWidget(table)

        total_available = format_decimal(group.get("total_available"))
        coverage_label = COVERAGE_LABELS.get(group.get("coverage_status"), group.get("coverage_status") or "-")
        summary = QLabel(f"Disponivel encontrado: {total_available} {unit} | Cobertura: {coverage_label}".strip())
        summary.setStyleSheet("font-weight: 700;")
        layout.addWidget(summary)
        return frame

    def _refresh_clicked(self):
        error = self._load_availability()
        self._render_groups()
        if error:
            QMessageBox.warning(self, "Remanejamento", error)
