"""payroll item settlements ledger; one snapshot per finalize

Revision ID: adec41479191
Revises: 1ff3dd1a844a
Create Date: 2026-09-29 00:00:00.000000

Audit finding C-6. Records which payslip used which loan / advance / bonus /
arrear / commission / reimbursement and for how much, so finalizing a run
applies those effects and reversing or reopening it can undo them exactly.
See PayrollItemSettlement in app/models/payroll.py.

Also: payroll_snapshots.payroll_run_id was UNIQUE, so finalizing a run a
second time (after a reopen) always failed with an HTTP 500. A run now keeps
one snapshot per finalize — the constraint (found by catalog lookup, not by
name) becomes a plain index.

Runs generated BEFORE this migration changed their source records directly
and have no ledger rows; reversing such a run cannot restore them (same as
before). Everything generated afterwards is fully reversible.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "adec41479191"
down_revision: Union[str, None] = "1ff3dd1a844a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_item_settlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("payroll_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payslip_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payslips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_status", sa.String(30), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_payroll_item_settlements_tenant_id", "payroll_item_settlements", ["tenant_id"])
    op.create_index("ix_payroll_item_settlements_payroll_run_id", "payroll_item_settlements", ["payroll_run_id"])
    op.create_index("ix_payroll_item_settlements_payslip_id", "payroll_item_settlements", ["payslip_id"])
    op.create_index("ix_payroll_item_settlements_source_id", "payroll_item_settlements", ["source_id"])
    op.create_index("ix_payroll_item_settlements_is_deleted", "payroll_item_settlements", ["is_deleted"])

    names = op.get_bind().execute(sa.text(
        """
        SELECT c.conname FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.conrelid = 'payroll_snapshots'::regclass AND c.contype = 'u'
          AND array_length(c.conkey, 1) = 1 AND a.attname = 'payroll_run_id'
        """
    )).scalars().all()
    for name in names:
        op.drop_constraint(name, "payroll_snapshots", type_="unique")
    op.create_index("ix_payroll_snapshots_payroll_run_id", "payroll_snapshots", ["payroll_run_id"])


def downgrade() -> None:
    # Fails if a run has more than one snapshot by then — that is expected.
    op.execute("DROP INDEX IF EXISTS ix_payroll_snapshots_payroll_run_id")
    op.create_unique_constraint("payroll_snapshots_payroll_run_id_key", "payroll_snapshots", ["payroll_run_id"])
    op.drop_table("payroll_item_settlements")
