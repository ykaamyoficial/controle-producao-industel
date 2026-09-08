from __future__ import annotations

from fastapi import APIRouter, Depends

from api.app.core.exceptions import MaintenanceConcurrencyError, MaintenanceTransitionError
from api.app.maintenance.exceptions import ConcurrentMaintenanceOperationError, InvalidMaintenanceTransitionError
from api.app.maintenance.models import MaintenanceState
from api.app.maintenance.service import MaintenanceService, build_default_service
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import SYSTEM_MAINTENANCE_MANAGE
from api.app.modules.maintenance.schemas import (
    ActivateMaintenanceRequest,
    BeginDrainingRequest,
    BeginRecoveryRequest,
    MaintenanceAdminStateResponse,
    ScheduleMaintenanceRequest,
)

router = APIRouter(prefix="/system/maintenance/admin", tags=["maintenance-admin"])


def _service() -> MaintenanceService:
    return build_default_service()


def _actor(user: User) -> str:
    return user.username


def _state_response(state: MaintenanceState) -> MaintenanceAdminStateResponse:
    return MaintenanceAdminStateResponse(
        state=state.state.value,
        maintenance_id=state.maintenance_id,
        reason_code=state.reason_code.value,
        message=state.message,
        scheduled_start_at=state.scheduled_start_at.isoformat() if state.scheduled_start_at else None,
        started_at=state.started_at.isoformat() if state.started_at else None,
        expected_end_at=state.expected_end_at.isoformat() if state.expected_end_at else None,
        activated_by=state.activated_by,
        policy_revision=state.policy_revision,
        updated_at=state.updated_at.isoformat(),
    )


def _translate(func):
    """Traduz excecoes de dominio (api.app.maintenance.exceptions) para o
    contrato HTTP dos routers administrativos -- unico ponto de traducao,
    evita duplicar try/except em cada rota."""
    try:
        return func()
    except InvalidMaintenanceTransitionError as exc:
        raise MaintenanceTransitionError(str(exc)) from exc
    except ConcurrentMaintenanceOperationError as exc:
        raise MaintenanceConcurrencyError(str(exc)) from exc


@router.post("/schedule", response_model=MaintenanceAdminStateResponse, summary="Programa uma janela de manutencao futura (admin)")
async def schedule_maintenance(body: ScheduleMaintenanceRequest, user: User = Depends(require_permission(SYSTEM_MAINTENANCE_MANAGE))):
    state = _translate(lambda: _service().schedule_maintenance(
        reason_code=body.reason_code,
        message=body.message,
        scheduled_start_at=body.scheduled_start_at,
        expected_end_at=body.expected_end_at,
        activated_by=_actor(user),
        maintenance_id=body.maintenance_id,
    ))
    return _state_response(state)


@router.post("/draining", response_model=MaintenanceAdminStateResponse, summary="Inicia o esvaziamento seguro (DRAINING) antes de ACTIVE (admin)")
async def begin_draining(body: BeginDrainingRequest, user: User = Depends(require_permission(SYSTEM_MAINTENANCE_MANAGE))):
    state = _translate(lambda: _service().begin_draining(
        reason_code=body.reason_code,
        message=body.message,
        expected_end_at=body.expected_end_at,
        activated_by=_actor(user),
        maintenance_id=body.maintenance_id,
    ))
    return _state_response(state)


@router.post("/activate", response_model=MaintenanceAdminStateResponse, summary="Ativa a manutencao (ACTIVE) -- bloqueia operacao de negocio (admin)")
async def activate_maintenance(body: ActivateMaintenanceRequest, user: User = Depends(require_permission(SYSTEM_MAINTENANCE_MANAGE))):
    state = _translate(lambda: _service().activate_maintenance(
        reason_code=body.reason_code,
        message=body.message,
        expected_end_at=body.expected_end_at,
        activated_by=_actor(user),
        maintenance_id=body.maintenance_id,
    ))
    return _state_response(state)


@router.post("/recovery", response_model=MaintenanceAdminStateResponse, summary="Inicia a validacao final (RECOVERY) apos o servico voltar (admin)")
async def begin_recovery(body: BeginRecoveryRequest, user: User = Depends(require_permission(SYSTEM_MAINTENANCE_MANAGE))):
    state = _translate(lambda: _service().begin_recovery(activated_by=_actor(user), message=body.message))
    return _state_response(state)


@router.post("/finish", response_model=MaintenanceAdminStateResponse, summary="Conclui a manutencao (RECOVERY -> OFF) (admin)")
async def finish_maintenance(user: User = Depends(require_permission(SYSTEM_MAINTENANCE_MANAGE))):
    state = _translate(lambda: _service().finish_maintenance(activated_by=_actor(user)))
    return _state_response(state)


@router.post("/cancel", response_model=MaintenanceAdminStateResponse, summary="Cancela uma manutencao SCHEDULED/DRAINING sem ativa-la (admin)")
async def cancel_scheduled_maintenance(user: User = Depends(require_permission(SYSTEM_MAINTENANCE_MANAGE))):
    state = _translate(lambda: _service().cancel_scheduled_maintenance(activated_by=_actor(user)))
    return _state_response(state)
