"""employee status history (E-08) and contracts (E-07)

Revision ID: a4c6e8f0b2d4
Revises: f3b5d7e9a193
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4c6e8f0b2d4"
down_revision: Union[str, None] = "f3b5d7e9a193"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
    ]


def upgrade() -> None:
    op.create_table(
        "employee_status_history",
        *_base_columns(),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(30), nullable=True),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("changed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="update"),
    )
    op.create_index("ix_employee_status_history_employee_id", "employee_status_history", ["employee_id"])
    op.create_index("ix_employee_status_history_tenant_id", "employee_status_history", ["tenant_id"])
    op.create_index("ix_employee_status_history_id", "employee_status_history", ["id"])
    op.create_index("ix_employee_status_history_is_deleted", "employee_status_history", ["is_deleted"])
    op.create_index("ix_employee_status_history_deleted_at", "employee_status_history", ["deleted_at"])

    op.create_table(
        "employee_contracts",
        *_base_columns(),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_type", sa.String(30), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("renewal_alert_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_alerted_at", sa.Date(), nullable=True),
        sa.Column("renewed_from_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_contract_end_after_start"),
    )
    op.create_index("ix_employee_contracts_employee_id", "employee_contracts", ["employee_id"])
    op.create_index("ix_employee_contracts_tenant_id", "employee_contracts", ["tenant_id"])
    op.create_index("ix_employee_contracts_id", "employee_contracts", ["id"])
    op.create_index("ix_employee_contracts_end_date", "employee_contracts", ["end_date"])
    op.create_index("ix_employee_contracts_status", "employee_contracts", ["status"])
    op.create_index("ix_employee_contracts_is_deleted", "employee_contracts", ["is_deleted"])
    op.create_index("ix_employee_contracts_deleted_at", "employee_contracts", ["deleted_at"])
    # An employee has at most ONE active contract at a time (renew it instead of adding a second).
    op.execute(
        "CREATE UNIQUE INDEX uq_employee_contracts_one_active ON employee_contracts (employee_id) "
        "WHERE status = 'active' AND is_deleted = false"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_employee_contracts_one_active")
    op.drop_table("employee_contracts")
    op.drop_table("employee_status_history")
