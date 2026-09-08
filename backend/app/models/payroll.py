"""
Payroll models.

PayrollSettings  — one row per tenant: frequency, working-days method,
                   rounding, divisors, proration method (Phase 1)
SalaryStructure  — template defining how salary is computed for a group
                   (effective-dated/versioned — Phase 1)
SalaryComponent  — individual earning or deduction line item
                   (effective-dated/versioned — Phase 1)
PayrollComponentRule — per-employee, per-component override with its own
                   effective dates (replaces the old JSON overrides blob;
                   the JSON field is kept for backward compatibility and
                   used only as a fallback when no rule row exists)
EmployeeSalary   — links an employee to a salary structure with overrides
PayrollRun       — a payroll processing event for a period
Payslip          — individual payslip generated during a PayrollRun
PayslipLine      — single component row inside a payslip
"""

import uuid
import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey,
    Integer, Numeric, String, Text, JSON,
    Enum as SAEnum, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel


class PayrollFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    SEMI_MONTHLY = "semi_monthly"


class WorkingDaysMethod(str, enum.Enum):
    CALENDAR_DAYS = "calendar_days"    # every day in the period counts
    WORKING_DAYS = "working_days"      # Mon-Fri (or shift-defined) only
    FIXED_DIVISOR = "fixed_divisor"    # always divide by a constant, e.g. 30
    HOURLY = "hourly"                  # driven by scheduled/worked hours


class RoundingMode(str, enum.Enum):
    HALF_UP = "half_up"
    HALF_DOWN = "half_down"
    BANKERS = "bankers"       # round-half-to-even
    FLOOR = "floor"
    CEILING = "ceiling"
    NONE = "none"


class TaxCalculationBase(str, enum.Enum):
    MONTHLY_TAXABLE_INCOME = "monthly_taxable_income"
    ANNUAL_TAXABLE_INCOME = "annual_taxable_income"


class ContributionCalculationBase(str, enum.Enum):
    BASIC = "basic"
    GROSS = "gross"


class PayrollTaxRule(TenantModel):
    """
    A named, versioned tax configuration — e.g. "Pakistan Salaried Individuals
    FY2025-26". Deliberately generic: this engine does NOT ship with any
    country's real tax brackets baked in (see PayrollTaxBracket) — every
    tenant configures their own rule + brackets for their jurisdiction.
    """
    __tablename__ = "payroll_tax_rules"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tax_year: Mapped[str] = mapped_column(String(20), nullable=False, comment='e.g. "2025-2026"')
    calculation_base: Mapped[TaxCalculationBase] = mapped_column(
        SAEnum(TaxCalculationBase, name="tax_calculation_base_enum"),
        default=TaxCalculationBase.MONTHLY_TAXABLE_INCOME, nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    brackets: Mapped[list["PayrollTaxBracket"]] = relationship(
        "PayrollTaxBracket", back_populates="tax_rule", order_by="PayrollTaxBracket.min_amount"
    )

    def __repr__(self) -> str:
        return f"<PayrollTaxRule {self.name!r} {self.country}/{self.tax_year}>"


class PayrollTaxBracket(TenantModel):
    """
    One marginal bracket of a PayrollTaxRule: income between min_amount and
    max_amount (None = no upper bound — the top bracket) is taxed at
    rate_percentage. Standard progressive/marginal calculation — see
    app/services/payroll_tax.py::calculate_progressive_tax.
    """
    __tablename__ = "payroll_tax_brackets"

    tax_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_tax_rules.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    min_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    rate_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    tax_rule: Mapped["PayrollTaxRule"] = relationship("PayrollTaxRule", back_populates="brackets")

    def __repr__(self) -> str:
        upper = self.max_amount if self.max_amount is not None else "∞"
        return f"<PayrollTaxBracket {self.min_amount}-{upper} @ {self.rate_percentage}%>"


class PayrollContributionRule(TenantModel):
    """
    A statutory/company contribution (pension, social security, insurance,
    etc.) with independently configurable employee-side and employer-side
    amounts. Employer side is informational/costing only — it never reduces
    the employee's net salary, but shows up as an EMPLOYER_CONTRIBUTION
    payslip line (see ComponentType) for accounting/cost-analysis purposes.
    """
    __tablename__ = "payroll_contribution_rules"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    calculation_base: Mapped[ContributionCalculationBase] = mapped_column(
        SAEnum(ContributionCalculationBase, name="contribution_calculation_base_enum"),
        default=ContributionCalculationBase.BASIC, nullable=False,
    )
    employee_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    employee_fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    employer_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    employer_fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    min_base: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True, comment="Base below this -> no contribution",
    )
    max_base: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True, comment="Base is capped at this before applying percentage",
    )
    is_taxable: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="Whether the EMPLOYER-side contribution counts as taxable income for the employee",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<PayrollContributionRule {self.code!r}>"


