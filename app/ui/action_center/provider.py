from __future__ import annotations

from typing import Protocol

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionCategory, ActionDescriptor
from app.ui.icons import AppIcons

# Visual-only remaps: keep the label/status/permission logic in backend_adapter.py untouched,
# only pick a more legible icon glyph for a handful of well-known actions. Keyed by action id,
# by (id, target status) when the id alone is shared by several unrelated transitions (e.g.
# "STATUS" covers start/pause/cancel/deliver/etc across areas), or by (id, status, area) on the
# rare case where the same (id, status) pair means different things in different areas (e.g.
# "STATUS"/"SEPARADO" is both Almoxarifado's "separacao concluida" and Expedicao's "registrar
# separacao"). Lookup tries the most specific key first - see `_lookup()`.
ICON_OVERRIDES = {
    "DEFINE_ITEM_FLOW": AppIcons.WORKFLOW,
    "EDIT_ITEM_WEIGHTS": AppIcons.SCALE,
    "REGISTER_PRODUCTION": AppIcons.SUCCESS,
    ("STATUS", "INICIADO"): AppIcons.CIRCLE_PLAY,
    ("STATUS", "PARADO"): AppIcons.CIRCLE_PAUSE,
    # Backend sends icon="delete" (Controle Geral) for Cancelar proposta - there is no
    # AppIcons.DELETE, REMOVE ("trash-2") is the closest existing semantic match.
    ("STATUS", "CANCELADA"): AppIcons.REMOVE,
}
# Curated, desktop-only copy for the action cards. Actions without an entry here simply show
# icon + title, which the card component already supports.
ACTION_DESCRIPTIONS = {
    "DEFINE_ITEM_FLOW": "Escolha quais itens serao produzidos e galvanizados.",
    "REGISTER_PRODUCTION": "Informe as quantidades produzidas de cada item.",
    "EDIT_ITEM_WEIGHTS": "Cadastre ou atualize os pesos dos itens.",
    "REGISTER_DELIVERY": "Registre os itens efetivamente retirados pelo cliente.",
    "MANAGE_LOAD_EXISTING": "Escolha uma carga aberta e adicione as propostas selecionadas a ela.",
    "MANAGE_LOAD_NEW": "Cria uma carga nova ja com as propostas selecionadas.",
    "REGISTER_RETURN": "Resolve a carga certa e registra o retorno das propostas selecionadas.",
    ("STATUS", "PARADO"): "Suspende temporariamente a producao desta proposta.",
    ("STATUS", "INICIADO"): "Inicia ou retoma a fabricacao dos itens liberados.",
    ("STATUS", "LIBERADO_PRODUCAO"): "Envia a proposta para o processo produtivo.",
    ("STATUS", "CANCELADA"): "Cancela esta proposta conforme as regras atuais do sistema.",
    ("STATUS", "EM_SEPARACAO"): "Indica que esta proposta precisa de itens do almoxarifado.",
    ("STATUS", "SEM_PARAFUSOS"): "Indica que esta proposta nao precisa de itens do almoxarifado.",
    ("STATUS", "SEPARADO"): "Confirma que a separacao dos itens do almoxarifado foi concluida.",
    ("STATUS", "ALMOXARIFADO_ENTREGUE"): "Confirma a entrega completa dos itens do almoxarifado.",
    ("STATUS", "ALMOXARIFADO_ENTREGUE_PARCIAL"): "Registra a entrega parcial dos itens do almoxarifado.",
    ("STATUS", "SEPARACAO_INICIADA"): "Inicia a separacao dos itens desta proposta na expedicao.",
    # "SEPARADO" is ambiguous between areas (see comment on ICON_OVERRIDES) - scoped to Expedicao
    # so it never shadows Almoxarifado's ("STATUS", "SEPARADO") entry above.
    ("STATUS", "SEPARADO", "EXPEDICAO"): "Registre os itens desta proposta que ja foram separados.",
}
# Actions that represent moving the proposal's main operation forward - the first (id, status,
# area) triple present becomes the "primary" card (status/area=None matches anything). If none
# is present, no card is forced primary - safer than guessing (see primary_action_index). area is
# only needed when the same (id, status) pair is shared by more than one area with different
# priority (see "SEPARADO" above).
PRIMARY_ACTION_KEYS = (
    ("REGISTER_PRODUCTION", None, None),
    ("REGISTER_GALVANIZATION_RETURN", None, None),
    ("REGISTER_DELIVERY", None, None),
    ("MANAGE_LOAD", None, None),
    ("STATUS", "INICIADO", None),
    ("STATUS", "LIBERADO_PRODUCAO", None),
    ("STATUS", "SEPARACAO_INICIADA", "EXPEDICAO"),
    ("STATUS", "SEPARADO", "EXPEDICAO"),
)
# Statuses that pause/suspend a flow (not destructive) get the discreet "attention" treatment.
WARNING_STATUSES = ("PARADO",)
# Statuses that permanently end a proposal get the "destructive" treatment. Checked before
# WARNING/PRIMARY so a destructive transition is never mistaken for either.
DESTRUCTIVE_STATUSES = ("CANCELADA",)
AREA_COLOR_KEYS = {
    "CONTROLE GERAL": "area_control",
    "PRODUCAO": "area_production",
    "GALVANIZACAO": "area_galvanization",
    "EXPEDICAO": "area_expedition",
    "ALMOXARIFADO": "area_stock",
}


