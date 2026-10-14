from __future__ import annotations

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult
from app.ui.delivery_wizard import DeliveryWizardDialog


class ExpeditionStatusHandler:
    """STATUS na Expedicao: Iniciar separacao (SEPARACAO_INICIADA) e
    Registrar separacao (SEPARADO) sao transicoes simples de proposta. O
    sistema atual nao possui nenhum dialogo de selecao de itens para
    nenhuma das duas (o service aceita item_ids, mas nenhuma tela jamais os
    preencheu para esta acao) - preservamos exatamente esse comportamento:
    chama `service.update_status(process_id, "EXPEDICAO", status,
    observacao)` sem item_ids, como o StatusDialog monolitico sempre fez.
    Fica aberta e recarrega o contexto apos sucesso, como pedido
    explicitamente pela Fase 5 para estas duas acoes."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        status = action.status
        observation = dialog.observation.toPlainText().strip()
        dialog._run_background_action(
            lambda: dialog.service.update_status(context.proposal_id, action.area, status, observation),
            reload_on_success=True,
        )
        return ActionResult(success=True, changed=True, refresh_required=True, close_action_center=False)


class RegisterDeliveryHandler:
    """REGISTER_DELIVERY: abre o assistente de retirada do cliente (itens,
    revisao e conclusao numa janela so). A central de acoes sai da tela
    enquanto ele esta aberto. ENTREGUE vs ENTREGUE_PARCIAL vem da selecao
    real do usuario; proposta sem item pendente e entregue direto."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        parent = dialog.parentWidget() or dialog
        observation = dialog.observation.toPlainText().strip()
        dialog.hide()
        wizard = DeliveryWizardDialog(dialog.service, [context.proposal_id], parent, observation=observation)
        wizard.exec()
        if wizard.registered:
            dialog.accept()
            return ActionResult(success=True, changed=True, refresh_required=True)
        dialog.reject()
        return ActionResult(success=True, changed=False, close_action_center=True)
