"""backfill relational parents for legacy partial proposals"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0022"
down_revision: str | None = "20260814_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    proposals = sa.table(
        "proposals",
        sa.column("id", sa.BigInteger()),
        sa.column("legacy_id", sa.BigInteger()),
        sa.column("parent_legacy_id", sa.BigInteger()),
        sa.column("parent_proposal_id", sa.BigInteger()),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            proposals.c.id,
            proposals.c.parent_legacy_id,
        ).where(
            proposals.c.parent_proposal_id.is_(None),
            proposals.c.parent_legacy_id.is_not(None),
        )
    ).all()
    parent_ids = {
        row.legacy_id: row.id
        for row in connection.execute(
            sa.select(proposals.c.id, proposals.c.legacy_id).where(proposals.c.legacy_id.is_not(None))
        ).all()
    }
    for row in rows:
        parent_id = parent_ids.get(row.parent_legacy_id)
        if parent_id is not None and parent_id != row.id:
            connection.execute(
                proposals.update().where(proposals.c.id == row.id).values(parent_proposal_id=parent_id)
            )


def downgrade() -> None:
    # Nao desfazemos os vinculos: eles corrigem dados historicos e remover
    # relacoes validas durante downgrade poderia reexpor filhas no sistema.
    pass
