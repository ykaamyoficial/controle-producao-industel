"""indexes for operational list queries and partial hierarchy"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260817_0024"
down_revision: str | None = "20260817_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ix_proposals_parent_proposal_id ja e criado por
    # 20260814_0021_proposal_partial_hierarchy.py junto com a propria coluna -
    # incluir de novo aqui e um duplicado (bug pre-existente, nao relacionado
    # a este indice em si) que quebra qualquer banco criado do zero.
    indexes = (
        ("ix_proposals_current_area", "proposals", ["current_area"]),
        ("ix_proposals_current_status", "proposals", ["current_status"]),
        ("ix_proposals_customer_status", "proposals", ["customer_name", "current_status"]),
        ("ix_proposals_deadline_date", "proposals", ["deadline_date"]),
        ("ix_proposal_items_proposal_produced", "proposal_items", ["proposal_id", "produced"]),
        ("ix_galvanization_load_items_load_status", "galvanization_load_items", ["load_id", "status"]),
        ("ix_expedition_items_proposal_status", "expedition_items", ["proposal_id", "status"]),
        ("ix_fiscal_records_status_entry", "fiscal_records", ["status_fiscal", "entry_date"]),
    )
    for name, table, columns in indexes:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in (
        ("ix_fiscal_records_status_entry", "fiscal_records", None),
        ("ix_expedition_items_proposal_status", "expedition_items", None),
        ("ix_galvanization_load_items_load_status", "galvanization_load_items", None),
        ("ix_proposal_items_proposal_produced", "proposal_items", None),
        ("ix_proposals_deadline_date", "proposals", None),
        ("ix_proposals_customer_status", "proposals", None),
        ("ix_proposals_current_status", "proposals", None),
        ("ix_proposals_current_area", "proposals", None),
    ):
        op.drop_index(name, table_name=table)
