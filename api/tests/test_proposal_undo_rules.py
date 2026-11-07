"""Regras puras do desfazer (api/app/modules/proposals/undo.py): grupos, pilha, classificacao, avaliacao dos
handlers e permissao. Sem banco - os caminhos HTTP/PostgreSQL ficam em test_proposal_undo.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from api.app.core import error_codes
from api.app.modules.almox_integration.state import almox_state
from api.app.modules.almox_integration.tracker import PendingTransitions
from api.app.modules.auth import permissions as perms
from api.app.modules.proposals import undo
from api.app.modules.proposals.service import _activity_headline, _history_observation, _NOTIFY_PROPOSAL_EVENTS

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_seq = iter(range(1, 10_000))


def ev(event_type, request_id, *, minutes=0, source="proposal", actor=1, metadata=None, **kwargs) -> undo.EventRef:
    return undo.EventRef(
        source=source, id=next(_seq), event_type=event_type, request_id=request_id, actor_user_id=actor,
        created_at=T0 + timedelta(minutes=minutes), metadata=metadata or {}, **kwargs,
    )


def proposal(**overrides):
    values = dict(
        id=10, version=5, is_cancelled=False, is_completed=False, is_partial=False,
        current_area="PRODUCAO", current_status="LIBERADO_PRODUCAO", general_status="EM_PRODUCAO",
        production_status="NAO_INICIADO", galvanization_status=None, shipping_status=None,
        warehouse_status=None, flow_situation="NORMAL", has_production_pending=False,
        updated_by=None, updated_at=None, expedition_items=[],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def user(user_id=1, *, superuser=False, permissions=()):
    return SimpleNamespace(
        id=user_id, is_superuser=superuser, active=True, roles=[],
        _perms=set(permissions),
    )


@pytest.fixture(autouse=True)
def _permissions(monkeypatch):
    monkeypatch.setattr(undo, "user_has_permission", lambda actor, code: actor.is_superuser or code in actor._perms)


def ctx(group_events, current, exp_items=()):
    groups = undo.build_groups(group_events)
    assert len(groups) == 1
    return undo.UndoContext(proposal=current, group=groups[0], exp_items={int(i.id): i for i in exp_items})


INITIAL_SNAPSHOT = {
    "current_area": "CONTROLE_GERAL", "current_status": "AGUARDANDO_LIBERACAO", "general_status": "AGUARDANDO_LIBERACAO",
    "production_status": None, "galvanization_status": None, "shipping_status": None, "warehouse_status": None,
    "flow_situation": None, "has_production_pending": False, "is_completed": False,
}


def release_event(request_id="rid-release", **metadata):
    return ev(
        "PROPOSAL_STATUS_CHANGED", request_id, from_area="CONTROLE_GERAL", from_status="AGUARDANDO_LIBERACAO",
        to_area="PRODUCAO", to_status="LIBERADO_PRODUCAO", metadata={"previous_state": INITIAL_SNAPSHOT, **metadata},
    )


# --- pilha (LIFO) -------------------------------------------------------------------------------


def test_sem_eventos_nao_ha_candidato():
    assert undo.pick_latest(undo.build_groups([])) is None


def test_candidato_e_o_grupo_mais_recente_por_request_id():
    events = [
        ev("PROPOSAL_CREATED", "r1", minutes=0),
        ev("PROPOSAL_STATUS_CHANGED", "r2", minutes=1),
        ev("PRODUCTION_STARTED", "r3", minutes=2),
        ev("PRODUCTION_STARTED", "r3", minutes=2, source="expedition"),
    ]
    latest = undo.pick_latest(undo.build_groups(events))
    assert latest.request_id == "r3"
    assert len(latest.events) == 2


def test_grupo_desfeito_e_o_proprio_desfazer_saem_da_pilha():
    events = [
        ev("PROPOSAL_CREATED", "r1", minutes=0),
        ev("PROPOSAL_STATUS_CHANGED", "r2", minutes=1),
        ev("PRODUCTION_STARTED", "r3", minutes=2),
        ev(undo.ACTION_UNDONE, "r4", minutes=3, metadata={"undone_request_id": "r3"}),
    ]
    groups = undo.build_groups(events)
    by_id = {g.request_id: g for g in groups}
    assert by_id["r3"].undone and by_id["r4"].is_undo and not by_id["r2"].undone
    assert undo.pick_latest(groups).request_id == "r2"


def test_desfazer_em_cadeia_chega_ate_a_criacao_e_acaba():
    events = [
        ev("PROPOSAL_CREATED", "r1", minutes=0),
        ev("PROPOSAL_STATUS_CHANGED", "r2", minutes=1),
        ev(undo.ACTION_UNDONE, "r3", minutes=2, metadata={"undone_request_id": "r2"}),
    ]
    assert undo.pick_latest(undo.build_groups(events)).request_id == "r1"


def test_almoxarifado_e_fiscal_tem_pilha_propria():
    events = [
        ev("PRODUCTION_STARTED", "r-prod", minutes=0),
        ev("WAREHOUSE_STATUS_CHANGED", "r-almox", minutes=1),
        ev("FISCAL_INVOICE_REGISTERED", "r-fiscal", minutes=2, source="fiscal"),
    ]
    groups = undo.build_groups(events)
    # a ultima acao do fluxo geral ignora Almox e Fiscal, mesmo sendo mais antiga
    assert undo.pick_latest(groups).request_id == "r-prod"
    assert undo.pick_latest(groups, undo.LANE_GENERAL).request_id == "r-prod"
    # e Almox/Fiscal nao enxergam o fluxo geral nem um ao outro
    assert undo.pick_latest(groups, undo.LANE_WAREHOUSE).request_id == "r-almox"
    assert undo.pick_latest(groups, undo.LANE_FISCAL).request_id == "r-fiscal"


def test_pista_sem_acoes_nao_tem_candidato():
    groups = undo.build_groups([ev("PRODUCTION_STARTED", "r1"), ev("WAREHOUSE_STATUS_CHANGED", "r2", minutes=1)])
    assert undo.pick_latest(groups, undo.LANE_FISCAL) is None


def test_evento_sem_request_id_e_um_grupo_proprio():
    events = [ev("PROPOSAL_STATUS_CHANGED", None, minutes=0), ev("PRODUCTION_STARTED", None, minutes=1)]
    groups = undo.build_groups(events)
    assert len(groups) == 2 and all(group.request_id is None for group in groups)


def test_mapa_de_desfeitos_por_proposta_e_request_id():
    mapped = undo.undone_event_map([
        (7, 10, undo.ACTION_UNDONE, {"undone_request_id": "r3"}),
        (9, 10, undo.ACTION_UNDONE, {"undone_request_id": "r3"}),
        (8, 11, undo.ACTION_UNDONE, {"undone_request_id": "r3"}),
        (5, 10, "PRODUCTION_STARTED", {}),
        (6, None, undo.ACTION_UNDONE, {"undone_request_id": "x"}),
    ])
    assert mapped == {(10, "r3"): 7, (11, "r3"): 8}


# --- classificacao ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("types", "name"),
    [
        ({"PROPOSAL_STATUS_CHANGED"}, "RELEASE_PROPOSAL"),
        ({"WAREHOUSE_STATUS_CHANGED"}, "WAREHOUSE_STATUS"),
        ({"PRODUCTION_STARTED"}, "START_PRODUCTION"),
        ({"PRODUCTION_PAUSED"}, "PAUSE_PRODUCTION"),
        ({"PRODUCTION_RESUMED"}, "RESUME_PRODUCTION"),
        ({"EXPEDITION_SEPARATION_STARTED"}, "START_SEPARATION"),
        ({"EXPEDITION_SEPARATION_RECALCULATED", "EXPEDITION_ITEM_SEPARATED"}, "SEPARATE_ITEMS"),
    ],
)
def test_classifica_cada_acao_da_v1(types, name):
    group = undo.build_groups([ev(t, "r") for t in types])[0]
    assert undo.classify(group).name == name


@pytest.mark.parametrize(
    "types",
    [
        {"PROPOSAL_STATUS_CHANGED", "PRODUCTION_FLOW_AUTO_ROUTED"},
        {"EXPEDITION_SEPARATION_RECALCULATED", "PARENT_PROPOSAL_REBORN"},
        {"PROPOSAL_CANCELLED"},
        {"PRODUCTION_ITEM_COMPLETED"},
    ],
)
def test_grupo_com_evento_extra_ou_acao_fora_da_v1_nao_tem_handler(types):
    assert undo.classify(undo.build_groups([ev(t, "r") for t in types])[0]) is None


@pytest.mark.parametrize(
    ("event_type", "label", "fragment"),
    [
        ("PROPOSAL_CANCELLED", "Cancelamento da proposta", "nova proposta"),
        ("COMPENSATED_REMANAGEMENT_APPLIED", "Remanejamento", "assistente de remanejamento"),
        ("PRODUCTION_ITEM_COMPLETED", "Conclusao de itens de producao", "correcao administrativa"),
        ("GALVANIZATION_ITEM_RETURNED", "Carga ou retorno de galvanizacao", "Galvanizacao"),
        ("GALVANIZATION_LOAD_CLOSED", "Carga ou retorno de galvanizacao", "Galvanizacao"),
        ("EXPEDITION_ITEM_DELIVERED", "Entrega", "correcao administrativa"),
        ("FISCAL_INVOICE_CANCELLED", "Nota fiscal", "aba Fiscal"),
        ("PROPOSAL_UPDATED", "Atualizacao da proposta", "Edite"),
        ("PROPOSAL_CREATED", "Criacao da proposta", "desative"),
    ],
)
def test_acoes_fora_da_v1_trazem_rotulo_e_alternativa(event_type, label, fragment):
    group = undo.build_groups([ev(event_type, "r")])[0]
    got_label, reason = undo.describe_unsupported(group)
    assert got_label == label and fragment in reason


def test_acao_conhecida_com_evento_extra_vira_motivo_composto():
    group = undo.build_groups([ev("PROPOSAL_STATUS_CHANGED", "r"), ev("PRODUCTION_FLOW_AUTO_ROUTED", "r")])[0]
    label, reason = undo.describe_unsupported(group)
    assert label == "Liberacao da proposta" and "outras partes" in reason


# --- permissao ----------------------------------------------------------------------------------


def test_permissao_exige_a_permissao_da_acao_e_ser_o_autor_ou_superusuario():
    handler = next(h for h in undo.HANDLERS if h.name == "START_PRODUCTION")
    group = undo.build_groups([ev("PRODUCTION_STARTED", "r", actor=7)])[0]
    author = user(7, permissions={perms.PRODUCTION_UPDATE})
    assert undo.permission_problem(author, handler, group) is None
    assert "permissao" in undo.permission_problem(user(7), handler, group)
    other = user(8, permissions={perms.PRODUCTION_UPDATE})
    assert "Somente quem fez a acao" in undo.permission_problem(other, handler, group)
    assert undo.permission_problem(user(9, superuser=True), handler, group) is None


def test_permissao_exigida_por_handler():
    required = {h.name: h.permission for h in undo.HANDLERS}
    assert required == {
        "RELEASE_PROPOSAL": perms.PROPOSALS_CHANGE_STATUS,
        "WAREHOUSE_STATUS": perms.PROPOSALS_CHANGE_STATUS,
        "START_PRODUCTION": perms.PRODUCTION_UPDATE,
        "PAUSE_PRODUCTION": perms.PRODUCTION_UPDATE,
        "RESUME_PRODUCTION": perms.PRODUCTION_UPDATE,
        "START_SEPARATION": perms.EXPEDITION_UPDATE,
        "SEPARATE_ITEMS": perms.EXPEDITION_UPDATE,
    }


# --- handlers -----------------------------------------------------------------------------------


def test_liberacao_restaura_o_estado_anterior_e_avisa_do_almox():
    result = undo._eval_release(ctx([release_event()], proposal()))
    assert not result.unsupported and not result.blockers
    assert result.proposal_restore["current_area"] == "CONTROLE_GERAL"
    assert [code for code, _ in result.side_effects] == ["ALMOX_NOT_NOTIFIED"]
    assert "conciliacao horaria" in result.side_effects[0][1]
    labels = {change.label for change in undo.build_changes(proposal(), result)}
    assert {"Area atual", "Status atual", "Status geral"} <= labels


def test_liberacao_bloqueada_se_a_producao_ja_comecou_ou_o_estado_mudou():
    started = proposal(production_status="INICIADO", current_status="INICIADO")
    codes = {code for code, _ in undo._eval_release(ctx([release_event()], started)).blockers}
    assert codes == {"STATE_CHANGED", "PRODUCTION_ALREADY_STARTED"}


def test_liberacao_cancelada_bloqueia():
    codes = {code for code, _ in undo._eval_release(ctx([release_event()], proposal(is_cancelled=True))).blockers}
    assert "PROPOSAL_CANCELLED" in codes


def test_evento_antigo_sem_snapshot_nao_e_desfazivel():
    old = ev("PROPOSAL_STATUS_CHANGED", "r", from_area="CONTROLE_GERAL", from_status="AGUARDANDO_LIBERACAO", to_area="PRODUCAO", to_status="LIBERADO_PRODUCAO")
    assert undo._eval_release(ctx([old], proposal())).unsupported == undo.NO_SNAPSHOT_REASON
    started = ev("PRODUCTION_STARTED", "r", from_status="NAO_INICIADO", to_status="INICIADO")
    assert undo._eval_production(ctx([started], proposal(production_status="INICIADO")), "PRODUCTION_STARTED").unsupported


def test_status_do_almoxarifado_usa_from_status_do_evento():
    event = ev("WAREHOUSE_STATUS_CHANGED", "r", from_status="AGUARDANDO_CONFIRMACAO", to_status="EM_SEPARACAO")
    result = undo._eval_warehouse(ctx([event], proposal(warehouse_status="EM_SEPARACAO")))
    assert not result.blockers and result.proposal_restore == {"warehouse_status": "AGUARDANDO_CONFIRMACAO"}
    stale = undo._eval_warehouse(ctx([event], proposal(warehouse_status="SEPARADO")))
    assert [code for code, _ in stale.blockers] == ["STATE_CHANGED"]

    exact = ev("WAREHOUSE_STATUS_CHANGED", "r", from_status="AGUARDANDO_CONFIRMACAO", to_status="EM_SEPARACAO", metadata={"previous_warehouse_status": None})
    assert undo._eval_warehouse(ctx([exact], proposal(warehouse_status="EM_SEPARACAO"))).proposal_restore == {"warehouse_status": None}


def test_iniciar_producao_restaura_snapshot_e_pausa_retomada_sao_inversas():
    snapshot = {**INITIAL_SNAPSHOT, "production_status": "NAO_INICIADO", "current_status": "LIBERADO_PRODUCAO", "general_status": "EM_PRODUCAO"}
    started = ev("PRODUCTION_STARTED", "r", from_status="NAO_INICIADO", to_status="INICIADO", metadata={"previous_state": snapshot})
    current = proposal(production_status="INICIADO", current_status="INICIADO")
    result = undo._eval_production(ctx([started], current), "PRODUCTION_STARTED")
    assert not result.blockers
    assert result.proposal_restore == {"production_status": "NAO_INICIADO", "current_status": "LIBERADO_PRODUCAO", "general_status": "EM_PRODUCAO"}

    paused = ev("PRODUCTION_PAUSED", "r", from_status="INICIADO", to_status="PARADO", metadata={"current_area": "PRODUCAO"})
    pause_result = undo._eval_production(ctx([paused], proposal(production_status="PARADO", current_status="PARADO")), "PRODUCTION_PAUSED")
    assert pause_result.proposal_restore == {"production_status": "INICIADO", "current_status": "INICIADO"}
    assert undo._eval_production(ctx([paused], proposal(production_status="INICIADO")), "PRODUCTION_PAUSED").blockers

    resumed = ev("PRODUCTION_RESUMED", "r", from_status="PARADO", to_status="INICIADO", metadata={"current_area": "PRODUCAO"})
    resume_result = undo._eval_production(ctx([resumed], proposal(production_status="INICIADO", current_status="INICIADO")), "PRODUCTION_RESUMED")
    assert resume_result.proposal_restore == {"production_status": "PARADO", "current_status": "PARADO"}


def _exp_item(item_id=1, **overrides):
    values = dict(
        id=item_id, status="SEPARACAO_INICIADA", separated_quantity=Decimal("0"), separation_started_at=T0, separated_at=None,
        version=3, updated_by=None, updated_at=None, proposal_item=SimpleNamespace(item_number="1"),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_iniciar_separacao_restaura_item_e_proposta():
    snapshot = {**INITIAL_SNAPSHOT, "current_area": "EXPEDICAO", "current_status": "EM_SEPARACAO", "shipping_status": "EM_SEPARACAO", "general_status": "EM_EXPEDICAO"}
    item_event = ev("EXPEDITION_SEPARATION_STARTED", "r", source="expedition", from_status="EM_SEPARACAO", to_status="SEPARACAO_INICIADA",
                    expedition_item_id=1, metadata={"previous_separation_started_at": None})
    proposal_event = ev("EXPEDITION_SEPARATION_STARTED", "r", from_area="EXPEDICAO", from_status="EM_SEPARACAO", to_area="EXPEDICAO",
                        to_status="SEPARACAO_INICIADA", metadata={"previous_state": snapshot})
    item = _exp_item()
    current = proposal(current_area="EXPEDICAO", current_status="SEPARACAO_INICIADA", shipping_status="SEPARACAO_INICIADA", general_status="EM_EXPEDICAO")
    result = undo._eval_start_separation(ctx([item_event, proposal_event], current, [item]))
    assert not result.blockers and not result.unsupported
    assert result.item_restores[0].values == {"status": "EM_SEPARACAO", "separation_started_at": None}
    assert result.proposal_restore["current_status"] == "EM_SEPARACAO"

    item.status = "SEPARADO"  # mudou depois da acao
    assert [code for code, _ in undo._eval_start_separation(ctx([item_event, proposal_event], current, [item])).blockers] == ["ITEM_CHANGED"]


def test_separar_itens_restaura_quantidade_e_bloqueia_se_a_quantidade_mudou():
    snapshot = {**INITIAL_SNAPSHOT, "current_area": "EXPEDICAO", "current_status": "SEPARACAO_INICIADA", "shipping_status": "SEPARACAO_INICIADA"}
    item_event = ev("EXPEDITION_ITEM_SEPARATED", "r", source="expedition", from_status="SEPARACAO_INICIADA", to_status="SEPARADO", expedition_item_id=1,
                    metadata={"quantity": "2", "previous_separated_quantity": "0.0000", "previous_separated_at": None})
    proposal_event = ev("EXPEDITION_SEPARATION_RECALCULATED", "r", to_area="EXPEDICAO", to_status="SEPARADO", metadata={"previous_state": snapshot})
    item = _exp_item(status="SEPARADO", separated_quantity=Decimal("2"), separated_at=T0)
    current = proposal(current_area="EXPEDICAO", current_status="SEPARADO", shipping_status="SEPARADO")
    result = undo._eval_separate_items(ctx([item_event, proposal_event], current, [item]))
    assert not result.blockers
    assert result.item_restores[0].values == {"status": "SEPARACAO_INICIADA", "separated_quantity": Decimal("0.0000"), "separated_at": None}
    change_fields = {change.field for change in undo.build_changes(current, result)}
    assert "items[1].separated_quantity" in change_fields

    item.separated_quantity = Decimal("3")
    assert [code for code, _ in undo._eval_separate_items(ctx([item_event, proposal_event], current, [item])).blockers] == ["ITEM_CHANGED"]


def test_aplicar_restaura_campos_incrementa_versoes_e_registra_antes_depois():
    current = proposal(current_area="PRODUCAO", current_status="LIBERADO_PRODUCAO")
    result = undo._eval_release(ctx([release_event()], current))
    snapshots = undo.apply_evaluation(current, result, actor_id=3)
    assert current.current_area == "CONTROLE_GERAL" and current.version == 6 and current.updated_by == 3
    assert snapshots["before"]["proposal"]["current_area"] == "PRODUCAO"
    assert snapshots["after"]["proposal"]["current_area"] == "CONTROLE_GERAL"


# --- integracoes laterais -----------------------------------------------------------------------


def test_desfazer_liberacao_nunca_gera_webhook_do_almox():
    released = proposal()
    assert almox_state(released) == "LIBERADA"
    fila = PendingTransitions()
    fila.registrar("CP 1", almox_state(released), None)  # depois do desfazer: AGUARDANDO_LIBERACAO = sem estado
    assert fila.transicoes() == []


def test_acao_desfeita_tem_frase_no_feed_e_notifica_so_ela():
    metadata = {"undone_label": "Liberacao da proposta", "reason": "Liberei a proposta errada"}
    assert _activity_headline(undo.ACTION_UNDONE, "Ana", metadata, None, None) == 'Ana desfez a acao "Liberacao da proposta" (Liberei a proposta errada).'
    assert undo.ACTION_UNDONE in _NOTIFY_PROPOSAL_EVENTS
    assert "previous_state" not in (_history_observation({"quantity": "2", "previous_state": {"a": 1}, "previous_separated_at": None}) or "")


def test_codigos_de_erro_novos_existem():
    assert {
        error_codes.UNDO_NOT_SUPPORTED, error_codes.UNDO_NOT_LATEST, error_codes.UNDO_BLOCKED,
        error_codes.UNDO_ALREADY_UNDONE, error_codes.UNDO_IDEMPOTENCY_CONFLICT, error_codes.UNDO_ACTION_NOT_FOUND,
    } == {
        "UNDO_NOT_SUPPORTED", "UNDO_NOT_LATEST", "UNDO_BLOCKED", "UNDO_ALREADY_UNDONE",
        "UNDO_IDEMPOTENCY_CONFLICT", "UNDO_ACTION_NOT_FOUND",
    }
