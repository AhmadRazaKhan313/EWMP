"""
Payroll API endpoints.

Covers the full payroll engine:
  - Salary structure builder (structures + earning/deduction components)
  - Assigning a structure + basic salary to an employee
  - Generating a payroll run: pulls attendance for the period, computes each
    component per employee, creates Payslip + PayslipLine rows
  - Payslip PDF export (generated on demand with reportlab)
"""

import io
from datetime import date, datetime, UTC
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.models.attendance import AttendanceRecord, AttendanceStatus, LeaveRequest, LeaveRequestStatus, LeaveType
from app.models.employee import Employee, EmploymentStatus
from app.models.payroll import (
    ComponentCalculation,
    ComponentRuleOverrideType,
    ComponentType,
    ContributionCalculationBase,
    EmployeeSalary,
    PayrollAdvance,
    AdvanceStatus,
    PayrollArrear,
    ArrearStatus,
    PayrollBonus,
    BonusType,
    BonusStatus,
    PayrollCommission,
    CommissionStatus,
    PayrollCommissionPlan,
    PayrollCommissionTier,
    PayrollComponentRule,
    PayrollContributionRule,
    PayrollFrequency,
    PayrollLoan,
    LoanStatus,
    PayrollReimbursement,
    ReimbursementCategory,
    ReimbursementStatus,
    PayrollRun,
    PayrollRunStatus,
    PayrollSettings,
    PayrollTaxBracket,
    PayrollTaxRule,
    Payslip,
    PayslipLine,
    PayslipStatus,
    RoundingMode,
    SalaryComponent,
    SalaryStructure,
    TaxCalculationBase,
    WorkingDaysMethod,
)
from app.services.payroll_commission import CommissionTierData, calculate_tiered_commission
from app.services.payroll_contribution import ContributionRuleData, calculate_contribution
from app.services.payroll_formula import (
    CircularFormulaDependencyError,
    FormulaError,
    evaluate_formula,
    topological_sort_formulas,
    validate_formula,
)
from app.services.payroll_tax import TaxBracketData, calculate_progressive_tax, monthly_from_annual
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from app.repositories.employee import EmployeeRepository

router = APIRouter(prefix="/payroll", tags=["Payroll"])



class SalaryComponentInput(BaseModel):
    name: str
    code: str
    component_type: ComponentType
    calculation_type: ComponentCalculation = ComponentCalculation.FIXED
    amount: Decimal | None = None
    percentage: Decimal | None = None
    formula: str | None = None
    is_taxable: bool = True
    is_mandatory: bool = False
    display_order: int = 0


class SalaryStructureCreate(BaseModel):
    name: str
    code: str
    description: str | None = None
    currency: str = Field(default="USD", max_length=3)
    is_default: bool = False
    components: list[SalaryComponentInput] = []


class AssignSalaryRequest(BaseModel):
    salary_structure_id: UUID
    basic_salary: Decimal
    effective_from: date
    component_overrides: dict[str, float] = {}


class CreatePayrollRunRequest(BaseModel):
    name: str
    period_start: date
    period_end: date
    pay_date: date
    currency: str = Field(default="USD", max_length=3)


class PayrollSettingsUpdate(BaseModel):
    frequency: PayrollFrequency | None = None
    period_start_day: int | None = Field(default=None, ge=1, le=31)
    pay_date_offset_days: int | None = Field(default=None, ge=0)
    working_days_method: WorkingDaysMethod | None = None
    fixed_monthly_divisor: Decimal | None = None
    hourly_divisor: Decimal | None = None
    overtime_divisor: Decimal | None = None
    rounding_mode: RoundingMode | None = None
    decimal_precision: int | None = Field(default=None, ge=0, le=6)
    default_currency: str | None = Field(default=None, max_length=3)
    allow_negative_net_salary: bool | None = None
    minimum_net_salary: Decimal | None = None
    maximum_deduction_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    proration_method: WorkingDaysMethod | None = None


class SalaryStructureUpdate(BaseModel):
    """
    Editing structure-level metadata creates a NEW version rather than
    mutating the existing row — see create_or_update_salary_structure.
    Only structure-level fields here; per-component edits go through
    PATCH /salary-components/{id} instead, so changing one allowance's
    amount doesn't force a whole new structure version.
    """
    name: str | None = None
    description: str | None = None
    currency: str | None = Field(default=None, max_length=3)
    is_default: bool | None = None
    effective_from: date | None = None


class SalaryComponentUpdate(BaseModel):
    name: str | None = None
    calculation_type: ComponentCalculation | None = None
    amount: Decimal | None = None
    percentage: Decimal | None = None
    formula: str | None = None
    is_taxable: bool | None = None
    is_mandatory: bool | None = None
    display_order: int | None = None
    effective_from: date | None = None


class ComponentRuleCreate(BaseModel):
    salary_component_id: UUID
    override_type: ComponentRuleOverrideType = ComponentRuleOverrideType.FIXED_AMOUNT
    amount: Decimal | None = None
    percentage: Decimal | None = None
    effective_from: date | None = None
    notes: str | None = None


# ── Payroll Settings ─────────────────────────────────────────────────────────
def _serialize_settings(s: PayrollSettings) -> dict:
    return {
        "frequency": s.frequency.value,
        "period_start_day": s.period_start_day,
        "pay_date_offset_days": s.pay_date_offset_days,
        "working_days_method": s.working_days_method.value,
        "fixed_monthly_divisor": str(s.fixed_monthly_divisor) if s.fixed_monthly_divisor is not None else None,
        "hourly_divisor": str(s.hourly_divisor) if s.hourly_divisor is not None else None,
        "overtime_divisor": str(s.overtime_divisor) if s.overtime_divisor is not None else None,
        "rounding_mode": s.rounding_mode.value,
        "decimal_precision": s.decimal_precision,
        "default_currency": s.default_currency,
        "allow_negative_net_salary": s.allow_negative_net_salary,
        "minimum_net_salary": str(s.minimum_net_salary) if s.minimum_net_salary is not None else None,
        "maximum_deduction_percentage": (
            str(s.maximum_deduction_percentage) if s.maximum_deduction_percentage is not None else None
        ),
        "proration_method": s.proration_method.value,
    }


