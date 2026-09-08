from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.services.remanagement_flow_state import RemanagementFlowState, review_from_api
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.numeric_utils import format_decimal

STATUS_LABELS = {
    "COMPLETO": "COMPLETO",
    "PARCIAL": "PARCIAL",
    "NAO_ALOCADO": "NAO ALOCADO",
    "INVALIDO": "INVALIDO",
}


class RemanagementReviewStepDialog(QDialog):
    """Etapa 6 do novo fluxo de Remanejamento Compensado: revisao final,
    simulacao (antes/depois) e confirmacao consciente antes de qualquer
    gravacao definitiva.

    Nao recalcula nada com regra propria - revalida e simula chamando
    `service.remanagement_review`, que no backend reusa a MESMA leitura de
    saldo da Fase 5 (`_load_compensation_snapshots`) e o MESMO motor de
    compensacao (`build_compensation_plan`). Esta classe so apresenta o
    resultado, valida o motivo e protege a confirmacao contra duplo clique.
    Nenhuma escrita acontece aqui - a persistencia definitiva e da Fase 7.
    """

    RESULT_BACK = 2

    def __init__(self, service, parent, state: RemanagementFlowState):
        super().__init__(parent)
        self.service = service
        self.state = state
        self.destination_summary: dict | None = None
        self.load_error: str | None = None
        self.confirm_result: dict | None = None
        self._result = None
        self._item_selection_by_id = {row.destination_item_id: row for row in state.item_selections}
        self._candidate_by_key = {
            (group.destination_item_id, (candidate.source_proposal_id, candidate.source_item_id)): candidate
            for group in state.availability
            for candidate in group.candidates
        }
        self.setWindowTitle("Remanejamento de materiais")
        self.setMinimumSize(1000, 720)
        style_dialog_from_parent(self, parent)
        self._build()
        self.load_error = self._load_review(state.reason)
        if self.load_error is None:
            self._render_result()

    # -- construcao -------------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("6. Revisar remanejamento")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        root.addWidget(title)

        notice = QLabel("Esta operacao NAO registra entrega ao cliente. Ela apenas realoca material pronto entre propostas e transfere a obrigacao produtiva equivalente.")
        notice.setObjectName("Caption")
        notice.setWordWrap(True)
        root.addWidget(notice)

        self.destination_frame = QFrame()
        self.destination_frame.setObjectName("Card")
        destination_layout = QVBoxLayout(self.destination_frame)
        destination_layout.setContentsMargins(14, 12, 14, 12)
        self.destination_label = QLabel("Destino")
        self.destination_label.setWordWrap(True)
        destination_layout.addWidget(self.destination_label)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-weight: 700;")
        self.summary_label.setWordWrap(True)
        destination_layout.addWidget(self.summary_label)
        root.addWidget(self.destination_frame)

        self.warnings_label = QLabel("")
        self.warnings_label.setObjectName("Caption")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setVisible(False)
        root.addWidget(self.warnings_label)

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

        root.addWidget(QLabel("Motivo do remanejamento *"))
        self.reason_edit = QTextEdit()
        self.reason_edit.setPlaceholderText("Descreva o motivo real desta operacao (obrigatorio).")
        self.reason_edit.setMaximumHeight(72)
        self.reason_edit.setPlainText(self.state.reason)
        self.reason_edit.textChanged.connect(self._on_reason_changed)
        root.addWidget(self.reason_edit)

        footer = QHBoxLayout()
        back = ModernButton("Voltar", "clear")
        revalidate = ModernButton("Revalidar", "status")
        self.confirm_button = ModernButton("Confirmar remanejamento", "save", accent=True)
        self.confirm_button.setEnabled(False)
        back.clicked.connect(lambda: self.done(self.RESULT_BACK))
        revalidate.clicked.connect(self._revalidate_clicked)
        self.confirm_button.clicked.connect(self._confirm_clicked)
        footer.addWidget(revalidate)
        footer.addStretch()
        footer.addWidget(back)
        footer.addWidget(self.confirm_button)
        root.addLayout(footer)

    # -- carregamento / revalidacao ------------------------------------------------

    def _load_review(self, reason: str) -> str | None:
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
        if not self.state.allocations:
            return "Nenhuma alocacao foi definida na etapa anterior. Volte e defina de onde retirar os materiais."

        items_payload, allocations_payload = self._plan_payloads()
        try:
            response = self.service.remanagement_review(
                self.state.destination_proposal_id, items_payload, allocations_payload, reason,
            )
        except Exception as exc:
            return str(exc)
        result = review_from_api(response)
        self._result = result
        self.state.set_simulation(result)
        return None

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

    def _revalidate_clicked(self):
        error = self._load_review(self.reason_edit.toPlainText())
        if error:
            QMessageBox.warning(self, "Remanejamento", error)
            return
        self._render_result()

    def _on_reason_changed(self):
        self.state.set_reason(self.reason_edit.toPlainText())
        self._update_confirm_enabled()

    # -- apresentacao -------------------------------------------------------------

    def _clear_groups(self):
        while self.groups_layout.count() > 1:
            item = self.groups_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_result(self):
        result = self._result
        self._clear_groups()
        if result is None:
            self._update_confirm_enabled()
            return

        self.summary_label.setText(self._summary_text(result))

        non_reason_errors = [error for error in result.errors if error.code != "REASON_REQUIRED"]
        if non_reason_errors:
            messages = "; ".join(error.message for error in non_reason_errors[:3])
            self.warnings_label.setText(f"Erros que impedem a confirmacao: {messages}")
            self.warnings_label.setStyleSheet("color: #c0392b; font-weight: 600;")
            self.warnings_label.setVisible(True)
        elif result.warnings:
            self.warnings_label.setText("Atencao: " + " | ".join(result.warnings))
            self.warnings_label.setStyleSheet("")
            self.warnings_label.setVisible(True)
        else:
            self.warnings_label.setVisible(False)

        errors_by_item: dict[int, list] = {}
        for error in result.errors:
            if error.destination_item_id is not None:
                errors_by_item.setdefault(error.destination_item_id, []).append(error)

        for item in result.items:
            frame = self._build_item_frame(item, errors_by_item.get(item.destination_item_id, []))
            self.groups_layout.insertWidget(self.groups_layout.count() - 1, frame)

        self._update_confirm_enabled()

    def _summary_text(self, result) -> str:
        summary = result.summary
        parts = [f"{summary.product_count} produto(s)", f"{summary.source_proposal_count} origem(ns)"]
        if summary.total_quantity is not None and summary.total_unit:
            parts.append(f"{format_decimal(summary.total_quantity)} {summary.total_unit} alocadas")
        coverage_parts = []
        if summary.complete_items:
            coverage_parts.append(f"{summary.complete_items} completo(s)")
        if summary.partial_items:
            coverage_parts.append(f"{summary.partial_items} parcial(is)")
        if summary.not_allocated_items:
            coverage_parts.append(f"{summary.not_allocated_items} nao alocado(s)")
        if summary.invalid_items:
            coverage_parts.append(f"{summary.invalid_items} invalido(s)")
        text = " | ".join(parts)
        if coverage_parts:
            text += " | " + ", ".join(coverage_parts)
        return text

    def _display_source(self, destination_item_id: int, source_proposal_id: int, source_item_id: int) -> tuple[str, str]:
        candidate = self._candidate_by_key.get((destination_item_id, (source_proposal_id, source_item_id)))
        if candidate is None:
            return f"#{source_proposal_id}", ""
        return candidate.source_proposal_number, candidate.unit or ""

    def _build_item_frame(self, item, item_errors: list) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        selection = self._item_selection_by_id.get(item.destination_item_id)
        description = selection.description if selection else ""
        unit = (selection.unit if selection else "") or ""
        destination_label = (self.destination_summary or {}).get("proposta") or ""

        heading = QLabel(f"Produto {item.product_code} - {description}")
        heading.setStyleSheet("font-weight: 700;")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        status_label = STATUS_LABELS.get(item.status, item.status)
        indicator = QLabel(
            f"Solicitado: {format_decimal(item.requested)} {unit} | Alocado: {format_decimal(item.allocated)} {unit} | "
            f"Restante: {format_decimal(item.remaining)} {unit} | Status: {status_label}"
        )
        indicator.setObjectName("Caption")
        if item.status in {"INVALIDO"}:
            indicator.setStyleSheet("color: #c0392b; font-weight: 600;")
        layout.addWidget(indicator)

        if item.status == "PARCIAL":
            partial_notice = QLabel(f"Atencao: {format_decimal(item.remaining)} {unit} continuarao sem atendimento por remanejamento.")
            partial_notice.setObjectName("Caption")
            layout.addWidget(partial_notice)

        for error in item_errors:
            error_label = QLabel(f"Bloqueio: {error.message}")
            error_label.setStyleSheet("color: #c0392b;")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)

        if item.sources:
            ready_header = QLabel("MATERIAL PRONTO (origem -> destino)")
            ready_header.setStyleSheet("font-weight: 700;")
            layout.addWidget(ready_header)
            for source in item.sources:
                proposal_number, source_unit = self._display_source(item.destination_item_id, source.source_proposal_id, source.source_item_id)
                display_unit = source_unit or unit
                line = QLabel(
                    f"{proposal_number} -- {format_decimal(source.ready_transfer)} {display_unit} --> {destination_label}"
                    f"    (Pronto na Expedicao: {format_decimal(source.source_before)} -> {format_decimal(source.source_after_simulated)})"
                )
                line.setWordWrap(True)
                layout.addWidget(line)

            obligation_header = QLabel("OBRIGACAO DE PRODUCAO (destino -> origem)")
            obligation_header.setStyleSheet("font-weight: 700;")
            layout.addWidget(obligation_header)
            for source in item.sources:
                proposal_number, source_unit = self._display_source(item.destination_item_id, source.source_proposal_id, source.source_item_id)
                display_unit = source_unit or unit
                line = QLabel(
                    f"{destination_label} -- obrigacao equivalente {format_decimal(source.production_compensation)} {display_unit} --> {proposal_number}"
                )
                line.setWordWrap(True)
                layout.addWidget(line)
        else:
            empty = QLabel("Nenhuma origem alocada para este item.")
            empty.setObjectName("Caption")
            layout.addWidget(empty)

        return frame

    # -- confirmacao -------------------------------------------------------------

    def _update_confirm_enabled(self):
        result = self._result
        plan_valid = result is not None and not any(error.code != "REASON_REQUIRED" for error in result.errors)
        reason_filled = bool(self.reason_edit.toPlainText().strip())
        self.confirm_button.setEnabled(plan_valid and reason_filled)

    def _confirm_clicked(self):
        if not self.confirm_button.isEnabled():
            return
        self.confirm_button.setEnabled(False)
        try:
            result = self._result
            summary = result.summary
            lines = [
                f"Destino: {(self.destination_summary or {}).get('proposta') or ''}",
                f"{summary.product_count} produto(s)",
                f"{summary.source_proposal_count} proposta(s) de origem",
                f"{sum(len(item.sources) for item in result.items)} alocacao(oes)",
                "",
                "Esta operacao alterara a vinculacao dos materiais prontos",
                "e compensara a obrigacao de producao das propostas envolvidas.",
            ]
            answer = QMessageBox.question(self, "Confirmar remanejamento?", "\n".join(lines), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            reason = self.reason_edit.toPlainText().strip()
            self.state.set_reason(reason)
            items_payload, allocations_payload = self._plan_payloads()
            try:
                self.confirm_result = self.service.remanagement_confirm(
                    self.state.operation_id, self.state.destination_proposal_id, items_payload, allocations_payload, reason,
                )
            except Exception as exc:
                # Fase 7: o backend revalida tudo (saldo, compatibilidade, status
                # das propostas) dentro da propria transacao antes de gravar -
                # se algo mudou desde a Etapa 6, nada foi gravado. Revalidar
                # aqui atualiza a tela (o mesmo mecanismo do botao "Revalidar")
                # para destacar o item afetado, em vez de so fechar com erro.
                QMessageBox.warning(self, "Remanejamento", str(exc))
                error = self._load_review(reason)
                if error:
                    self.load_error = error
                    self.done(self.RESULT_BACK)
                    return
                self._render_result()
                return
            self.accept()
        finally:
            if self.result() != QDialog.Accepted:
                self.confirm_button.setEnabled(True)
