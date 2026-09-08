"""
End-to-end integration tests for Payroll Phase 2: formula-driven salary
components, the tax engine, the contribution engine, and the leave.is_paid
fix — all exercised through the real generate_payroll_run() endpoint
against a real (in-memory SQLite) database, not mocks.

Run:  cd backend && pytest tests/test_payroll_phase2_generate_run_integration.py -v
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio

TENANT = uuid.uuid4()


@pytest_asyncio.fixture
async def db_session():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    import app.models.payroll  # noqa: F401
    import app.models.employee  # noqa: F401
    import app.models.attendance  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_employee(db, **overrides):
    from app.models.employee import Employee, EmploymentStatus, EmploymentType, JobNature

    defaults = dict(
        tenant_id=TENANT, user_id=uuid.uuid4(), employee_code=f"EMP-{uuid.uuid4().hex[:6]}",
        employment_type=EmploymentType.FULL_TIME, job_nature=JobNature.PERMANENT,
        employment_status=EmploymentStatus.ACTIVE, date_of_joining=date(2020, 1, 1),
    )
    defaults.update(overrides)
    emp = Employee(**defaults)
    db.add(emp)
    await db.flush()
    return emp


async def _make_structure_and_salary(db, employee, components: list[dict], basic_salary=Decimal("100000")):
    from app.models.payroll import SalaryStructure, SalaryComponent, EmployeeSalary

    structure = SalaryStructure(tenant_id=TENANT, name="Standard", code=f"STD-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(structure)
    await db.flush()

    for c in components:
        db.add(SalaryComponent(tenant_id=TENANT, salary_structure_id=structure.id, **c))
    await db.flush()

    salary = EmployeeSalary(
        tenant_id=TENANT, employee_id=employee.id, salary_structure_id=structure.id,
        basic_salary=basic_salary, effective_from=date(2020, 1, 1), is_current=True,
    )
    db.add(salary)
    await db.flush()
    return structure, salary


async def _make_run(db, period_start, period_end, pay_date=None):
    from app.models.payroll import PayrollRun, PayrollRunStatus

    run = PayrollRun(
        tenant_id=TENANT, name="Test Run", period_start=period_start, period_end=period_end,
        pay_date=pay_date or period_end, currency="USD", status=PayrollRunStatus.DRAFT,
        processed_by_id=uuid.uuid4(),
    )
    db.add(run)
    await db.flush()
    return run


def _user():
    return SimpleNamespace(id=uuid.uuid4())


class TestFormulaComponentsInGenerateRun:
    @pytest.mark.asyncio
    async def test_formula_earning_component_computed_from_basic(self, db_session):
        from app.models.payroll import ComponentType, ComponentCalculation
        from app.api.v1.hrms.payroll import generate_payroll_run

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, [
            dict(name="Basic", code="BASIC", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FIXED, amount=Decimal("100000"), display_order=1),
            dict(name="House Allowance", code="HOUSE", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FORMULA, formula="BASIC * 0.2", display_order=2),
        ])
        # Monday-Friday full period, no attendance records -> full pay (attendance_factor=1)
        run = await _make_run(db_session, date(2026, 6, 1), date(2026, 6, 30))

        result = await generate_payroll_run(run.id, _user(), TENANT, db_session)

        assert result["employee_count"] == 1
        assert Decimal(str(result["total_gross"])) == Decimal("120000.00")

    @pytest.mark.asyncio
    async def test_formula_deduction_component_can_reference_gross(self, db_session):
        from app.models.payroll import ComponentType, ComponentCalculation, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, [
            dict(name="Basic", code="BASIC", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FIXED, amount=Decimal("100000"), display_order=1),
            dict(name="Special Deduction", code="SPECIAL_DED", component_type=ComponentType.DEDUCTION,
                 calculation_type=ComponentCalculation.FORMULA, formula="ROUND(GROSS * 0.05, 2)", display_order=1),
        ])
        run = await _make_run(db_session, date(2026, 6, 1), date(2026, 6, 30))

        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.gross_salary == Decimal("100000.00")
        assert payslip.total_deductions == Decimal("5000.00")  # 100000 * 5%
        assert payslip.net_salary == Decimal("95000.00")

    @pytest.mark.asyncio
    async def test_circular_formula_dependency_raises_validation_error_not_a_500(self, db_session):
        from app.models.payroll import ComponentType, ComponentCalculation
        from app.api.v1.hrms.payroll import generate_payroll_run
        from app.core.exceptions import ValidationError

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, [
            dict(name="A", code="A", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FORMULA, formula="B + 1", display_order=1),
            dict(name="B", code="B", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FORMULA, formula="A + 1", display_order=2),
        ])
        run = await _make_run(db_session, date(2026, 6, 1), date(2026, 6, 30))

        with pytest.raises(ValidationError, match="CIRCULAR_FORMULA_DEPENDENCY"):
            await generate_payroll_run(run.id, _user(), TENANT, db_session)


class TestTaxEngineInGenerateRun:
    @pytest.mark.asyncio
    async def test_progressive_tax_applied_as_a_deduction_line(self, db_session):
        from app.models.payroll import (
            ComponentType, ComponentCalculation, Payslip, PayslipLine,
            PayrollTaxRule, PayrollTaxBracket, TaxCalculationBase,
        )
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, [
            dict(name="Basic", code="BASIC", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FIXED, amount=Decimal("120000"), display_order=1, is_taxable=True),
        ])

        tax_rule = PayrollTaxRule(
            tenant_id=TENANT, name="Example Tax FY26", country="Testland", tax_year="2026",
            calculation_base=TaxCalculationBase.MONTHLY_TAXABLE_INCOME,
            is_active=True, effective_from=date(2026, 1, 1),
        )
        db_session.add(tax_rule)
        await db_session.flush()
        db_session.add_all([
            PayrollTaxBracket(tenant_id=TENANT, tax_rule_id=tax_rule.id, min_amount=Decimal("0"), max_amount=Decimal("50000"), rate_percentage=Decimal("0")),
            PayrollTaxBracket(tenant_id=TENANT, tax_rule_id=tax_rule.id, min_amount=Decimal("50000"), max_amount=Decimal("100000"), rate_percentage=Decimal("10")),
            PayrollTaxBracket(tenant_id=TENANT, tax_rule_id=tax_rule.id, min_amount=Decimal("100000"), max_amount=None, rate_percentage=Decimal("20")),
        ])
        await db_session.flush()

        run = await _make_run(db_session, date(2026, 6, 1), date(2026, 6, 30))
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        lines = (await db_session.execute(select(PayslipLine).where(PayslipLine.payslip_id == payslip.id))).scalars().all()
        tax_line = next(l for l in lines if l.component_code == "TAX")

        # 120,000: 0 on first 50k, 10%*50k=5000, 20%*20k=4000 -> 9000 tax
        assert tax_line.amount == Decimal("9000.00")
        assert payslip.net_salary == Decimal("111000.00")

    @pytest.mark.asyncio
    async def test_no_tax_rule_configured_means_no_tax_line_not_a_crash(self, db_session):
        from app.models.payroll import ComponentType, ComponentCalculation, Payslip, PayslipLine
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, [
            dict(name="Basic", code="BASIC", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FIXED, amount=Decimal("100000"), display_order=1, is_taxable=True),
        ])
        run = await _make_run(db_session, date(2026, 6, 1), date(2026, 6, 30))

        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        lines = (await db_session.execute(select(PayslipLine).where(PayslipLine.payslip_id == payslip.id))).scalars().all()
        assert not any(l.component_code == "TAX" for l in lines)
        assert payslip.net_salary == payslip.gross_salary


class TestContributionEngineInGenerateRun:
    @pytest.mark.asyncio
    async def test_contribution_generates_employee_and_employer_lines(self, db_session):
        from app.models.payroll import (
            ComponentType, ComponentCalculation, Payslip, PayslipLine,
            PayrollContributionRule, ContributionCalculationBase,
        )
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, [
            dict(name="Basic", code="BASIC", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FIXED, amount=Decimal("100000"), display_order=1),
        ])
        db_session.add(PayrollContributionRule(
            tenant_id=TENANT, name="Pension Fund", code="PENSION",
            calculation_base=ContributionCalculationBase.BASIC,
            employee_percentage=Decimal("5"), employer_percentage=Decimal("8"),
            is_active=True, effective_from=date(2026, 1, 1),
        ))
        await db_session.flush()
        run = await _make_run(db_session, date(2026, 6, 1), date(2026, 6, 30))

        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        lines = (await db_session.execute(select(PayslipLine).where(PayslipLine.payslip_id == payslip.id))).scalars().all()

        ee_line = next(l for l in lines if l.component_code == "PENSION_EE")
        er_line = next(l for l in lines if l.component_code == "PENSION_ER")
        assert ee_line.amount == Decimal("5000.00")
        assert ee_line.component_type == ComponentType.DEDUCTION
        assert er_line.amount == Decimal("8000.00")
        assert er_line.component_type == ComponentType.EMPLOYER_CONTRIBUTION

        # Employer contribution must NOT reduce net salary.
        assert payslip.net_salary == Decimal("95000.00")  # 100000 - 5000 (employee side only)

    @pytest.mark.asyncio
    async def test_contribution_below_minimum_base_produces_no_lines(self, db_session):
        from app.models.payroll import (
            ComponentType, ComponentCalculation, Payslip, PayslipLine,
            PayrollContributionRule, ContributionCalculationBase,
        )
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, [
            dict(name="Basic", code="BASIC", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FIXED, amount=Decimal("5000"), display_order=1),
        ], basic_salary=Decimal("5000"))
        db_session.add(PayrollContributionRule(
            tenant_id=TENANT, name="Pension Fund", code="PENSION",
            calculation_base=ContributionCalculationBase.BASIC,
            employee_percentage=Decimal("5"), employer_percentage=Decimal("8"),
            min_base=Decimal("10000"), is_active=True, effective_from=date(2026, 1, 1),
        ))
        await db_session.flush()
        run = await _make_run(db_session, date(2026, 6, 1), date(2026, 6, 30))

        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        lines = (await db_session.execute(select(PayslipLine).where(PayslipLine.payslip_id == payslip.id))).scalars().all()
        assert not any(l.component_code in ("PENSION_EE", "PENSION_ER") for l in lines)


async def _mark_present(db, employee, period_start: date, period_end: date, *, except_dates: set[date] = frozenset()):
    """Creates a PRESENT AttendanceRecord for every weekday in the period
    except the given dates — realistic setup so proration reflects
    'worked every day except the leave', not 'no record = present'."""
    from app.models.attendance import AttendanceRecord, AttendanceStatus

    d = period_start
    while d <= period_end:
        if d.weekday() < 5 and d not in except_dates:
            db.add(AttendanceRecord(tenant_id=TENANT, employee_id=employee.id, date=d, status=AttendanceStatus.PRESENT))
        d = date.fromordinal(d.toordinal() + 1)
    await db.flush()


class TestUnpaidLeaveFixInGenerateRun:
    @pytest.mark.asyncio
    async def test_unpaid_leave_reduces_earnings_paid_leave_does_not(self, db_session):
        from app.models.payroll import ComponentType, ComponentCalculation, Payslip
        from app.models.attendance import LeaveType, LeaveRequest, LeaveRequestStatus
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, [
            dict(name="Basic", code="BASIC", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FIXED, amount=Decimal("100000"), display_order=1),
        ])

        unpaid_type = LeaveType(tenant_id=TENANT, name="Unpaid Leave", code="UNPAID", is_paid=False)
        db_session.add(unpaid_type)
        await db_session.flush()

        # June 2026: 22 weekdays. 5 unpaid leave days (all weekdays).
        db_session.add(LeaveRequest(
            tenant_id=TENANT, employee_id=employee.id, leave_type_id=unpaid_type.id,
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 5), total_days=Decimal("5"),
            duration_type="full_day", status=LeaveRequestStatus.APPROVED,
        ))
        await db_session.flush()
        # Present every OTHER working day in the period — realistic setup.
        leave_dates = {date(2026, 6, d) for d in range(1, 6)}
        await _mark_present(db_session, employee, date(2026, 6, 1), date(2026, 6, 30), except_dates=leave_dates)

        run = await _make_run(db_session, date(2026, 6, 1), date(2026, 6, 30))
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()

        assert payslip.unpaid_leave_days == Decimal("5.00")
        # 17 present days (out of 22 working days) counted, 5 unpaid days excluded
        # -> attendance_factor = 17/22, gross = 100000 * 17/22 ≈ 77272.73
        assert payslip.gross_salary < Decimal("100000.00")
        assert payslip.gross_salary == Decimal("77272.73")

    @pytest.mark.asyncio
    async def test_paid_leave_does_not_reduce_earnings(self, db_session):
        from app.models.payroll import ComponentType, ComponentCalculation, Payslip
        from app.models.attendance import LeaveType, LeaveRequest, LeaveRequestStatus
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee, [
            dict(name="Basic", code="BASIC", component_type=ComponentType.EARNING,
                 calculation_type=ComponentCalculation.FIXED, amount=Decimal("100000"), display_order=1),
        ])

        paid_type = LeaveType(tenant_id=TENANT, name="Annual Leave", code="ANNUAL", is_paid=True)
        db_session.add(paid_type)
        await db_session.flush()
        db_session.add(LeaveRequest(
            tenant_id=TENANT, employee_id=employee.id, leave_type_id=paid_type.id,
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 5), total_days=Decimal("5"),
            duration_type="full_day", status=LeaveRequestStatus.APPROVED,
        ))
        await db_session.flush()
        leave_dates = {date(2026, 6, d) for d in range(1, 6)}
        await _mark_present(db_session, employee, date(2026, 6, 1), date(2026, 6, 30), except_dates=leave_dates)

        run = await _make_run(db_session, date(2026, 6, 1), date(2026, 6, 30))
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()

        assert payslip.unpaid_leave_days == Decimal("0.00")
        # 17 present + 5 PAID leave days = all 22 working days counted -> full pay
        assert payslip.gross_salary == Decimal("100000.00")
