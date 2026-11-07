"""Metodos de "Desfazer ultima acao" para os Fakes de service que a Central de Acoes e os
Detalhes tocam: a proposta nao tem acao para desfazer e qualquer tentativa de desfazer
falha alto (nunca abre QMessageBox real nem esconde um erro)."""

from __future__ import annotations


class NoUndoActionMixin:
    def undo_candidate(self, process_id):
        return {
            "proposal_id": process_id, "proposal_version": 1, "action": None, "handler": None, "undo_class": None,
            "undoable": False, "can_undo": False, "blockers": [], "changes": [], "side_effects": [],
            "cannot_undo_reason": "Nao ha nenhuma acao para desfazer nesta proposta.",
        }

    def undo_last_action(self, *args, **kwargs):
        raise AssertionError("desfazer nao era esperado neste teste")
