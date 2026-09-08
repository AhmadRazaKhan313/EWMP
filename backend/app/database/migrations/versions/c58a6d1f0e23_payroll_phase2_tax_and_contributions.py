"""payroll phase 2 — tax rules/brackets, contribution rules, unpaid leave tracking

Revision ID: c58a6d1f0e23
Revises: b4e7f2a91c56
Create Date: 2026-09-05 00:00:00.000000

Phase 2 of the enterprise payroll rebuild: tax engine schema, contribution
engine schema, and a payslip column to report unpaid-leave days separately
(needed for the leave.is_paid fix — see app/api/v1/hrms/payroll.py).

No real country's tax brackets or contribution rates are seeded here —
this is deliberately generic. Each tenant configures its own
PayrollTaxRule + PayrollTaxBracket rows and PayrollContributionRule rows
for its own jurisdiction via the new /payroll/tax-rules and
/payroll/contribution-rules endpoints.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c58a6d1f0e23'
down_revision: Union[str, None] = 'b4e7f2a91c56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    tax_calculation_base_enum = postgresql.ENUM(
        "monthly_taxable_income", "annual_taxable_income", name="tax_calculation_base_enum"
    )
    contribution_calculation_base_enum = postgresql.ENUM(
        "basic", "gross", name="contribution_calculation_base_enum"
    )
    for enum_type in (tax_calculation_base_enum, contribution_calculation_base_enum):
        enum_type.create(bind, checkfirst=True)

    # ── payroll_tax_rules ───────────────────────────────────────────────
    op.create_table(
        "payroll_tax_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("tax_year", sa.String(20), nullable=False),
        sa.Column("calculation_base", tax_calculation_base_enum, nullable=False, server_default="monthly_taxable_income"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_payroll_tax_rules_tenant_id", "payroll_tax_rules", ["tenant_id"])
    op.create_index("ix_payroll_tax_rules_country", "payroll_tax_rules", ["country"])

    # ── payroll_tax_brackets ────────────────────────────────────────────
    op.create_table(
        "payroll_tax_brackets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("tax_rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_tax_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("min_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("max_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("rate_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_payroll_tax_brackets_tenant_id", "payroll_tax_brackets", ["tenant_id"])
    op.create_index("ix_payroll_tax_brackets_tax_rule_id", "payroll_tax_brackets", ["tax_rule_id"])

    # ── payroll_contribution_rules ──────────────────────────────────────
    op.create_table(
        "payroll_contribution_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("calculation_base", contribution_calculation_base_enum, nullable=False, server_default="basic"),
        sa.Column("employee_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("employee_fixed_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("employer_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("employer_fixed_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("min_base", sa.Numeric(14, 2), nullable=True),
        sa.Column("max_base", sa.Numeric(14, 2), nullable=True),
        sa.Column("is_taxable", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("effective_from", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("effective_to", sa.Date, nullable=True),
    )
    op.create_index("ix_payroll_contribution_rules_tenant_id", "payroll_contribution_rules", ["tenant_id"])
    op.create_index("ix_payroll_contribution_rules_code", "payroll_contribution_rules", ["code"])

    # ── payslips.unpaid_leave_days ──────────────────────────────────────
    # Separates "total leave days" (existing leave_days, unchanged) from
    # the unpaid portion specifically — see the leave.is_paid fix in
    # generate_payroll_run, which previously counted every ON_LEAVE day as
    # paid regardless of the leave type.
    op.add_column(
        "payslips",
        sa.Column("unpaid_leave_days", sa.Numeric(5, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("payslips", "unpaid_leave_days")

    op.drop_index("ix_payroll_contribution_rules_code", table_name="payroll_contribution_rules")
    op.drop_index("ix_payroll_contribution_rules_tenant_id", table_name="payroll_contribution_rules")
    op.drop_table("payroll_contribution_rules")

    op.drop_index("ix_payroll_tax_brackets_tax_rule_id", table_name="payroll_tax_brackets")
    op.drop_index("ix_payroll_tax_brackets_tenant_id", table_name="payroll_tax_brackets")
    op.drop_table("payroll_tax_brackets")

    op.drop_index("ix_payroll_tax_rules_country", table_name="payroll_tax_rules")
    op.drop_index("ix_payroll_tax_rules_tenant_id", table_name="payroll_tax_rules")
    op.drop_table("payroll_tax_rules")

    bind = op.get_bind()
    for enum_name in ("contribution_calculation_base_enum", "tax_calculation_base_enum"):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