def _lookup(table: dict, action: dict[str, str], default=None):
    """Tries the most specific key first: (id, status, area), then (id,
    status), then plain id. Lets a handful of area-ambiguous (id, status)
    pairs (e.g. "STATUS"/"SEPARADO") be overridden per-area without
    disturbing the unscoped entries every other action relies on."""
    id_ = action["id"]
    status = action.get("status", "")
    area = action.get("area", "")
    if (id_, status, area) in table:
        return table[(id_, status, area)]
    if (id_, status) in table:
        return table[(id_, status)]
    return table.get(id_, default)


def action_description(action: dict[str, str]) -> str:
    return _lookup(ACTION_DESCRIPTIONS, action, "")


def action_icon(action: dict[str, str]):
    return _lookup(ICON_OVERRIDES, action, action["icon"])


def primary_action_index(actions: list[dict[str, str]]) -> int:
    """A acao principal reflete o estado atual da proposta (ja calculado
    pelo backend em `actions`) - nunca escolhe uma auxiliar (definir
    fluxo/pesos) so porque ela apareceu primeiro na lista. Se nenhuma
    acao "de avanco" estiver disponivel neste status, nenhum card vira
    primary (mais seguro que adivinhar)."""
    for action_id, target_status, target_area in PRIMARY_ACTION_KEYS:
        for index, action in enumerate(actions):
            if action["id"] != action_id:
                continue
            if target_status is not None and action.get("status") != target_status:
                continue
            if target_area is not None and action.get("area") != target_area:
                continue
            return index
    return -1


def action_category(action: dict[str, str], index: int, primary_index: int) -> ActionCategory:
    if action.get("status") in DESTRUCTIVE_STATUSES:
        return ActionCategory.DESTRUCTIVE
    if action.get("status") in WARNING_STATUSES:
        return ActionCategory.ATTENTION
    if index == primary_index:
        return ActionCategory.PRIMARY
    return ActionCategory.NORMAL


CATEGORY_TO_CARD_TYPE = {
    ActionCategory.PRIMARY: "primary",
    ActionCategory.NORMAL: "secondary",
    ActionCategory.ATTENTION: "warning",
    ActionCategory.DESTRUCTIVE: "destructive",
}


class ProposalActionProvider(Protocol):
    """Converts the domain's available actions into presentation descriptors.
    Never decides which actions exist - that's the domain's job."""

    def get_actions(self, context: ProposalActionContext) -> list[ActionDescriptor]: ...


class BackendActionProvider:
    """Generic provider backed by `service.process_actions()` (the existing,
    already-authoritative source of which actions are available for a given
    proposal/area/user). Reads the area from the context it receives - the
    same area the Action Center already resolved - instead of caching its
    own, so there is a single place that decides "which area". Nesta fase, a
    unica instancia real e a de Producao, passada explicitamente por
    StatusDialog - nenhum provider vazio e criado so para preencher a
    arquitetura."""

    def __init__(self, service):
        self.service = service

    def get_actions(self, context: ProposalActionContext) -> list[ActionDescriptor]:
        try:
            raw_actions = self.service.process_actions(context.proposal_id, context.area, row_context=context.proposal_data)
        except TypeError:
            # Compatibilidade com adaptadores/test doubles antigos que ainda
            # expõem somente (process_id, area).
            raw_actions = self.service.process_actions(context.proposal_id, context.area)
        primary_index = primary_action_index(raw_actions)
        return [
            ActionDescriptor(
                id=action["id"],
                label=action["label"],
                description=action_description(action),
                icon=action_icon(action),
                category=action_category(action, index, primary_index),
                area=action.get("area", context.area),
                order=index,
                status=action.get("status", ""),
                raw=action,
            )
            for index, action in enumerate(raw_actions)
        ]


