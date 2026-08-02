"""create fiscal records

Revision ID: 20260721_0008
Revises: 20260721_0007
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260721_0008"
down_revision: str | None = "20260721_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FISCAL_PERMISSIONS = [
    ("fiscal.view", "Visualizar Fiscal", "fiscal"),
    ("fiscal.register_emission", "Registrar emissao fiscal", "fiscal"),
    ("fiscal.cancel_link", "Cancelar vinculo fiscal interno", "fiscal"),
]


def upgrade() -> None:
    permissions_table = sa.table(
        "permissions",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("module", sa.String),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(
        permissions_table,
        [{"code": code, "name": name, "module": module, "description": None} for code, name, module in FISCAL_PERMISSIONS],
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT roles.id, permissions.id
        FROM roles
        CROSS JOIN permissions
        WHERE roles.code = 'admin'
          AND permissions.code IN ('fiscal.view', 'fiscal.register_emission', 'fiscal.cancel_link')
        ON CONFLICT DO NOTHING
        """
    )

    op.create_table(
        "fiscal_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("status_fiscal", sa.String(length=80), server_default="FALTA_EMITIR_NOTA_FISCAL", nullable=False),
        sa.Column("fiscal_situation", sa.String(length=80), server_default="AGUARDANDO_NF", nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("last_emission_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invoice_withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_by", sa.BigInteger(), nullable=True),
        sa.Column("withdrawal_observation", sa.Text(), nullable=True),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status_fiscal IN ('FALTA_EMITIR_NOTA_FISCAL', 'NOTA_FISCAL_PARCIAL', 'NOTA_FISCAL_EMITIDA', 'FISCAL_CANCELADO')",
            name="ck_fiscal_records_status",
        ),
        sa.CheckConstraint(
            "fiscal_situation IN ('AGUARDANDO_NF', 'CP_EM_PROCESSAMENTO', 'NF_EM_PROCESSAMENTO', 'DISPONIVEL_PARA_EMISSAO', 'PENDENCIA_FISCAL_CRITICA', 'NF_PARCIAL', 'NF_EMITIDA', 'NF_RETIRADA_CLIENTE', 'FISCAL_CANCELADO')",
            name="ck_fiscal_records_situation",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_fiscal_records_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_fiscal_records_proposal_id_proposals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_fiscal_records_updated_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["withdrawn_by"], ["users.id"], name=op.f("fk_fiscal_records_withdrawn_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fiscal_records")),
        sa.UniqueConstraint("proposal_id", name="uq_fiscal_records_proposal"),
    )
    op.create_index("ix_fiscal_records_status", "fiscal_records", ["status_fiscal"])
    op.create_index("ix_fiscal_records_situation", "fiscal_records", ["fiscal_situation"])
    op.create_index("ix_fiscal_records_entry_date", "fiscal_records", ["entry_date"])

    op.create_table(
        "fiscal_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("fiscal_record_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_item_id", sa.BigInteger(), nullable=False),
        sa.Column("total_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("billed_quantity", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("total_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("billed_weight", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=40), server_default="PENDENTE", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("total_quantity >= 0", name="ck_fiscal_items_total_quantity"),
        sa.CheckConstraint("billed_quantity >= 0 AND billed_quantity <= total_quantity", name="ck_fiscal_items_billed_quantity"),
        sa.CheckConstraint("total_weight >= 0", name="ck_fiscal_items_total_weight"),
        sa.CheckConstraint("billed_weight >= 0 AND billed_weight <= total_weight", name="ck_fiscal_items_billed_weight"),
        sa.CheckConstraint("status IN ('PENDENTE', 'PARCIAL', 'FATURADO', 'CANCELADO')", name="ck_fiscal_items_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_fiscal_items_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fiscal_record_id"], ["fiscal_records.id"], name=op.f("fk_fiscal_items_fiscal_record_id_fiscal_records"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_fiscal_items_proposal_id_proposals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_item_id"], ["proposal_items.id"], name=op.f("fk_fiscal_items_proposal_item_id_proposal_items"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_fiscal_items_updated_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fiscal_items")),
        sa.UniqueConstraint("fiscal_record_id", "proposal_item_id", name="uq_fiscal_items_record_item"),
    )
    op.create_index("ix_fiscal_items_record", "fiscal_items", ["fiscal_record_id"])
    op.create_index("ix_fiscal_items_proposal_item", "fiscal_items", ["proposal_item_id"])
    op.create_index("ix_fiscal_items_status", "fiscal_items", ["status"])

    op.create_table(
        "fiscal_invoices",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("fiscal_record_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("invoice_number", sa.String(length=80), nullable=False),
        sa.Column("series", sa.String(length=40), nullable=True),
        sa.Column("access_key", sa.String(length=80), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("emission_type", sa.String(length=40), server_default="PARCIAL", nullable=False),
        sa.Column("status", sa.String(length=40), server_default="REGISTRADA", nullable=False),
        sa.Column("source", sa.String(length=40), server_default="MANUAL", nullable=False),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("emission_type IN ('PARCIAL', 'TOTAL')", name="ck_fiscal_invoices_emission_type"),
        sa.CheckConstraint("status IN ('REGISTRADA', 'CANCELADA')", name="ck_fiscal_invoices_status"),
        sa.CheckConstraint("source IN ('MANUAL', 'NOMUS', 'SYSTEM')", name="ck_fiscal_invoices_source"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_fiscal_invoices_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fiscal_record_id"], ["fiscal_records.id"], name=op.f("fk_fiscal_invoices_fiscal_record_id_fiscal_records"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_fiscal_invoices_proposal_id_proposals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_fiscal_invoices_updated_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fiscal_invoices")),
        sa.UniqueConstraint("invoice_number", "series", name="uq_fiscal_invoices_number_series"),
    )
    op.create_index("ix_fiscal_invoices_record", "fiscal_invoices", ["fiscal_record_id"])
    op.create_index("ix_fiscal_invoices_number", "fiscal_invoices", ["invoice_number"])
    op.create_index("ix_fiscal_invoices_status", "fiscal_invoices", ["status"])

    op.create_table(
        "fiscal_invoice_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("fiscal_invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("fiscal_item_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_item_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.BigInteger(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_fiscal_invoice_items_quantity"),
        sa.CheckConstraint("weight >= 0", name="ck_fiscal_invoice_items_weight"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], name=op.f("fk_fiscal_invoice_items_cancelled_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_fiscal_invoice_items_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fiscal_invoice_id"], ["fiscal_invoices.id"], name=op.f("fk_fiscal_invoice_items_fiscal_invoice_id_fiscal_invoices"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fiscal_item_id"], ["fiscal_items.id"], name=op.f("fk_fiscal_invoice_items_fiscal_item_id_fiscal_items"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_fiscal_invoice_items_proposal_id_proposals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_item_id"], ["proposal_items.id"], name=op.f("fk_fiscal_invoice_items_proposal_item_id_proposal_items"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fiscal_invoice_items")),
    )
    op.create_index("ix_fiscal_invoice_items_invoice", "fiscal_invoice_items", ["fiscal_invoice_id"])
    op.create_index("ix_fiscal_invoice_items_fiscal_item", "fiscal_invoice_items", ["fiscal_item_id"])
    op.create_index("ix_fiscal_invoice_items_active", "fiscal_invoice_items", ["active"])

    op.create_table(
        "fiscal_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("fiscal_record_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("fiscal_item_id", sa.BigInteger(), nullable=True),
        sa.Column("fiscal_invoice_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=80), nullable=True),
        sa.Column("to_status", sa.String(length=80), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_fiscal_events_actor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fiscal_invoice_id"], ["fiscal_invoices.id"], name=op.f("fk_fiscal_events_fiscal_invoice_id_fiscal_invoices"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fiscal_item_id"], ["fiscal_items.id"], name=op.f("fk_fiscal_events_fiscal_item_id_fiscal_items"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fiscal_record_id"], ["fiscal_records.id"], name=op.f("fk_fiscal_events_fiscal_record_id_fiscal_records"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_fiscal_events_proposal_id_proposals"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fiscal_events")),
    )
    op.create_index("ix_fiscal_events_record_created", "fiscal_events", ["fiscal_record_id", "created_at"])
    op.create_index("ix_fiscal_events_event_type", "fiscal_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_fiscal_events_event_type", table_name="fiscal_events")
    op.drop_index("ix_fiscal_events_record_created", table_name="fiscal_events")
    op.drop_table("fiscal_events")
    op.drop_index("ix_fiscal_invoice_items_active", table_name="fiscal_invoice_items")
    op.drop_index("ix_fiscal_invoice_items_fiscal_item", table_name="fiscal_invoice_items")
    op.drop_index("ix_fiscal_invoice_items_invoice", table_name="fiscal_invoice_items")
    op.drop_table("fiscal_invoice_items")
    op.drop_index("ix_fiscal_invoices_status", table_name="fiscal_invoices")
    op.drop_index("ix_fiscal_invoices_number", table_name="fiscal_invoices")
    op.drop_index("ix_fiscal_invoices_record", table_name="fiscal_invoices")
    op.drop_table("fiscal_invoices")
    op.drop_index("ix_fiscal_items_status", table_name="fiscal_items")
    op.drop_index("ix_fiscal_items_proposal_item", table_name="fiscal_items")
    op.drop_index("ix_fiscal_items_record", table_name="fiscal_items")
    op.drop_table("fiscal_items")
    op.drop_index("ix_fiscal_records_entry_date", table_name="fiscal_records")
    op.drop_index("ix_fiscal_records_situation", table_name="fiscal_records")
    op.drop_index("ix_fiscal_records_status", table_name="fiscal_records")
    op.drop_table("fiscal_records")
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions
            WHERE code IN ('fiscal.view', 'fiscal.register_emission', 'fiscal.cancel_link')
        )
        """
    )
    op.execute("DELETE FROM permissions WHERE code IN ('fiscal.view', 'fiscal.register_emission', 'fiscal.cancel_link')")
