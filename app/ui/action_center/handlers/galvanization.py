from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout,
)

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.galvanization_load_details_dialog import GalvanizationLoadDetailsDialog
from app.ui.galvanization_load_dialog import (
    GalvanizationLoadDialog, GalvanizationReturnDialog,
)
from app.ui.icons import AppIcons

# Loads whose status still represents an open operational relationship with the
# proposal. Mirrors the filter `BackendAdapter.process_actions()` already applies
# before offering REGISTER_GALVANIZATION_RETURN - a closed/returned load
# (RETORNADA_GALVANIZACAO) is history, never "the current carga" for navigation
# or eligibility purposes.
ACTIVE_LOAD_STATUSES = ("AGUARDANDO_LIBERACAO", "LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL")
# Unico status em que uma carga ainda aceita novas propostas - mesma regra
# que GalvanizationLoadManagerDialog.edit_load() ja aplicava ("Apenas cargas
# aguardando liberacao podem ser editadas").
OPEN_FOR_ADDITION_STATUS = "AGUARDANDO_LIBERACAO"

_LOAD_STATUS_LABELS = {
    "AGUARDANDO_LIBERACAO": "Aguardando liberação",
    "LIBERADA_PARA_ENVIO": "Liberada para envio",
    "RETORNO_PARCIAL": "Retorno parcial",
    "RETORNADA_GALVANIZACAO": "Retornada da galvanização",
}


def relevant_galvanization_loads(service, proposal_id: int) -> list[dict]:
    """Cargas ativas relacionadas a proposal_id - usado tanto pelo provider
    (para decidir se o card de navegacao existe) quanto pelo handler (para
    resolver de novo no clique, nunca confiando num snapshot tirado quando a
    Central abriu: outro usuario pode ter liberado/fechado a carga enquanto
    a Central estava aberta - Fase 6, secao 43)."""
    try:
        loads = service.process_loads(proposal_id)
    except Exception:
        return []
    return [row for row in loads if (row.get("status") or "") in ACTIVE_LOAD_STATUSES]


class ManageGalvanizationLoadExistingHandler:
    """MANAGE_LOAD_EXISTING: mostra a lista de cargas abertas (aguardando
    liberacao) e adiciona a proposta a carga escolhida (Fase 8 - divisao de
    MANAGE_LOAD em "carga existente" vs "criar nova", mesmo tratamento
    dado ao lote em `BatchProposalActionCenter`). Elegibilidade de
    item/saldo continua exclusivamente no `GalvanizationLoadDialog`/service
    oficial - nada e decidido aqui."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        load_id = choose_existing_load_for_addition(dialog.service, dialog)
        if load_id is None:
            return ActionResult(success=True, changed=False, close_action_center=False)
        try:
            result = dialog.service.add_items_to_galvanization_load(
                load_id,
                proposal_ids=[context.proposal_id],
            )
        except Exception as exc:
            QMessageBox.warning(dialog, "Adicionar a uma carga", str(exc))
            return ActionResult(success=False, changed=False, close_action_center=False)
        added_items = result.get("added_item_ids") or [] if isinstance(result, dict) else []
        QMessageBox.information(
            dialog,
            "Carga atualizada",
            f"A proposta {context.proposal_number} foi adicionada à carga #{load_id}.\n"
            f"Itens adicionados: {len(added_items)}.",
        )
        dialog.accept()
        return ActionResult(success=True, changed=True, refresh_required=True)


class ManageGalvanizationLoadNewHandler:
    """MANAGE_LOAD_NEW: cria uma carga nova ja com a proposta selecionada -
    vai direto para `GalvanizationLoadDialog`, sem passar pelo gerenciador
    generico de cargas."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        load_dialog = GalvanizationLoadDialog(dialog.service, [context.proposal_id], parent=dialog)
        if load_dialog.exec():
            dialog.accept()
            return ActionResult(success=True, changed=True, refresh_required=True)
        return ActionResult(success=True, changed=False, close_action_center=False)


