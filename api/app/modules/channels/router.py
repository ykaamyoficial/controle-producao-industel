from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.channels import gates as gates_module
from api.app.channels import installations as channel_installations
from api.app.channels.exceptions import (
    ArtifactMismatchError,
    ConcurrentPromotionOperationError,
    InvalidPromotionTransitionError,
    PilotGatesNotMetError,
    ReleaseNotEligibleError,
)
from api.app.channels.models import Channel, PilotGates, ReleaseChannelState
from api.app.channels.service import ChannelPromotionService, build_default_service
from api.app.core.exceptions import (
    ChannelArtifactMismatchError,
    ChannelConcurrencyError,
    ChannelGatesNotMetError,
    ChannelReleaseNotEligibleError,
    ChannelTransitionError,
)
from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import get_current_active_user, require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import UPDATES_MANAGE
from api.app.modules.channels.schemas import (
    ApprovePilotRequest,
    AssignChannelRequest,
    AuthorizePilotRequest,
    ClientInstallationList,
    ClientInstallationOut,
    PilotActionRequest,
    PilotClientReportOut,
    PilotClientReportRequest,
    PilotGateEvaluationOut,
    ReleaseChannelStateList,
    ReleaseChannelStateOut,
    RevokeChannelReleaseRequest,
)

router = APIRouter(prefix="/channels", tags=["channels"])


def _service() -> ChannelPromotionService:
    return build_default_service()


def _translate(func):
    try:
        return func()
    except InvalidPromotionTransitionError as exc:
        raise ChannelTransitionError(str(exc)) from exc
    except ConcurrentPromotionOperationError as exc:
        raise ChannelConcurrencyError(str(exc)) from exc
    except ArtifactMismatchError as exc:
        raise ChannelArtifactMismatchError(str(exc)) from exc
    except PilotGatesNotMetError as exc:
        raise ChannelGatesNotMetError(str(exc)) from exc
    except ReleaseNotEligibleError as exc:
        raise ChannelReleaseNotEligibleError(str(exc)) from exc


def _promotion_out(state: ReleaseChannelState) -> ReleaseChannelStateOut:
    return ReleaseChannelStateOut(**state.to_dict())


def _installation_out(row) -> ClientInstallationOut:
    return ClientInstallationOut(**row.to_dict())


# -- cadastro de instalacoes (Secao 6/7/26) ----------------------------------


@router.get("/installations", response_model=ClientInstallationList, summary="Lista instalacoes e seus canais (admin)")
async def list_installations(
    channel: Channel | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _user: User = Depends(require_permission(UPDATES_MANAGE)),
) -> ClientInstallationList:
    rows = await channel_installations.list_installations(session, channel=channel)
    return ClientInstallationList(items=[_installation_out(row) for row in rows])


@router.post("/installations/{installation_id}/assign", response_model=ClientInstallationOut, summary="Atribui uma instalacao a um canal (admin)")
async def assign_channel(
    installation_id: str, body: AssignChannelRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permission(UPDATES_MANAGE)),
) -> ClientInstallationOut:
    row = await channel_installations.assign_channel(session, installation_id, channel=body.channel, actor=user.username)
    return _installation_out(row)


@router.delete("/installations/{installation_id}/assign", response_model=ClientInstallationOut, summary="Remove atribuicao explicita -- volta ao fallback PRODUCTION (admin)")
async def remove_channel_assignment(
    installation_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permission(UPDATES_MANAGE)),
) -> ClientInstallationOut:
    row = await channel_installations.remove_channel_assignment(session, installation_id, actor=user.username)
    if row is None:
        row = await channel_installations.assign_channel(session, installation_id, channel=Channel.PRODUCTION, actor=user.username)
    return _installation_out(row)


# -- promocao de release por canal (Secao 9-13, 21-23) -----------------------


@router.get("/pilot", response_model=ReleaseChannelStateList, summary="Lista todas as promocoes registradas (admin)")
async def list_promotions(_user: User = Depends(require_permission(UPDATES_MANAGE))) -> ReleaseChannelStateList:
    return ReleaseChannelStateList(items=[_promotion_out(state) for state in _service().list_promotions()])


@router.get("/pilot/{version}", response_model=ReleaseChannelStateOut, summary="Ve a promocao de uma release (admin)")
async def get_promotion(version: str, _user: User = Depends(require_permission(UPDATES_MANAGE))) -> ReleaseChannelStateOut:
    state = _service().get_promotion(version)
    if state is None:
        raise ChannelTransitionError(f"Release {version} nao tem promocao registrada.")
    return _promotion_out(state)


@router.post("/pilot/{version}/authorize", response_model=ReleaseChannelStateOut, summary="Autoriza o piloto para uma release READY/AUTHORIZED (admin)")
async def authorize_pilot(version: str, body: AuthorizePilotRequest, user: User = Depends(require_permission(UPDATES_MANAGE))) -> ReleaseChannelStateOut:
    state = _translate(lambda: _service().authorize_pilot(version, actor=user.username, note=body.note))
    return _promotion_out(state)