class ComponentType(str, enum.Enum):
    EARNING = "earning"
    DEDUCTION = "deduction"
    EMPLOYER_CONTRIBUTION = "employer_contribution"


class ComponentCalculation(str, enum.Enum):
    FIXED = "fixed"
    PERCENTAGE_OF_BASIC = "percentage_of_basic"
    PERCENTAGE_OF_GROSS = "percentage_of_gross"
    FORMULA = "formula"


class PayrollRunStatus(str, enum.Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    REVIEW = "review"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class PayslipStatus(str, enum.Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    SENT = "sent"
    PAID = "paid"
    ON_HOLD = "on_hold"


class PayrollSettings(TenantModel):
    """
    One row per tenant — the configuration knobs every calculation engine
    (Phase 2+) reads from instead of hardcoding rules. Payroll-settings
    CHANGES themselves aren't multi-versioned yet (that's covered by the
    general payroll audit log planned in Phase 4); what's versioned here
    is what those settings apply TO — salary structures/components below.
    """
    __tablename__ = "payroll_settings"

    frequency: Mapped[PayrollFrequency] = mapped_column(
        SAEnum(PayrollFrequency, name="payroll_frequency_enum"),
        default=PayrollFrequency.MONTHLY, server_default="monthly", nullable=False,
    )
    period_start_day: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1",
        comment="Day of month a MONTHLY/SEMI_MONTHLY period starts on",
    )
    pay_date_offset_days: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0",
        comment="Days after period_end that pay_date defaults to",
    )

    working_days_method: Mapped[WorkingDaysMethod] = mapped_column(
        SAEnum(WorkingDaysMethod, name="working_days_method_enum"),
        default=WorkingDaysMethod.WORKING_DAYS, server_default="working_days", nullable=False,
    )
    fixed_monthly_divisor: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True,
        comment="Used when working_days_method=FIXED_DIVISOR, e.g. 30 or 26",
    )
    hourly_divisor: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True, comment="Standard hours/day used to derive an hourly rate from basic",
    )
    overtime_divisor: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True, comment="Hours used to derive the base hourly rate overtime multipliers apply to",
    )

    rounding_mode: Mapped[RoundingMode] = mapped_column(
        SAEnum(RoundingMode, name="rounding_mode_enum"),
        default=RoundingMode.HALF_UP, server_default="half_up", nullable=False,
    )
    decimal_precision: Mapped[int] = mapped_column(Integer, default=2, server_default="2")

    default_currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")

    allow_negative_net_salary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    minimum_net_salary: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True, comment="Validation floor — payroll blocks finalization below this if set",
    )
    maximum_deduction_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True, comment="e.g. 50.00 = deductions may never exceed 50% of gross",
    )

    proration_method: Mapped[WorkingDaysMethod] = mapped_column(
        SAEnum(WorkingDaysMethod, name="working_days_method_enum"),
        default=WorkingDaysMethod.CALENDAR_DAYS, server_default="calendar_days", nullable=False,
        comment="Used for mid-period joining/leaving/unpaid-leave proration (Phase 2+ engines read this). "
        "Shares the working_days_method_enum Postgres type with working_days_method above.",
    )

    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PayrollSettings tenant={self.tenant_id}>"