class _SelectGalvanizationLoadDialog(QDialog):
    """Escolha explicita entre varias cargas - usado tanto para navegacao
    (mais de uma carga ativa relacionada a proposta, Fase 6 secao 19) quanto
    para escolher a carga de destino ao adicionar propostas a uma carga
    existente (Fase 8). A tela nunca abre/usa uma carga arbitraria."""

    def __init__(
        self,
        loads: list[dict],
        parent=None,
        *,
        title: str = "Cargas da proposta",
        prompt: str = "Esta proposta possui mais de uma carga ativa. Escolha qual deseja abrir:",
        confirm_label: str = "Abrir carga",
    ):
        super().__init__(parent)
        self.selected_load_id: int | None = None
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        style_dialog_from_parent(self, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)
        root.addWidget(QLabel(prompt))

        self.list_widget = QListWidget()
        for load in loads:
            status_label = _LOAD_STATUS_LABELS.get(load.get("status") or "", load.get("status") or "-")
            item = QListWidgetItem(f"Carga #{load.get('id')} — {status_label}")
            item.setData(Qt.UserRole, int(load["id"]))
            self.list_widget.addItem(item)
        self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_selected())
        root.addWidget(self.list_widget)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel = ModernButton("Cancelar", AppIcons.CLOSE)
        confirm_button = ModernButton(confirm_label, AppIcons.CARGO, accent=True)
        cancel.clicked.connect(self.reject)
        confirm_button.clicked.connect(self._accept_selected)
        footer.addWidget(cancel)
        footer.addWidget(confirm_button)
        root.addLayout(footer)

    def _accept_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.warning(self, "Cargas da proposta", "Selecione uma carga.")
            return
        self.selected_load_id = item.data(Qt.UserRole)
        self.accept()


def choose_existing_load_for_addition(service, parent) -> int | None:
    """Mostra a lista de cargas ainda abertas (aguardando liberacao, logo
    ainda aceitam novas propostas) e devolve o load_id escolhido. `None`
    significa "nao prossiga" - ou nao ha cargas disponiveis (mensagem ja
    mostrada) ou o usuario cancelou a escolha."""
    try:
        loads = service.galvanization_loads()
    except Exception:
        loads = []
    open_loads = [row for row in loads if (row.get("status") or "") == OPEN_FOR_ADDITION_STATUS]
    if not open_loads:
        QMessageBox.information(
            parent,
            "Adicionar a uma carga",
            'Não há cargas abertas (aguardando liberação) no momento. Use "Criar nova carga" para iniciar uma.',
        )
        return None
    chooser = _SelectGalvanizationLoadDialog(
        open_loads,
        parent,
        title="Cargas disponíveis",
        prompt="Escolha a carga em que deseja incluir as propostas selecionadas:",
        confirm_label="Adicionar a esta carga",
    )
    if not chooser.exec() or chooser.selected_load_id is None:
        return None
    return int(chooser.selected_load_id)


RETURNABLE_LOAD_STATUSES = ("LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL")


def resolve_return_load_ids(service, proposal_ids: list[int], parent) -> list[int]:
    """Resolve TODAS as cargas retornaveis relacionadas ao conjunto de
    propostas selecionado (Propostas ou Itens da Galvanizacao > Acoes >
    Registrar retorno). Uma proposta pode ter itens em mais de uma carga
    ativa ao mesmo tempo, e a selecao do usuario pode abranger propostas de
    cargas diferentes de proposito - quem usa o resultado abre uma unica
    `GalvanizationReturnDialog` com todas as cargas retornadas aqui
    (`load_ids[0]` + `extra_load_ids=load_ids[1:]`); a tela mostra as
    propostas de todas elas juntas, com uma coluna "Carga" para
    diferenciar, mesmo que o backend continue exigindo uma chamada por
    carga por baixo dos panos (o endpoint e por carga). Lista vazia
    significa "nao prossiga" (mensagem ja mostrada)."""
    loads_by_id: dict[int, dict] = {}
    for proposal_id in dict.fromkeys(int(value) for value in proposal_ids if value):
        try:
            loads = service.process_loads(proposal_id)
        except Exception:
            loads = []
        for load in loads:
            if (load.get("status") or "") in RETURNABLE_LOAD_STATUSES:
                loads_by_id[int(load["id"])] = load
    if not loads_by_id:
        QMessageBox.information(
            parent, "Registrar retorno", "Não há carga ativa com saldo pendente para a seleção."
        )
        return []
    return sorted(loads_by_id)


