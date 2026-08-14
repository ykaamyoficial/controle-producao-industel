from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "api"
VERSIONS_DIR = API_DIR / "alembic" / "versions"
TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")


def _database_name(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return parsed.path.lstrip("/")


def integration_enabled() -> bool:
    """Mesmo guard de seguranca usado por test_postgresql_integration.py: so roda
    contra um banco descartavel explicitamente marcado para teste."""
    return (
        bool(TEST_DATABASE_URL)
        and os.environ.get("APP_ENV") == "test"
        and TEST_DATABASE_URL.startswith("postgresql+asyncpg://")
        and "test" in _database_name(TEST_DATABASE_URL).lower()
    )


def alembic_config(*, script_location: Path | None = None) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(script_location or (API_DIR / "alembic")))
    return config


_BROKEN_MIGRATION_TEMPLATE = '''"""migration de teste, propositalmente quebrada (Fase 04 - teste de atomicidade)

Revision ID: {revision}
Revises: {down_revision}
Create Date: 2026-08-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "{revision}"
down_revision: str | None = "{down_revision}"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fase04_atomicity_probe",
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    # Erro deliberado apos a primeira operacao ter sido emitida na transacao, para
    # provar que o Alembic reverte a transacao inteira (tabela incluida) em falha.
    op.execute("SELECT 1/0")


def downgrade() -> None:
    op.drop_table("fase04_atomicity_probe")
'''


@contextmanager
def temporary_chain_with_broken_head(down_revision: str):
    """Copia o diretorio real de migrations para uma pasta temporaria e acrescenta
    uma revisao quebrada por cima de down_revision, sem tocar em api/alembic/versions/.

    Usado apenas para o teste de falha/atomicidade (Secao 23 da Fase 04): precisamos
    exercitar o comportamento real de rollback do executor Alembic/Postgres sem
    jamais escrever um arquivo permanente no historico real de migrations.
    """
    with tempfile.TemporaryDirectory(prefix="fase04_migrations_") as tmp:
        # Copia env.py/script.py.mako/versions inteiros (Alembic precisa de env.py
        # para rodar upgrade/downgrade de verdade, nao so de listar revisoes).
        tmp_alembic_dir = Path(tmp) / "alembic"
        shutil.copytree(API_DIR / "alembic", tmp_alembic_dir, ignore=shutil.ignore_patterns("__pycache__"))
        broken_revision = "99999999_broken"
        (tmp_alembic_dir / "versions" / f"{broken_revision}_probe.py").write_text(
            _BROKEN_MIGRATION_TEMPLATE.format(revision=broken_revision, down_revision=down_revision),
            encoding="utf-8",
        )
        yield alembic_config(script_location=tmp_alembic_dir), broken_revision
