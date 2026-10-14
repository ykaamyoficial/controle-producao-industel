from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.services.remanagement_allocation import AllocationCandidate, suggest_allocation
from app.services.remanagement_flow_state import (
    RemanagementItemAllocation, RemanagementItemAvailability, RemanagementSourceAllocation,
    RemanagementSourceCandidate, availability_from_api,
)
from app.ui.components.detail_widgets import ThinProgressBar, make_panel
from app.ui.components.modern_button import ModernButton
from app.ui.numeric_utils import format_decimal, parse_decimal
from app.ui.remanagement_wizard.base import WizardPage
from app.ui.remanagement_wizard.widgets import coverage_badge, coverage_kind, mark_editable, quantity_text, set_coverage_badge

SOURCE_COLUMN_NUMBER, SOURCE_COLUMN_CLIENT, SOURCE_COLUMN_COVERS, SOURCE_COLUMN_TAKING = range(4)
ITEM_COLUMN_CODE, ITEM_COLUMN_DESCRIPTION, ITEM_COLUMN_REQUESTED, ITEM_COLUMN_AVAILABLE, ITEM_COLUMN_TAKE = range(5)
SOURCES_WIDTH = 410
COVERAGE_WIDTH = 330

Key = tuple[int, int]  # (source_proposal_id, source_item_id)


@dataclass
class SourceProposal:
    """Uma proposta da Expedicao com material pronto para algum item pedido."""

    proposal_id: int
    number: str
    client: str
    site: str
    status: str
    # item do destino -> candidatos desta proposta para ele (normalmente 1).
    candidates: dict[int, list[RemanagementSourceCandidate]] = field(default_factory=dict)

    @property
    def covered_items(self) -> int:
        return len(self.candidates)

    def total_available(self) -> Decimal:
        return sum((c.available_quantity for rows in self.candidates.values() for c in rows), Decimal("0"))


