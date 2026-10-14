from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QWidget,
)

from app.ui.components.detail_widgets import clear_panel, kv_grid, make_panel
from app.ui.components.dialog_shell import info_notice
from app.ui.components.status_badge import area_badge
from app.ui.remanagement_wizard.base import WizardPage
from app.ui.styles import area_color
from app.ui.theme_tokens import active_tokens

COLUMN_PROPOSAL, COLUMN_CLIENT, COLUMN_SITE, COLUMN_STAGE, COLUMN_DEADLINE = range(5)
SUMMARY_WIDTH = 380

AREA_NAMES = {"PRODUCAO": "Produção", "GALVANIZACAO": "Galvanização"}


def stage_key(row: dict) -> str:
    """"PRODUCAO" / "GALVANIZACAO" da linha de proposta ("" quando nao vier)."""
    return str(row.get("localizacao_atual") or "").strip().upper().replace(" ", "_")


def stage_name(row: dict) -> str:
    return AREA_NAMES.get(stage_key(row), "")


class DestinationPage(WizardPage):
    """Passo 1: qual proposta vai RECEBER o material. So aparecem propostas
    que ainda estao em Producao ou Galvanizacao - quem ja chegou a Expedicao
    ou foi entregue nao precisa ser adiantada (regra em
    `service.early_delivery_destination_candidates`)."""

    step_name = "Proposta destino"
    instruction = "Escolha a proposta que vai receber o material pronto."
    next_label = "Escolher itens"

    def __init__(self, service, state, parent=None):
        super().__init__(service, state, parent)
        self._rows: list[dict] = []
        self._by_id: dict[int, dict] = {}
        self._selected_id: int | None = state.destination_proposal_id
        self._build()

    # -- construcao -----------------------------------------------------------

    def _build(self):
        self.rule_notice = info_notice(
            "Aparecem só propostas que ainda estão em Produção ou Galvanização. "
            "As que já estão na Expedição ou foram entregues não precisam receber material."
        )
        self.root.addWidget(self.rule_notice)

        body = QHBoxLayout()
        body.setSpacing(12)

        self.count_label = QLabel("")
        self.count_label.setObjectName("KeyLabel")
        self.list_panel, list_layout = make_panel("Propostas que podem receber material", right=self.count_label)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por proposta, cliente ou obra/site...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render_rows)
        list_layout.addWidget(self.search)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Obra/Site", "Etapa", "Prazo"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COLUMN_PROPOSAL, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_CLIENT, header.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMN_SITE, header.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMN_STAGE, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_DEADLINE, header.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self.is_valid() and self.advance_requested.emit())
        list_layout.addWidget(self.table, 1)
        body.addWidget(self.list_panel, 1)

        self.summary_panel, _summary_layout = make_panel("Proposta selecionada")
        self.summary_panel.setFixedWidth(SUMMARY_WIDTH)
        body.addWidget(self.summary_panel)
        self.root.addLayout(body, 1)
        self._render_summary()

    # -- dados ------------------------------------------------------------------

    def enter(self) -> None:
        self.clear_notice()
        self._load_candidates()
        self._render_rows()

    def _load_candidates(self) -> bool:
        try:
            self._rows = list(self.service.early_delivery_destination_candidates(""))
        except Exception as exc:
            self._rows = []
            self.show_error(str(exc))
            return False
        self._by_id = {int(row["id"]): row for row in self._rows}
        return True

    def _filtered_rows(self) -> list[dict]:
        needle = self.search.text().strip().upper()
        if not needle:
            return list(self._rows)
        return [
            row for row in self._rows
            if needle in str(row.get("proposta") or "").upper()
            or needle in str(row.get("cliente") or "").upper()
            or needle in str(row.get("obra_site") or "").upper()
        ]

    # -- apresentacao -----------------------------------------------------------

    def _stage_cell(self, row: dict) -> QWidget:
        name = stage_name(row) or str(row.get("status_localizacao") or "-")
        key = stage_key(row)
        palette = getattr(self.service, "palette", None) or active_tokens()
        try:
            color = area_color(key, palette)
        except KeyError:
            color = active_tokens()["accent"]
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.addWidget(area_badge(name, color), 0, Qt.AlignVCenter)
        layout.addStretch(1)
        return holder

    def _render_rows(self):
        rows = self._filtered_rows()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        selected_row = -1
        for data in rows:
            proposal_id = int(data["id"])
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, text in (
                (COLUMN_PROPOSAL, data.get("proposta")),
                (COLUMN_CLIENT, data.get("cliente")),
                (COLUMN_SITE, data.get("obra_site")),
                (COLUMN_DEADLINE, data.get("prazo_entrega")),
            ):
                cell = QTableWidgetItem(str(text or ""))
                cell.setData(Qt.UserRole, proposal_id)
                self.table.setItem(row, column, cell)
            stage_cell = QTableWidgetItem("")
            stage_cell.setData(Qt.UserRole, proposal_id)
            self.table.setItem(row, COLUMN_STAGE, stage_cell)
            self.table.setCellWidget(row, COLUMN_STAGE, self._stage_cell(data))
            if proposal_id == self._selected_id:
                selected_row = row
        self.table.blockSignals(False)
        total = len(self._rows)
        self.count_label.setText(f"{len(rows)} de {total}" if len(rows) != total else f"{total} proposta(s)")
        if selected_row >= 0:
            self.table.blockSignals(True)
            self.table.selectRow(selected_row)
            self.table.blockSignals(False)
        elif self._selected_id is not None and self._selected_id not in self._by_id:
            self._selected_id = None
        self._render_summary()
        self.validity_changed.emit()

    def _selection_changed(self):
        selected = self.table.selectedItems()
        self._selected_id = int(selected[0].data(Qt.UserRole)) if selected else None
        self._render_summary()
        self.validity_changed.emit()

    def _render_summary(self):
        clear_panel(self.summary_panel, keep=1)
        layout = self.summary_panel.layout()
        row = self._by_id.get(self._selected_id) if self._selected_id is not None else None
        if row is None:
            hint = QLabel("Selecione uma proposta na lista para ver os detalhes.")
            hint.setObjectName("KeyLabel")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            layout.addStretch(1)
            return
        title = QLabel(str(row.get("proposta") or ""))
        title.setObjectName("DetailTitle")
        layout.addWidget(title)
        layout.addLayout(kv_grid([
            ("Cliente", str(row.get("cliente") or "")),
            ("Obra/Site", str(row.get("obra_site") or "")),
            ("Etapa atual", stage_name(row) or str(row.get("status_localizacao") or "")),
            ("Prazo de entrega", str(row.get("prazo_entrega") or "")),
            ("Pedido de compra", str(row.get("pedido_compra") or "")),
        ], key_width=120))
        layout.addStretch(1)

    # -- contrato ---------------------------------------------------------------

    def is_valid(self) -> bool:
        return self._selected_id is not None and self._selected_id in self._by_id

    def summary(self) -> str:
        row = self._by_id.get(self._selected_id) if self._selected_id is not None else None
        if row is None:
            return "Nenhuma proposta selecionada."
        return f"Destino: {row.get('proposta') or ''} — {row.get('cliente') or ''}"

    def commit(self) -> bool:
        if not self.is_valid():
            return False
        # Revalida na hora de avancar: outra pessoa pode ter movido a proposta.
        if not self._load_candidates() or self._selected_id not in self._by_id:
            QMessageBox.warning(
                self, "Remanejamento",
                "A proposta escolhida não está mais disponível para receber material. Escolha outra.",
            )
            self._render_rows()
            return False
        row = self._by_id[self._selected_id]
        self.state.set_destination(self._selected_id, row.get("api_version"))
        return True

    def selected_row(self) -> dict | None:
        return self._by_id.get(self._selected_id) if self._selected_id is not None else None
