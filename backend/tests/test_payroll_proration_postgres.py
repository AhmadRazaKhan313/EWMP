"""
End-to-end regression tests for audit findings C-7 / H-9, through the real
POST /payroll/runs/{id}/generate against a live Postgres (TEST_DATABASE_URL,
same convention as the other *_postgres tests).

Period: September 2026 (22 Mon–Fri days, 26 Mon–Sat). Basic salary 100,000.
"""

import os
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.attendance import AttendanceRecord, AttendanceStatus, Holiday
from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.organization import Organization
from app.models.payroll import (
    ComponentCalculation, ComponentType, EmployeeSalary, LoanStatus, PayrollItemSettlement, PayrollLoan, PayrollRun,
    PayrollSettings, Payslip, PayslipLine, SalaryComponent, SalaryStructure, WorkingDaysMethod,
)
from app.models.rbac import Permission, Role
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

SEPT = {"name": "September", "period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"}


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    async def _get_db():
        async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def org(engine):
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Pro Co", slug=f"pro-{org_id.hex[:8]}", email=f"pro-{org_id.hex[:8]}@example.com"))
        await s.flush()
        perm = (await s.execute(select(Permission).where(Permission.codename == "payroll.process"))).scalar_one_or_none()
        if perm is None:
            perm = Permission(resource="payroll", action="process", codename="payroll.process", label="x", category="payroll")
            s.add(perm)
            await s.flush()
        role = Role(organization_id=org_id, name="Payroll", slug="payroll", permissions=[perm])
        email = f"pro-{uuid.uuid4().hex[:8]}@example.com"
        user = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                    first_name="P", last_name="A", is_active=True, is_email_verified=True, roles=[role])
        structure = SalaryStructure(tenant_id=org_id, name="Std", code=f"S-{uuid.uuid4().hex[:6]}", is_active=True)
        s.add_all([role, user, structure])
        await s.flush()
        s.add(SalaryComponent(tenant_id=org_id, salary_structure_id=structure.id, name="Basic", code="BASIC",
                              component_type=ComponentType.EARNING, calculation_type=ComponentCalculation.FIXED,
                              amount=Decimal("100000"), display_order=1))
        await s.commit()
        ids = {"org": org_id, "user": user.id, "structure": structure.id}
    yield ids
    async with AsyncSession(engine) as s:
        for model in (PayrollItemSettlement, PayslipLine, Payslip, PayrollRun, PayrollLoan, EmployeeSalary,
                      SalaryComponent, SalaryStructure, PayrollSettings, AttendanceRecord, Holiday, Employee):
            await s.execute(delete(model).where(model.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


async def employee(engine, org, *, status=EmploymentStatus.ACTIVE, joined=date(2020, 1, 1), left=None,
                   deleted=False, salary=Decimal("100000"), salary_from=date(2020, 1, 1)) -> uuid.UUID:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        email = f"e-{uuid.uuid4().hex[:8]}@example.com"
        u = User(organization_id=org["org"], email=email, email_normalized=email, password_hash="x",
                 first_name="E", last_name="T", is_active=True)
        s.add(u)
        await s.flush()
        e = Employee(tenant_id=org["org"], user_id=u.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                     employment_type=EmploymentType.FULL_TIME, employment_status=status,
                     date_of_joining=joined, date_of_leaving=left, is_deleted=deleted)
        s.add(e)
        await s.flush()
        s.add(EmployeeSalary(tenant_id=org["org"], employee_id=e.id, salary_structure_id=org["structure"],
                             basic_salary=salary, effective_from=salary_from, is_current=True))
        await s.commit()
        return e.id


async def generate(client, org) -> dict:
    r = await client.post("/api/v1/payroll/runs", headers=H(org), json=SEPT)
    assert r.status_code == 201, r.text
    g = await client.post(f"/api/v1/payroll/runs/{r.json()['id']}/generate", headers=H(org))
    assert g.status_code == 200, g.text
    return r.json()["id"]


def H(org) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(org['user']))}"}


async def payslip(engine, run_id, employee_id) -> Payslip | None:
    async with AsyncSession(engine) as s:
        return (await s.execute(select(Payslip).where(
            Payslip.payroll_run_id == uuid.UUID(run_id), Payslip.employee_id == employee_id))).scalar_one_or_none()


async def settings(engine, org, **values):
    async with AsyncSession(engine) as s:
        s.add(PayrollSettings(tenant_id=org["org"], **values))
        await s.commit()


class TestTheCliff:
    async def test_one_attendance_record_does_not_cut_pay_to_a_fraction(self, client, engine, org):
        """THE C-7 bug: no data = full pay, one PRESENT record = ~1/22."""
        emp = await employee(engine, org)
        async with AsyncSession(engine) as s:
            s.add(AttendanceRecord(tenant_id=org["org"], employee_id=emp, date=date(2026, 9, 1), status=AttendanceStatus.PRESENT))
            await s.commit()
        run = await generate(client, org)
        assert (await payslip(engine, run, emp)).gross_salary == Decimal("100000.00")


