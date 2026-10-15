"""payroll phase 3 — loans, advances, bonuses, commissions, arrears, reimbursements

Revision ID: d71b4e9c3a58
Revises: c58a6d1f0e23
Create Date: 2026-09-05 00:00:00.000000

Phase 3 of the enterprise payroll rebuild: the remaining earning/deduction
types from the spec that generate_payroll_run now pulls in automatically
each run — loan/advance installments, approved bonuses/arrears/
reimbursements targeting the run's period, and pre-computed commissions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd71b4e9c3a58'
down_revision: Union[str, None] = 'c58a6d1f0e23'
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

    # Uppercase labels (matching each Python enum member's .name) —
    # SQLAlchemy's Enum(python_enum_class) binds by .name by default, not
    # .value. See ebe9ce81bf8e_fix_work_session_status_enum_casing.py for
    # the same bug hit and fixed elsewhere in this codebase.
    enums = {
        "loan_status_enum": ("ACTIVE", "SUSPENDED", "CLOSED", "CANCELLED"),
        "advance_status_enum": ("ACTIVE", "CLOSED", "CANCELLED"),
        "bonus_type_enum": ("PERFORMANCE", "ANNUAL", "FESTIVAL", "JOINING", "RETENTION", "SPOT", "ATTENDANCE", "CUSTOM"),
        "bonus_status_enum": ("PENDING", "APPROVED", "PAID", "CANCELLED"),
        "commission_status_enum": ("PENDING", "APPROVED", "PAID", "CANCELLED"),
        "arrear_status_enum": ("PENDING", "APPROVED", "PAID", "CANCELLED"),
        "reimbursement_category_enum": ("TRAVEL", "MEDICAL", "FUEL", "INTERNET", "MEALS", "ACCOMMODATION", "OTHER"),
        "reimbursement_status_enum": ("SUBMITTED", "REVIEWED", "APPROVED", "INCLUDED_IN_PAYROLL", "PAID", "REJECTED"),
    }
    pg_enums = {}
    for name, values in enums.items():
        # create_type=False: see phase1/phase2 migrations for why this is
        # required — without it, using this same enum object as a column
        # type in op.create_table below re-issues CREATE TYPE a second
        # time and fails with "already exists".
        pg_enums[name] = postgresql.ENUM(*values, name=name, create_type=False)
        pg_enums[name].create(bind, checkfirst=True)

    # ── payroll_loans ───────────────────────────────────────────────────
    op.create_table(
        "payroll_loans", *_base_columns(),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("principal_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("interest_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("number_of_installments", sa.Integer, nullable=False),
        sa.Column("installment_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("remaining_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("deduction_priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("status", pg_enums["loan_status_enum"], nullable=False, server_default="ACTIVE"),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_payroll_loans_tenant_id", "payroll_loans", ["tenant_id"])
    op.create_index("ix_payroll_loans_employee_id", "payroll_loans", ["employee_id"])

    # ── payroll_advances ────────────────────────────────────────────────
    op.create_table(
        "payroll_advances", *_base_columns(),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("advance_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("number_of_installments", sa.Integer, nullable=False),
        sa.Column("installment_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("remaining_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("recovery_start_date", sa.Date, nullable=False),
        sa.Column("deduction_priority", sa.Integer, nullable=False, server_default="110"),
        sa.Column("status", pg_enums["advance_status_enum"], nullable=False, server_default="ACTIVE"),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_payroll_advances_tenant_id", "payroll_advances", ["tenant_id"])
    op.create_index("ix_payroll_advances_employee_id", "payroll_advances", ["employee_id"])

    # ── payroll_bonuses ─────────────────────────────────────────────────
    op.create_table(
        "payroll_bonuses", *_base_columns(),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bonus_type", pg_enums["bonus_type_enum"], nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_taxable", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_recurring", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("target_period_start", sa.Date, nullable=False),
        sa.Column("target_period_end", sa.Date, nullable=False),
        sa.Column("status", pg_enums["bonus_status_enum"], nullable=False, server_default="PENDING"),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_payroll_bonuses_tenant_id", "payroll_bonuses", ["tenant_id"])
    op.create_index("ix_payroll_bonuses_employee_id", "payroll_bonuses", ["employee_id"])

    # ── payroll_commission_plans / tiers / commissions ─────────────────
    op.create_table(
        "payroll_commission_plans", *_base_columns(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index("ix_payroll_commission_plans_tenant_id", "payroll_commission_plans", ["tenant_id"])

    op.create_table(
        "payroll_commission_tiers", *_base_columns(),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_commission_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("min_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("max_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("rate_percentage", sa.Numeric(5, 2), nullable=False),
    )
    op.create_index("ix_payroll_commission_tiers_tenant_id", "payroll_commission_tiers", ["tenant_id"])
    op.create_index("ix_payroll_commission_tiers_plan_id", "payroll_commission_tiers", ["plan_id"])

    op.create_table(
        "payroll_commissions", *_base_columns(),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_commission_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_period_start", sa.Date, nullable=False),
        sa.Column("target_period_end", sa.Date, nullable=False),
        sa.Column("sales_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("computed_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", pg_enums["commission_status_enum"], nullable=False, server_default="PENDING"),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_payroll_commissions_tenant_id", "payroll_commissions", ["tenant_id"])
    op.create_index("ix_payroll_commissions_employee_id", "payroll_commissions", ["employee_id"])

    # ── payroll_arrears ─────────────────────────────────────────────────
    op.create_table(
        "payroll_arrears", *_base_columns(),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("source_period_start", sa.Date, nullable=False),
        sa.Column("source_period_end", sa.Date, nullable=False),
        sa.Column("target_period_start", sa.Date, nullable=False),
        sa.Column("target_period_end", sa.Date, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_taxable", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("calculation_details", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("status", pg_enums["arrear_status_enum"], nullable=False, server_default="PENDING"),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_payroll_arrears_tenant_id", "payroll_arrears", ["tenant_id"])
    op.create_index("ix_payroll_arrears_employee_id", "payroll_arrears", ["employee_id"])

    # ── payroll_reimbursements ──────────────────────────────────────────
    op.create_table(
        "payroll_reimbursements", *_base_columns(),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", pg_enums["reimbursement_category_enum"], nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("receipt_url", sa.String(500), nullable=True),
        sa.Column("is_taxable", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", pg_enums["reimbursement_status_enum"], nullable=False, server_default="SUBMITTED"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
    )
    op.create_index("ix_payroll_reimbursements_tenant_id", "payroll_reimbursements", ["tenant_id"])
    op.create_index("ix_payroll_reimbursements_employee_id", "payroll_reimbursements", ["employee_id"])


def downgrade() -> None:
    for table, idx_cols in [
        ("payroll_reimbursements", ["employee_id", "tenant_id"]),
        ("payroll_arrears", ["employee_id", "tenant_id"]),
        ("payroll_commissions", ["employee_id", "tenant_id"]),
        ("payroll_commission_tiers", ["plan_id", "tenant_id"]),
        ("payroll_commission_plans", ["tenant_id"]),
        ("payroll_bonuses", ["employee_id", "tenant_id"]),
        ("payroll_advances", ["employee_id", "tenant_id"]),
        ("payroll_loans", ["employee_id", "tenant_id"]),
    ]:
        for col in idx_cols:
            op.drop_index(f"ix_{table}_{col}", table_name=table)
        op.drop_table(table)

    bind = op.get_bind()
    for enum_name in (
        "reimbursement_status_enum", "reimbursement_category_enum", "arrear_status_enum",
        "commission_status_enum", "bonus_status_enum", "bonus_type_enum",
        "advance_status_enum", "loan_status_enum",
    ):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
