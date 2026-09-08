from __future__ import annotations


class MaintenanceError(RuntimeError):
    """Erro generico da camada de dominio do Maintenance Mode (Fase 14)."""


class InvalidMaintenanceTransitionError(MaintenanceError):
    """Transicao de estado nao permitida pela maquina de estados (Secao 13)."""


class ConcurrentMaintenanceOperationError(MaintenanceError):
    """Dois comandos administrativos concorrentes -- lock de arquivo ocupado
    (Secao 27: "dois comandos administrativos concorrentes devem ser
    serializados/validados")."""


class MaintenanceStateCorruptedError(MaintenanceError):
    """Arquivo de estado presente porem ilegivel/invalido (Secao 26). Nunca
    tratado como OFF -- quem chama aplica o fallback conservador (fail
    closed) em vez de liberar operacao silenciosamente."""