class SourcesPage(WizardPage):
    """Passo 3: de qual proposta vai sair o material. Depois que os itens sao
    escolhidos o sistema procura, na Expedicao, o que ja esta pronto e pode
    atender cada item; aqui o usuario ESCOLHE a proposta de origem e quanto
    retirar de cada uma, vendo ao lado quanto do pedido ja esta coberto.

    A busca e `service.remanagement_availability` (so leitura); o que for
    escolhido vira `RemanagementFlowState.allocations`. A confirmacao
    transacional continua sendo da pagina de revisao."""

    step_name = "Origem do material"
    instruction = "Escolha de qual proposta o material vai sair e quanto retirar de cada uma."
    next_label = "Revisar remanejamento"

    def __init__(self, service, state, parent=None):
        super().__init__(service, state, parent)
        self._groups: dict[int, RemanagementItemAvailability] = {}
        self._sources: dict[int, SourceProposal] = {}
        self._lookup: dict[tuple[int, Key], RemanagementSourceCandidate] = {}
        self._allocations: dict[int, dict[Key, Decimal]] = {
            item.destination_item_id: {(a.source_proposal_id, a.source_item_id): a.allocated_quantity for a in item.allocations}
            for item in state.allocations
        }
        self._loaded_destination = state.destination_proposal_id
        self._selected_source: int | None = None
        self._coverage: dict[int, dict] = {}
        self._build()

    # -- construcao -----------------------------------------------------------

    def _build(self):
        body = QHBoxLayout()
        body.setSpacing(12)

        # Coluna 1: propostas de origem
        self.sources_panel, sources_layout = make_panel("1. Propostas com material pronto")
        self.sources_panel.setFixedWidth(SOURCES_WIDTH)
        self.sources_search = QLineEdit()
        self.sources_search.setPlaceholderText("Buscar proposta, cliente ou obra...")
        self.sources_search.setClearButtonEnabled(True)
        self.sources_search.textChanged.connect(self._render_sources)
        sources_layout.addWidget(self.sources_search)
        self.sources_table = QTableWidget(0, 4)
        self.sources_table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Cobre", "Retirando"])
        self.sources_table.verticalHeader().setVisible(False)
        self.sources_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sources_table.setSelectionMode(QTableWidget.SingleSelection)
        self.sources_table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.sources_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(SOURCE_COLUMN_NUMBER, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(SOURCE_COLUMN_CLIENT, header.ResizeMode.Stretch)
        header.setSectionResizeMode(SOURCE_COLUMN_COVERS, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(SOURCE_COLUMN_TAKING, header.ResizeMode.ResizeToContents)
        self.sources_table.itemSelectionChanged.connect(self._source_selection_changed)
        sources_layout.addWidget(self.sources_table, 1)
        self.refresh_button = ModernButton("Atualizar disponibilidade", "refresh", variant="ghost")
        self.refresh_button.clicked.connect(self._refresh_clicked)
        sources_layout.addWidget(self.refresh_button, 0, Qt.AlignLeft)
        body.addWidget(self.sources_panel)

        # Coluna 2: itens da proposta escolhida
        self.detail_panel, detail_layout = make_panel()
        self.detail_title = QLabel("2. Itens da proposta escolhida")
        self.detail_title.setObjectName("PanelTitle")
        self.detail_caption = QLabel("Escolha uma proposta na lista ao lado.")
        self.detail_caption.setObjectName("KeyLabel")
        self.detail_caption.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_caption)
        self.detail_table = QTableWidget(0, 5)
        self.detail_table.setHorizontalHeaderLabels(["Código", "Descrição", "Pedido", "Disponível aqui", "Retirar"])
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.setSelectionMode(QTableWidget.NoSelection)
        detail_header = self.detail_table.horizontalHeader()
        detail_header.setStretchLastSection(False)
        detail_header.setSectionResizeMode(ITEM_COLUMN_CODE, detail_header.ResizeMode.ResizeToContents)
        detail_header.setSectionResizeMode(ITEM_COLUMN_DESCRIPTION, detail_header.ResizeMode.Stretch)
        for column in (ITEM_COLUMN_REQUESTED, ITEM_COLUMN_AVAILABLE, ITEM_COLUMN_TAKE):
            detail_header.setSectionResizeMode(column, detail_header.ResizeMode.ResizeToContents)
        self.detail_table.itemChanged.connect(self._on_take_changed)
        detail_layout.addWidget(self.detail_table, 1)
        detail_buttons = QHBoxLayout()
        detail_buttons.setSpacing(8)
        self.take_max_button = ModernButton("Retirar o máximo desta proposta", "status")
        self.take_max_button.clicked.connect(self._take_max_from_source)
        self.clear_source_button = ModernButton("Limpar esta proposta", "clear", variant="ghost")
        self.clear_source_button.clicked.connect(self._clear_source)
        detail_buttons.addWidget(self.take_max_button)
        detail_buttons.addWidget(self.clear_source_button)
        detail_buttons.addStretch(1)
        detail_layout.addLayout(detail_buttons)
        body.addWidget(self.detail_panel, 1)

        # Coluna 3: cobertura do pedido
        self.coverage_panel, coverage_layout = make_panel("Cobertura do pedido")
        self.coverage_panel.setFixedWidth(COVERAGE_WIDTH)
        self.coverage_summary = QLabel("")
        self.coverage_summary.setObjectName("KeyLabel")
        self.coverage_summary.setWordWrap(True)
        coverage_layout.addWidget(self.coverage_summary)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.coverage_container = QWidget()
        self.coverage_layout = QVBoxLayout(self.coverage_container)
        self.coverage_layout.setContentsMargins(0, 0, 4, 0)
        self.coverage_layout.setSpacing(8)
        self.coverage_layout.addStretch(1)
        scroll.setWidget(self.coverage_container)
        coverage_layout.addWidget(scroll, 1)
        coverage_buttons = QHBoxLayout()
        coverage_buttons.setSpacing(8)
        self.suggest_button = ModernButton("Sugerir origens", "status")
        self.suggest_button.setToolTip(
            "Preenche todos os itens, usando primeiro a proposta com mais material pronto. Você pode ajustar depois."
        )
        self.suggest_button.clicked.connect(self._suggest_all)
        self.clear_all_button = ModernButton("Limpar tudo", "clear", variant="ghost")
        self.clear_all_button.clicked.connect(self._clear_all)
        coverage_buttons.addWidget(self.suggest_button)
        coverage_buttons.addWidget(self.clear_all_button)
        coverage_buttons.addStretch(1)
        coverage_layout.addLayout(coverage_buttons)
        body.addWidget(self.coverage_panel)

        self.root.addLayout(body, 1)

    # -- carga ------------------------------------------------------------------

    def enter(self) -> None:
        self.clear_notice()
        if self._loaded_destination != self.state.destination_proposal_id:
            self._allocations.clear()
            self._selected_source = None
            self._loaded_destination = self.state.destination_proposal_id
        if not self._load_availability():
            return
        adjusted = self._reconcile_allocations()
        self._build_coverage()
        self._render_sources()
        if not self._sources:
            self.show_notice(
                "Nenhuma proposta da Expedição tem material pronto compatível com os itens escolhidos. "
                "Volte e escolha outros itens, ou tente de novo mais tarde.",
                "warning",
            )
        elif adjusted:
            self.show_notice(
                "A disponibilidade mudou desde a última busca: algumas quantidades foram ajustadas. Confira antes de avançar.",
                "warning",
            )
        self._update_all()

    def _load_availability(self) -> bool:
        if not self.state.item_selections:
            self._clear_data()
            self.show_error("Nenhum item foi selecionado no passo anterior. Volte e selecione ao menos um item.")
            return False
        items_payload = [
            {"destination_item_id": selection.destination_item_id, "requested_quantity": selection.remanage_quantity}
            for selection in self.state.item_selections
        ]
        try:
            response = self.service.remanagement_availability(self.state.destination_proposal_id, items_payload)
        except Exception as exc:
            self._clear_data()
            self.show_error(str(exc))
            return False
        availability = availability_from_api(response.get("items") or [])
        self.state.set_availability(availability)
        self._index(availability)
        return True

    def _clear_data(self) -> None:
        self._groups, self._sources, self._lookup = {}, {}, {}
        self._build_coverage()
        self._render_sources()

    def _index(self, availability: list[RemanagementItemAvailability]) -> None:
        self._groups = {group.destination_item_id: group for group in availability}
        self._sources = {}
        self._lookup = {}
        for group in availability:
            for candidate in group.candidates:
                key = (candidate.source_proposal_id, candidate.source_item_id)
                self._lookup[(group.destination_item_id, key)] = candidate
                source = self._sources.get(candidate.source_proposal_id)
                if source is None:
                    source = SourceProposal(
                        proposal_id=candidate.source_proposal_id,
                        number=candidate.source_proposal_number,
                        client=candidate.client,
                        site=str(candidate.site or ""),
                        status=str(candidate.operational_status or ""),
                    )
                    self._sources[candidate.source_proposal_id] = source
                source.candidates.setdefault(group.destination_item_id, []).append(candidate)

    def _reconcile_allocations(self) -> bool:
        """Confere o que ja tinha sido escolhido contra a disponibilidade
        atual: some o que nao existe mais e corta o que passou do saldo ou do
        pedido. Devolve True quando algo teve de ser ajustado."""
        adjusted = False
        for item_id in list(self._allocations):
            group = self._groups.get(item_id)
            allocations = self._allocations[item_id]
            if group is None:
                adjusted = adjusted or bool(allocations)
                del self._allocations[item_id]
                continue
            total = Decimal("0")
            for key, quantity in list(allocations.items()):
                candidate = self._lookup.get((item_id, key))
                limit = max(min(candidate.available_quantity if candidate else Decimal("0"), group.requested_quantity - total), Decimal("0"))
                kept = min(quantity, limit)
                if kept != quantity:
                    adjusted = True
                if kept > 0:
                    allocations[key] = kept
                    total += kept
                else:
                    del allocations[key]
            if not allocations:
                del self._allocations[item_id]
        return adjusted

    # -- coluna 1: propostas de origem -------------------------------------------

    def _sorted_sources(self) -> list[SourceProposal]:
        needle = self.sources_search.text().strip().upper()
        sources = [
            source for source in self._sources.values()
            if not needle or needle in source.number.upper() or needle in source.client.upper() or needle in source.site.upper()
        ]
        return sorted(sources, key=lambda s: (-s.covered_items, -s.total_available(), s.number))

    def _taking_text(self, source_id: int) -> str:
        count = 0
        total = Decimal("0")
        units: dict[str, str] = {}  # unidade normalizada -> como foi escrita
        for item_id, allocations in self._allocations.items():
            for (proposal_id, _item), quantity in allocations.items():
                if proposal_id == source_id and quantity > 0:
                    count += 1
                    total += quantity
                    unit = str(self._groups[item_id].unit or "").strip()
                    units.setdefault(unit.upper(), unit)
        if not count:
            return "—"
        label = f"{count} item" if count == 1 else f"{count} itens"
        if len(units) == 1:
            return f"{label} · {quantity_text(total, next(iter(units.values())))}"
        return label

    def _render_sources(self):
        sources = self._sorted_sources()
        self.sources_table.blockSignals(True)
        self.sources_table.setRowCount(0)
        selected_row = -1
        total_items = len(self._groups)
        for source in sources:
            row = self.sources_table.rowCount()
            self.sources_table.insertRow(row)
            values = (
                source.number,
                source.client,
                f"{source.covered_items} de {total_items}",
                self._taking_text(source.proposal_id),
            )
            for column, text in enumerate(values):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.UserRole, source.proposal_id)
                tooltip = f"{source.number} — {source.client}"
                if source.site:
                    tooltip += f"\nObra/Site: {source.site}"
                if source.status:
                    tooltip += f"\nSituação: {source.status}"
                cell.setToolTip(tooltip)
                self.sources_table.setItem(row, column, cell)
            if source.proposal_id == self._selected_source:
                selected_row = row
        if selected_row < 0 and sources:
            # Sem escolha anterior (ou ela saiu do filtro): comeca pela que cobre mais itens.
            selected_row = 0
            self._selected_source = sources[0].proposal_id
        if selected_row >= 0:
            self.sources_table.selectRow(selected_row)
        else:
            self._selected_source = None
        self.sources_table.blockSignals(False)
        self._render_detail()

    def _refresh_source_row(self, source_id: int) -> None:
        for row in range(self.sources_table.rowCount()):
            item = self.sources_table.item(row, SOURCE_COLUMN_NUMBER)
            if item is not None and int(item.data(Qt.UserRole)) == source_id:
                cell = self.sources_table.item(row, SOURCE_COLUMN_TAKING)
                if cell is not None:
                    cell.setText(self._taking_text(source_id))
                return

    def _source_selection_changed(self):
        selected = self.sources_table.selectedItems()
        self._selected_source = int(selected[0].data(Qt.UserRole)) if selected else None
        self._render_detail()

    # -- coluna 2: itens da proposta escolhida ---------------------------------------

    def _allocated(self, item_id: int) -> Decimal:
        return sum(self._allocations.get(item_id, {}).values(), Decimal("0"))

    def _render_detail(self):
        source = self._sources.get(self._selected_source) if self._selected_source is not None else None
        self.detail_table.blockSignals(True)
        self.detail_table.setRowCount(0)
        if source is None:
            self.detail_title.setText("2. Itens da proposta escolhida")
            self.detail_caption.setText("Escolha uma proposta na lista ao lado.")
            self.detail_table.blockSignals(False)
            self.take_max_button.setEnabled(False)
            self.clear_source_button.setEnabled(False)
            return
        self.detail_title.setText(f"2. Itens que {source.number} pode fornecer")
        caption = source.client
        if source.site:
            caption += f" · {source.site}"
        missing = len(self._groups) - source.covered_items
        if missing > 0:
            caption += f" — não tem {missing} dos {len(self._groups)} itens pedidos"
        self.detail_caption.setText(caption)
        for item_id in sorted(source.candidates, key=lambda i: self._groups[i].product_code):
            group = self._groups[item_id]
            for candidate in source.candidates[item_id]:
                key = (candidate.source_proposal_id, candidate.source_item_id)
                row = self.detail_table.rowCount()
                self.detail_table.insertRow(row)
                unit = candidate.unit or group.unit
                taken = self._allocations.get(item_id, {}).get(key, Decimal("0"))
                cells = (
                    (ITEM_COLUMN_CODE, group.product_code),
                    (ITEM_COLUMN_DESCRIPTION, group.description),
                    (ITEM_COLUMN_REQUESTED, quantity_text(group.requested_quantity, group.unit)),
                    (ITEM_COLUMN_AVAILABLE, quantity_text(candidate.available_quantity, unit)),
                )
                for column, text in cells:
                    cell = QTableWidgetItem(text)
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                    self.detail_table.setItem(row, column, cell)
                take = QTableWidgetItem(format_decimal(taken))
                mark_editable(take)
                take.setData(Qt.UserRole, (item_id, key))
                take.setToolTip("Quantidade a retirar desta proposta para o item. Pode digitar.")
                self.detail_table.setItem(row, ITEM_COLUMN_TAKE, take)
        self.detail_table.blockSignals(False)
        self.take_max_button.setEnabled(True)
        self.clear_source_button.setEnabled(True)

    def _on_take_changed(self, cell: QTableWidgetItem):
        if cell.column() != ITEM_COLUMN_TAKE:
            return
        item_id, key = cell.data(Qt.UserRole)
        clamped = self._set_allocation(item_id, key, parse_decimal(cell.text(), "-1"))
        self.detail_table.blockSignals(True)
        if format_decimal(clamped) != cell.text():
            cell.setText(format_decimal(clamped))
        self.detail_table.blockSignals(False)
        self._after_allocation_change(item_id, key[0])

    def _set_allocation(self, item_id: int, key: Key, entered: Decimal) -> Decimal:
        """Grava `entered` para (item, origem) cortando no saldo da origem e no
        que ainda falta do pedido; devolve o valor que ficou valendo."""
        group = self._groups[item_id]
        candidate = self._lookup.get((item_id, key))
        allocations = self._allocations.setdefault(item_id, {})
        available = candidate.available_quantity if candidate is not None else Decimal("0")
        others = sum((qty for other, qty in allocations.items() if other != key), Decimal("0"))
        room = max(group.requested_quantity - others, Decimal("0"))
        clamped = max(min(entered, available, room), Decimal("0"))
        if clamped > 0:
            allocations[key] = clamped
        else:
            allocations.pop(key, None)
            if not allocations:
                self._allocations.pop(item_id, None)
        return clamped

    def _after_allocation_change(self, item_id: int, source_id: int) -> None:
        self._refresh_source_row(source_id)
        self._update_coverage(item_id)
        self._update_summary()
        self.validity_changed.emit()

    def _take_max_from_source(self):
        source = self._sources.get(self._selected_source) if self._selected_source is not None else None
        if source is None:
            return
        for item_id, candidates in source.candidates.items():
            for candidate in candidates:
                key = (candidate.source_proposal_id, candidate.source_item_id)
                self._set_allocation(item_id, key, candidate.available_quantity)
        self._update_all()

    def _clear_source(self):
        source = self._sources.get(self._selected_source) if self._selected_source is not None else None
        if source is None:
            return
        for item_id in list(self._allocations):
            allocations = self._allocations[item_id]
            for key in [k for k in allocations if k[0] == source.proposal_id]:
                del allocations[key]
            if not allocations:
                del self._allocations[item_id]
        self._update_all()

    # -- coluna 3: cobertura ---------------------------------------------------------

    def _build_coverage(self):
        while self.coverage_layout.count() > 1:
            item = self.coverage_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._coverage = {}
        for item_id, group in self._groups.items():
            frame = QFrame()
            frame.setObjectName("Card")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(5)
            top = QHBoxLayout()
            top.setSpacing(8)
            code = QLabel(group.product_code)
            code.setObjectName("ValueLabel")
            badge = coverage_badge("SEM_ORIGEM")
            top.addWidget(code)
            top.addStretch(1)
            top.addWidget(badge)
            layout.addLayout(top)
            description = QLabel(group.description)
            description.setObjectName("KeyLabel")
            description.setToolTip(group.description)
            description.setMinimumWidth(10)
            description.setText(QFontMetrics(description.font()).elidedText(group.description, Qt.ElideRight, COVERAGE_WIDTH - 80))
            layout.addWidget(description)
            bar = ThinProgressBar(0.0, color=None, height=6)
            layout.addWidget(bar)
            amount = QLabel("")
            amount.setObjectName("KeyLabel")
            layout.addWidget(amount)
            self.coverage_layout.insertWidget(self.coverage_layout.count() - 1, frame)
            self._coverage[item_id] = {"badge": badge, "bar": bar, "amount": amount}
            self._update_coverage(item_id)
        self._update_summary()

    def _update_coverage(self, item_id: int) -> None:
        widgets = self._coverage.get(item_id)
        group = self._groups.get(item_id)
        if widgets is None or group is None:
            return
        allocated = self._allocated(item_id)
        kind = coverage_kind(group.requested_quantity, allocated, bool(group.candidates))
        set_coverage_badge(widgets["badge"], kind)
        requested = group.requested_quantity
        widgets["bar"].set_fraction(float(allocated / requested) if requested > 0 else 0.0)
        remaining = max(requested - allocated, Decimal("0"))
        text = f"{quantity_text(allocated, group.unit)} de {quantity_text(requested, group.unit)}"
        if kind == "PARCIAL" or kind == "SEM_ORIGEM":
            text += f" · falta {quantity_text(remaining, group.unit)}"
        widgets["amount"].setText(text)

    def _update_summary(self) -> None:
        total = len(self._groups)
        complete = sum(
            1 for item_id, group in self._groups.items()
            if self._allocated(item_id) >= group.requested_quantity > 0
        )
        self.coverage_summary.setText(f"{complete} de {total} item(ns) com o pedido completo" if total else "")

    def _update_all(self) -> None:
        for item_id in self._groups:
            self._update_coverage(item_id)
        self._update_summary()
        self._render_sources()
        self.validity_changed.emit()

    # -- acoes globais ---------------------------------------------------------------

    def _suggest_all(self):
        for item_id, group in self._groups.items():
            candidates = [
                AllocationCandidate(
                    source_proposal_id=c.source_proposal_id, source_item_id=c.source_item_id, available_quantity=c.available_quantity,
                )
                for c in group.candidates
            ]
            suggestions, _remaining = suggest_allocation(group.requested_quantity, candidates)
            if suggestions:
                self._allocations[item_id] = {(row.source_proposal_id, row.source_item_id): row.allocated_quantity for row in suggestions}
            else:
                self._allocations.pop(item_id, None)
        self._update_all()

    def _clear_all(self):
        self._allocations.clear()
        self._update_all()

    def _refresh_clicked(self):
        self.enter()

    # -- contrato ---------------------------------------------------------------------

    def is_valid(self) -> bool:
        return any(qty > 0 for allocations in self._allocations.values() for qty in allocations.values())

    def summary(self) -> str:
        if not self._groups:
            return ""
        complete = sum(1 for item_id, group in self._groups.items() if self._allocated(item_id) >= group.requested_quantity > 0)
        origins = {key[0] for allocations in self._allocations.values() for key in allocations}
        text = f"{complete} de {len(self._groups)} item(ns) completos"
        if origins:
            text += f" · {len(origins)} proposta(s) de origem"
        return text

    def commit(self) -> bool:
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
                        available_snapshot=self._lookup[(group.destination_item_id, key)].available_quantity,
                        allocated_quantity=quantity,
                    )
                    for key, quantity in allocations.items()
                ],
            ))
        if not item_allocations:
            QMessageBox.warning(self, "Remanejamento", "Escolha de qual proposta vai sair o material antes de avançar.")
            return False
        self.state.set_allocations(item_allocations)
        return True

    # -- consulta para testes/telas ------------------------------------------------------

    def allocation(self, item_id: int, key: Key) -> Decimal:
        return self._allocations.get(item_id, {}).get(key, Decimal("0"))