async def _get_or_create_settings(db: AsyncSession, tenant_id: UUID) -> PayrollSettings:
    """
    Get-or-create rather than requiring an explicit setup step — a tenant
    that's never touched payroll settings still gets sane, documented
    defaults (monthly / working-days / half-up rounding) instead of every
    other endpoint needing to handle "settings row doesn't exist yet".
    """
    settings = (
        await db.execute(select(PayrollSettings).where(PayrollSettings.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if settings is None:
        # Explicit defaults here, not relying on the column's default=/
        # server_default= alone — those only apply once SQLAlchemy's unit of
        # work actually flushes the INSERT, so an object serialized right
        # after construction (as happens a few lines below) would otherwise
        # briefly have None for every defaulted field.
        settings = PayrollSettings(
            tenant_id=tenant_id,
            frequency=PayrollFrequency.MONTHLY,
            period_start_day=1,
            pay_date_offset_days=0,
            working_days_method=WorkingDaysMethod.WORKING_DAYS,
            rounding_mode=RoundingMode.HALF_UP,
            decimal_precision=2,
            default_currency="USD",
            allow_negative_net_salary=False,
            proration_method=WorkingDaysMethod.CALENDAR_DAYS,
        )
        db.add(settings)
        await db.flush()
    return settings


@router.get("/settings", summary="Get this tenant's payroll settings (created with defaults on first read)")
async def get_payroll_settings(
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = await _get_or_create_settings(db, tenant_id)
    return _serialize_settings(settings)


@router.put("/settings", summary="Update this tenant's payroll settings")
async def update_payroll_settings(
    body: PayrollSettingsUpdate,
    current_user: User = Depends(require_permission("payroll.manage_settings")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = await _get_or_create_settings(db, tenant_id)
    updates = body.model_dump(exclude_unset=True)

    resulting_method = updates.get("working_days_method", settings.working_days_method)
    resulting_divisor = updates.get("fixed_monthly_divisor", settings.fixed_monthly_divisor)
    if resulting_method == WorkingDaysMethod.FIXED_DIVISOR and (
        resulting_divisor is None or resulting_divisor <= 0
    ):
        raise ValidationError(
            "fixed_monthly_divisor must be a positive number when working_days_method is fixed_divisor"
        )

    for field, value in updates.items():
        setattr(settings, field, value)
    settings.updated_by_id = current_user.id

    await db.flush()
    return _serialize_settings(settings)


# ── Tax Rules ─────────────────────────────────────────────────────────────────
class TaxBracketInput(BaseModel):
    min_amount: Decimal
    max_amount: Decimal | None = None
    rate_percentage: Decimal
    display_order: int = 0


class TaxRuleCreate(BaseModel):
    name: str
    country: str
    tax_year: str
    calculation_base: TaxCalculationBase = TaxCalculationBase.MONTHLY_TAXABLE_INCOME
    effective_from: date
    effective_to: date | None = None
    notes: str | None = None
    brackets: list[TaxBracketInput] = Field(default_factory=list)


def _serialize_tax_rule(r: PayrollTaxRule) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "country": r.country,
        "tax_year": r.tax_year,
        "calculation_base": r.calculation_base.value,
        "is_active": r.is_active,
        "effective_from": str(r.effective_from),
        "effective_to": str(r.effective_to) if r.effective_to else None,
        "notes": r.notes,
        "brackets": [
            {
                "id": str(b.id), "min_amount": str(b.min_amount),
                "max_amount": str(b.max_amount) if b.max_amount is not None else None,
                "rate_percentage": str(b.rate_percentage), "display_order": b.display_order,
            }
            for b in sorted(r.brackets, key=lambda b: b.min_amount)
        ],
    }


@router.get("/tax-rules", summary="List payroll tax rules")
async def list_tax_rules(
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy.orm import selectinload

    rules = (
        await db.execute(
            select(PayrollTaxRule)
            .where(PayrollTaxRule.tenant_id == tenant_id, PayrollTaxRule.is_deleted == False)  # noqa: E712
            .options(selectinload(PayrollTaxRule.brackets))
            .order_by(PayrollTaxRule.effective_from.desc())
        )
    ).scalars().all()
    return {"items": [_serialize_tax_rule(r) for r in rules], "total": len(rules)}


@router.post("/tax-rules", status_code=status.HTTP_201_CREATED, summary="Create a payroll tax rule with brackets")
async def create_tax_rule(
    body: TaxRuleCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Validate the bracket set is internally consistent before saving —
    # catches copy-paste mistakes (overlapping/reversed ranges, negative
    # rates) at configuration time rather than surfacing as a wrong payslip
    # number later.
    sorted_brackets = sorted(body.brackets, key=lambda b: b.min_amount)
    for i, b in enumerate(sorted_brackets):
        if b.rate_percentage < 0 or b.rate_percentage > 100:
            raise ValidationError(f"Bracket rate must be between 0 and 100 (got {b.rate_percentage})")
        if b.max_amount is not None and b.max_amount <= b.min_amount:
            raise ValidationError(f"Bracket max_amount must be greater than min_amount ({b.min_amount})")
        if i > 0 and sorted_brackets[i - 1].max_amount is not None and b.min_amount < sorted_brackets[i - 1].max_amount:
            raise ValidationError("Tax brackets must not overlap")

    rule = PayrollTaxRule(
        tenant_id=tenant_id, name=body.name, country=body.country, tax_year=body.tax_year,
        calculation_base=body.calculation_base, effective_from=body.effective_from,
        effective_to=body.effective_to, notes=body.notes, is_active=True,
    )
    db.add(rule)
    await db.flush()

    for b in body.brackets:
        db.add(PayrollTaxBracket(
            tenant_id=tenant_id, tax_rule_id=rule.id, min_amount=b.min_amount,
            max_amount=b.max_amount, rate_percentage=b.rate_percentage, display_order=b.display_order,
        ))
    await db.flush()
    await db.refresh(rule, attribute_names=["brackets"])
    return _serialize_tax_rule(rule)


@router.delete("/tax-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate a tax rule")
async def deactivate_tax_rule(
    rule_id: UUID,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = (
        await db.execute(select(PayrollTaxRule).where(PayrollTaxRule.id == rule_id, PayrollTaxRule.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if rule is None:
        raise NotFoundError("Tax rule not found")
    rule.is_active = False
    await db.flush()


# ── Contribution Rules ───────────────────────────────────────────────────────
class ContributionRuleCreate(BaseModel):
    name: str
    code: str
    calculation_base: ContributionCalculationBase = ContributionCalculationBase.BASIC
    employee_percentage: Decimal | None = None
    employee_fixed_amount: Decimal | None = None
    employer_percentage: Decimal | None = None
    employer_fixed_amount: Decimal | None = None
    min_base: Decimal | None = None
    max_base: Decimal | None = None
    is_taxable: bool = False
    effective_from: date | None = None
    effective_to: date | None = None


def _serialize_contribution_rule(r: PayrollContributionRule) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "code": r.code,
        "calculation_base": r.calculation_base.value,
        "employee_percentage": str(r.employee_percentage) if r.employee_percentage is not None else None,
        "employee_fixed_amount": str(r.employee_fixed_amount) if r.employee_fixed_amount is not None else None,
        "employer_percentage": str(r.employer_percentage) if r.employer_percentage is not None else None,
        "employer_fixed_amount": str(r.employer_fixed_amount) if r.employer_fixed_amount is not None else None,
        "min_base": str(r.min_base) if r.min_base is not None else None,
        "max_base": str(r.max_base) if r.max_base is not None else None,
        "is_taxable": r.is_taxable,
        "is_active": r.is_active,
        "effective_from": str(r.effective_from),
        "effective_to": str(r.effective_to) if r.effective_to else None,
    }


@router.get("/contribution-rules", summary="List payroll contribution rules")
async def list_contribution_rules(
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rules = (
        await db.execute(
            select(PayrollContributionRule)
            .where(PayrollContributionRule.tenant_id == tenant_id, PayrollContributionRule.is_deleted == False)  # noqa: E712
            .order_by(PayrollContributionRule.name)
        )
    ).scalars().all()
    return {"items": [_serialize_contribution_rule(r) for r in rules], "total": len(rules)}


@router.post("/contribution-rules", status_code=status.HTTP_201_CREATED, summary="Create a payroll contribution rule")
async def create_contribution_rule(
    body: ContributionRuleCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not any([body.employee_percentage, body.employee_fixed_amount, body.employer_percentage, body.employer_fixed_amount]):
        raise ValidationError("At least one of employee/employer percentage or fixed amount must be set")
    if body.min_base is not None and body.max_base is not None and body.min_base > body.max_base:
        raise ValidationError("min_base cannot be greater than max_base")

    rule = PayrollContributionRule(
        tenant_id=tenant_id, name=body.name, code=body.code, calculation_base=body.calculation_base,
        employee_percentage=body.employee_percentage, employee_fixed_amount=body.employee_fixed_amount,
        employer_percentage=body.employer_percentage, employer_fixed_amount=body.employer_fixed_amount,
        min_base=body.min_base, max_base=body.max_base, is_taxable=body.is_taxable,
        effective_from=body.effective_from or date.today(), effective_to=body.effective_to, is_active=True,
    )
    db.add(rule)
    await db.flush()
    return _serialize_contribution_rule(rule)


@router.delete("/contribution-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate a contribution rule")
async def deactivate_contribution_rule(
    rule_id: UUID,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = (
        await db.execute(
            select(PayrollContributionRule).where(
                PayrollContributionRule.id == rule_id, PayrollContributionRule.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        raise NotFoundError("Contribution rule not found")
    rule.is_active = False
    await db.flush()


@router.post("/formulas/validate", summary="Validate a formula expression before saving a component")
async def validate_formula_endpoint(
    expression: str = Body(embed=True),
    known_codes: list[str] = Body(default_factory=list, embed=True),
    current_user: User = Depends(require_permission("payroll.manage_structure")),
) -> dict:
    errors = validate_formula(expression, set(known_codes) | {"BASIC", "GROSS"} if known_codes else None)
    return {"valid": len(errors) == 0, "errors": errors}


# ── Loans ─────────────────────────────────────────────────────────────────────
class LoanCreate(BaseModel):
    employee_id: UUID
    principal_amount: Decimal
    interest_rate: Decimal = Decimal("0")
    number_of_installments: int
    start_date: date
    reason: str | None = None


def _serialize_loan(l: PayrollLoan) -> dict:
    return {
        "id": str(l.id), "employee_id": str(l.employee_id),
        "principal_amount": str(l.principal_amount), "interest_rate": str(l.interest_rate),
        "number_of_installments": l.number_of_installments, "installment_amount": str(l.installment_amount),
        "remaining_balance": str(l.remaining_balance), "start_date": str(l.start_date),
        "status": l.status.value, "reason": l.reason,
    }


@router.get("/loans", summary="List employee loans")
async def list_loans(
    employee_id: UUID | None = Query(None),
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [PayrollLoan.tenant_id == tenant_id, PayrollLoan.is_deleted == False]  # noqa: E712
    if employee_id:
        filters.append(PayrollLoan.employee_id == employee_id)
    loans = (await db.execute(select(PayrollLoan).where(*filters).order_by(PayrollLoan.start_date.desc()))).scalars().all()
    return {"items": [_serialize_loan(l) for l in loans], "total": len(loans)}


@router.post("/loans", status_code=status.HTTP_201_CREATED, summary="Create an employee loan")
async def create_loan(
    body: LoanCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.principal_amount <= 0:
        raise ValidationError("principal_amount must be positive")
    if body.number_of_installments <= 0:
        raise ValidationError("number_of_installments must be positive")

    total_payable = body.principal_amount * (1 + body.interest_rate / Decimal("100"))
    installment_amount = (total_payable / body.number_of_installments).quantize(Decimal("0.01"))

    loan = PayrollLoan(
        tenant_id=tenant_id, employee_id=body.employee_id, principal_amount=body.principal_amount,
        interest_rate=body.interest_rate, number_of_installments=body.number_of_installments,
        installment_amount=installment_amount, remaining_balance=total_payable.quantize(Decimal("0.01")),
        start_date=body.start_date, status=LoanStatus.ACTIVE, reason=body.reason,
        approved_by_id=current_user.id,
    )
    db.add(loan)
    await db.flush()
    return _serialize_loan(loan)


@router.post("/loans/{loan_id}/cancel", summary="Cancel a loan (no further deductions)")
async def cancel_loan(
    loan_id: UUID,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    loan = (await db.execute(select(PayrollLoan).where(PayrollLoan.id == loan_id, PayrollLoan.tenant_id == tenant_id))).scalar_one_or_none()
    if loan is None:
        raise NotFoundError("Loan not found")
    loan.status = LoanStatus.CANCELLED
    await db.flush()
    return _serialize_loan(loan)


# ── Advances ──────────────────────────────────────────────────────────────────
class AdvanceCreate(BaseModel):
    employee_id: UUID
    advance_amount: Decimal
    number_of_installments: int
    recovery_start_date: date
    reason: str | None = None


def _serialize_advance(a: PayrollAdvance) -> dict:
    return {
        "id": str(a.id), "employee_id": str(a.employee_id),
        "advance_amount": str(a.advance_amount), "number_of_installments": a.number_of_installments,
        "installment_amount": str(a.installment_amount), "remaining_balance": str(a.remaining_balance),
        "recovery_start_date": str(a.recovery_start_date), "status": a.status.value, "reason": a.reason,
    }


@router.get("/advances", summary="List salary advances")
async def list_advances(
    employee_id: UUID | None = Query(None),
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [PayrollAdvance.tenant_id == tenant_id, PayrollAdvance.is_deleted == False]  # noqa: E712
    if employee_id:
        filters.append(PayrollAdvance.employee_id == employee_id)
    advances = (await db.execute(select(PayrollAdvance).where(*filters).order_by(PayrollAdvance.recovery_start_date.desc()))).scalars().all()
    return {"items": [_serialize_advance(a) for a in advances], "total": len(advances)}


@router.post("/advances", status_code=status.HTTP_201_CREATED, summary="Create a salary advance")
async def create_advance(
    body: AdvanceCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.advance_amount <= 0:
        raise ValidationError("advance_amount must be positive")
    if body.number_of_installments <= 0:
        raise ValidationError("number_of_installments must be positive")

    installment_amount = (body.advance_amount / body.number_of_installments).quantize(Decimal("0.01"))
    advance = PayrollAdvance(
        tenant_id=tenant_id, employee_id=body.employee_id, advance_amount=body.advance_amount,
        number_of_installments=body.number_of_installments, installment_amount=installment_amount,
        remaining_balance=body.advance_amount, recovery_start_date=body.recovery_start_date,
        status=AdvanceStatus.ACTIVE, reason=body.reason, approved_by_id=current_user.id,
    )
    db.add(advance)
    await db.flush()
    return _serialize_advance(advance)


# ── Bonuses ───────────────────────────────────────────────────────────────────
class BonusCreate(BaseModel):
    employee_id: UUID
    bonus_type: BonusType
    name: str
    amount: Decimal
    is_taxable: bool = True
    target_period_start: date
    target_period_end: date
    notes: str | None = None


def _serialize_bonus(b: PayrollBonus) -> dict:
    return {
        "id": str(b.id), "employee_id": str(b.employee_id), "bonus_type": b.bonus_type.value,
        "name": b.name, "amount": str(b.amount), "is_taxable": b.is_taxable,
        "target_period_start": str(b.target_period_start), "target_period_end": str(b.target_period_end),
        "status": b.status.value, "notes": b.notes,
    }


@router.get("/bonuses", summary="List employee bonuses")
async def list_bonuses(
    employee_id: UUID | None = Query(None),
    status_filter: BonusStatus | None = Query(None, alias="status"),
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [PayrollBonus.tenant_id == tenant_id, PayrollBonus.is_deleted == False]  # noqa: E712
    if employee_id:
        filters.append(PayrollBonus.employee_id == employee_id)
    if status_filter:
        filters.append(PayrollBonus.status == status_filter)
    bonuses = (await db.execute(select(PayrollBonus).where(*filters).order_by(PayrollBonus.target_period_start.desc()))).scalars().all()
    return {"items": [_serialize_bonus(b) for b in bonuses], "total": len(bonuses)}


@router.post("/bonuses", status_code=status.HTTP_201_CREATED, summary="Create a bonus (starts as pending)")
async def create_bonus(
    body: BonusCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.amount <= 0:
        raise ValidationError("amount must be positive")
    bonus = PayrollBonus(
        tenant_id=tenant_id, employee_id=body.employee_id, bonus_type=body.bonus_type, name=body.name,
        amount=body.amount, is_taxable=body.is_taxable, target_period_start=body.target_period_start,
        target_period_end=body.target_period_end, status=BonusStatus.PENDING, notes=body.notes,
    )
    db.add(bonus)
    await db.flush()
    return _serialize_bonus(bonus)


@router.post("/bonuses/{bonus_id}/approve", summary="Approve a bonus so the next matching payroll run includes it")
async def approve_bonus(
    bonus_id: UUID,
    current_user: User = Depends(require_permission("payroll.approve")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    bonus = (await db.execute(select(PayrollBonus).where(PayrollBonus.id == bonus_id, PayrollBonus.tenant_id == tenant_id))).scalar_one_or_none()
    if bonus is None:
        raise NotFoundError("Bonus not found")
    if bonus.status != BonusStatus.PENDING:
        raise ValidationError(f"Only PENDING bonuses can be approved (this one is {bonus.status.value})")
    bonus.status = BonusStatus.APPROVED
    bonus.approved_by_id = current_user.id
    await db.flush()
    return _serialize_bonus(bonus)


# ── Arrears ───────────────────────────────────────────────────────────────────
class ArrearCreate(BaseModel):
    employee_id: UUID
    reason: str
    source_period_start: date
    source_period_end: date
    target_period_start: date
    target_period_end: date
    amount: Decimal
    is_taxable: bool = True
    calculation_details: dict = Field(default_factory=dict)


def _serialize_arrear(a: PayrollArrear) -> dict:
    return {
        "id": str(a.id), "employee_id": str(a.employee_id), "reason": a.reason,
        "source_period_start": str(a.source_period_start), "source_period_end": str(a.source_period_end),
        "target_period_start": str(a.target_period_start), "target_period_end": str(a.target_period_end),
        "amount": str(a.amount), "is_taxable": a.is_taxable, "calculation_details": a.calculation_details,
        "status": a.status.value,
    }


@router.get("/arrears", summary="List payroll arrears")
async def list_arrears(
    employee_id: UUID | None = Query(None),
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [PayrollArrear.tenant_id == tenant_id, PayrollArrear.is_deleted == False]  # noqa: E712
    if employee_id:
        filters.append(PayrollArrear.employee_id == employee_id)
    arrears = (await db.execute(select(PayrollArrear).where(*filters).order_by(PayrollArrear.target_period_start.desc()))).scalars().all()
    return {"items": [_serialize_arrear(a) for a in arrears], "total": len(arrears)}


@router.post("/arrears", status_code=status.HTTP_201_CREATED, summary="Create an arrear (starts as pending)")
async def create_arrear(
    body: ArrearCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.amount <= 0:
        raise ValidationError("amount must be positive")
    arrear = PayrollArrear(
        tenant_id=tenant_id, employee_id=body.employee_id, reason=body.reason,
        source_period_start=body.source_period_start, source_period_end=body.source_period_end,
        target_period_start=body.target_period_start, target_period_end=body.target_period_end,
        amount=body.amount, is_taxable=body.is_taxable, calculation_details=body.calculation_details,
        status=ArrearStatus.PENDING,
    )
    db.add(arrear)
    await db.flush()
    return _serialize_arrear(arrear)


@router.post("/arrears/{arrear_id}/approve", summary="Approve an arrear so the next matching payroll run includes it")
async def approve_arrear(
    arrear_id: UUID,
    current_user: User = Depends(require_permission("payroll.approve")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    arrear = (await db.execute(select(PayrollArrear).where(PayrollArrear.id == arrear_id, PayrollArrear.tenant_id == tenant_id))).scalar_one_or_none()
    if arrear is None:
        raise NotFoundError("Arrear not found")
    if arrear.status != ArrearStatus.PENDING:
        raise ValidationError(f"Only PENDING arrears can be approved (this one is {arrear.status.value})")
    arrear.status = ArrearStatus.APPROVED
    arrear.approved_by_id = current_user.id
    await db.flush()
    return _serialize_arrear(arrear)


# ── Commissions ───────────────────────────────────────────────────────────────
class CommissionPlanCreate(BaseModel):
    name: str
    tiers: list[TaxBracketInput]  # same shape (min/max/rate) as tax brackets


class CommissionCreate(BaseModel):
    employee_id: UUID
    plan_id: UUID | None = None
    target_period_start: date
    target_period_end: date
    sales_amount: Decimal


def _serialize_commission(c: PayrollCommission) -> dict:
    return {
        "id": str(c.id), "employee_id": str(c.employee_id), "plan_id": str(c.plan_id) if c.plan_id else None,
        "target_period_start": str(c.target_period_start), "target_period_end": str(c.target_period_end),
        "sales_amount": str(c.sales_amount), "computed_amount": str(c.computed_amount), "status": c.status.value,
    }


@router.post("/commission-plans", status_code=status.HTTP_201_CREATED, summary="Create a tiered commission plan")
async def create_commission_plan(
    body: CommissionPlanCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plan = PayrollCommissionPlan(tenant_id=tenant_id, name=body.name, is_active=True)
    db.add(plan)
    await db.flush()
    for t in body.tiers:
        db.add(PayrollCommissionTier(
            tenant_id=tenant_id, plan_id=plan.id, min_amount=t.min_amount,
            max_amount=t.max_amount, rate_percentage=t.rate_percentage,
        ))
    await db.flush()
    return {"id": str(plan.id), "name": plan.name}


@router.post("/commissions", status_code=status.HTTP_201_CREATED, summary="Compute and record an employee's commission for a period")
async def create_commission(
    body: CommissionCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    computed = Decimal("0")
    if body.plan_id:
        tier_rows = (
            await db.execute(select(PayrollCommissionTier).where(PayrollCommissionTier.plan_id == body.plan_id))
        ).scalars().all()
        tier_data = [CommissionTierData(t.min_amount, t.max_amount, t.rate_percentage) for t in tier_rows]
        computed = calculate_tiered_commission(body.sales_amount, tier_data)

    commission = PayrollCommission(
        tenant_id=tenant_id, employee_id=body.employee_id, plan_id=body.plan_id,
        target_period_start=body.target_period_start, target_period_end=body.target_period_end,
        sales_amount=body.sales_amount, computed_amount=computed, status=CommissionStatus.PENDING,
    )
    db.add(commission)
    await db.flush()
    return _serialize_commission(commission)


@router.post("/commissions/{commission_id}/approve", summary="Approve a commission so the next matching payroll run includes it")
async def approve_commission(
    commission_id: UUID,
    current_user: User = Depends(require_permission("payroll.approve")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    commission = (
        await db.execute(select(PayrollCommission).where(PayrollCommission.id == commission_id, PayrollCommission.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if commission is None:
        raise NotFoundError("Commission not found")
    if commission.status != CommissionStatus.PENDING:
        raise ValidationError(f"Only PENDING commissions can be approved (this one is {commission.status.value})")
    commission.status = CommissionStatus.APPROVED
    commission.approved_by_id = current_user.id
    await db.flush()
    return _serialize_commission(commission)


# ── Reimbursements ────────────────────────────────────────────────────────────
class ReimbursementCreate(BaseModel):
    employee_id: UUID
    category: ReimbursementCategory
    amount: Decimal
    description: str | None = None
    receipt_url: str | None = None
    is_taxable: bool = False


def _serialize_reimbursement(r: PayrollReimbursement) -> dict:
    return {
        "id": str(r.id), "employee_id": str(r.employee_id), "category": r.category.value,
        "amount": str(r.amount), "description": r.description, "receipt_url": r.receipt_url,
        "is_taxable": r.is_taxable, "status": r.status.value,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "rejection_reason": r.rejection_reason,
    }


@router.get("/reimbursements", summary="List reimbursement claims")
async def list_reimbursements(
    employee_id: UUID | None = Query(None),
    status_filter: ReimbursementStatus | None = Query(None, alias="status"),
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [PayrollReimbursement.tenant_id == tenant_id, PayrollReimbursement.is_deleted == False]  # noqa: E712
    if employee_id:
        filters.append(PayrollReimbursement.employee_id == employee_id)
    if status_filter:
        filters.append(PayrollReimbursement.status == status_filter)
    items = (await db.execute(select(PayrollReimbursement).where(*filters).order_by(PayrollReimbursement.submitted_at.desc()))).scalars().all()
    return {"items": [_serialize_reimbursement(r) for r in items], "total": len(items)}


@router.post("/reimbursements", status_code=status.HTTP_201_CREATED, summary="Submit a reimbursement claim")
async def submit_reimbursement(
    body: ReimbursementCreate,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.amount <= 0:
        raise ValidationError("amount must be positive")
    reimbursement = PayrollReimbursement(
        tenant_id=tenant_id, employee_id=body.employee_id, category=body.category, amount=body.amount,
        description=body.description, receipt_url=body.receipt_url, is_taxable=body.is_taxable,
        status=ReimbursementStatus.SUBMITTED,
    )
    db.add(reimbursement)
    await db.flush()
    return _serialize_reimbursement(reimbursement)


@router.post("/reimbursements/{reimbursement_id}/approve", summary="Approve a reimbursement claim")
async def approve_reimbursement(
    reimbursement_id: UUID,
    current_user: User = Depends(require_permission("payroll.approve")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = (
        await db.execute(select(PayrollReimbursement).where(PayrollReimbursement.id == reimbursement_id, PayrollReimbursement.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Reimbursement not found")
    if r.status not in (ReimbursementStatus.SUBMITTED, ReimbursementStatus.REVIEWED):
        raise ValidationError(f"Cannot approve a reimbursement in status {r.status.value}")
    r.status = ReimbursementStatus.APPROVED
    r.approved_by_id = current_user.id
    r.approved_at = datetime.now(UTC)
    await db.flush()
    return _serialize_reimbursement(r)


@router.post("/reimbursements/{reimbursement_id}/reject", summary="Reject a reimbursement claim")
async def reject_reimbursement(
    reimbursement_id: UUID,
    reason: str = Body(embed=True),
    current_user: User = Depends(require_permission("payroll.approve")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = (
        await db.execute(select(PayrollReimbursement).where(PayrollReimbursement.id == reimbursement_id, PayrollReimbursement.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Reimbursement not found")
    r.status = ReimbursementStatus.REJECTED
    r.rejection_reason = reason
    await db.flush()
    return _serialize_reimbursement(r)


# ── Salary Structures ────────────────────────────────────────────────────────
def _serialize_structure(s: SalaryStructure) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "code": s.code,
        "description": s.description,
        "currency": s.currency,
        "is_active": s.is_active,
        "is_default": s.is_default,
        "version": s.version,
        "effective_from": str(s.effective_from),
        "effective_to": str(s.effective_to) if s.effective_to else None,
        "is_current": s.is_current,
        "components": [
            {
                "id": str(c.id),
                "name": c.name,
                "code": c.code,
                "component_type": c.component_type.value,
                "calculation_type": c.calculation_type.value,
                "amount": str(c.amount) if c.amount is not None else None,
                "percentage": str(c.percentage) if c.percentage is not None else None,
                "is_taxable": c.is_taxable,
                "is_mandatory": c.is_mandatory,
                "display_order": c.display_order,
                "version": c.version,
                "effective_from": str(c.effective_from),
                "effective_to": str(c.effective_to) if c.effective_to else None,
            }
            for c in sorted(s.components, key=lambda c: c.display_order) if c.is_current
        ],
    }


@router.get("/salary-structures", summary="List salary structures")
async def list_salary_structures(
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(SalaryStructure)
        .where(
            SalaryStructure.tenant_id == tenant_id,
            SalaryStructure.is_deleted == False,  # noqa: E712
            SalaryStructure.is_current == True,  # noqa: E712  — hide superseded versions from the main list
        )
        .options(selectinload(SalaryStructure.components))
        .order_by(SalaryStructure.name)
    )
    items = (await db.execute(stmt)).unique().scalars().all()
    return {"items": [_serialize_structure(s) for s in items], "total": len(items)}


@router.post("/salary-structures", status_code=status.HTTP_201_CREATED, summary="Create a salary structure")
async def create_salary_structure(
    body: SalaryStructureCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Validate formulas up front — circular dependencies or bad syntax
    # should surface here, not silently at the first payroll run months
    # later. Mirrors the check generate_payroll_run does at calculation time.
    formula_map = {c.code: c.formula for c in body.components if c.calculation_type == ComponentCalculation.FORMULA and c.formula}
    known_codes = {c.code for c in body.components} | {"BASIC", "GROSS"}
    for code, expr in formula_map.items():
        errors = validate_formula(expr, known_codes)
        if errors:
            raise ValidationError(f"INVALID_PAYROLL_FORMULA ({code}): {'; '.join(errors)}")
    try:
        topological_sort_formulas(formula_map)
    except CircularFormulaDependencyError as exc:
        raise ValidationError(f"CIRCULAR_FORMULA_DEPENDENCY: {exc}") from exc

    structure = SalaryStructure(
        tenant_id=tenant_id,
        name=body.name,
        code=body.code,
        description=body.description,
        currency=body.currency,
        is_default=body.is_default,
        is_active=True,
    )
    db.add(structure)
    await db.flush()

    for i, comp in enumerate(body.components):
        db.add(SalaryComponent(
            tenant_id=tenant_id,
            salary_structure_id=structure.id,
            name=comp.name,
            code=comp.code,
            component_type=comp.component_type,
            calculation_type=comp.calculation_type,
            amount=comp.amount,
            percentage=comp.percentage,
            formula=comp.formula,
            is_taxable=comp.is_taxable,
            is_mandatory=comp.is_mandatory,
            display_order=comp.display_order or i,
        ))
    await db.flush()
    return {"id": str(structure.id), "created": True}


@router.patch("/salary-structures/{structure_id}", summary="Update a salary structure (creates a new version)")
async def update_salary_structure(
    structure_id: UUID,
    body: SalaryStructureUpdate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Never mutates the existing row. Instead: closes it out
    (is_current=False, effective_to=<new effective date>, superseded_by_id
    set) and inserts a new SalaryStructure row carrying forward whatever
    wasn't changed, plus the CURRENT component set re-pointed to the new
    structure id. Existing payroll runs/payslips are untouched either way —
    they never re-read the structure after generation.
    """
    from sqlalchemy.orm import selectinload

    old = (
        await db.execute(
            select(SalaryStructure)
            .where(SalaryStructure.id == structure_id, SalaryStructure.tenant_id == tenant_id)
            .options(selectinload(SalaryStructure.components))
        )
    ).scalar_one_or_none()
    if old is None:
        raise NotFoundError("Salary structure not found")
    if not old.is_current:
        raise ValidationError("This is a superseded version — edit the current version instead")

    effective_from = body.effective_from or date.today()

    new = SalaryStructure(
        tenant_id=tenant_id,
        name=body.name if body.name is not None else old.name,
        code=old.code,  # code identifies the structure across versions — never changes
        description=body.description if body.description is not None else old.description,
        currency=body.currency if body.currency is not None else old.currency,
        is_active=old.is_active,
        is_default=body.is_default if body.is_default is not None else old.is_default,
        version=old.version + 1,
        effective_from=effective_from,
        is_current=True,
    )
    db.add(new)
    await db.flush()

    old.is_current = False
    old.effective_to = effective_from
    old.superseded_by_id = new.id

    # COPY the current component set onto the new structure version — do
    # NOT move/repoint the old components. Any EmployeeSalary rows still
    # pointing at the OLD structure id (nothing reassigns them
    # automatically just because the structure got a new version) must
    # keep finding their original components there; moving them would
    # silently zero out those employees' gross salary on next payroll run.
    # Component-level edits are independent (PATCH /salary-components/{id}
    # below) — copying here doesn't touch each component's own version.
    for comp in old.components:
        if comp.is_current:
            db.add(SalaryComponent(
                tenant_id=tenant_id,
                salary_structure_id=new.id,
                name=comp.name,
                code=comp.code,
                component_type=comp.component_type,
                calculation_type=comp.calculation_type,
                amount=comp.amount,
                percentage=comp.percentage,
                formula=comp.formula,
                is_taxable=comp.is_taxable,
                is_mandatory=comp.is_mandatory,
                display_order=comp.display_order,
                is_active=comp.is_active,
                version=comp.version,
                effective_from=comp.effective_from,
                is_current=True,
            ))

    await db.flush()
    return {"id": str(new.id), "version": new.version, "updated": True}


@router.patch("/salary-components/{component_id}", summary="Update a salary component (creates a new version)")
async def update_salary_component(
    component_id: UUID,
    body: SalaryComponentUpdate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Same versioning approach as the structure endpoint above, at the
    individual-component level — editing one allowance's rate doesn't
    force every other component or the structure itself to re-version.
    """
    old = (
        await db.execute(
            select(SalaryComponent).where(SalaryComponent.id == component_id, SalaryComponent.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if old is None:
        raise NotFoundError("Salary component not found")
    if not old.is_current:
        raise ValidationError("This is a superseded version — edit the current version instead")

    effective_from = body.effective_from or date.today()

    new = SalaryComponent(
        tenant_id=tenant_id,
        salary_structure_id=old.salary_structure_id,
        name=body.name if body.name is not None else old.name,
        code=old.code,  # code identifies the component across versions — never changes
        component_type=old.component_type,
        calculation_type=body.calculation_type if body.calculation_type is not None else old.calculation_type,
        amount=body.amount if body.amount is not None else old.amount,
        percentage=body.percentage if body.percentage is not None else old.percentage,
        formula=body.formula if body.formula is not None else old.formula,
        is_taxable=body.is_taxable if body.is_taxable is not None else old.is_taxable,
        is_mandatory=body.is_mandatory if body.is_mandatory is not None else old.is_mandatory,
        display_order=body.display_order if body.display_order is not None else old.display_order,
        is_active=old.is_active,
        version=old.version + 1,
        effective_from=effective_from,
        is_current=True,
    )
    db.add(new)
    await db.flush()

    old.is_current = False
    old.effective_to = effective_from
    old.superseded_by_id = new.id

    await db.flush()
    return {"id": str(new.id), "version": new.version, "updated": True}


@router.delete("/salary-structures/{structure_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate a salary structure")
async def delete_salary_structure(
    structure_id: UUID,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    structure = (
        await db.execute(
            select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if structure is None:
        raise NotFoundError("Salary structure not found")
    structure.soft_delete()
    await db.flush()


# ── Employee Salary Assignment ───────────────────────────────────────────────
@router.get("/employees/{employee_id}/salary", summary="Get an employee's current salary assignment")
async def get_employee_salary(
    employee_id: UUID,
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(EmployeeSalary).where(
        EmployeeSalary.employee_id == employee_id,
        EmployeeSalary.tenant_id == tenant_id,
        EmployeeSalary.is_current == True,  # noqa: E712
        EmployeeSalary.is_deleted == False,  # noqa: E712
    )
    salary = (await db.execute(stmt)).scalar_one_or_none()
    if salary is None:
        return {"assigned": False}
    return {
        "assigned": True,
        "id": str(salary.id),
        "salary_structure_id": str(salary.salary_structure_id),
        "basic_salary": str(salary.basic_salary),
        "effective_from": str(salary.effective_from),
        "component_overrides": salary.component_overrides,
    }


@router.post("/employees/{employee_id}/salary", status_code=status.HTTP_201_CREATED, summary="Assign salary structure to an employee")
async def assign_employee_salary(
    employee_id: UUID,
    body: AssignSalaryRequest,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    employee = (
        await db.execute(select(Employee).where(Employee.id == employee_id, Employee.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if employee is None:
        raise NotFoundError("Employee not found")

    structure = (
        await db.execute(
            select(SalaryStructure).where(
                SalaryStructure.id == body.salary_structure_id, SalaryStructure.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if structure is None:
        raise NotFoundError("Salary structure not found")

    # Supersede any previous "current" assignment instead of leaving two
    # rows marked current (which would make payroll generation ambiguous).
    await db.execute(
        select(EmployeeSalary).where(
            EmployeeSalary.employee_id == employee_id,
            EmployeeSalary.tenant_id == tenant_id,
            EmployeeSalary.is_current == True,  # noqa: E712
        )
    )
    prev_stmt = select(EmployeeSalary).where(
        EmployeeSalary.employee_id == employee_id,
        EmployeeSalary.tenant_id == tenant_id,
        EmployeeSalary.is_current == True,  # noqa: E712
    )
    previous_rows = (await db.execute(prev_stmt)).scalars().all()
    for prev in previous_rows:
        prev.is_current = False
        prev.effective_to = body.effective_from

    new_salary = EmployeeSalary(
        tenant_id=tenant_id,
        employee_id=employee_id,
        salary_structure_id=body.salary_structure_id,
        basic_salary=body.basic_salary,
        effective_from=body.effective_from,
        is_current=True,
        component_overrides={k: str(v) for k, v in body.component_overrides.items()},
        approved_by_id=current_user.id,
    )
    db.add(new_salary)

    # Keep Employee.current_salary in sync — used for quick display elsewhere
    # (employee list/detail) without an extra join to employee_salaries.
    employee.current_salary = body.basic_salary
    employee.currency = structure.currency

    await db.flush()
    return {"id": str(new_salary.id), "assigned": True}


def _serialize_rule(r: PayrollComponentRule) -> dict:
    return {
        "id": str(r.id),
        "salary_component_id": str(r.salary_component_id),
        "override_type": r.override_type.value,
        "amount": str(r.amount) if r.amount is not None else None,
        "percentage": str(r.percentage) if r.percentage is not None else None,
        "effective_from": str(r.effective_from),
        "effective_to": str(r.effective_to) if r.effective_to else None,
        "is_active": r.is_active,
        "notes": r.notes,
    }


async def _get_current_employee_salary(db: AsyncSession, tenant_id: UUID, employee_id: UUID) -> EmployeeSalary:
    salary = (
        await db.execute(
            select(EmployeeSalary).where(
                EmployeeSalary.employee_id == employee_id,
                EmployeeSalary.tenant_id == tenant_id,
                EmployeeSalary.is_current == True,  # noqa: E712
                EmployeeSalary.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if salary is None:
        raise NotFoundError("This employee has no current salary assignment to attach an override to")
    return salary


@router.get(
    "/employees/{employee_id}/salary/component-rules",
    summary="List an employee's active component overrides",
)
async def list_component_rules(
    employee_id: UUID,
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    salary = await _get_current_employee_salary(db, tenant_id, employee_id)
    rules = (
        await db.execute(
            select(PayrollComponentRule).where(
                PayrollComponentRule.employee_salary_id == salary.id,
                PayrollComponentRule.tenant_id == tenant_id,
                PayrollComponentRule.is_active == True,  # noqa: E712
                PayrollComponentRule.is_deleted == False,  # noqa: E712
            )
        )
    ).scalars().all()
    return {"items": [_serialize_rule(r) for r in rules], "total": len(rules)}


@router.post(
    "/employees/{employee_id}/salary/component-rules",
    status_code=status.HTTP_201_CREATED,
    summary="Add a per-employee override for one salary component (replaces the legacy JSON override approach)",
)
async def create_component_rule(
    employee_id: UUID,
    body: ComponentRuleCreate,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    salary = await _get_current_employee_salary(db, tenant_id, employee_id)

    component = (
        await db.execute(
            select(SalaryComponent).where(
                SalaryComponent.id == body.salary_component_id, SalaryComponent.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if component is None:
        raise NotFoundError("Salary component not found")

    # One active rule per component at a time — deactivate any existing
    # active rule for this (employee_salary, component) pair rather than
    # leaving two active overrides that would make resolution ambiguous.
    existing_rules = (
        await db.execute(
            select(PayrollComponentRule).where(
                PayrollComponentRule.employee_salary_id == salary.id,
                PayrollComponentRule.salary_component_id == body.salary_component_id,
                PayrollComponentRule.is_active == True,  # noqa: E712
            )
        )
    ).scalars().all()
    effective_from = body.effective_from or date.today()
    for r in existing_rules:
        r.is_active = False
        r.effective_to = effective_from

    rule = PayrollComponentRule(
        tenant_id=tenant_id,
        employee_salary_id=salary.id,
        salary_component_id=body.salary_component_id,
        override_type=body.override_type,
        amount=body.amount,
        percentage=body.percentage,
        effective_from=effective_from,
        is_active=True,
        created_by_id=current_user.id,
        notes=body.notes,
    )
    db.add(rule)
    await db.flush()
    return _serialize_rule(rule)


@router.delete(
    "/employees/{employee_id}/salary/component-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a component override",
)
async def delete_component_rule(
    employee_id: UUID,
    rule_id: UUID,
    current_user: User = Depends(require_permission("payroll.manage_structure")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Deactivated, never hard-deleted — a rule that applied to a past
    # payroll run must remain in history even after it stops applying.
    rule = (
        await db.execute(
            select(PayrollComponentRule).where(
                PayrollComponentRule.id == rule_id, PayrollComponentRule.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        raise NotFoundError("Component rule not found")
    rule.is_active = False
    rule.effective_to = date.today()
    await db.flush()


# ── Payroll Run Generation ───────────────────────────────────────────────────
def _resolve_components_with_formulas(
    components: list[SalaryComponent],
    context: dict[str, Decimal],
    basic_salary: Decimal,
    gross_so_far: Decimal,
    overrides: dict,
    component_rules: dict[UUID, PayrollComponentRule],
) -> dict[str, Decimal]:
    """
    Computes {component_code: raw_amount} for one phase of components
    (e.g. all EARNING components, or all DEDUCTION components).

    FIXED/PERCENTAGE/rule-overridden components are self-contained and
    computed first; their amounts are folded into `context` so FORMULA
    components can reference them by code. FORMULA components are then
    evaluated in dependency order (topological_sort_formulas) — a formula
    can reference another formula component's code, a plain component's
    code, or the special BASIC/GROSS variables already in `context`.

    Raises ValidationError (caught by the run/preview endpoints and
    surfaced as a payroll validation issue, not a 500) for circular
    dependencies or invalid formula syntax — never lets a malformed
    formula silently produce a wrong number.
    """
    amounts: dict[str, Decimal] = {}
    non_formula = [c for c in components if c.calculation_type != ComponentCalculation.FORMULA]
    formula_comps = [c for c in components if c.calculation_type == ComponentCalculation.FORMULA]

    for comp in non_formula:
        amounts[comp.code] = _component_amount(comp, basic_salary, gross_so_far, overrides, component_rules)

    if formula_comps:
        formula_map = {c.code: c.formula for c in formula_comps if c.formula}
        try:
            order = topological_sort_formulas(formula_map)
        except CircularFormulaDependencyError as exc:
            raise ValidationError(f"CIRCULAR_FORMULA_DEPENDENCY: {exc}") from exc

        eval_context = {**context, **amounts}
        for code in order:
            expr = formula_map[code]
            try:
                value = evaluate_formula(expr, eval_context)
            except FormulaError as exc:
                raise ValidationError(f"INVALID_PAYROLL_FORMULA ({code}): {exc}") from exc
            eval_context[code] = value
            amounts[code] = value

        for comp in formula_comps:
            amounts.setdefault(comp.code, Decimal("0"))  # formula component with no formula text set

    return amounts


def _component_amount(
    comp: SalaryComponent,
    basic_salary: Decimal,
    gross_so_far: Decimal,
    overrides: dict,
    component_rules: dict[UUID, PayrollComponentRule] | None = None,
) -> Decimal:
    """
    Compute a single component's amount, honoring per-employee overrides.

    Resolution order: an active PayrollComponentRule for this exact
    component wins first; the legacy component_overrides JSON is checked
    only as a fallback for data written before rules existed; otherwise
    the component's own structure-level definition applies.
    """
    rule = (component_rules or {}).get(comp.id)
    if rule is not None:
        if rule.override_type == ComponentRuleOverrideType.FIXED_AMOUNT:
            return rule.amount or Decimal("0")
        if rule.override_type == ComponentRuleOverrideType.PERCENTAGE_OF_BASIC:
            return (basic_salary * (rule.percentage or Decimal("0")) / Decimal("100")).quantize(Decimal("0.01"))
        if rule.override_type == ComponentRuleOverrideType.PERCENTAGE_OF_GROSS:
            return (gross_so_far * (rule.percentage or Decimal("0")) / Decimal("100")).quantize(Decimal("0.01"))

    if comp.code in overrides:
        try:
            return Decimal(str(overrides[comp.code]))
        except Exception:
            pass

    if comp.calculation_type == ComponentCalculation.FIXED:
        return comp.amount or Decimal("0")
    if comp.calculation_type == ComponentCalculation.PERCENTAGE_OF_BASIC:
        return (basic_salary * (comp.percentage or Decimal("0")) / Decimal("100")).quantize(Decimal("0.01"))
    if comp.calculation_type == ComponentCalculation.PERCENTAGE_OF_GROSS:
        return (gross_so_far * (comp.percentage or Decimal("0")) / Decimal("100")).quantize(Decimal("0.01"))
    # FORMULA components are handled by _resolve_components_with_formulas
    # (Phase 2 formula engine), which never calls this function for a
    # FORMULA-type component — this is a defensive fallback only, in case
    # this function is ever called directly on one.
    return Decimal("0")


def _count_working_days(period_start: date, period_end: date) -> int:
    """Mon–Fri count in the period. A simple default until per-shift work_days is wired in here."""
    days = 0
    d = period_start
    while d <= period_end:
        if d.weekday() < 5:
            days += 1
        d = date.fromordinal(d.toordinal() + 1)
    return days


@router.post("/runs", status_code=status.HTTP_201_CREATED, summary="Create a draft payroll run")
async def create_payroll_run(
    body: CreatePayrollRunRequest,
    current_user: User = Depends(require_permission("payroll.process")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = PayrollRun(
        tenant_id=tenant_id,
        name=body.name,
        period_start=body.period_start,
        period_end=body.period_end,
        pay_date=body.pay_date,
        currency=body.currency,
        status=PayrollRunStatus.DRAFT,
        processed_by_id=current_user.id,
    )
    db.add(run)
    await db.flush()
    return {"id": str(run.id), "created": True}


async def _get_leave_days_breakdown(
    db: AsyncSession, tenant_id: UUID, employee_id: UUID, period_start: date, period_end: date,
) -> tuple[Decimal, Decimal]:
    """
    Returns (paid_leave_days, unpaid_leave_days) for this employee's
    APPROVED leave requests overlapping the payroll period.

    Bug fix: generate_payroll_run previously counted every AttendanceRecord
    with status=ON_LEAVE as a fully-paid day, regardless of whether the
    LeaveType behind it was actually paid (LeaveType.is_paid). This reads
    the real leave requests + their leave type instead, so e.g. unpaid
    sick leave correctly reduces earnings proration while paid annual
    leave doesn't.
    """
    rows = (
        await db.execute(
            select(LeaveRequest, LeaveType.is_paid)
            .join(LeaveType, LeaveRequest.leave_type_id == LeaveType.id)
            .where(
                LeaveRequest.tenant_id == tenant_id,
                LeaveRequest.employee_id == employee_id,
                LeaveRequest.status == LeaveRequestStatus.APPROVED,
                LeaveRequest.start_date <= period_end,
                LeaveRequest.end_date >= period_start,
                LeaveRequest.is_deleted == False,  # noqa: E712
            )
        )
    ).all()

    paid_days = Decimal("0")
    unpaid_days = Decimal("0")
    for leave_request, is_paid in rows:
        if leave_request.duration_type != "full_day":
            # half_day/hourly requests are inherently single-day in this
            # codebase's duration model — total_days already holds the
            # fractional day count (e.g. 0.5), just check it falls in-period.
            days = (
                leave_request.total_days
                if period_start <= leave_request.start_date <= period_end
                else Decimal("0")
            )
        else:
            overlap_start = max(leave_request.start_date, period_start)
            overlap_end = min(leave_request.end_date, period_end)
            days = Decimal((overlap_end - overlap_start).days + 1) if overlap_end >= overlap_start else Decimal("0")

        if is_paid:
            paid_days += days
        else:
            unpaid_days += days

    return paid_days, unpaid_days


@router.post("/runs/{run_id}/generate", summary="Generate payslips for all salaried employees")
async def generate_payroll_run(
    run_id: UUID,
    current_user: User = Depends(require_permission("payroll.process")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Computes payslips for every ACTIVE/PROBATION employee who has a current
    salary assignment: pulls their attendance for the run's period, prorates
    earnings by attendance, applies deductions, and writes Payslip +
    PayslipLine rows. Re-running a DRAFT run recomputes from scratch;
    non-DRAFT runs are locked to avoid overwriting approved figures.
    """
    from sqlalchemy.orm import selectinload

    run = (
        await db.execute(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Payroll run not found")
    if run.status != PayrollRunStatus.DRAFT:
        raise HTTPException(status_code=400, detail=f"Run is {run.status.value} — only DRAFT runs can be (re)generated")

    # Clear any previous partial generation for this run (safe: DRAFT only).
    #
    # Bug fix: this used to loop `await db.delete(p)` over loaded Payslip
    # ORM objects. Payslip.lines has no cascade="all, delete-orphan", so on
    # flush SQLAlchemy's unit-of-work tries to NULL OUT PayslipLine.payslip_id
    # before deleting the parent — but that FK is NOT NULL, so every
    # regeneration of a run that already had payslips crashed with
    # IntegrityError ("NOT NULL constraint failed: payslip_lines.payslip_id").
    # A bulk DELETE bypasses ORM relationship-cascade evaluation entirely and
    # lets the database's own `ondelete="CASCADE"` FK constraint (already
    # correctly declared on PayslipLine.payslip_id) remove the child rows.
    from sqlalchemy import delete as sa_delete

    await db.execute(sa_delete(Payslip).where(Payslip.payroll_run_id == run_id))
    await db.flush()

    salaries = (await db.execute(select(EmployeeSalary).where(
        EmployeeSalary.tenant_id == tenant_id, EmployeeSalary.is_current == True  # noqa: E712
    ))).scalars().all()

    working_days = _count_working_days(run.period_start, run.period_end)
    total_gross = Decimal("0")
    total_deductions = Decimal("0")
    total_net = Decimal("0")
    generated = 0

    for salary in salaries:
        employee = (
            await db.execute(select(Employee).where(Employee.id == salary.employee_id, Employee.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if employee is None or employee.employment_status not in (
            EmploymentStatus.ACTIVE, EmploymentStatus.PROBATION, EmploymentStatus.NOTICE_PERIOD,
        ):
            continue

        structure = (
            await db.execute(
                select(SalaryStructure).where(SalaryStructure.id == salary.salary_structure_id)
            )
        ).scalar_one_or_none()
        if structure is None:
            continue
        components = (
            await db.execute(
                select(SalaryComponent).where(
                    SalaryComponent.salary_structure_id == structure.id,
                    SalaryComponent.is_active == True,  # noqa: E712
                    SalaryComponent.is_current == True,  # noqa: E712  — exclude superseded versions
                ).order_by(SalaryComponent.display_order)
            )
        ).scalars().all()

        # Attendance for the period
        att_stmt = select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee.id,
            AttendanceRecord.tenant_id == tenant_id,
            AttendanceRecord.date >= run.period_start,
            AttendanceRecord.date <= run.period_end,
        )
        records = (await db.execute(att_stmt)).scalars().all()
        present_days = Decimal(sum(1 for r in records if r.status in (AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.WORK_FROM_HOME)))
        absent_days = Decimal(sum(1 for r in records if r.status == AttendanceStatus.ABSENT))
        leave_days = Decimal(sum(1 for r in records if r.status == AttendanceStatus.ON_LEAVE))
        overtime_minutes = sum(r.overtime_minutes or 0 for r in records)
        overtime_hours = Decimal(overtime_minutes) / Decimal("60")

        # Bug fix: not every leave type is paid. Resolve the actual
        # approved leave requests (+ their LeaveType.is_paid flag) rather
        # than assuming every ON_LEAVE attendance day is compensated.
        paid_leave_days, unpaid_leave_days = await _get_leave_days_breakdown(
            db, tenant_id, employee.id, run.period_start, run.period_end
        )

        # Prorate earnings by attendance — if there's no attendance data at
        # all for the period (e.g. remote/manual-only org), default to full pay.
        counted_days = present_days + paid_leave_days
        has_any_data = len(records) > 0 or paid_leave_days > 0 or unpaid_leave_days > 0
        attendance_factor = (counted_days / Decimal(working_days)) if (working_days > 0 and has_any_data) else Decimal("1")
        attendance_factor = min(attendance_factor, Decimal("1"))

        overrides = {k: v for k, v in (salary.component_overrides or {}).items()}

        # Active component-specific rules for this employee's current salary
        # assignment, covering this run's period — one query per employee
        # rather than per component (avoids N+1 across dozens of components).
        rule_rows = (
            await db.execute(
                select(PayrollComponentRule).where(
                    PayrollComponentRule.employee_salary_id == salary.id,
                    PayrollComponentRule.tenant_id == tenant_id,
                    PayrollComponentRule.is_active == True,  # noqa: E712
                    PayrollComponentRule.is_deleted == False,  # noqa: E712
                    PayrollComponentRule.effective_from <= run.period_end,
                    (PayrollComponentRule.effective_to.is_(None)) | (PayrollComponentRule.effective_to > run.period_start),
                )
            )
        ).scalars().all()
        component_rules = {r.salary_component_id: r for r in rule_rows}

        earning_components = [c for c in components if c.component_type == ComponentType.EARNING]
        deduction_components = [c for c in components if c.component_type == ComponentType.DEDUCTION]
        contribution_components = [c for c in components if c.component_type == ComponentType.EMPLOYER_CONTRIBUTION]

        # ── Earnings (formula components resolved in dependency order) ──
        raw_earning_amounts = _resolve_components_with_formulas(
            earning_components, {"BASIC": salary.basic_salary}, salary.basic_salary, Decimal("0"),
            overrides, component_rules,
        )
        gross = Decimal("0")
        taxable_income = Decimal("0")
        prorated_earnings: dict[str, Decimal] = {}
        lines: list[dict] = []
        for comp in earning_components:
            amount = (raw_earning_amounts[comp.code] * attendance_factor).quantize(Decimal("0.01"))
            gross += amount
            prorated_earnings[comp.code] = amount
            if comp.is_taxable:
                taxable_income += amount
            lines.append({
                "code": comp.code, "name": comp.name, "type": comp.component_type,
                "amount": amount, "is_taxable": comp.is_taxable, "order": comp.display_order,
            })

        # ── Loans, Advances, Bonuses, Arrears, Reimbursements, Commissions ──
        # Placed here (before tax) so taxable bonuses/arrears correctly
        # count toward taxable_income — computing tax first and adding
        # these afterward would under-tax them.
        loan_advance_deductions = Decimal("0")

        active_loans = (
            await db.execute(
                select(PayrollLoan).where(
                    PayrollLoan.employee_id == employee.id, PayrollLoan.tenant_id == tenant_id,
                    PayrollLoan.status == LoanStatus.ACTIVE, PayrollLoan.is_deleted == False,  # noqa: E712
                    PayrollLoan.start_date <= run.period_end,
                ).order_by(PayrollLoan.deduction_priority)
            )
        ).scalars().all()
        for loan in active_loans:
            installment = min(loan.installment_amount, loan.remaining_balance)
            if installment <= 0:
                continue
            loan_advance_deductions += installment
            lines.append({
                "code": f"LOAN_{str(loan.id)[:8]}", "name": "Loan Repayment", "type": ComponentType.DEDUCTION,
                "amount": installment, "is_taxable": False, "order": 9200,
            })
            loan.remaining_balance -= installment
            if loan.remaining_balance <= 0:
                loan.status = LoanStatus.CLOSED

        active_advances = (
            await db.execute(
                select(PayrollAdvance).where(
                    PayrollAdvance.employee_id == employee.id, PayrollAdvance.tenant_id == tenant_id,
                    PayrollAdvance.status == AdvanceStatus.ACTIVE, PayrollAdvance.is_deleted == False,  # noqa: E712
                    PayrollAdvance.recovery_start_date <= run.period_end,
                ).order_by(PayrollAdvance.deduction_priority)
            )
        ).scalars().all()
        for advance in active_advances:
            installment = min(advance.installment_amount, advance.remaining_balance)
            if installment <= 0:
                continue
            loan_advance_deductions += installment
            lines.append({
                "code": f"ADVANCE_{str(advance.id)[:8]}", "name": "Salary Advance Recovery", "type": ComponentType.DEDUCTION,
                "amount": installment, "is_taxable": False, "order": 9210,
            })
            advance.remaining_balance -= installment
            if advance.remaining_balance <= 0:
                advance.status = AdvanceStatus.CLOSED

        # Approved, period-matched bonuses/arrears/commissions/reimbursements
        # — PENDING ones are visible for review but never silently paid.
        approved_bonuses = (
            await db.execute(
                select(PayrollBonus).where(
                    PayrollBonus.employee_id == employee.id, PayrollBonus.tenant_id == tenant_id,
                    PayrollBonus.status == BonusStatus.APPROVED, PayrollBonus.is_deleted == False,  # noqa: E712
                    PayrollBonus.target_period_start <= run.period_end,
                    PayrollBonus.target_period_end >= run.period_start,
                )
            )
        ).scalars().all()
        for bonus in approved_bonuses:
            gross += bonus.amount
            if bonus.is_taxable:
                taxable_income += bonus.amount
            lines.append({
                "code": f"BONUS_{bonus.bonus_type.value.upper()}", "name": bonus.name, "type": ComponentType.EARNING,
                "amount": bonus.amount, "is_taxable": bonus.is_taxable, "order": 9300,
            })
            bonus.status = BonusStatus.PAID

        approved_arrears = (
            await db.execute(
                select(PayrollArrear).where(
                    PayrollArrear.employee_id == employee.id, PayrollArrear.tenant_id == tenant_id,
                    PayrollArrear.status == ArrearStatus.APPROVED, PayrollArrear.is_deleted == False,  # noqa: E712
                    PayrollArrear.target_period_start <= run.period_end,
                    PayrollArrear.target_period_end >= run.period_start,
                )
            )
        ).scalars().all()
        for arrear in approved_arrears:
            gross += arrear.amount
            if arrear.is_taxable:
                taxable_income += arrear.amount
            lines.append({
                "code": "ARREAR", "name": f"Arrear: {arrear.reason}", "type": ComponentType.EARNING,
                "amount": arrear.amount, "is_taxable": arrear.is_taxable, "order": 9310,
            })
            arrear.status = ArrearStatus.PAID

        approved_commissions = (
            await db.execute(
                select(PayrollCommission).where(
                    PayrollCommission.employee_id == employee.id, PayrollCommission.tenant_id == tenant_id,
                    PayrollCommission.status == CommissionStatus.APPROVED, PayrollCommission.is_deleted == False,  # noqa: E712
                    PayrollCommission.target_period_start <= run.period_end,
                    PayrollCommission.target_period_end >= run.period_start,
                )
            )
        ).scalars().all()
        for commission in approved_commissions:
            gross += commission.computed_amount
            taxable_income += commission.computed_amount  # commission is standard taxable income
            lines.append({
                "code": "COMMISSION", "name": "Sales Commission", "type": ComponentType.EARNING,
                "amount": commission.computed_amount, "is_taxable": True, "order": 9320,
            })
            commission.status = CommissionStatus.PAID

        approved_reimbursements = (
            await db.execute(
                select(PayrollReimbursement).where(
                    PayrollReimbursement.employee_id == employee.id, PayrollReimbursement.tenant_id == tenant_id,
                    PayrollReimbursement.status == ReimbursementStatus.APPROVED, PayrollReimbursement.is_deleted == False,  # noqa: E712
                )
            )
        ).scalars().all()
        for reimbursement in approved_reimbursements:
            gross += reimbursement.amount
            if reimbursement.is_taxable:
                taxable_income += reimbursement.amount
            lines.append({
                "code": f"REIMB_{reimbursement.category.value.upper()}",
                "name": f"Reimbursement: {reimbursement.category.value.title()}", "type": ComponentType.EARNING,
                "amount": reimbursement.amount, "is_taxable": reimbursement.is_taxable, "order": 9330,
            })
            reimbursement.status = ReimbursementStatus.INCLUDED_IN_PAYROLL

        # ── Deductions (GROSS + every earning code now available to formulas) ──
        deduction_context = {"BASIC": salary.basic_salary, "GROSS": gross, **prorated_earnings}
        raw_deduction_amounts = _resolve_components_with_formulas(
            deduction_components, deduction_context, salary.basic_salary, gross, overrides, component_rules,
        )
        deductions = Decimal("0")
        for comp in deduction_components:
            amount = raw_deduction_amounts[comp.code].quantize(Decimal("0.01"))
            deductions += amount
            lines.append({
                "code": comp.code, "name": comp.name, "type": comp.component_type,
                "amount": amount, "is_taxable": comp.is_taxable, "order": comp.display_order,
            })

        # ── Tax engine — one active PayrollTaxRule per tenant, versioned
        # by tax year/effective dates. No tenant is REQUIRED to configure
        # one; payroll still runs without it (validation should warn, not
        # block — a missing tax rule isn't a reason to stop paying people).
        tax_rule = (
            await db.execute(
                select(PayrollTaxRule).where(
                    PayrollTaxRule.tenant_id == tenant_id,
                    PayrollTaxRule.is_active == True,  # noqa: E712
                    PayrollTaxRule.is_deleted == False,  # noqa: E712
                    PayrollTaxRule.effective_from <= run.pay_date,
                    (PayrollTaxRule.effective_to.is_(None)) | (PayrollTaxRule.effective_to >= run.pay_date),
                ).order_by(PayrollTaxRule.effective_from.desc())
            )
        ).scalars().first()

        if tax_rule is not None:
            bracket_rows = (
                await db.execute(select(PayrollTaxBracket).where(PayrollTaxBracket.tax_rule_id == tax_rule.id))
            ).scalars().all()
            bracket_data = [TaxBracketData(b.min_amount, b.max_amount, b.rate_percentage) for b in bracket_rows]

            if tax_rule.calculation_base == TaxCalculationBase.ANNUAL_TAXABLE_INCOME:
                annual_tax = calculate_progressive_tax(taxable_income * Decimal("12"), bracket_data)
                tax_amount = monthly_from_annual(annual_tax)
            else:
                tax_amount = calculate_progressive_tax(taxable_income, bracket_data)

            if tax_amount > 0:
                deductions += tax_amount
                lines.append({
                    "code": "TAX", "name": f"Income Tax ({tax_rule.name})", "type": ComponentType.DEDUCTION,
                    "amount": tax_amount, "is_taxable": False, "order": 9000,
                })

        # ── Contribution engine — every active PayrollContributionRule
        # applies independently; employee side reduces net, employer side
        # is informational (costing/accounting only, never reduces net).
        contribution_rules = (
            await db.execute(
                select(PayrollContributionRule).where(
                    PayrollContributionRule.tenant_id == tenant_id,
                    PayrollContributionRule.is_active == True,  # noqa: E712
                    PayrollContributionRule.is_deleted == False,  # noqa: E712
                    PayrollContributionRule.effective_from <= run.pay_date,
                    (PayrollContributionRule.effective_to.is_(None)) | (PayrollContributionRule.effective_to >= run.pay_date),
                )
            )
        ).scalars().all()
        for rule in contribution_rules:
            base_amount = salary.basic_salary if rule.calculation_base == ContributionCalculationBase.BASIC else gross
            rule_data = ContributionRuleData(
                employee_percentage=rule.employee_percentage, employee_fixed_amount=rule.employee_fixed_amount,
                employer_percentage=rule.employer_percentage, employer_fixed_amount=rule.employer_fixed_amount,
                min_base=rule.min_base, max_base=rule.max_base,
            )
            employee_amount, employer_amount = calculate_contribution(base_amount, rule_data)
            if employee_amount > 0:
                deductions += employee_amount
                lines.append({
                    "code": f"{rule.code}_EE", "name": f"{rule.name} (Employee)", "type": ComponentType.DEDUCTION,
                    "amount": employee_amount, "is_taxable": False, "order": 9100,
                })
            if employer_amount > 0:
                lines.append({
                    "code": f"{rule.code}_ER", "name": f"{rule.name} (Employer)", "type": ComponentType.EMPLOYER_CONTRIBUTION,
                    "amount": employer_amount, "is_taxable": rule.is_taxable, "order": 9100,
                })

        # ── Structure-defined employer contributions (unchanged, formula-aware) ──
        raw_contribution_amounts = _resolve_components_with_formulas(
            contribution_components, deduction_context, salary.basic_salary, gross, overrides, component_rules,
        )
        for comp in contribution_components:
            amount = raw_contribution_amounts[comp.code].quantize(Decimal("0.01"))
            lines.append({
                "code": comp.code, "name": comp.name, "type": comp.component_type,
                "amount": amount, "is_taxable": comp.is_taxable, "order": comp.display_order,
            })

        net = gross - deductions - loan_advance_deductions

        payslip = Payslip(
            tenant_id=tenant_id,
            payroll_run_id=run.id,
            employee_id=employee.id,
            status=PayslipStatus.GENERATED,
            working_days=working_days,
            present_days=present_days,
            absent_days=absent_days,
            leave_days=leave_days,
            unpaid_leave_days=unpaid_leave_days,
            overtime_hours=overtime_hours,
            gross_salary=gross,
            total_deductions=deductions + loan_advance_deductions,
            net_salary=net,
        )
        db.add(payslip)
        await db.flush()

        for line in lines:
            db.add(PayslipLine(
                tenant_id=tenant_id,
                payslip_id=payslip.id,
                component_code=line["code"],
                component_name=line["name"],
                component_type=line["type"],
                amount=line["amount"],
                is_taxable=line["is_taxable"],
                display_order=line["order"],
            ))

        total_gross += gross
        total_deductions += deductions + loan_advance_deductions
        total_net += net
        generated += 1

    run.total_gross = total_gross
    run.total_deductions = total_deductions
    run.total_net = total_net
    run.employee_count = generated
    run.status = PayrollRunStatus.REVIEW

    await db.flush()
    return {
        "id": str(run.id),
        "status": run.status.value,
        "employee_count": generated,
        "total_gross": str(total_gross),
        "total_deductions": str(total_deductions),
        "total_net": str(total_net),
    }


@router.post("/runs/{run_id}/approve", summary="Approve a payroll run")
async def approve_payroll_run(
    run_id: UUID,
    current_user: User = Depends(require_permission("payroll.approve")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import datetime, timezone

    run = (
        await db.execute(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Payroll run not found")
    if run.status != PayrollRunStatus.REVIEW:
        raise HTTPException(status_code=400, detail=f"Run must be in REVIEW to approve (currently {run.status.value})")

    run.status = PayrollRunStatus.APPROVED
    run.approved_by_id = current_user.id
    run.approved_at = datetime.now(timezone.utc)
    await db.flush()
    return {"id": str(run.id), "status": run.status.value}


@router.get("/runs/{run_id}", summary="Get a single payroll run")
async def get_payroll_run(
    run_id: UUID,
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = (
        await db.execute(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Payroll run not found")
    return {
        "id": str(run.id), "name": run.name,
        "period_start": str(run.period_start), "period_end": str(run.period_end), "pay_date": str(run.pay_date),
        "status": run.status.value, "currency": run.currency,
        "total_gross": str(run.total_gross), "total_deductions": str(run.total_deductions),
        "total_net": str(run.total_net), "employee_count": run.employee_count,
    }


@router.get("/runs", summary="List payroll runs")
async def list_payroll_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("payroll.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    offset = (page - 1) * page_size
    filters = [PayrollRun.tenant_id == tenant_id, PayrollRun.is_deleted == False]
    stmt = select(PayrollRun).where(*filters).order_by(PayrollRun.period_start.desc()).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(PayrollRun).where(*filters)
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()

    return {
        "items": [
            {
                "id": str(r.id),
                "name": r.name,
                "period_start": str(r.period_start),
                "period_end": str(r.period_end),
                "pay_date": str(r.pay_date),
                "status": r.status.value,
                "total_gross": str(r.total_gross),
                "total_deductions": str(r.total_deductions),
                "total_net": str(r.total_net),
                "employee_count": r.employee_count,
                "currency": r.currency,
            }
            for r in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }


@router.get("/runs/{run_id}/payslips", summary="List payslips for a run")
async def list_payslips(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Self-service aware (bug fix): this used to hard-require
    payroll.view, so an employee without it got a flat 403 and could never
    even discover their own payslip_id — which meant the self-view PDF
    download (_can_view_payslip, below) was unreachable in practice. Callers
    with payroll.view see every payslip in the run; everyone else sees only
    their own.
    """
    filters = [Payslip.payroll_run_id == run_id, Payslip.tenant_id == tenant_id]
    if not current_user.has_permission("payroll.view"):
        own_employee = await EmployeeRepository(db, tenant_id).get_by_user_id(current_user.id)
        if own_employee is None:
            raise NotFoundError("Employee profile not found for this user")
        filters.append(Payslip.employee_id == own_employee.id)

    from sqlalchemy.orm import selectinload

    stmt = select(Payslip).where(*filters).options(selectinload(Payslip.payroll_run))
    items = (await db.execute(stmt)).scalars().all()

    # Resolve employee names in one batch query rather than per-row.
    employee_ids = [p.employee_id for p in items]
    employees = (
        await db.execute(select(Employee).where(Employee.id.in_(employee_ids)))
    ).scalars().all() if employee_ids else []
    employee_map = {e.id: e for e in employees}
    user_ids = [e.user_id for e in employees]
    users = (
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars().all() if user_ids else []
    user_map = {u.id: u for u in users}

    def _employee_name(employee_id: UUID) -> str:
        emp = employee_map.get(employee_id)
        if emp is None:
            return "Unknown"
        user = user_map.get(emp.user_id)
        return f"{user.first_name} {user.last_name}".strip() if user else emp.employee_code

    return {
        "items": [
            {
                "id": str(p.id), "employee_id": str(p.employee_id), "employee_name": _employee_name(p.employee_id),
                "gross_salary": str(p.gross_salary), "total_deductions": str(p.total_deductions),
                "net_salary": str(p.net_salary), "status": p.status.value,
            }
            for p in items
        ],
        "total": len(items),
    }


@router.get("/payslips/{payslip_id}", summary="Get a payslip's full calculation breakdown")
async def get_payslip(
    payslip_id: UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Self-service aware, same reasoning as list_payslips above: HR/payroll
    staff can view any payslip; an employee without payroll.view can only
    view their OWN."""
    from sqlalchemy.orm import selectinload

    payslip = (
        await db.execute(
            select(Payslip).where(Payslip.id == payslip_id, Payslip.tenant_id == tenant_id)
            .options(selectinload(Payslip.lines), selectinload(Payslip.payroll_run))
        )
    ).scalar_one_or_none()
    if payslip is None:
        raise NotFoundError("Payslip not found")

    if not current_user.has_permission("payroll.view"):
        own_employee = await EmployeeRepository(db, tenant_id).get_by_user_id(current_user.id)
        if own_employee is None or own_employee.id != payslip.employee_id:
            raise PermissionDeniedError("You can only view your own payslip.")

    employee = (await db.execute(select(Employee).where(Employee.id == payslip.employee_id))).scalar_one_or_none()
    user = (await db.execute(select(User).where(User.id == employee.user_id))).scalar_one_or_none() if employee else None
    employee_name = f"{user.first_name} {user.last_name}".strip() if user else (employee.employee_code if employee else "Unknown")

    lines = sorted(payslip.lines, key=lambda l: l.display_order)
    return {
        "id": str(payslip.id),
        "employee_id": str(payslip.employee_id),
        "employee_name": employee_name,
        "employee_code": employee.employee_code if employee else None,
        "run": {
            "id": str(payslip.payroll_run.id), "name": payslip.payroll_run.name,
            "period_start": str(payslip.payroll_run.period_start), "period_end": str(payslip.payroll_run.period_end),
            "pay_date": str(payslip.payroll_run.pay_date), "currency": payslip.payroll_run.currency,
        },
        "status": payslip.status.value,
        "working_days": payslip.working_days,
        "present_days": str(payslip.present_days),
        "absent_days": str(payslip.absent_days),
        "leave_days": str(payslip.leave_days),
        "unpaid_leave_days": str(payslip.unpaid_leave_days),
        "overtime_hours": str(payslip.overtime_hours),
        "gross_salary": str(payslip.gross_salary),
        "total_deductions": str(payslip.total_deductions),
        "net_salary": str(payslip.net_salary),
        "earnings": [
            {"code": l.component_code, "name": l.component_name, "amount": str(l.amount), "is_taxable": l.is_taxable}
            for l in lines if l.component_type == ComponentType.EARNING
        ],
        "deductions": [
            {"code": l.component_code, "name": l.component_name, "amount": str(l.amount), "is_taxable": l.is_taxable}
            for l in lines if l.component_type == ComponentType.DEDUCTION
        ],
        "employer_contributions": [
            {"code": l.component_code, "name": l.component_name, "amount": str(l.amount), "is_taxable": l.is_taxable}
            for l in lines if l.component_type == ComponentType.EMPLOYER_CONTRIBUTION
        ],
    }


@router.get("/payslips/{payslip_id}/pdf", summary="Download a payslip as PDF")
async def download_payslip_pdf(
    payslip_id: UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Generated on demand with reportlab — nothing is persisted to disk, so
    there's no storage backend to configure for this to work in dev.
    Self-service aware: an employee can download their own payslip;
    anyone with `payroll.view` (or a platform admin) can download any
    payslip in their org. See `_can_view_payslip` below.
    """
    payslip = (
        await db.execute(
            select(Payslip).where(Payslip.id == payslip_id, Payslip.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if payslip is None:
        raise NotFoundError("Payslip not found")

    if not (
        current_user.is_platform_admin
        or await _can_view_payslip(db, current_user, tenant_id, payslip)
    ):
        raise HTTPException(status_code=403, detail="Not allowed to view this payslip")

    employee = (
        await db.execute(select(Employee).where(Employee.id == payslip.employee_id))
    ).scalar_one_or_none()
    emp_user = (
        await db.execute(select(User).where(User.id == employee.user_id))
    ).scalar_one_or_none() if employee else None
    run = (
        await db.execute(select(PayrollRun).where(PayrollRun.id == payslip.payroll_run_id))
    ).scalar_one_or_none()
    lines = (
        await db.execute(
            select(PayslipLine).where(PayslipLine.payslip_id == payslip.id).order_by(PayslipLine.display_order)
        )
    ).scalars().all()

    pdf_bytes = _render_payslip_pdf(payslip, employee, emp_user, run, lines)
    filename = f"payslip-{employee.employee_code if employee else payslip_id}-{run.pay_date if run else ''}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _can_view_payslip(db: AsyncSession, current_user: User, tenant_id: UUID, payslip: Payslip) -> bool:
    """Employees can view their own payslip; anyone with payroll.view can view any."""
    if current_user.has_permission("payroll.view"):
        return True
    employee = (
        await db.execute(select(Employee).where(Employee.id == payslip.employee_id))
    ).scalar_one_or_none()
    return bool(employee and employee.user_id == current_user.id)


def _render_payslip_pdf(payslip: Payslip, employee, emp_user, run, lines: list[PayslipLine]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()
    elements = []

    name = f"{emp_user.first_name} {emp_user.last_name}" if emp_user else "Employee"
    elements.append(Paragraph("Payslip", styles["Title"]))
    elements.append(Spacer(1, 6))
    period = f"{run.period_start} to {run.period_end}" if run else ""
    elements.append(Paragraph(f"{name} ({employee.employee_code if employee else '-'})", styles["Heading3"]))
    elements.append(Paragraph(f"Pay period: {period} &nbsp;&nbsp; Pay date: {run.pay_date if run else '-'}", styles["Normal"]))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"Working days: {payslip.working_days} &nbsp; Present: {payslip.present_days} &nbsp; "
        f"Absent: {payslip.absent_days} &nbsp; Leave: {payslip.leave_days} "
        f"(Unpaid: {payslip.unpaid_leave_days}) &nbsp; "
        f"Overtime: {payslip.overtime_hours}h",
        styles["Normal"],
    ))
    elements.append(Spacer(1, 12))

    earning_rows = [["Earnings", "Amount"]]
    deduction_rows = [["Deductions", "Amount"]]
    for line in lines:
        row = [line.component_name, f"{line.amount:,.2f}"]
        if line.component_type == ComponentType.EARNING:
            earning_rows.append(row)
        elif line.component_type == ComponentType.DEDUCTION:
            deduction_rows.append(row)

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ])
    earn_table = Table(earning_rows, colWidths=[300, 100])
    earn_table.setStyle(table_style)
    ded_table = Table(deduction_rows, colWidths=[300, 100])
    ded_table.setStyle(table_style)

    elements.append(earn_table)
    elements.append(Spacer(1, 10))
    elements.append(ded_table)
    elements.append(Spacer(1, 16))

    summary = Table([
        ["Gross Salary", f"{payslip.gross_salary:,.2f}"],
        ["Total Deductions", f"{payslip.total_deductions:,.2f}"],
        ["Net Salary", f"{payslip.net_salary:,.2f}"],
    ], colWidths=[300, 100])
    summary.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("LINEABOVE", (0, 2), (-1, 2), 1, colors.black),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    elements.append(summary)

    doc.build(elements)
    return buf.getvalue()