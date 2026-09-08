"""
End-to-end integration tests for Payroll Phase 3: loans, advances, bonuses,
arrears, commissions, and reimbursements — all exercised through the real
generate_payroll_run() endpoint against a real (in-memory SQLite) database.

Run:  cd backend && pytest tests/test_payroll_phase3_generate_run_integration.py -v
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio

TENANT = uuid.uuid4()
PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 6, 30)


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


async def _make_employee(db):
    from app.models.employee import Employee, EmploymentStatus, EmploymentType, JobNature

    emp = Employee(
        tenant_id=TENANT, user_id=uuid.uuid4(), employee_code=f"EMP-{uuid.uuid4().hex[:6]}",
        employment_type=EmploymentType.FULL_TIME, job_nature=JobNature.PERMANENT,
        employment_status=EmploymentStatus.ACTIVE, date_of_joining=date(2020, 1, 1),
    )
    db.add(emp)
    await db.flush()
    return emp


async def _make_structure_and_salary(db, employee, basic_salary=Decimal("100000")):
    from app.models.payroll import SalaryStructure, SalaryComponent, EmployeeSalary, ComponentType, ComponentCalculation

    structure = SalaryStructure(tenant_id=TENANT, name="Standard", code=f"STD-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(structure)
    await db.flush()
    db.add(SalaryComponent(
        tenant_id=TENANT, salary_structure_id=structure.id, name="Basic", code="BASIC",
        component_type=ComponentType.EARNING, calculation_type=ComponentCalculation.FIXED,
        amount=basic_salary, display_order=1,
    ))
    await db.flush()
    salary = EmployeeSalary(
        tenant_id=TENANT, employee_id=employee.id, salary_structure_id=structure.id,
        basic_salary=basic_salary, effective_from=date(2020, 1, 1), is_current=True,
    )
    db.add(salary)
    await db.flush()
    return structure, salary


async def _make_run(db, period_start=PERIOD_START, period_end=PERIOD_END):
    from app.models.payroll import PayrollRun, PayrollRunStatus

    run = PayrollRun(
        tenant_id=TENANT, name="Test Run", period_start=period_start, period_end=period_end,
        pay_date=period_end, currency="USD", status=PayrollRunStatus.DRAFT, processed_by_id=uuid.uuid4(),
    )
    db.add(run)
    await db.flush()
    return run


def _user():
    return SimpleNamespace(id=uuid.uuid4())


class TestLoanRepayment:
    @pytest.mark.asyncio
    async def test_installment_deducted_and_balance_reduced(self, db_session):
        from app.models.payroll import PayrollLoan, LoanStatus, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        loan = PayrollLoan(
            tenant_id=TENANT, employee_id=employee.id, principal_amount=Decimal("12000"),
            interest_rate=Decimal("0"), number_of_installments=12, installment_amount=Decimal("1000"),
            remaining_balance=Decimal("12000"), start_date=date(2026, 1, 1), status=LoanStatus.ACTIVE,
        )
        db_session.add(loan)
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.net_salary == Decimal("99000.00")  # 100000 - 1000 installment
        assert loan.remaining_balance == Decimal("11000")
        assert loan.status == LoanStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_final_installment_never_exceeds_remaining_balance_and_closes_loan(self, db_session):
        from app.models.payroll import PayrollLoan, LoanStatus, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        # Only 300 left, but the fixed installment is 1000 -> must deduct only 300, not 1000.
        loan = PayrollLoan(
            tenant_id=TENANT, employee_id=employee.id, principal_amount=Decimal("12000"),
            number_of_installments=12, installment_amount=Decimal("1000"),
            remaining_balance=Decimal("300"), start_date=date(2026, 1, 1), status=LoanStatus.ACTIVE,
        )
        db_session.add(loan)
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.net_salary == Decimal("99700.00")  # only 300 deducted, never overpaid
        assert loan.remaining_balance == Decimal("0")
        assert loan.status == LoanStatus.CLOSED

    @pytest.mark.asyncio
    async def test_closed_loan_is_not_deducted_again(self, db_session):
        from app.models.payroll import PayrollLoan, LoanStatus, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        db_session.add(PayrollLoan(
            tenant_id=TENANT, employee_id=employee.id, principal_amount=Decimal("12000"),
            number_of_installments=12, installment_amount=Decimal("1000"),
            remaining_balance=Decimal("0"), start_date=date(2026, 1, 1), status=LoanStatus.CLOSED,
        ))
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.net_salary == Decimal("100000.00")


class TestAdvanceRecovery:
    @pytest.mark.asyncio
    async def test_advance_installment_deducted(self, db_session):
        from app.models.payroll import PayrollAdvance, AdvanceStatus, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        db_session.add(PayrollAdvance(
            tenant_id=TENANT, employee_id=employee.id, advance_amount=Decimal("5000"),
            number_of_installments=5, installment_amount=Decimal("1000"),
            remaining_balance=Decimal("5000"), recovery_start_date=date(2026, 1, 1), status=AdvanceStatus.ACTIVE,
        ))
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.net_salary == Decimal("99000.00")


class TestBonus:
    @pytest.mark.asyncio
    async def test_approved_bonus_in_period_is_paid_and_taxed(self, db_session):
        from app.models.payroll import PayrollBonus, BonusType, BonusStatus, Payslip, PayslipLine
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        bonus = PayrollBonus(
            tenant_id=TENANT, employee_id=employee.id, bonus_type=BonusType.PERFORMANCE, name="Q2 Performance Bonus",
            amount=Decimal("10000"), is_taxable=True, target_period_start=PERIOD_START, target_period_end=PERIOD_END,
            status=BonusStatus.APPROVED,
        )
        db_session.add(bonus)
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.gross_salary == Decimal("110000.00")
        assert bonus.status == BonusStatus.PAID

    @pytest.mark.asyncio
    async def test_pending_bonus_is_never_silently_paid(self, db_session):
        from app.models.payroll import PayrollBonus, BonusType, BonusStatus, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        db_session.add(PayrollBonus(
            tenant_id=TENANT, employee_id=employee.id, bonus_type=BonusType.SPOT, name="Spot Bonus",
            amount=Decimal("5000"), target_period_start=PERIOD_START, target_period_end=PERIOD_END,
            status=BonusStatus.PENDING,  # not approved!
        ))
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.gross_salary == Decimal("100000.00")  # bonus excluded

    @pytest.mark.asyncio
    async def test_bonus_outside_period_is_not_included(self, db_session):
        from app.models.payroll import PayrollBonus, BonusType, BonusStatus, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        db_session.add(PayrollBonus(
            tenant_id=TENANT, employee_id=employee.id, bonus_type=BonusType.ANNUAL, name="Next Month's Bonus",
            amount=Decimal("5000"), target_period_start=date(2026, 7, 1), target_period_end=date(2026, 7, 31),
            status=BonusStatus.APPROVED,
        ))
        await db_session.flush()

        run = await _make_run(db_session)  # June run
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.gross_salary == Decimal("100000.00")


class TestArrear:
    @pytest.mark.asyncio
    async def test_approved_arrear_added_with_explanation(self, db_session):
        from app.models.payroll import PayrollArrear, ArrearStatus, Payslip, PayslipLine
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        arrear = PayrollArrear(
            tenant_id=TENANT, employee_id=employee.id, reason="Backdated raise approved in June for Jan-Mar",
            source_period_start=date(2026, 1, 1), source_period_end=date(2026, 3, 31),
            target_period_start=PERIOD_START, target_period_end=PERIOD_END,
            amount=Decimal("15000"), is_taxable=True,
            calculation_details={"jan": "5000", "feb": "5000", "mar": "5000"},
            status=ArrearStatus.APPROVED,
        )
        db_session.add(arrear)
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        lines = (await db_session.execute(select(PayslipLine).where(PayslipLine.payslip_id == payslip.id))).scalars().all()
        arrear_line = next(l for l in lines if l.component_code == "ARREAR")

        assert payslip.gross_salary == Decimal("115000.00")
        assert "Backdated raise" in arrear_line.component_name
        assert arrear.status == ArrearStatus.PAID


class TestCommission:
    @pytest.mark.asyncio
    async def test_approved_commission_added_as_taxable_earning(self, db_session):
        from app.models.payroll import PayrollCommission, CommissionStatus, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        commission = PayrollCommission(
            tenant_id=TENANT, employee_id=employee.id, target_period_start=PERIOD_START, target_period_end=PERIOD_END,
            sales_amount=Decimal("600000"), computed_amount=Decimal("30000"), status=CommissionStatus.APPROVED,
        )
        db_session.add(commission)
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.gross_salary == Decimal("130000.00")
        assert commission.status == CommissionStatus.PAID


class TestReimbursement:
    @pytest.mark.asyncio
    async def test_approved_reimbursement_added_as_non_taxable_earning(self, db_session):
        from app.models.payroll import PayrollReimbursement, ReimbursementCategory, ReimbursementStatus, Payslip, PayslipLine
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        reimbursement = PayrollReimbursement(
            tenant_id=TENANT, employee_id=employee.id, category=ReimbursementCategory.TRAVEL,
            amount=Decimal("2500"), is_taxable=False, status=ReimbursementStatus.APPROVED,
        )
        db_session.add(reimbursement)
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.gross_salary == Decimal("102500.00")
        assert reimbursement.status == ReimbursementStatus.INCLUDED_IN_PAYROLL

    @pytest.mark.asyncio
    async def test_already_included_reimbursement_is_not_paid_twice(self, db_session):
        """Regenerating a DRAFT run must not double-pay a reimbursement
        that a previous generation already marked INCLUDED_IN_PAYROLL."""
        from app.models.payroll import PayrollReimbursement, ReimbursementCategory, ReimbursementStatus, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        db_session.add(PayrollReimbursement(
            tenant_id=TENANT, employee_id=employee.id, category=ReimbursementCategory.MEDICAL,
            amount=Decimal("2500"), status=ReimbursementStatus.INCLUDED_IN_PAYROLL,  # from a prior run
        ))
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        assert payslip.gross_salary == Decimal("100000.00")


class TestMultipleDeductionsCombined:
    @pytest.mark.asyncio
    async def test_loan_and_advance_and_bonus_all_combine_correctly(self, db_session):
        from app.models.payroll import PayrollLoan, LoanStatus, PayrollAdvance, AdvanceStatus, PayrollBonus, BonusType, BonusStatus, Payslip
        from app.api.v1.hrms.payroll import generate_payroll_run
        from sqlalchemy import select

        employee = await _make_employee(db_session)
        await _make_structure_and_salary(db_session, employee)
        db_session.add(PayrollLoan(
            tenant_id=TENANT, employee_id=employee.id, principal_amount=Decimal("12000"),
            number_of_installments=12, installment_amount=Decimal("1000"),
            remaining_balance=Decimal("12000"), start_date=date(2026, 1, 1), status=LoanStatus.ACTIVE,
        ))
        db_session.add(PayrollAdvance(
            tenant_id=TENANT, employee_id=employee.id, advance_amount=Decimal("3000"),
            number_of_installments=3, installment_amount=Decimal("1000"),
            remaining_balance=Decimal("3000"), recovery_start_date=date(2026, 1, 1), status=AdvanceStatus.ACTIVE,
        ))
        db_session.add(PayrollBonus(
            tenant_id=TENANT, employee_id=employee.id, bonus_type=BonusType.FESTIVAL, name="Festival Bonus",
            amount=Decimal("5000"), is_taxable=False, target_period_start=PERIOD_START, target_period_end=PERIOD_END,
            status=BonusStatus.APPROVED,
        ))
        await db_session.flush()

        run = await _make_run(db_session)
        await generate_payroll_run(run.id, _user(), TENANT, db_session)

        payslip = (await db_session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalar_one()
        # gross: 100000 + 5000 bonus = 105000
        # deductions: 1000 loan + 1000 advance = 2000
        # net: 105000 - 2000 = 103000
        assert payslip.gross_salary == Decimal("105000.00")
        assert payslip.net_salary == Decimal("103000.00")
