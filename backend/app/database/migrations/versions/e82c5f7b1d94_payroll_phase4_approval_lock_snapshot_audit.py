"""payroll phase 4 — approval workflow, locking/reopening/reversal, snapshots, audit log

Revision ID: e82c5f7b1d94
Revises: d71b4e9c3a58
Create Date: 2026-09-08 00:00:00.000000

Phase 4: makes a finalized payroll run immutable, reproducible, and
reversible. Adds multi-level approval (optional — a tenant with no
configured levels keeps the original single-approve behavior), lock/
reopen/reverse lifecycle fields on payroll_runs, a point-in-time snapshot
taken at finalization, and an append-only audit log.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e82c5f7b1d94'
down_revision: Union[str, None] = 'd71b4e9c3a58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    ]


def upgrade() -> None:
    bind = op.get_bind()

    # ── extend payroll_run_status_enum / payslip_status_enum ────────────
    # Postgres requires ALTER TYPE ... ADD VALUE to run outside an explicit
    # transaction block in older versions; Alembic's autocommit block
    # handles this safely.
    # Uppercase labels ('LOCKED' not 'locked'), matching the existing
    # payroll_run_status_enum/payslip_status_enum labels ('DRAFT',
    # 'PROCESSING', ... — all uppercase, from initial_schema) and matching
    # how SQLAlchemy's Enum(python_enum_class) binds by the member's .name
    # by default, not .value. See
    # ebe9ce81bf8e_fix_work_session_status_enum_casing.py for the same bug
    # hit and fixed elsewhere in this codebase.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE payroll_run_status_enum ADD VALUE IF NOT EXISTS 'LOCKED'")
        op.execute("ALTER TYPE payroll_run_status_enum ADD VALUE IF NOT EXISTS 'REOPENED'")
        op.execute("ALTER TYPE payslip_status_enum ADD VALUE IF NOT EXISTS 'REVERSED'")

    approval_decision_enum = postgresql.ENUM("APPROVED", "REJECTED", name="approval_decision_enum", create_type=False)
    # create_type=False: see phase1/phase2/phase3 migrations for why —
    # without it, using this same enum object as payroll_approvals.decision's
    # column type below re-issues CREATE TYPE a second time and fails with
    # "already exists".
    approval_decision_enum.create(bind, checkfirst=True)

    # ── payroll_runs: lock/reopen/reverse lifecycle fields ──────────────
    op.add_column("payroll_runs", sa.Column("locked_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("payroll_runs", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_runs", sa.Column("reopened_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("payroll_runs", sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_runs", sa.Column("reopen_reason", sa.Text, nullable=True))
    op.add_column("payroll_runs", sa.Column("reversed_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("payroll_runs", sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_runs", sa.Column("reversal_reason", sa.Text, nullable=True))

    # ── payroll_approval_levels ──────────────────────────────────────────
    op.create_table(
        "payroll_approval_levels", *_base_columns(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("level_order", sa.Integer, nullable=False),
        sa.Column("required_permission", sa.String(100), nullable=False, server_default="payroll.approve"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index("ix_payroll_approval_levels_tenant_id", "payroll_approval_levels", ["tenant_id"])

    # ── payroll_approvals ─────────────────────────────────────────────────
    op.create_table(
        "payroll_approvals", *_base_columns(),
        sa.Column("payroll_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_approval_levels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", approval_decision_enum, nullable=False),
        sa.Column("comments", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_payroll_approvals_tenant_id", "payroll_approvals", ["tenant_id"])
    op.create_index("ix_payroll_approvals_payroll_run_id", "payroll_approvals", ["payroll_run_id"])

    # ── payroll_snapshots ─────────────────────────────────────────────────
    op.create_table(
        "payroll_snapshots", *_base_columns(),
        sa.Column("payroll_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("snapshot_data", sa.JSON, nullable=False),
        sa.Column("taken_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_payroll_snapshots_tenant_id", "payroll_snapshots", ["tenant_id"])

    # ── payroll_audit_logs ────────────────────────────────────────────────
    op.create_table(
        "payroll_audit_logs", *_base_columns(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_value", sa.JSON, nullable=True),
        sa.Column("new_value", sa.JSON, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
    )
    op.create_index("ix_payroll_audit_logs_tenant_id", "payroll_audit_logs", ["tenant_id"])
    op.create_index("ix_payroll_audit_logs_user_id", "payroll_audit_logs", ["user_id"])
    op.create_index("ix_payroll_audit_logs_action", "payroll_audit_logs", ["action"])
    op.create_index("ix_payroll_audit_logs_entity_id", "payroll_audit_logs", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_payroll_audit_logs_entity_id", table_name="payroll_audit_logs")
    op.drop_index("ix_payroll_audit_logs_action", table_name="payroll_audit_logs")
    op.drop_index("ix_payroll_audit_logs_user_id", table_name="payroll_audit_logs")
    op.drop_index("ix_payroll_audit_logs_tenant_id", table_name="payroll_audit_logs")
    op.drop_table("payroll_audit_logs")

    op.drop_index("ix_payroll_snapshots_tenant_id", table_name="payroll_snapshots")
    op.drop_table("payroll_snapshots")

    op.drop_index("ix_payroll_approvals_payroll_run_id", table_name="payroll_approvals")
    op.drop_index("ix_payroll_approvals_tenant_id", table_name="payroll_approvals")
    op.drop_table("payroll_approvals")

    op.drop_index("ix_payroll_approval_levels_tenant_id", table_name="payroll_approval_levels")
    op.drop_table("payroll_approval_levels")

    op.drop_column("payroll_runs", "reversal_reason")
    op.drop_column("payroll_runs", "reversed_at")
    op.drop_column("payroll_runs", "reversed_by_id")
    op.drop_column("payroll_runs", "reopen_reason")
    op.drop_column("payroll_runs", "reopened_at")
    op.drop_column("payroll_runs", "reopened_by_id")
    op.drop_column("payroll_runs", "locked_at")
    op.drop_column("payroll_runs", "locked_by_id")

    bind = op.get_bind()
    postgresql.ENUM(name="approval_decision_enum").drop(bind, checkfirst=True)
    # Note: Postgres does not support removing a value from an enum type
    # (ALTER TYPE ... DROP VALUE doesn't exist) — 'locked'/'reopened'/
    # 'reversed' remain valid enum labels even after this downgrade. This
    # is the standard, accepted limitation for additive enum migrations.
