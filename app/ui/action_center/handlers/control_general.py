from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult


class ControlGeneralStatusHandler:
    """STATUS no Controle Geral: Liberar para Producao (LIBERADO_PRODUCAO) e
    Cancelar proposta (CANCELADA). Mesma chamada oficial que o StatusDialog
    monolitico usava (`service.update_status(process_id, "CONTROLE GERAL",
    status, observation)`) - nenhuma regra nova, so roteamento e UX de
    confirmacao para a operacao destrutiva."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        status = action.status
        if status == "CANCELADA":
            return self._cancel(context, action, dialog)
        if status == "LIBERADO_PRODUCAO":
            return self._release_to_production(context, action, dialog)
        # Fallback generico para uma eventual transicao de Controle Geral que o
        # backend passe a expor no futuro sem esta fase ter previsto.
        dialog._run_background_action(
            lambda: dialog.service.update_status(
                context.proposal_id, action.area, status, dialog.observation.toPlainText().strip()
            )
        )
        return ActionResult(success=True, changed=True, refresh_required=True)

    @staticmethod
    def _release_to_production(context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        # Sem confirmacao: a versao anterior do StatusDialog nao pedia confirmacao
        # para liberar, e esta fase pede para nao inventar uma so por padronizacao visual.
        observation = dialog.observation.toPlainText().strip()
        dialog._run_background_action(
            lambda: dialog.service.update_status(context.proposal_id, action.area, "LIBERADO_PRODUCAO", observation),
            reload_on_success=True,
        )
        return ActionResult(success=True, changed=True, refresh_required=True, close_action_center=False)

    @staticmethod
    def _cancel(context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        observation = dialog.observation.toPlainText().strip()
        if not observation:
            QMessageBox.warning(dialog, "Cancelar proposta", "Informe o motivo do cancelamento na observacao.")
            return ActionResult(success=True, changed=False, close_action_center=False)
        answer = QMessageBox.question(
            dialog,
            "Cancelar proposta",
            f"Cancelar definitivamente a proposta {context.proposal_number} — {context.client_name or '-'}?\n\n"
            "Esta operacao nao pode ser desfeita pela tela e ficara registrada na auditoria.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return ActionResult(success=True, changed=False, close_action_center=False)
        dialog._run_background_action(
            lambda: dialog.service.update_status(context.proposal_id, action.area, "CANCELADA", observation)
        )
        return ActionResult(success=True, changed=True, refresh_required=True)
