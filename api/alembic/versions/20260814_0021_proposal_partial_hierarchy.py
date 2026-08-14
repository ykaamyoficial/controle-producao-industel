"""create the proposal mother and partial-child hierarchy"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260814_0021"
down_revision: str | None = "20260813_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("proposals", "legacy_id", nullable=True)
    op.add_column("proposals", sa.Column("parent_proposal_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_proposals_parent_proposal_id",
        "proposals",
        "proposals",
        ["parent_proposal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_proposals_parent_proposal_id", "proposals", ["parent_proposal_id"])


def downgrade() -> None:
    op.drop_index("ix_proposals_parent_proposal_id", table_name="proposals")
    op.drop_constraint("fk_proposals_parent_proposal_id", "proposals", type_="foreignkey")
    op.drop_column("proposals", "parent_proposal_id")

