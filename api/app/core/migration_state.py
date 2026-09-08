from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache

from alembic.config import Config
from alembic.script import ScriptDirectory

API_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class MigrationState:
    """Retrato da compatibilidade entre a revisao aplicada no banco e o historico
    real de migrations (Alembic), conforme Fase 04 (Secao 12). Nao expoe nada
    sensivel: apenas identificadores de revisao ja publicos via alembic_version.
    """

    current_revision: str | None
    expected_head_revision: str
    is_at_head: bool
    migration_history_consistent: bool


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


@lru_cache
def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(_alembic_config())


def known_revisions() -> frozenset[str]:
    """Todas as revisoes que existem no historico real de arquivos de migration."""
    return frozenset(script.revision for script in _script_directory().walk_revisions())


def script_head_revision() -> str:
    """Head calculado a partir dos arquivos reais em api/alembic/versions/ (nao a
    constante EXPECTED_DATABASE_REVISION, mantida separadamente em config.py e
    conferida contra este valor pelos testes -- ver Secao 12 do prompt: 'conecte
    esse conceito ao mecanismo real de migration sem criar numeracao artificial')."""
    head = _script_directory().get_current_head()
    if head is None:
        raise ValueError("Nenhuma migration encontrada em api/alembic/versions/.")
    return head


def build_migration_state(current_revision: str | None) -> MigrationState:
    """Monta o retrato de compatibilidade a partir de uma revisao ja lida do banco
    (ver api.app.database.health.database_check) -- esta funcao nao acessa o banco.
    """
    expected_head = script_head_revision()
    consistent = current_revision is None or current_revision in known_revisions()
    return MigrationState(
        current_revision=current_revision,
        expected_head_revision=expected_head,
        is_at_head=current_revision == expected_head,
        migration_history_consistent=consistent,
    )