# Loads whose status still represents an open operational relationship with the
# proposal - kept in sync with the identical filter in
# app/ui/action_center/handlers/galvanization.py (ACTIVE_LOAD_STATUSES).
_ACTIVE_GALVANIZATION_LOAD_STATUSES = ("AGUARDANDO_LIBERACAO", "LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL")


class GalvanizationActionProvider:
    """Envolve `BackendActionProvider` e, somente para GALVANIZACAO,
    acrescenta um descriptor de navegacao (OPEN_RELATED_GALVANIZATION_LOAD)
    quando a proposta tem uma carga ativa relacionada. Esta acao nunca vem
    do backend - e puramente de UI/roteamento (Fase 6, secao 15) - por isso
    e a unica montada aqui em vez de em `process_actions()`. Para qualquer
    outra area, delega 100% ao provider generico (Fase 6, secao 7: reusar
    antes de criar provider novo)."""

    def __init__(self, service):
        self.service = service
        self._inner = BackendActionProvider(service)

    def get_actions(self, context: ProposalActionContext) -> list[ActionDescriptor]:
        actions = self._inner.get_actions(context)
        if context.area != "GALVANIZACAO":
            return actions
        actions = self._split_manage_load(actions)
        try:
            loads = self.service.process_loads(context.proposal_id)
        except Exception:
            return actions
        relevant = [row for row in loads if (row.get("status") or "") in _ACTIVE_GALVANIZATION_LOAD_STATUSES]
        if not relevant:
            return actions
        if len(relevant) == 1:
            label = f"Abrir carga #{relevant[0]['id']}"
            description = "Consulte situação, itens e retorno desta carga."
        else:
            label = "Ver cargas da proposta"
            description = "Esta proposta possui mais de uma carga ativa. Escolha qual deseja abrir."
        return [
            *actions,
            ActionDescriptor(
                id="OPEN_RELATED_GALVANIZATION_LOAD",
                label=label,
                description=description,
                icon=AppIcons.CARGO,
                category=ActionCategory.NORMAL,
                area=context.area,
                order=len(actions),
                status="",
                raw={"load_ids": [int(row["id"]) for row in relevant]},
            ),
        ]

    @staticmethod
    def _split_manage_load(actions: list[ActionDescriptor]) -> list[ActionDescriptor]:
        """O backend devolve MANAGE_LOAD como uma unica acao ("Adicionar a
        uma carga"), mas a UX pede dois caminhos explicitos - carga
        existente ou criar nova (Fase 8, mesmo tratamento ja usado no lote
        em `BatchProposalActionCenter`). O split e puramente de
        apresentacao/roteamento: o backend continua sendo a unica
        autoridade sobre SE a proposta pode entrar em carga -
        `process_actions()` ja decidiu isso antes de MANAGE_LOAD chegar
        aqui; nunca QUAL carga, nem se pode, e decidido neste metodo."""
        result: list[ActionDescriptor] = []
        for action in actions:
            if action.id != "MANAGE_LOAD":
                result.append(action)
                continue
            result.append(ActionDescriptor(
                id="MANAGE_LOAD_EXISTING",
                label="Adicionar a uma carga existente",
                description=action_description({"id": "MANAGE_LOAD_EXISTING", "status": "", "area": action.area}),
                icon=action.icon,
                category=ActionCategory.NORMAL,
                area=action.area,
                order=action.order,
                status=action.status,
                raw=action.raw,
            ))
            result.append(ActionDescriptor(
                id="MANAGE_LOAD_NEW",
                label="Criar nova carga",
                description=action_description({"id": "MANAGE_LOAD_NEW", "status": "", "area": action.area}),
                icon=AppIcons.NEW,
                category=ActionCategory.NORMAL,
                area=action.area,
                order=action.order + 1,
                status=action.status,
                raw=action.raw,
            ))
        return result
