"""link admin proposal permissions

Revision ID: 20260720_0004
Revises: 20260720_0003
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260720_0004"
down_revision: str | None = "20260720_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT roles.id, permissions.id
        FROM roles
        CROSS JOIN permissions
        WHERE roles.code = 'admin'
          AND permissions.code IN ('proposals.view', 'proposal_items.view', 'proposals.sync')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE code = 'admin')
          AND permission_id IN (
              SELECT id FROM permissions
              WHERE code IN ('proposals.view', 'proposal_items.view', 'proposals.sync')
          )
        """
    )