class SalaryStructure(TenantModel):
    __tablename__ = "salary_structures"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Versioning — editing a structure's name/description closes this row
    # (effective_to + is_current=False) and inserts a new one, rather than
    # mutating in place. A payroll run that already referenced this exact
    # row keeps pointing at the version that was active when it ran.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("salary_structures.id", ondelete="SET NULL"), nullable=True,
    )

    components: Mapped[list["SalaryComponent"]] = relationship(
        "SalaryComponent", back_populates="salary_structure"
    )

    def __repr__(self) -> str:
        return f"<SalaryStructure {self.code!r} v{self.version}>"


class SalaryComponent(TenantModel):
    __tablename__ = "salary_components"

    salary_structure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("salary_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    component_type: Mapped[ComponentType] = mapped_column(
        SAEnum(ComponentType, name="component_type_enum"), nullable=False
    )
    calculation_type: Mapped[ComponentCalculation] = mapped_column(
        SAEnum(ComponentCalculation, name="component_calc_enum"),
        default=ComponentCalculation.FIXED,
    )

    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    formula: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Safe formula expression referencing component codes (Phase 2 formula engine)"
    )

    is_taxable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Versioning — same reasoning as SalaryStructure above. Editing a
    # component's amount/percentage/formula closes this row rather than
    # mutating it, so a PayslipLine generated last month keeps meaning what
    # it meant last month even after HR changes the rate today.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("salary_components.id", ondelete="SET NULL"), nullable=True,
    )

    salary_structure: Mapped["SalaryStructure"] = relationship(
        "SalaryStructure", back_populates="components"
    )


class EmployeeSalary(TenantModel):
    __tablename__ = "employee_salaries"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    salary_structure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("salary_structures.id", ondelete="RESTRICT"),
        nullable=False,
    )

    basic_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Per-employee component overrides (LEGACY — kept for backward
    # compatibility with data written before PayrollComponentRule existed).
    # New overrides should be written as PayrollComponentRule rows instead;
    # the resolver checks for a matching rule first and only falls back to
    # this JSON blob if none exists. See PayrollComponentRule below.
    component_overrides: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default="{}",
        comment="DEPRECATED fallback — component_code → amount override. Prefer PayrollComponentRule.",
    )

    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    component_rules: Mapped[list["PayrollComponentRule"]] = relationship(
        "PayrollComponentRule", back_populates="employee_salary"
    )


class ComponentRuleOverrideType(str, enum.Enum):
    FIXED_AMOUNT = "fixed_amount"
    PERCENTAGE_OF_BASIC = "percentage_of_basic"
    PERCENTAGE_OF_GROSS = "percentage_of_gross"


class PayrollComponentRule(TenantModel):
    """
    A single employee's override of a single salary component, with its own
    effective dates — replaces EmployeeSalary.component_overrides (a loose,
    untyped, unversioned JSON dict) with proper auditable rows.

    Resolution order (see resolve_component_override in the payroll
    service): an active PayrollComponentRule for
    (employee_salary_id, salary_component_id) covering the payroll date
    wins; if none exists, the legacy JSON field is checked; otherwise the
    component's own structure-level amount/percentage/formula applies.
    """
    __tablename__ = "payroll_component_rules"

    employee_salary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee_salaries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    salary_component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("salary_components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    override_type: Mapped[ComponentRuleOverrideType] = mapped_column(
        SAEnum(ComponentRuleOverrideType, name="component_rule_override_type_enum"),
        default=ComponentRuleOverrideType.FIXED_AMOUNT, nullable=False,
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)

    effective_from: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    employee_salary: Mapped["EmployeeSalary"] = relationship(
        "EmployeeSalary", back_populates="component_rules"
    )

    def __repr__(self) -> str:
        return f"<PayrollComponentRule employee_salary={self.employee_salary_id} component={self.salary_component_id}>"


class PayrollRun(TenantModel):
    __tablename__ = "payroll_runs"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")

    status: Mapped[PayrollRunStatus] = mapped_column(
        SAEnum(PayrollRunStatus, name="payroll_run_status_enum"),
        default=PayrollRunStatus.DRAFT,
        nullable=False,
        index=True,
    )

    total_gross: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    total_net: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    employee_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    processed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    payslips: Mapped[list["Payslip"]] = relationship("Payslip", back_populates="payroll_run")

    def __repr__(self) -> str:
        return f"<PayrollRun {self.name!r} {self.period_start}→{self.period_end}>"


