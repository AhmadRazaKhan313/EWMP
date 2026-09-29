"""payroll phase 5 — accounting integration and payment processing

Revision ID: f93d6a2e8c17
Revises: e82c5f7b1d94
Create Date: 2026-09-09 00:00:00.000000

Phase 5: configurable chart-of-account mappings for journal-entry
generation, and payment batches for bank-transfer preparation +
reconciliation. Reports and YTD are computed on the fly from existing
payslip data — no new tables needed for those.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f93d6a2e8c17'
down_revision: Union[str, None] = 'e82c5f7b1d94'
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

    # Uppercase values: SQLAlchemy's default Enum behavior for a Python
    # str-Enum stores the MEMBER NAME (e.g. "PREPARED"), not member.value
    # (e.g. "prepared") — see app/models/payroll.py's AccountMappingPurpose,
    # PaymentBatchStatus, PaymentItemStatus, all declared as plain
    # SAEnum(PythonEnumClass, name=...) with no values_callable override.
    account_mapping_purpose_enum = postgresql.ENUM(
        "SALARY_EXPENSE", "EMPLOYER_CONTRIBUTION_EXPENSE", "NET_PAY_PAYABLE", "TAX_PAYABLE",
        "CONTRIBUTION_PAYABLE", "LOAN_RECOVERY_PAYABLE", "ADVANCE_RECOVERY_PAYABLE", "OTHER_DEDUCTIONS_PAYABLE",
        name="account_mapping_purpose_enum", create_type=False,
    )
    payment_batch_status_enum = postgresql.ENUM(
        "PREPARED", "PROCESSING", "COMPLETED", "FAILED", name="payment_batch_status_enum", create_type=False,
    )
    payment_item_status_enum = postgresql.ENUM(
        "PENDING", "PAID", "FAILED", name="payment_item_status_enum", create_type=False,
    )
    # create_type=False above: without it, SQLAlchemy re-issues CREATE TYPE
    # (with checkfirst=False) the moment these same enum objects are used
    # as column types in op.create_table below — even though the explicit
    # .create(checkfirst=True) call right here already succeeded. That
    # second, unconditional attempt is what raises "type ... already
    # exists" (asyncpg.DuplicateObjectError) — see phases 1-4 for the same
    # fix.
    for enum_type in (account_mapping_purpose_enum, payment_batch_status_enum, payment_item_status_enum):
        enum_type.create(bind, checkfirst=True)

    # ── payroll_account_mappings ──────────────────────────────────────────
    op.create_table(
        "payroll_account_mappings", *_base_columns(),
        sa.Column("purpose", account_mapping_purpose_enum, nullable=False),
        sa.Column("account_code", sa.String(50), nullable=False),
        sa.Column("account_name", sa.String(200), nullable=False),
    )
    op.create_index("ix_payroll_account_mappings_tenant_id", "payroll_account_mappings", ["tenant_id"])
    op.create_unique_constraint("uq_payroll_account_mappings_tenant_purpose", "payroll_account_mappings", ["tenant_id", "purpose"])

    # ── payroll_payment_batches ───────────────────────────────────────────
    op.create_table(
        "payroll_payment_batches", *_base_columns(),
        sa.Column("payroll_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", payment_batch_status_enum, nullable=False, server_default="PREPARED"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_index("ix_payroll_payment_batches_tenant_id", "payroll_payment_batches", ["tenant_id"])
    op.create_index("ix_payroll_payment_batches_payroll_run_id", "payroll_payment_batches", ["payroll_run_id"])

    # ── payroll_payment_batch_items ───────────────────────────────────────
    op.create_table(
        "payroll_payment_batch_items", *_base_columns(),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_payment_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payslip_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payslips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("bank_account_number", sa.String(100), nullable=True),
        sa.Column("bank_account_title", sa.String(100), nullable=True),
        sa.Column("status", payment_item_status_enum, nullable=False, server_default="PENDING"),
        sa.Column("payment_reference", sa.String(200), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text, nullable=True),
    )
    op.create_index("ix_payroll_payment_batch_items_tenant_id", "payroll_payment_batch_items", ["tenant_id"])
    op.create_index("ix_payroll_payment_batch_items_batch_id", "payroll_payment_batch_items", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_payroll_payment_batch_items_batch_id", table_name="payroll_payment_batch_items")
    op.drop_index("ix_payroll_payment_batch_items_tenant_id", table_name="payroll_payment_batch_items")
    op.drop_table("payroll_payment_batch_items")

    op.drop_index("ix_payroll_payment_batches_payroll_run_id", table_name="payroll_payment_batches")
    op.drop_index("ix_payroll_payment_batches_tenant_id", table_name="payroll_payment_batches")
    op.drop_table("payroll_payment_batches")

    op.drop_constraint("uq_payroll_account_mappings_tenant_purpose", "payroll_account_mappings", type_="unique")
    op.drop_index("ix_payroll_account_mappings_tenant_id", table_name="payroll_account_mappings")
    op.drop_table("payroll_account_mappings")

    bind = op.get_bind()
    for enum_name in ("payment_item_status_enum", "payment_batch_status_enum", "account_mapping_purpose_enum"):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