class OpenRelatedGalvanizationLoadHandler:
    """OPEN_RELATED_GALVANIZATION_LOAD: acao de navegacao, nao de status
    (Fase 6, secao 15) - resolve a(s) carga(s) relevante(s) da proposta e
    abre `GalvanizationLoadDetailsDialog`. Nao decide elegibilidade nem
    regra de retorno: se a carga relevante deixou de existir entre a
    abertura da Central e o clique, mostra mensagem controlada e recarrega
    o contexto em vez de crashar ou escolher uma carga arbitraria (secoes
    41-43)."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        loads = relevant_galvanization_loads(dialog.service, context.proposal_id)
        if not loads:
            QMessageBox.information(
                dialog,
                "Carga de galvanização",
                "A carga relacionada não está mais disponível. Atualize os dados da proposta.",
            )
            dialog.reload_context()
            return ActionResult(success=True, changed=False, close_action_center=False)
        if len(loads) == 1:
            load_id = int(loads[0]["id"])
        else:
            chooser = _SelectGalvanizationLoadDialog(loads, dialog)
            if not chooser.exec() or chooser.selected_load_id is None:
                return ActionResult(success=True, changed=False, close_action_center=False)
            load_id = int(chooser.selected_load_id)
        details_dialog = GalvanizationLoadDetailsDialog(dialog.service, load_id, dialog)
        details_dialog.exec()
        if details_dialog.changed:
            # Nao passa por `_run_background_action` (nenhuma chamada de escrita e
            # feita por este handler - quem grava e o GalvanizationLoadDetailsDialog),
            # entao marcamos `_changed_since_open` aqui, do mesmo jeito que
            # `_action_success` faria: fechar a Central depois disso (Fechar/Escape)
            # ainda deve contar como "houve mudanca" para o ProcessPage recarregar.
            dialog._changed_since_open = True
            dialog.reload_context()
            return ActionResult(success=True, changed=True, refresh_required=True, close_action_center=False)
        return ActionResult(success=True, changed=False, close_action_center=False)


def register_galvanization_return_legacy(context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
    """REGISTER_GALVANIZATION_RETURN (Galvanizacao): compatibilidade
    temporaria (Fase 6, secoes 21-25) - o fluxo preferencial passa a ser
    Proposta -> Abrir carga -> Registrar retorno, mas esta entrada direta
    continua funcionando ate a navegacao proposta->carga estar comprovada
    em producao. Relocada de status_dialog.py sem nenhuma alteracao de
    logica; ainda roteada via LegacyActionHandler de proposito."""
    active_loads = [
        row for row in dialog.service.process_loads(context.proposal_id)
        if (row.get("status") or "") in ("LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL")
    ]
    if not active_loads:
        QMessageBox.information(
            dialog, "Retorno da galvanizacao", "Esta proposta nao possui carga ativa liberada para retorno."
        )
        return ActionResult(success=True, changed=False, close_action_center=False)
    # A acao foi aberta a partir de uma proposta. Mesmo que ela tenha itens
    # em mais de uma carga, o escopo do retorno deve continuar sendo somente
    # essa proposta. O dialogo ja possui o seletor de itens e agrupa a escrita
    # por carga internamente.
    load_ids = [int(row["id"]) for row in active_loads]
    return_dialog = GalvanizationReturnDialog(
        dialog.service,
        load_ids[0],
        dialog,
        proposal_ids=[int(context.proposal_id)],
        extra_load_ids=load_ids[1:],
    )
    if return_dialog.exec():
        dialog.accept()
        return ActionResult(success=True, changed=True, refresh_required=True)
    return ActionResult(success=True, changed=False, close_action_center=False)
