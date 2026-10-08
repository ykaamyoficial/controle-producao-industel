from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from app.services.remanagement_flow_state import review_from_api
from app.ui.components.detail_widgets import ThinProgressBar, block_grid, make_panel
from app.ui.components.dialog_shell import TABLE_HEADER_HEIGHT, TABLE_ROW_HEIGHT, info_notice, set_notice_kind, standardize_tables
from app.ui.components.modern_button import ModernButton
from app.ui.numeric_utils import format_decimal
from app.ui.remanagement_wizard.base import WizardPage
from app.ui.remanagement_wizard.widgets import REVIEW_STATUS_KINDS, coverage_badge, quantity_text

SIDE_WIDTH = 360


class ReviewPage(WizardPage):
    """Passo 4: revisao, simulacao (antes/depois) e confirmacao consciente.

    Nao recalcula nada com regra propria: revalida e simula chamando
    `service.remanagement_review`, que no backend reusa a MESMA leitura de
    saldo e o MESMO motor de compensacao da confirmacao. A gravacao so
    acontece em `commit()`, depois da pergunta final, via
    `service.remanagement_confirm` (transacional e idempotente pelo
    `operation_id` do estado)."""

    step_name = "Revisão"
    instruction = "Confira o que vai mudar, informe o motivo e confirme."
    next_label = "Confirmar remanejamento"
    next_icon = "save"

    def __init__(self, service, state, parent=None):
        super().__init__(service, state, parent)
        self._destination: dict = {}
        self._result = None
        self.confirm_result: dict | None = None
        self._selection_by_id = {}
        self._candidate_by_key = {}
        self._build()

    def set_destination(self, row: dict | None) -> None:
        self._destination = dict(row or {})

    # -- construcao -----------------------------------------------------------

    def _build(self):
        self.info_notice = info_notice(
            "Esta operação NÃO registra entrega ao cliente. Ela apenas passa material pronto de uma proposta "
            "para outra e transfere, no mesmo valor, a obrigação de produção para a proposta de origem."
        )
        self.root.addWidget(self.info_notice)

        body = QHBoxLayout()
        body.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(0, 0, 4, 0)
        self.groups_layout.setSpacing(12)
        self.groups_layout.addStretch(1)
        scroll.setWidget(self.groups_container)
        body.addWidget(scroll, 1)

        side = QVBoxLayout()
        side.setSpacing(12)
        self.summary_panel, summary_layout = make_panel("Resumo da operação")
        self.destination_label = QLabel("")
        self.destination_label.setObjectName("ValueLabel")
        self.destination_label.setWordWrap(True)
        summary_layout.addWidget(self.destination_label)
        self.summary_holder = QVBoxLayout()
        summary_layout.addLayout(self.summary_holder)
        self.warnings_label = QLabel("")
        self.warnings_label.setWordWrap(True)
        set_notice_kind(self.warnings_label, "warning")
        self.warnings_label.setVisible(False)
        summary_layout.addWidget(self.warnings_label)
        revalidate = ModernButton("Revalidar", "refresh", variant="ghost")
        revalidate.setToolTip("Confere de novo o saldo das propostas de origem e refaz a simulação.")
        revalidate.clicked.connect(self._revalidate_clicked)
        self.revalidate_button = revalidate
        summary_layout.addWidget(revalidate, 0, Qt.AlignLeft)
        side.addWidget(self.summary_panel)

        self.reason_panel, reason_layout = make_panel("Motivo do remanejamento *")
        self.reason_edit = QTextEdit()
        self.reason_edit.setPlaceholderText("Descreva o motivo real desta operação (obrigatório).")
        self.reason_edit.setMinimumHeight(96)
        self.reason_edit.textChanged.connect(self._on_reason_changed)
        reason_layout.addWidget(self.reason_edit, 1)
        side.addWidget(self.reason_panel, 1)

        side_holder = QWidget()
        side_holder.setLayout(side)
        side_holder.setFixedWidth(SIDE_WIDTH)
        side.setContentsMargins(0, 0, 0, 0)
        body.addWidget(side_holder)
        self.root.addLayout(body, 1)

    # -- carga ------------------------------------------------------------------

    def enter(self) -> None:
        self.clear_notice()
        self._selection_by_id = {row.destination_item_id: row for row in self.state.item_selections}
        self._candidate_by_key = {
            (group.destination_item_id, (candidate.source_proposal_id, candidate.source_item_id)): candidate
            for group in self.state.availability
            for candidate in group.candidates
        }
        label = f"{self._destination.get('proposta') or ''} — {self._destination.get('cliente') or ''}".strip(" —")
        site = self._destination.get("obra_site")
        self.destination_label.setText(f"Destino: {label}" + (f"\nObra/Site: {site}" if site else ""))
        if self.reason_edit.toPlainText() != self.state.reason:
            self.reason_edit.blockSignals(True)
            self.reason_edit.setPlainText(self.state.reason)
            self.reason_edit.blockSignals(False)
        error = self._load_review(self.state.reason)
        if error:
            self._result = None
            self._render_result()
            self.show_error(error)
            return
        self._render_result()

    def _plan_payloads(self) -> tuple[list[dict], list[dict]]:
        items_payload = [
            {"destination_item_id": item.destination_item_id, "requested_quantity": item.requested_quantity}
            for item in self.state.allocations
        ]
        allocations_payload = [
            {
                "destination_item_id": item.destination_item_id,
                "source_proposal_id": allocation.source_proposal_id,
                "source_item_id": allocation.source_item_id,
                "allocated_quantity": allocation.allocated_quantity,
            }
            for item in self.state.allocations
            for allocation in item.allocations
        ]
        return items_payload, allocations_payload

    def _load_review(self, reason: str) -> str | None:
        if not self.state.allocations:
            return "Nenhuma origem foi escolhida no passo anterior. Volte e escolha de qual proposta vai sair o material."
        items_payload, allocations_payload = self._plan_payloads()
        try:
            response = self.service.remanagement_review(self.state.destination_proposal_id, items_payload, allocations_payload, reason)
        except Exception as exc:
            return str(exc)
        self._result = review_from_api(response)
        self.state.set_simulation(self._result)
        return None

    def _revalidate_clicked(self):
        self.clear_notice()
        error = self._load_review(self.reason_edit.toPlainText())
        if error:
            QMessageBox.warning(self, "Remanejamento", error)
            return
        self._render_result()

    def _on_reason_changed(self):
        self.state.set_reason(self.reason_edit.toPlainText())
        self.validity_changed.emit()

    # -- apresentacao -----------------------------------------------------------

    def _clear_groups(self):
        while self.groups_layout.count() > 1:
            item = self.groups_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _clear_summary(self):
        while self.summary_holder.count():
            item = self.summary_holder.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget() is not None:
                        child.widget().deleteLater()

    def _render_result(self):
        result = self._result
        self._clear_groups()
        self._clear_summary()
        self.warnings_label.setVisible(False)
        if result is None:
            self.validity_changed.emit()
            return

        summary = result.summary
        rows = [("Produtos", str(summary.product_count)), ("Propostas de origem", str(summary.source_proposal_count))]
        if summary.total_quantity is not None and summary.total_unit:
            rows.append(("Quantidade", quantity_text(summary.total_quantity, summary.total_unit)))
        coverage = []
        if summary.complete_items:
            coverage.append(f"{summary.complete_items} completo(s)")
        if summary.partial_items:
            coverage.append(f"{summary.partial_items} parcial(is)")
        if summary.not_allocated_items:
            coverage.append(f"{summary.not_allocated_items} sem origem")
        if summary.invalid_items:
            coverage.append(f"{summary.invalid_items} inválido(s)")
        rows.append(("Cobertura", ", ".join(coverage) or "—"))
        self.summary_holder.addLayout(block_grid(rows, columns=2))

        blocking = [error for error in result.errors if error.code != "REASON_REQUIRED"]
        if blocking:
            self.warnings_label.setText("Erros que impedem a confirmação: " + "; ".join(error.message for error in blocking[:3]))
            set_notice_kind(self.warnings_label, "danger")
            self.warnings_label.setVisible(True)
        elif result.warnings:
            self.warnings_label.setText("Atenção: " + " | ".join(result.warnings))
            set_notice_kind(self.warnings_label, "warning")
            self.warnings_label.setVisible(True)

        errors_by_item: dict[int, list] = {}
        for error in result.errors:
            if error.destination_item_id is not None:
                errors_by_item.setdefault(error.destination_item_id, []).append(error)
        for item in result.items:
            self.groups_layout.insertWidget(
                self.groups_layout.count() - 1, self._build_item_card(item, errors_by_item.get(item.destination_item_id, []))
            )
        self.validity_changed.emit()

    def _source_label(self, item_id: int, source_proposal_id: int, source_item_id: int) -> tuple[str, str]:
        candidate = self._candidate_by_key.get((item_id, (source_proposal_id, source_item_id)))
        if candidate is None:
            return f"#{source_proposal_id}", ""
        return candidate.source_proposal_number, candidate.unit or ""

    def _build_item_card(self, item, item_errors: list) -> QFrame:
        selection = self._selection_by_id.get(item.destination_item_id)
        description = selection.description if selection else ""
        unit = (selection.unit if selection else "") or ""
        destination = str(self._destination.get("proposta") or "destino")

        panel, layout = make_panel()
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(f"{item.product_code} — {description}".strip(" —"))
        title.setObjectName("PanelTitle")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        head.addWidget(coverage_badge(REVIEW_STATUS_KINDS.get(item.status, "SEM_ORIGEM")))
        layout.addLayout(head)

        figures = QLabel(
            f"Solicitado {quantity_text(item.requested, unit)}  ·  Alocado {quantity_text(item.allocated, unit)}  ·  "
            f"Restante {quantity_text(item.remaining, unit)}"
        )
        figures.setObjectName("KeyLabel")
        layout.addWidget(figures)
        fraction = float(item.allocated / item.requested) if item.requested > 0 else 0.0
        layout.addWidget(ThinProgressBar(fraction, height=6))

        if item.status == "PARCIAL":
            partial = QLabel(f"Atenção: {quantity_text(item.remaining, unit)} continuarão sem atendimento por remanejamento.")
            set_notice_kind(partial, "warning")
            partial.setWordWrap(True)
            layout.addWidget(partial)
        for error in item_errors:
            label = QLabel(f"Bloqueio: {error.message}")
            set_notice_kind(label, "danger")
            label.setWordWrap(True)
            layout.addWidget(label)

        if not item.sources:
            empty = QLabel("Nenhuma origem alocada para este item.")
            empty.setObjectName("KeyLabel")
            layout.addWidget(empty)
            return panel

        table = QTableWidget(len(item.sources), 4)
        table.setHorizontalHeaderLabels([
            "Proposta de origem", f"Material pronto → {destination}", "Pronto na origem (antes → depois)",
            f"Produção que {destination} passa à origem",
        ])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(4):
            header.setSectionResizeMode(column, header.ResizeMode.Stretch)
        for row, source in enumerate(item.sources):
            number, source_unit = self._source_label(item.destination_item_id, source.source_proposal_id, source.source_item_id)
            display_unit = source_unit or unit
            values = (
                number,
                quantity_text(source.ready_transfer, display_unit),
                f"{format_decimal(source.source_before)} → {format_decimal(source.source_after_simulated)}",
                quantity_text(source.production_compensation, display_unit),
            )
            for column, text in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(text))
        table.setFixedHeight(TABLE_HEADER_HEIGHT + TABLE_ROW_HEIGHT * len(item.sources) + 4)
        layout.addWidget(table)
        # Tabela criada depois de o dialogo aparecer: padroniza ja (zebra, cabecalho, linha de 40 px).
        standardize_tables(panel)
        return panel

    # -- contrato ---------------------------------------------------------------

    def _plan_valid(self) -> bool:
        result = self._result
        return result is not None and not any(error.code != "REASON_REQUIRED" for error in result.errors)

    def is_valid(self) -> bool:
        return self.load_error is None and self._plan_valid() and bool(self.reason_edit.toPlainText().strip())

    def summary(self) -> str:
        result = self._result
        if result is None:
            return ""
        s = result.summary
        text = f"{s.product_count} produto(s) · {s.source_proposal_count} origem(ns)"
        if s.total_quantity is not None and s.total_unit:
            text += f" · {quantity_text(s.total_quantity, s.total_unit)}"
        return text

    def commit(self) -> bool:
        """Pergunta final + gravacao transacional. True so quando gravou."""
        if not self.is_valid():
            return False
        result = self._result
        summary = result.summary
        lines = [
            f"Destino: {self._destination.get('proposta') or ''}",
            f"{summary.product_count} produto(s)",
            f"{summary.source_proposal_count} proposta(s) de origem",
            f"{sum(len(item.sources) for item in result.items)} alocacao(oes)",
            "",
            "Esta operacao alterara a vinculacao dos materiais prontos",
            "e compensara a obrigacao de producao das propostas envolvidas.",
        ]
        answer = QMessageBox.question(self, "Confirmar remanejamento?", "\n".join(lines), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return False
        reason = self.reason_edit.toPlainText().strip()
        self.state.set_reason(reason)
        items_payload, allocations_payload = self._plan_payloads()
        try:
            self.confirm_result = self.service.remanagement_confirm(
                self.state.operation_id, self.state.destination_proposal_id, items_payload, allocations_payload, reason,
            )
        except Exception as exc:
            # O backend revalida tudo (saldo, compatibilidade, status) dentro da
            # propria transacao: se algo mudou, nada foi gravado. Revalidar
            # destaca o item afetado em vez de so fechar com erro.
            QMessageBox.warning(self, "Remanejamento", str(exc))
            error = self._load_review(reason)
            if error:
                self._result = None
                self._render_result()
                self.show_error(error)
            else:
                self._render_result()
            return False
        return True
