"""sector rbac permissions

Revision ID: 20260727_0010
Revises: 20260722_0009
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0010"
down_revision: str | None = "20260722_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SECTOR_PERMISSIONS = [
    ("production.view", "Visualizar Producao", "production"),
    ("production.update", "Alterar Producao", "production"),
    ("galvanization.view", "Visualizar Galvanizacao", "galvanization"),
    ("galvanization.update", "Alterar Galvanizacao", "galvanization"),
    ("expedition.view", "Visualizar Expedicao", "expedition"),
    ("expedition.update", "Alterar Expedicao", "expedition"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for code, name, module in SECTOR_PERMISSIONS:
        bind.execute(
            sa.text(
                """
                INSERT INTO permissions (code, name, module, description)
                VALUES (:code, :name, :module, NULL)
                ON CONFLICT (code) DO UPDATE
                   SET name = EXCLUDED.name,
                       module = EXCLUDED.module
                """
            ),
            {"code": code, "name": name, "module": module},
        )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT roles.id, permissions.id
          FROM roles
          CROSS JOIN permissions
         WHERE roles.code = 'admin'
           AND permissions.code IN (
               'production.view',
               'production.update',
               'galvanization.view',
               'galvanization.update',
               'expedition.view',
               'expedition.update'
           )
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        "update system_metadata set value = '\"20260727_0010\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
         WHERE permission_id IN (
            SELECT id FROM permissions
             WHERE code IN (
               'production.view',
               'production.update',
               'galvanization.view',
               'galvanization.update',
               'expedition.view',
               'expedition.update'
             )
         )
        """
    )
    op.execute(
        """
        DELETE FROM permissions
         WHERE code IN (
               'production.view',
               'production.update',
               'galvanization.view',
               'galvanization.update',
               'expedition.view',
               'expedition.update'
         )
        """
    )
    op.execute(
        "update system_metadata set value = '\"20260722_0009\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
