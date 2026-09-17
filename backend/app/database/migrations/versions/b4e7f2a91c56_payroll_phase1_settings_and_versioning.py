"""payroll phase 1 — settings, salary structures/components, employee salaries, payroll runs, payslips

Revision ID: b4e7f2a91c56
Revises: a3f9c1d8e4b7
Create Date: 2026-09-04 22:00:00.000000

Phase 1 of the enterprise payroll rebuild: per-tenant PayrollSettings,
versioned SalaryStructure/SalaryComponent templates, EmployeeSalary
assignments, and per-employee PayrollComponentRule overrides. See
app/models/payroll.py for the full field-by-field rationale — this
migration mirrors those model definitions exactly.

payroll_runs / payslips / payslip_lines / employee_salaries already exist
(created by the platform's initial_schema migration, 8796d530abeb) with
exactly the shape this phase needs — this migration does NOT recreate
them. The original draft of this migration did `op.create_table(...)` for
all four, which fails outright with "relation already exists" the moment
`alembic upgrade head` reaches this revision, since down_revision chains
back through initial_schema where they were already created. That failure
blocked every migration after this one (phase 2/3/4 never applied either),
while the ORM models already assumed the phase-4 shape (locked_by_id,
reopened_by_id, etc. on payroll_runs) — so even the simplest insert
(POST /payroll/runs) crashed with "column ... does not exist", surfacing
in the browser as a CORS error because the exception handler for bare
Exception is bound to Starlette's ServerErrorMiddleware, outside CORSMiddleware.

salary_structures and salary_components DO already exist too, but with an
older, non-versioned shape — this phase ADDS the new versioning columns
(version/effective_from/effective_to/is_current/superseded_by_id) onto
those existing tables instead of recreating them.

Enum casing: every new enum type below is created with the Python enum
member's UPPERCASE *name* as the Postgres label (e.g. 'MONTHLY', not
'monthly') to match how SQLAlchemy's `Enum(python_enum_class)` binds
values by default — see ebe9ce81bf8e_fix_work_session_status_enum_casing.py
for the exact same bug already hit (and fixed) elsewhere in this codebase.
component_type_enum and component_calc_enum are NOT created here — they
also already exist, correctly uppercase, from initial_schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b4e7f2a91c56'
down_revision: Union[str, None] = 'a3f9c1d8e4b7'
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

    enums = {
        "payroll_frequency_enum": ("MONTHLY", "WEEKLY", "BIWEEKLY", "SEMI_MONTHLY"),
        "working_days_method_enum": ("CALENDAR_DAYS", "WORKING_DAYS", "FIXED_DIVISOR", "HOURLY"),
        "rounding_mode_enum": ("HALF_UP", "HALF_DOWN", "BANKERS", "FLOOR", "CEILING", "NONE"),
        "component_rule_override_type_enum": ("FIXED_AMOUNT", "PERCENTAGE_OF_BASIC", "PERCENTAGE_OF_GROSS"),
    }
    pg_enums = {}
    for name, values in enums.items():
        # create_type=False: without this, SQLAlchemy tries to CREATE TYPE
        # a second time (with checkfirst=False) the moment this same enum
        # object is used as a column type below in op.create_table — even
        # though it was already created, successfully, on the line right
        # after this loop. That second attempt is what raises
        # "type ... already exists" (asyncpg.DuplicateObjectError).
        pg_enums[name] = postgresql.ENUM(*values, name=name, create_type=False)
        pg_enums[name].create(bind, checkfirst=True)

    # ── payroll_settings ──────────────────────────────────────────────
    op.create_table(
        "payroll_settings", *_base_columns(),
        sa.Column("frequency", pg_enums["payroll_frequency_enum"], nullable=False, server_default="MONTHLY"),
        sa.Column("period_start_day", sa.Integer, nullable=False, server_default="1"),
        sa.Column("pay_date_offset_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("working_days_method", pg_enums["working_days_method_enum"], nullable=False, server_default="WORKING_DAYS"),
        sa.Column("fixed_monthly_divisor", sa.Numeric(6, 2), nullable=True),
        sa.Column("hourly_divisor", sa.Numeric(6, 2), nullable=True),
        sa.Column("overtime_divisor", sa.Numeric(6, 2), nullable=True),
        sa.Column("rounding_mode", pg_enums["rounding_mode_enum"], nullable=False, server_default="HALF_UP"),
        sa.Column("decimal_precision", sa.Integer, nullable=False, server_default="2"),
        sa.Column("default_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("allow_negative_net_salary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("minimum_net_salary", sa.Numeric(12, 2), nullable=True),
        sa.Column("maximum_deduction_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("proration_method", pg_enums["working_days_method_enum"], nullable=False, server_default="CALENDAR_DAYS"),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_payroll_settings_tenant_id", "payroll_settings", ["tenant_id"])

    # ── salary_structures ─────────────────────────────────────────────
    # Table already exists (initial_schema) with name/code/description/
    # currency/is_active/is_default + base columns. Only add the new
    # versioning columns — do not recreate the table.
    op.add_column("salary_structures", sa.Column("version", sa.Integer, nullable=False, server_default="1"))
    op.add_column("salary_structures", sa.Column("effective_from", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")))
    op.add_column("salary_structures", sa.Column("effective_to", sa.Date, nullable=True))
    op.add_column("salary_structures", sa.Column("is_current", sa.Boolean, nullable=False, server_default="true"))
    op.add_column("salary_structures", sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_salary_structures_superseded_by_id", "salary_structures", "salary_structures",
        ["superseded_by_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_salary_structures_is_current", "salary_structures", ["is_current"])
    # ix_salary_structures_tenant_id / ix_salary_structures_code already
    # exist from initial_schema — not recreated here.

    # ── salary_components ─────────────────────────────────────────────
    # Table already exists (initial_schema) with salary_structure_id/name/
    # code/component_type/calculation_type/amount/percentage/formula/
    # is_taxable/is_mandatory/display_order/is_active + base columns,
    # using the already-correctly-uppercase component_type_enum /
    # component_calc_enum. Only add the new versioning columns.
    op.add_column("salary_components", sa.Column("version", sa.Integer, nullable=False, server_default="1"))
    op.add_column("salary_components", sa.Column("effective_from", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")))
    op.add_column("salary_components", sa.Column("effective_to", sa.Date, nullable=True))
    op.add_column("salary_components", sa.Column("is_current", sa.Boolean, nullable=False, server_default="true"))
    op.add_column("salary_components", sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_salary_components_superseded_by_id", "salary_components", "salary_components",
        ["superseded_by_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_salary_components_is_current", "salary_components", ["is_current"])
    # ix_salary_components_tenant_id / ix_salary_components_salary_structure_id
    # already exist from initial_schema — not recreated here.

    # employee_salaries already exists (initial_schema) with exactly the
    # shape this phase needs (employee_id, salary_structure_id,
    # basic_salary, effective_from/to, is_current, component_overrides,
    # approved_by_id, notes + base columns, plus its two indexes) — nothing
    # to add here.

    # ── payroll_component_rules ────────────────────────────────────────
    op.create_table(
        "payroll_component_rules", *_base_columns(),
        sa.Column("employee_salary_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee_salaries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("salary_component_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("salary_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("override_type", pg_enums["component_rule_override_type_enum"], nullable=False, server_default="FIXED_AMOUNT"),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("percentage", sa.Numeric(6, 4), nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_payroll_component_rules_tenant_id", "payroll_component_rules", ["tenant_id"])
    op.create_index("ix_payroll_component_rules_employee_salary_id", "payroll_component_rules", ["employee_salary_id"])
    op.create_index("ix_payroll_component_rules_salary_component_id", "payroll_component_rules", ["salary_component_id"])

    # payroll_runs / payslips / payslip_lines already exist (initial_schema)
    # with exactly the shape this phase needs — nothing to add here.
    # (unpaid_leave_days on payslips is genuinely new and is added by
    # Phase 2, not here.)


def downgrade() -> None:
    # payroll_runs / payslips / payslip_lines / employee_salaries are not
    # touched by upgrade() (they pre-date this migration), so nothing to
    # drop for them here.

    op.drop_index("ix_payroll_component_rules_salary_component_id", table_name="payroll_component_rules")
    op.drop_index("ix_payroll_component_rules_employee_salary_id", table_name="payroll_component_rules")
    op.drop_index("ix_payroll_component_rules_tenant_id", table_name="payroll_component_rules")
    op.drop_table("payroll_component_rules")

    op.drop_constraint("fk_salary_components_superseded_by_id", "salary_components", type_="foreignkey")
    op.drop_index("ix_salary_components_is_current", table_name="salary_components")
    op.drop_column("salary_components", "superseded_by_id")
    op.drop_column("salary_components", "is_current")
    op.drop_column("salary_components", "effective_to")
    op.drop_column("salary_components", "effective_from")
    op.drop_column("salary_components", "version")

    op.drop_constraint("fk_salary_structures_superseded_by_id", "salary_structures", type_="foreignkey")
    op.drop_index("ix_salary_structures_is_current", table_name="salary_structures")
    op.drop_column("salary_structures", "superseded_by_id")
    op.drop_column("salary_structures", "is_current")
    op.drop_column("salary_structures", "effective_to")
    op.drop_column("salary_structures", "effective_from")
    op.drop_column("salary_structures", "version")

    op.drop_index("ix_payroll_settings_tenant_id", table_name="payroll_settings")
    op.drop_table("payroll_settings")

    bind = op.get_bind()
    for name in (
        "component_rule_override_type_enum", "rounding_mode_enum",
        "working_days_method_enum", "payroll_frequency_enum",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
