from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.remanagement_allocation import AllocationCandidate, suggest_allocation
from app.services.remanagement_flow_state import (
    RemanagementFlowState, RemanagementItemAllocation, RemanagementSourceAllocation, availability_from_api,
)
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.numeric_utils import format_decimal, parse_decimal

COLUMN_SOURCE, COLUMN_CLIENT, COLUMN_AVAILABLE, COLUMN_TAKE = range(4)
INVALID_COLOR = QColor("#c0392b")


class RemanagementAllocationStepDialog(QDialog):
    """Etapa 4 do novo fluxo de Remanejamento Compensado: para cada item do
    destino, o usuario decide quanto retirar de cada origem encontrada pela
    Etapa 3 - uma unica origem ou varias, com sugestao automatica opcional.

    Nao busca origens por conta propria (reaproveita `state.availability`,
    o mesmo resultado oficial da Etapa 3) e nao calcula nenhuma regra de
    compensacao aqui - apenas registra a intencao do usuario em
    `RemanagementFlowState.allocations`. Nenhuma escrita no banco.
    """

    RESULT_BACK = 2

    def __init__(self, service, parent, state: RemanagementFlowState):
        super().__init__(parent)
        self.service = service
        self.state = state
        self.destination_summary: dict | None = None
        self.load_error: str | None = None
        # {destination_item_id: {(source_proposal_id, source_item_id): Decimal}}
        self._allocations: dict[int, dict[tuple[int, int], Decimal]] = {
            item.destination_item_id: {
                (row.source_proposal_id, row.source_item_id): row.allocated_quantity for row in item.allocations
            }
            for item in state.allocations
        }
        self._group_by_item: dict[int, object] = {}
        self._candidate_lookup: dict[tuple[int, tuple[int, int]], object] = {}
        self._tables: dict[int, QTableWidget] = {}
        self._indicator_labels: dict[int, QLabel] = {}
        self.setWindowTitle("Remanejamento de materiais")
        self.setMinimumSize(1000, 700)
        style_dialog_from_parent(self, parent)
        self._build()
        self.load_error = self._load_from_state()
        if self.load_error is None:
            self._render_groups()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("4. Defina de onde retirar os materiais")
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

        self.summary_label = QLabel("0 produto(s)")
        self.summary_label.setStyleSheet("font-weight: 700;")
        root.addWidget(self.summary_label)

        footer = QHBoxLayout()
        refresh = ModernButton("Atualizar disponibilidade", "status")
        clear_all = ModernButton("Limpar alocacoes", "clear")
        back = ModernButton("Voltar", "clear")
        self.advance_button = ModernButton("Avancar para compensacao", "status", accent=True)
        self.advance_button.setEnabled(False)
        refresh.clicked.connect(self._refresh_clicked)
        clear_all.clicked.connect(self._clear_all)
        back.clicked.connect(lambda: self.done(self.RESULT_BACK))
        self.advance_button.clicked.connect(self._advance)
        footer.addWidget(refresh)
        footer.addWidget(clear_all)
        footer.addStretch()
        footer.addWidget(back)
        footer.addWidget(self.advance_button)
        root.addLayout(footer)

    # -- carregamento / revalidacao ------------------------------------------------

    def _load_from_state(self) -> str | None:
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
        if not self.state.availability:
            return "Nenhuma disponibilidade foi encontrada na etapa anterior. Volte e refaca a busca."
        self._index_availability()
        return None

    def _index_availability(self):
        self._group_by_item = {group.destination_item_id: group for group in self.state.availability}
        self._candidate_lookup = {
            (group.destination_item_id, (candidate.source_proposal_id, candidate.source_item_id)): candidate
            for group in self.state.availability
            for candidate in group.candidates
        }
        # Um item que deixou de existir na disponibilidade atual nao pode
        # manter uma alocacao orfa.
        self._allocations = {
            item_id: allocations for item_id, allocations in self._allocations.items() if item_id in self._group_by_item
        }

    def _refresh_clicked(self):
        if not self.state.item_selections:
            QMessageBox.warning(self, "Remanejamento", "Nenhum item selecionado para atualizar.")
            return
        items_payload = [
            {"destination_item_id": selection.destination_item_id, "requested_quantity": selection.remanage_quantity}
            for selection in self.state.item_selections
        ]
        try:
            response = self.service.remanagement_availability(self.state.destination_proposal_id, items_payload)
        except Exception as exc:
            QMessageBox.warning(self, "Remanejamento", str(exc))
            return
        self.state.set_availability(availability_from_api(response.get("items") or []))
        self._index_availability()
        self._render_groups()

    # -- construcao visual ----------------------------------------------------------

    def _clear_groups(self):
        while self.groups_layout.count() > 1:
            item = self.groups_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_groups(self):
        self._clear_groups()
        self._tables = {}
        self._indicator_labels = {}
        for group in self.state.availability:
            frame = self._build_group_frame(group)
            self.groups_layout.insertWidget(self.groups_layout.count() - 1, frame)
            self._update_indicator(group.destination_item_id)
        self._update_summary()

    def _rows_for_group(self, group) -> list[tuple[tuple[int, int], object | None]]:
        rows = []
        seen = set()
        for candidate in group.candidates:
            key = (candidate.source_proposal_id, candidate.source_item_id)
            rows.append((key, candidate))
            seen.add(key)
        for key in self._allocations.get(group.destination_item_id, {}):
            if key not in seen:
                rows.append((key, None))
        return rows

    def _build_group_frame(self, group) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        heading = QLabel(f"Produto {group.product_code} - {group.description}")
        heading.setStyleSheet("font-weight: 700;")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        indicator = QLabel()
        indicator.setObjectName("Caption")
        layout.addWidget(indicator)
        self._indicator_labels[group.destination_item_id] = indicator

        rows = self._rows_for_group(group)
        if not rows:
            empty = QLabel("Nenhum candidato disponivel para este produto.")
            empty.setObjectName("Caption")
            layout.addWidget(empty)
            return frame

        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(["Origem", "Cliente", "Disponivel", "Retirar"])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.horizontalHeader().setStretchLastSection(True)
        table.blockSignals(True)
        allocations = self._allocations.get(group.destination_item_id, {})
        for row, (key, candidate) in enumerate(rows):
            allocated = allocations.get(key, Decimal("0"))
            available = candidate.available_quantity if candidate is not None else Decimal("0")
            invalid = candidate is None or allocated > available

            source_cell = QTableWidgetItem(candidate.source_proposal_number if candidate else f"#{key[1]} (indisponivel)")
            source_cell.setFlags(source_cell.flags() & ~Qt.ItemIsEditable)
            source_cell.setData(Qt.UserRole, key)
            table.setItem(row, COLUMN_SOURCE, source_cell)

            client_cell = QTableWidgetItem(candidate.client if candidate else "-")
            client_cell.setFlags(client_cell.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, COLUMN_CLIENT, client_cell)

            unit = (candidate.unit if candidate else group.unit) or ""
            available_cell = QTableWidgetItem(f"{format_decimal(available)} {unit}".strip())
            available_cell.setFlags(available_cell.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, COLUMN_AVAILABLE, available_cell)

            take_cell = QTableWidgetItem(format_decimal(allocated))
            table.setItem(row, COLUMN_TAKE, take_cell)

            if invalid:
                tooltip = "A disponibilidade desta origem mudou desde que a quantidade foi informada. Corrija ou atualize a disponibilidade."
                for cell in (source_cell, client_cell, available_cell, take_cell):
                    cell.setForeground(INVALID_COLOR)
                    cell.setToolTip(tooltip)
        table.blockSignals(False)
        table.itemChanged.connect(lambda cell, item_id=group.destination_item_id: self._on_take_changed(item_id, cell))
        table.resizeRowsToContents()
        table.setMinimumHeight(min(28 * (len(rows) + 1) + 12, 220))
        layout.addWidget(table)
        self._tables[group.destination_item_id] = table

        buttons = QHBoxLayout()
        suggest = ModernButton("Sugerir melhor remanejamento", "status")
        suggest.clicked.connect(lambda: self._suggest_item(group.destination_item_id))
        clear_item = ModernButton("Limpar este item", "clear")
        clear_item.clicked.connect(lambda: self._clear_item(group.destination_item_id))
        buttons.addWidget(suggest)
        buttons.addWidget(clear_item)
        buttons.addStretch()
        layout.addLayout(buttons)
        return frame

    # -- edicao manual ----------------------------------------------------------

    def _on_take_changed(self, destination_item_id: int, cell: QTableWidgetItem):
        if cell.column() != COLUMN_TAKE:
            return
        table = self._tables[destination_item_id]
        key = table.item(cell.row(), COLUMN_SOURCE).data(Qt.UserRole)
        candidate = self._candidate_lookup.get((destination_item_id, key))
        group = self._group_by_item[destination_item_id]
        allocations = self._allocations.setdefault(destination_item_id, {})

        entered = parse_decimal(cell.text(), "-1")
        available = candidate.available_quantity if candidate is not None else Decimal("0")
        other_total = sum((qty for existing_key, qty in allocations.items() if existing_key != key), Decimal("0"))
        max_additional = max(group.requested_quantity - other_total, Decimal("0"))
        clamped = min(max(entered, Decimal("0")), available, max_additional) if entered >= 0 else Decimal("0")

        if clamped > 0:
            allocations[key] = clamped
        else:
            allocations.pop(key, None)

        table.blockSignals(True)
        if format_decimal(clamped) != cell.text():
            cell.setText(format_decimal(clamped))
        # Uma edicao manual bem-sucedida sempre produz um valor dentro dos
        # limites atuais (o clamp acima garante isso), entao esta linha nunca
        # fica invalida por causa dela - remove qualquer destaque de erro
        # herdado de uma disponibilidade desatualizada.
        row = cell.row()
        for col in (COLUMN_SOURCE, COLUMN_CLIENT, COLUMN_AVAILABLE, COLUMN_TAKE):
            row_cell = table.item(row, col)
            if row_cell is not None:
                row_cell.setForeground(QBrush())
                row_cell.setToolTip("")
        table.blockSignals(False)
        self._update_indicator(destination_item_id)
        self._update_summary()

    # -- acoes por item / globais ------------------------------------------------

    def _suggest_item(self, destination_item_id: int):
        group = self._group_by_item[destination_item_id]
        candidates = [
            AllocationCandidate(source_proposal_id=c.source_proposal_id, source_item_id=c.source_item_id, available_quantity=c.available_quantity)
            for c in group.candidates
        ]
        suggestions, _remaining = suggest_allocation(group.requested_quantity, candidates)
        self._allocations[destination_item_id] = {
            (row.source_proposal_id, row.source_item_id): row.allocated_quantity for row in suggestions
        }
        self._render_groups()

    def _clear_item(self, destination_item_id: int):
        self._allocations.pop(destination_item_id, None)
        self._render_groups()

    def _clear_all(self):
        self._allocations.clear()
        self._render_groups()

    # -- indicadores / validade ------------------------------------------------

    def _item_has_invalid_row(self, destination_item_id: int) -> bool:
        for key, qty in self._allocations.get(destination_item_id, {}).items():
            candidate = self._candidate_lookup.get((destination_item_id, key))
            if candidate is None or qty > candidate.available_quantity:
                return True
        return False

    def _update_indicator(self, destination_item_id: int):
        group = self._group_by_item[destination_item_id]
        allocated = sum(self._allocations.get(destination_item_id, {}).values(), Decimal("0"))
        remaining = max(group.requested_quantity - allocated, Decimal("0"))
        if self._item_has_invalid_row(destination_item_id):
            status = "INVALIDO"
        elif allocated <= 0:
            status = "NAO ALOCADO"
        elif allocated >= group.requested_quantity:
            status = "COMPLETO"
        else:
            status = "PARCIAL"
        unit = group.unit or ""
        label = self._indicator_labels.get(destination_item_id)
        if label is not None:
            label.setText(
                f"Solicitado: {format_decimal(group.requested_quantity)} {unit} | "
                f"Alocado: {format_decimal(allocated)} {unit} | "
                f"Restante: {format_decimal(remaining)} {unit} | Status: {status}"
            )

    def _update_summary(self):
        groups = self.state.availability
        total_requested = sum((group.requested_quantity for group in groups), Decimal("0"))
        total_allocated = Decimal("0")
        units = set()
        any_allocated = False
        any_invalid = False
        for group in groups:
            allocated = sum(self._allocations.get(group.destination_item_id, {}).values(), Decimal("0"))
            total_allocated += allocated
            if allocated > 0:
                any_allocated = True
            if self._item_has_invalid_row(group.destination_item_id):
                any_invalid = True
            units.add((group.unit or "").strip().upper())
        count = len(groups)
        if len(units) == 1:
            unit_label = next(iter(units))
            self.summary_label.setText(
                f"{count} produto(s) | {format_decimal(total_requested)} {unit_label} solicitadas | "
                f"{format_decimal(total_allocated)} {unit_label} alocadas"
            )
        else:
            self.summary_label.setText(f"{count} produto(s) selecionados")
        self.advance_button.setEnabled(any_allocated and not any_invalid)

    # -- avancar ----------------------------------------------------------------

    def _advance(self):
        if any(self._item_has_invalid_row(item_id) for item_id in self._group_by_item):
            QMessageBox.warning(
                self, "Remanejamento",
                "Existem alocacoes que nao correspondem mais a disponibilidade atual. Corrija ou atualize a disponibilidade antes de avancar.",
            )
            return
        item_allocations = []
        for group in self.state.availability:
            allocations = self._allocations.get(group.destination_item_id, {})
            if not allocations:
                continue
            item_allocations.append(RemanagementItemAllocation(
                destination_item_id=group.destination_item_id,
                product_code=group.product_code,
                unit=group.unit,
                requested_quantity=group.requested_quantity,
                allocations=[
                    RemanagementSourceAllocation(
                        source_proposal_id=key[0],
                        source_item_id=key[1],
                        available_snapshot=self._candidate_lookup[(group.destination_item_id, key)].available_quantity,
                        allocated_quantity=qty,
                    )
                    for key, qty in allocations.items()
                ],
            ))
        if not item_allocations:
            QMessageBox.warning(self, "Remanejamento", "Aloque pelo menos uma origem para avancar.")
            return
        self.state.set_allocations(item_allocations)
        self.accept()
