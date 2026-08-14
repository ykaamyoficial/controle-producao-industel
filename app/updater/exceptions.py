from __future__ import annotations

from app.updater.contract import UpdateJournal


class UpdaterError(RuntimeError):
    """Base de todos os erros do Updater (Fase 10)."""


class ConcurrentUpdateError(UpdaterError):
    """Ja existe um Updater aplicando uma atualizacao (Secao 29)."""


class UpdateFailedError(UpdaterError):
    """A atualizacao foi interrompida; `journal` reflete o estado final
    persistido (FAILED, ROLLED_BACK ou MANUAL_INTERVENTION_REQUIRED)."""

    def __init__(self, message: str, *, journal: UpdateJournal):
        super().__init__(message)
        self.journal = journal
