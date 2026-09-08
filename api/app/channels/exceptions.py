from __future__ import annotations


class ChannelError(RuntimeError):
    """Erro generico da camada de dominio de canais/promocao (Fase 15)."""


class InvalidPromotionTransitionError(ChannelError):
    """Transicao de estado de promocao nao permitida (Secao 10)."""


class ConcurrentPromotionOperationError(ChannelError):
    """Duas promocoes/operacoes administrativas concorrentes (Secao 27)."""


class ArtifactMismatchError(ChannelError):
    """manifest_sha256/artifact_sha256 divergente do snapshot tirado na
    autorizacao do piloto (Secao 4/12) -- a promocao NUNCA prossegue quando
    o artefato pode ter mudado sob o mesmo numero de versao."""


class PilotGatesNotMetError(ChannelError):
    """Aprovacao de piloto tentada sem os gates minimos satisfeitos (Secao 20)."""


class ReleaseNotEligibleError(ChannelError):
    """A release referenciada nao esta em estado elegivel na Fase 12
    (precisa estar pelo menos READY para iniciar o piloto)."""
