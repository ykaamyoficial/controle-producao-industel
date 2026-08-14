from __future__ import annotations

from api.app.maintenance.models import MaintenanceStateName

# Maquina de estados oficial (Fase 14, Secao 13). Deliberadamente sem
# self-loops aqui: repetir o estado atual (ex.: ACTIVE -> ACTIVE) e tratado
# como idempotencia pela camada de servico (Secao 27), nao como uma
# transicao valida da maquina -- ver MaintenanceService._transition.
ALLOWED_TRANSITIONS: dict[MaintenanceStateName, frozenset[MaintenanceStateName]] = {
    MaintenanceStateName.OFF: frozenset({
        MaintenanceStateName.SCHEDULED,
        MaintenanceStateName.DRAINING,
        MaintenanceStateName.ACTIVE,  # emergencia controlada
    }),
    MaintenanceStateName.SCHEDULED: frozenset({
        MaintenanceStateName.DRAINING,
        MaintenanceStateName.ACTIVE,
        MaintenanceStateName.OFF,  # cancelamento
    }),
    MaintenanceStateName.DRAINING: frozenset({
        MaintenanceStateName.ACTIVE,
        MaintenanceStateName.OFF,  # cancelamento seguro
    }),
    MaintenanceStateName.ACTIVE: frozenset({
        MaintenanceStateName.RECOVERY,
    }),
    MaintenanceStateName.RECOVERY: frozenset({
        MaintenanceStateName.OFF,
    }),
}


def is_transition_allowed(current: MaintenanceStateName, target: MaintenanceStateName) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())