@router.post("/pilot/{version}/pause", response_model=ReleaseChannelStateOut, summary="Pausa o piloto -- impede novos downloads (admin)")
async def pause_pilot(version: str, body: PilotActionRequest, user: User = Depends(require_permission(UPDATES_MANAGE))) -> ReleaseChannelStateOut:
    state = _translate(lambda: _service().pause_pilot(version, actor=user.username, note=body.note))
    return _promotion_out(state)


@router.post("/pilot/{version}/resume", response_model=ReleaseChannelStateOut, summary="Retoma um piloto pausado (admin)")
async def resume_pilot(version: str, body: PilotActionRequest, user: User = Depends(require_permission(UPDATES_MANAGE))) -> ReleaseChannelStateOut:
    state = _translate(lambda: _service().resume_pilot(version, actor=user.username, note=body.note))
    return _promotion_out(state)


@router.post("/pilot/{version}/fail", response_model=ReleaseChannelStateOut, summary="Marca o piloto como falho -- nao pode ser promovido (admin)")
async def fail_pilot(version: str, body: PilotActionRequest, user: User = Depends(require_permission(UPDATES_MANAGE))) -> ReleaseChannelStateOut:
    state = _translate(lambda: _service().fail_pilot(version, actor=user.username, note=body.note))
    return _promotion_out(state)


@router.post("/pilot/{version}/gates", response_model=PilotGateEvaluationOut, summary="Avalia os gates minimos do piloto sem aprovar (admin)")
async def evaluate_gates(
    version: str, body: ApprovePilotRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: User = Depends(require_permission(UPDATES_MANAGE)),
) -> PilotGateEvaluationOut:
    evaluation = await _evaluate_gates(session, version, body)
    return PilotGateEvaluationOut(**evaluation.__dict__)


@router.post("/pilot/{version}/approve", response_model=ReleaseChannelStateOut, summary="Aprova o piloto apos os gates minimos serem satisfeitos (admin)")
async def approve_pilot(
    version: str, body: ApprovePilotRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_permission(UPDATES_MANAGE)),
) -> ReleaseChannelStateOut:
    evaluation = await _evaluate_gates(session, version, body)
    state = _translate(lambda: _service().approve_pilot(version, actor=user.username, evaluation=evaluation, note=body.note))
    return _promotion_out(state)


@router.post("/pilot/{version}/promote", response_model=ReleaseChannelStateOut, summary="Promove a mesma release ja aprovada para PRODUCTION (admin)")
async def promote_to_production(version: str, user: User = Depends(require_permission(UPDATES_MANAGE))) -> ReleaseChannelStateOut:
    state = _translate(lambda: _service().promote_to_production(version, actor=user.username))
    return _promotion_out(state)


@router.post("/pilot/{version}/revoke", response_model=ReleaseChannelStateOut, summary="Revoga a promocao (integra com REVOKED da Fase 12) (admin)")
async def revoke_promotion(version: str, body: RevokeChannelReleaseRequest, user: User = Depends(require_permission(UPDATES_MANAGE))) -> ReleaseChannelStateOut:
    state = _translate(lambda: _service().revoke(version, actor=user.username, reason=body.reason))
    return _promotion_out(state)


async def _evaluate_gates(session: AsyncSession, version: str, body: ApprovePilotRequest):
    state = _service().get_promotion(version)
    if state is None:
        raise ChannelTransitionError(f"Release {version} nao tem promocao registrada.")
    gates = PilotGates(min_pilot_clients_updated=body.min_pilot_clients_updated, observation_minutes=body.observation_minutes)
    pilot_client_count = await channel_installations.count_pilot_clients(session)
    signals = await channel_installations.report_signals_for_version(session, version)
    pilot_authorized_at = state.pilot_authorized_at or state.created_at
    return gates_module.evaluate_pilot_gates(
        gates=gates, pilot_client_count=pilot_client_count, reports=signals,
        pilot_authorized_at=pilot_authorized_at, now=datetime.now(timezone.utc),
    )


# -- relatorio de cliente piloto (Secao 18) ----------------------------------


@router.post("/pilot-reports", response_model=PilotClientReportOut, summary="Registra um sinal minimo de sucesso/falha de um cliente piloto")
async def submit_pilot_report(
    body: PilotClientReportRequest,
    session: AsyncSession = Depends(get_db_session),
    _user: User = Depends(get_current_active_user),
) -> PilotClientReportOut:
    report = await channel_installations.submit_pilot_report(
        session, installation_id=body.installation_id, release_version=body.release_version,
        update_result=body.update_result, app_start_result=body.app_start_result,
        compatibility_result=body.compatibility_result, error_code=body.error_code,
    )
    return PilotClientReportOut(**report.to_dict())
