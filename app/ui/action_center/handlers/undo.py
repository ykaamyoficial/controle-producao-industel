from __future__ import annotations

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult
from app.ui.action_center.undo_dialog import UndoActionDialog


class UndoLastActionHandler:
    """UNDO_LAST_ACTION: abre o dialogo de desfazer a ultima acao da proposta.
    O candidato ja consultado pelo provider segue no descriptor; se estiver
    velho, a API responde com conflito de versao e o dialogo se recarrega. Quem
    decide se pode desfazer e a API - o handler so roteia."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        undo = UndoActionDialog(dialog.service, context.proposal_id, dialog, candidate=action.raw.get("candidate"))
        if undo.exec():
            dialog.accept()
            return ActionResult(success=True, changed=True, refresh_required=True)
        return ActionResult(success=True, changed=False, close_action_center=False)
