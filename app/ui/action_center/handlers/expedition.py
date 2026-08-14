from __future__ import annotations

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult
from app.ui.item_selection_dialog import ItemSelectionDialog


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
    """REGISTER_DELIVERY: abre o dialogo oficial de selecao de itens
    (`ItemSelectionDialog`, modo "delivery") quando existem itens pendentes
    de retirada, decide ENTREGUE vs ENTREGUE_PARCIAL a partir da selecao
    real do usuario (nunca assume "todos os itens" so porque a proposta
    esta na Expedicao) e delega ao service oficial. Migrado sem alteracao
    de logica do LegacyActionHandler que o StatusDialog monolitico usava -
    continua fechando a Central em sucesso, igual aos demais handlers que
    abrem um dialogo especializado de itens (ex.: RegisterProductionHandler)."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        observation = dialog.observation.toPlainText().strip()
        available = dialog.service.proposal_items(context.proposal_id, pending_delivery=True)
        if available:
            selector = ItemSelectionDialog(
                dialog.service, context.proposal_id, "delivery", dialog, allow_full_selection=True
            )
            selector.setWindowTitle("Registrar itens retirados pelo cliente")
            if not selector.exec():
                return ActionResult(success=True, changed=False, close_action_center=False)
            status = "ENTREGUE" if len(selector.selected_ids) == len(available) else "ENTREGUE_PARCIAL"
            selected_ids = list(selector.selected_ids)
            dialog._run_background_action(
                lambda: dialog.service.update_status(
                    context.proposal_id, action.area, status, observation, selected_ids
                )
            )
        else:
            dialog._run_background_action(
                lambda: dialog.service.update_status(context.proposal_id, action.area, "ENTREGUE", observation)
            )
        return ActionResult(success=True, changed=True, refresh_required=True)
