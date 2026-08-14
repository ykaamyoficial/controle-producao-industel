from __future__ import annotations


class DeploymentError(RuntimeError):
    """Base de todos os erros do modulo de deployment/rollback (Fase 08)."""


class ConcurrentDeploymentOperationError(DeploymentError):
    """Ja existe um deploy/rollback em andamento (lock ativo ou registro nao
    terminal pendente de recuperacao) -- Secao 17."""


class InvalidDeploymentTransitionError(DeploymentError):
    """Transicao de estado nao permitida pela maquina de estados (Secao 7)."""


class RollbackNotAllowedError(DeploymentError):
    """Rollback automatico bloqueado -- sem release HEALTHY anterior conhecida,
    ou schema do banco incompativel com a versao anterior (Secao 9)."""


class RollbackFailedError(DeploymentError):
    """O rollback foi tentado (imagem anterior reativada) mas a validacao de
    saude/smoke pos-rollback nao passou -- estado final ROLLBACK_FAILED."""
