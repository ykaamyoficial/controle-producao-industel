"""add user profile avatar fields"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0010"
down_revision: str | None = "20260812_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_bytes", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("avatar_mime", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_mime")
    op.drop_column("users", "avatar_bytes")