class Payslip(TenantModel):
    __tablename__ = "payslips"

    payroll_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    status: Mapped[PayslipStatus] = mapped_column(
        SAEnum(PayslipStatus, name="payslip_status_enum"),
        default=PayslipStatus.DRAFT,
        nullable=False,
    )

    working_days: Mapped[int] = mapped_column(Integer, default=0)
    present_days: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    absent_days: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    leave_days: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    unpaid_leave_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=0, server_default="0",
        comment="Portion of leave_days that came from an unpaid LeaveType — excluded from earnings proration",
    )
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)

    gross_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    net_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)

    payroll_run: Mapped["PayrollRun"] = relationship("PayrollRun", back_populates="payslips")
    lines: Mapped[list["PayslipLine"]] = relationship("PayslipLine", back_populates="payslip")


class PayslipLine(TenantModel):
    __tablename__ = "payslip_lines"

    payslip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payslips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    component_code: Mapped[str] = mapped_column(String(50), nullable=False)
    component_name: Mapped[str] = mapped_column(String(200), nullable=False)
    component_type: Mapped[ComponentType] = mapped_column(
        SAEnum(ComponentType, name="component_type_enum"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    payslip: Mapped["Payslip"] = relationship("Payslip", back_populates="lines")


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3: Loans, Advances, Bonuses, Commissions, Arrears, Reimbursements
# ═══════════════════════════════════════════════════════════════════════════
class LoanStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"       # fully repaid
    CANCELLED = "cancelled"


class PayrollLoan(TenantModel):
    """
    An employee loan repaid via fixed installments deducted each payroll
    run. remaining_balance is the single source of truth for how much is
    left — each deduction decrements it, and a deduction is capped at
    whatever's left (see resolve_loan_deduction), so a loan can never be
    overpaid past its principal.
    """
    __tablename__ = "payroll_loans"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, server_default="0")
    number_of_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    installment_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    remaining_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    deduction_priority: Mapped[int] = mapped_column(
        Integer, default=100, server_default="100",
        comment="Lower runs first when multiple deductions compete for a capped net salary",
    )
    status: Mapped[LoanStatus] = mapped_column(
        SAEnum(LoanStatus, name="loan_status_enum"), default=LoanStatus.ACTIVE, nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PayrollLoan employee={self.employee_id} balance={self.remaining_balance}>"


class AdvanceStatus(str, enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class PayrollAdvance(TenantModel):
    """A salary advance recovered via fixed installments — same repayment
    shape as PayrollLoan (remaining_balance decremented each run, capped),
    kept as a separate model since advances/loans have different approval
    workflows and reporting in most HR systems."""
    __tablename__ = "payroll_advances"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    advance_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    number_of_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    installment_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    remaining_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    recovery_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    deduction_priority: Mapped[int] = mapped_column(Integer, default=110, server_default="110")
    status: Mapped[AdvanceStatus] = mapped_column(
        SAEnum(AdvanceStatus, name="advance_status_enum"), default=AdvanceStatus.ACTIVE, nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PayrollAdvance employee={self.employee_id} balance={self.remaining_balance}>"


class BonusType(str, enum.Enum):
    PERFORMANCE = "performance"
    ANNUAL = "annual"
    FESTIVAL = "festival"
    JOINING = "joining"
    RETENTION = "retention"
    SPOT = "spot"
    ATTENDANCE = "attendance"
    CUSTOM = "custom"


class BonusStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class PayrollBonus(TenantModel):
    """
    A one-time (or recurring — is_recurring) bonus payment, targeted at a
    specific payroll period via target_period_start/end. Only APPROVED
    bonuses whose target period overlaps a run get pulled into that run
    (see generate_payroll_run) — PENDING ones are visible for review but
    never silently paid.
    """
    __tablename__ = "payroll_bonuses"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    bonus_type: Mapped[BonusType] = mapped_column(SAEnum(BonusType, name="bonus_type_enum"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_taxable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    target_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    target_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[BonusStatus] = mapped_column(
        SAEnum(BonusStatus, name="bonus_status_enum"), default=BonusStatus.PENDING, nullable=False,
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<PayrollBonus {self.bonus_type.value} employee={self.employee_id} {self.amount}>"


class CommissionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class PayrollCommissionPlan(TenantModel):
    """A named, reusable tiered-commission structure — e.g. 'Sales Team
    FY26'. Tiers work exactly like tax brackets (marginal, not
    lookup-single-rate): see calculate_tiered_commission."""
    __tablename__ = "payroll_commission_plans"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    tiers: Mapped[list["PayrollCommissionTier"]] = relationship(
        "PayrollCommissionTier", back_populates="plan", order_by="PayrollCommissionTier.min_amount"
    )


class PayrollCommissionTier(TenantModel):
    __tablename__ = "payroll_commission_tiers"

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_commission_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    rate_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    plan: Mapped["PayrollCommissionPlan"] = relationship("PayrollCommissionPlan", back_populates="tiers")


class PayrollCommission(TenantModel):
    """One employee's commission for one period, computed from a
    PayrollCommissionPlan against their achieved sales_amount. The
    computed amount is stored (not recomputed at payroll-generation time)
    so a later plan-tier edit never silently changes an already-approved
    commission — matches the snapshot/explainability principle used
    elsewhere in this module."""
    __tablename__ = "payroll_commissions"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_commission_plans.id", ondelete="SET NULL"), nullable=True)
    target_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    target_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    sales_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    computed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[CommissionStatus] = mapped_column(
        SAEnum(CommissionStatus, name="commission_status_enum"), default=CommissionStatus.PENDING, nullable=False,
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PayrollCommission employee={self.employee_id} {self.computed_amount}>"


class ArrearStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class PayrollArrear(TenantModel):
    """
    A backdated adjustment — e.g. a salary increment approved in March but
    effective from January, or a missed bonus. source_period_start/end
    records WHICH past period(s) this arrear corrects, while
    target_period records WHEN it actually gets paid (the run whose
    generation should include it). Keeping both is what makes an arrear
    explainable ("this ₹X is the January+February shortfall from the raise
    approved in March") instead of just an unexplained lump sum.
    """
    __tablename__ = "payroll_arrears"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    source_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    source_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    target_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    target_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_taxable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    calculation_details: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default="{}",
        comment="Free-form breakdown (e.g. per-month old vs new amount) shown on the payslip for explainability",
    )
    status: Mapped[ArrearStatus] = mapped_column(
        SAEnum(ArrearStatus, name="arrear_status_enum"), default=ArrearStatus.PENDING, nullable=False,
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PayrollArrear employee={self.employee_id} {self.amount}>"


class ReimbursementCategory(str, enum.Enum):
    TRAVEL = "travel"
    MEDICAL = "medical"
    FUEL = "fuel"
    INTERNET = "internet"
    MEALS = "meals"
    ACCOMMODATION = "accommodation"
    OTHER = "other"


class ReimbursementStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    INCLUDED_IN_PAYROLL = "included_in_payroll"
    PAID = "paid"
    REJECTED = "rejected"


class PayrollReimbursement(TenantModel):
    """
    Submitted → Reviewed → Approved → Included in Payroll → Paid.
    Only APPROVED reimbursements are eligible to be pulled into a payroll
    run (see generate_payroll_run); once pulled in, status flips to
    INCLUDED_IN_PAYROLL so the same claim is never double-paid across runs.
    """
    __tablename__ = "payroll_reimbursements"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[ReimbursementCategory] = mapped_column(SAEnum(ReimbursementCategory, name="reimbursement_category_enum"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_taxable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[ReimbursementStatus] = mapped_column(
        SAEnum(ReimbursementStatus, name="reimbursement_status_enum"), default=ReimbursementStatus.SUBMITTED, nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(), server_default=func.now())
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<PayrollReimbursement {self.category.value} employee={self.employee_id} {self.amount}>"