class TestHolidaysAndWorkWeek:
    async def test_a_public_holiday_is_not_docked(self, client, engine, org):
        await settings(engine, org, proration_method=WorkingDaysMethod.WORKING_DAYS)
        emp = await employee(engine, org)
        async with AsyncSession(engine) as s:
            s.add(Holiday(tenant_id=org["org"], name="Holiday", date=date(2026, 9, 14)))
            for d in range(1, 31):
                day = date(2026, 9, d)
                if day.weekday() < 5 and day != date(2026, 9, 14):
                    s.add(AttendanceRecord(tenant_id=org["org"], employee_id=emp, date=day, status=AttendanceStatus.PRESENT))
            await s.commit()
        run = await generate(client, org)
        slip = await payslip(engine, run, emp)
        assert slip.gross_salary == Decimal("100000.00")
        assert slip.working_days == 21

    async def test_the_organisations_six_day_week_is_used(self, client, engine, org):
        await settings(engine, org, proration_method=WorkingDaysMethod.WORKING_DAYS)
        async with AsyncSession(engine) as s:
            (await s.get(Organization, org["org"])).settings = {"work_days": ["mon", "tue", "wed", "thu", "fri", "sat"]}
            await s.commit()
        emp = await employee(engine, org)
        async with AsyncSession(engine) as s:
            s.add(AttendanceRecord(tenant_id=org["org"], employee_id=emp, date=date(2026, 9, 12), status=AttendanceStatus.ABSENT))
            await s.commit()
        slip = await payslip(engine, await generate(client, org), emp)
        assert slip.working_days == 26
        assert slip.gross_salary == (Decimal("100000") * 25 / 26).quantize(Decimal("0.01"))


class TestWhoIsPaid:
    async def test_a_deleted_employee_is_not_paid(self, client, engine, org):
        emp = await employee(engine, org, deleted=True)
        assert await payslip(engine, await generate(client, org), emp) is None

    async def test_an_employee_on_leave_still_gets_a_payslip(self, client, engine, org):
        emp = await employee(engine, org, status=EmploymentStatus.ON_LEAVE)
        assert (await payslip(engine, await generate(client, org), emp)).gross_salary == Decimal("100000.00")

    async def test_someone_leaving_mid_month_gets_a_prorated_final_payslip(self, client, engine, org):
        emp = await employee(engine, org, status=EmploymentStatus.RESIGNED, left=date(2026, 9, 15))
        assert (await payslip(engine, await generate(client, org), emp)).gross_salary == Decimal("50000.00")  # 15/30

    async def test_someone_who_left_last_month_is_not_paid_again(self, client, engine, org):
        emp = await employee(engine, org, status=EmploymentStatus.RESIGNED, left=date(2026, 8, 31))
        assert await payslip(engine, await generate(client, org), emp) is None

    async def test_someone_joining_mid_month_is_prorated(self, client, engine, org):
        emp = await employee(engine, org, joined=date(2026, 9, 16))
        assert (await payslip(engine, await generate(client, org), emp)).gross_salary == Decimal("50000.00")


class TestSalaryInEffect:
    async def test_a_raise_dated_next_month_is_not_paid_this_month(self, client, engine, org):
        # BASIC = 50% of the salary record's basic_salary, so the payslip
        # shows WHICH salary record generation used (the fixture's FIXED
        # component would pay 100,000 either way).
        async with AsyncSession(engine) as s:
            comp = (await s.execute(select(SalaryComponent).where(
                SalaryComponent.salary_structure_id == org["structure"]))).scalar_one()
            comp.calculation_type = ComponentCalculation.PERCENTAGE_OF_BASIC
            comp.percentage = Decimal("50")  # column is NUMERIC(6,4): 100 doesn't fit
            await s.commit()
        emp = await employee(engine, org, salary=Decimal("100000"), salary_from=date(2020, 1, 1))
        async with AsyncSession(engine) as s:
            old = (await s.execute(select(EmployeeSalary).where(EmployeeSalary.employee_id == emp))).scalar_one()
            old.is_current = False
            s.add(EmployeeSalary(tenant_id=org["org"], employee_id=emp, salary_structure_id=org["structure"],
                                 basic_salary=Decimal("150000"), effective_from=date(2026, 10, 1), is_current=True))
            await s.commit()
        run = await generate(client, org)
        async with AsyncSession(engine) as s:
            used = (await s.execute(select(Payslip).where(Payslip.payroll_run_id == uuid.UUID(run)))).scalar_one()
        assert used.gross_salary == Decimal("50000.00")  # 50% of 100,000 — not of next month's 150,000


class TestNetFloor:
    async def test_a_loan_installment_larger_than_pay_is_trimmed_to_keep_net_at_zero(self, client, engine, org):
        emp = await employee(engine, org)
        async with AsyncSession(engine, expire_on_commit=False) as s:
            loan = PayrollLoan(tenant_id=org["org"], employee_id=emp, principal_amount=Decimal("300000"), interest_rate=0,
                               number_of_installments=2, installment_amount=Decimal("150000"),
                               remaining_balance=Decimal("300000"), start_date=date(2026, 1, 1), status=LoanStatus.ACTIVE)
            s.add(loan)
            await s.commit()
        run = await generate(client, org)
        slip = await payslip(engine, run, emp)
        assert slip.net_salary == Decimal("0.00")   # used to be -50,000
        async with AsyncSession(engine) as s:
            taken = (await s.execute(select(PayrollItemSettlement.amount).where(
                PayrollItemSettlement.source_id == loan.id))).scalar_one()
        assert taken == Decimal("100000.00")        # the rest is collected in a later run
