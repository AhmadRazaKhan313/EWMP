"""
Regression tests for audit finding C-6: payroll run side effects could not
be undone, and a reopened run was a dead end.

Before: generating a run immediately cut loan/advance balances and marked
bonuses, arrears, commissions PAID and reimbursements INCLUDED — with no
record of which run did it. Reversing gave nothing back; reopening led to a
status nothing accepted; two runs over the same period paid twice.

Now generation only writes a settlement ledger; finalize applies it; reverse
and reopen undo it exactly; overlapping runs are refused. Real HTTP stack,
live Postgres via TEST_DATABASE_URL (same convention as the other
*_postgres tests).
"""

import os
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.organization import Organization
from app.models.payroll import (
    BonusStatus, BonusType, ComponentCalculation, ComponentType, EmployeeSalary, LoanStatus,
    PaymentBatch, PayrollApproval, PayrollAuditLog, PayrollBonus, PayrollItemSettlement, PayrollLoan,
    PayrollRun, PayrollSettings, PayrollSnapshot, Payslip, PayslipLine, SalaryComponent, SalaryStructure,
)
from app.models.rbac import Permission, Role
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

PERMS = ["payroll.process", "payroll.approve", "payroll.finalize", "payroll.reopen", "payroll.reverse"]
SEPT = {"name": "September", "period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"}
OCT = {"name": "October", "period_start": "2026-10-01", "period_end": "2026-10-31", "pay_date": "2026-10-31"}


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


async def _permission(s, codename):
    perm = (await s.execute(select(Permission).where(Permission.codename == codename))).scalar_one_or_none()
    if perm is None:
        resource, action = codename.split(".", 1)
        perm = Permission(resource=resource, action=action, codename=codename, label=codename, category=resource)
        s.add(perm)
        await s.flush()
    return perm


@pytest_asyncio.fixture
async def org(engine):
    """One employee on 100,000 basic, a loan (installment 1,000) and an
    approved 5,000 bonus spanning September–October."""
    org_id = uuid.uuid4()
    ids = {"org": org_id}
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Pay Co", slug=f"pay-{org_id.hex[:8]}", email=f"pay-{org_id.hex[:8]}@example.com"))
        await s.flush()
        role = Role(organization_id=org_id, name="Payroll", slug="payroll", permissions=[await _permission(s, c) for c in PERMS])
        s.add(role)
        email = f"pay-{uuid.uuid4().hex[:8]}@example.com"
        user = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                    first_name="Pay", last_name="Admin", is_active=True, is_email_verified=True, roles=[role])
        # A second person to approve: whoever generates a run can't approve it (audit H-10).
        approver_email = f"approver-{uuid.uuid4().hex[:8]}@example.com"
        approver = User(organization_id=org_id, email=approver_email, email_normalized=approver_email,
                        password_hash="x", first_name="Appr", last_name="Over", is_active=True,
                        is_email_verified=True, roles=[role])
        s.add_all([user, approver])
        await s.flush()
        emp_user = User(organization_id=org_id, email=f"e-{email}", email_normalized=f"e-{email}", password_hash="x",
                        first_name="E", last_name="T", is_active=True, is_email_verified=True)
        s.add(emp_user)
        await s.flush()
        emp = Employee(tenant_id=org_id, user_id=emp_user.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                       employment_type=EmploymentType.FULL_TIME, employment_status=EmploymentStatus.ACTIVE,
                       date_of_joining=date(2020, 1, 1))
        s.add(emp)
        structure = SalaryStructure(tenant_id=org_id, name="Std", code=f"STD-{uuid.uuid4().hex[:6]}", is_active=True)
        s.add(structure)
        await s.flush()
        s.add(SalaryComponent(tenant_id=org_id, salary_structure_id=structure.id, name="Basic", code="BASIC",
                              component_type=ComponentType.EARNING, calculation_type=ComponentCalculation.FIXED,
                              amount=Decimal("100000"), display_order=1))
        s.add(EmployeeSalary(tenant_id=org_id, employee_id=emp.id, salary_structure_id=structure.id,
                             basic_salary=Decimal("100000"), effective_from=date(2020, 1, 1), is_current=True))
        loan = PayrollLoan(tenant_id=org_id, employee_id=emp.id, principal_amount=Decimal("12000"), interest_rate=0,
                           number_of_installments=12, installment_amount=Decimal("1000"),
                           remaining_balance=Decimal("12000"), start_date=date(2026, 1, 1), status=LoanStatus.ACTIVE)
        bonus = PayrollBonus(tenant_id=org_id, employee_id=emp.id, bonus_type=BonusType.FESTIVAL, name="Festival",
                             amount=Decimal("5000"), is_taxable=True, target_period_start=date(2026, 9, 1),
                             target_period_end=date(2026, 10, 31), status=BonusStatus.APPROVED)
        s.add_all([loan, bonus])
        await s.flush()
        ids.update(user=user.id, approver=approver.id, emp=emp.id, loan=loan.id, bonus=bonus.id, structure=structure.id)
        await s.commit()
    yield ids
    async with AsyncSession(engine) as s:
        for model in (PayrollItemSettlement, PayslipLine, PaymentBatch, Payslip, PayrollApproval, PayrollSnapshot,
                      PayrollAuditLog, PayrollRun, PayrollBonus, PayrollLoan, EmployeeSalary, SalaryComponent,
                      SalaryStructure, PayrollSettings, Employee):
            await s.execute(delete(model).where(model.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


def H(org, who="user") -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(org[who]))}"}


async def new_run(client, org, period=SEPT):
    r = await client.post("/api/v1/payroll/runs", headers=H(org), json=period)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def step(client, org, run_id, action, body=None, expect=200):
    who = "approver" if action == "approve" else "user"
    r = await client.post(f"/api/v1/payroll/runs/{run_id}/{action}", headers=H(org, who), json=body or {})
    assert r.status_code == expect, f"{action}: {r.status_code} {r.text}"
    return r


async def through_finalize(client, org, run_id):
    await step(client, org, run_id, "generate")
    await step(client, org, run_id, "approve", {"decision": "approved"})
    await step(client, org, run_id, "finalize")


async def sources(engine, org):
    async with AsyncSession(engine) as s:
        loan = await s.get(PayrollLoan, org["loan"])
        bonus = await s.get(PayrollBonus, org["bonus"])
        return loan.remaining_balance, loan.status, bonus.status


async def net_of(engine, run_id):
    async with AsyncSession(engine) as s:
        return (await s.execute(select(Payslip.net_salary).where(Payslip.payroll_run_id == uuid.UUID(run_id)))).scalar_one()


class TestGenerateThenFinalize:
    async def test_generation_touches_nothing_finalize_applies(self, client, engine, org):
        run = await new_run(client, org)
        await step(client, org, run, "generate")
        assert await sources(engine, org) == (Decimal("12000"), LoanStatus.ACTIVE, BonusStatus.APPROVED)
        assert await net_of(engine, run) == Decimal("104000.00")  # 100k + 5k bonus − 1k loan

        await step(client, org, run, "approve", {"decision": "approved"})
        await step(client, org, run, "finalize")
        assert await sources(engine, org) == (Decimal("11000"), LoanStatus.ACTIVE, BonusStatus.PAID)


class TestReverse:
    async def test_reversing_a_finalized_run_gives_everything_back(self, client, engine, org):
        run = await new_run(client, org)
        await through_finalize(client, org, run)
        await step(client, org, run, "reverse", {"reason": "wrong basic salary"})
        assert await sources(engine, org) == (Decimal("12000"), LoanStatus.ACTIVE, BonusStatus.APPROVED)

    async def test_the_corrected_run_gets_the_bonus_and_the_loan_again(self, client, engine, org):
        run = await new_run(client, org)
        await through_finalize(client, org, run)
        await step(client, org, run, "reverse", {"reason": "redo"})
        again = await new_run(client, org)  # same period is free again
        await through_finalize(client, org, again)
        assert await net_of(engine, again) == Decimal("104000.00")
        assert await sources(engine, org) == (Decimal("11000"), LoanStatus.ACTIVE, BonusStatus.PAID)


class TestReopen:
    async def test_reopen_regenerate_and_finalize_again_charges_once(self, client, engine, org):
        run = await new_run(client, org)
        await through_finalize(client, org, run)
        await step(client, org, run, "reopen", {"reason": "late overtime"})
        assert await sources(engine, org) == (Decimal("12000"), LoanStatus.ACTIVE, BonusStatus.APPROVED)

        await through_finalize(client, org, run)  # used to be impossible: 400 from generate
        assert await net_of(engine, run) == Decimal("104000.00")
        assert await sources(engine, org) == (Decimal("11000"), LoanStatus.ACTIVE, BonusStatus.PAID)

    async def test_reopen_needs_fresh_approval(self, client, engine, org):
        run = await new_run(client, org)
        await through_finalize(client, org, run)
        await step(client, org, run, "reopen", {"reason": "fix"})
        async with AsyncSession(engine) as s:
            assert (await s.execute(select(func.count()).select_from(PayrollApproval).where(
                PayrollApproval.payroll_run_id == uuid.UUID(run)))).scalar_one() == 0
        await step(client, org, run, "generate")
        await step(client, org, run, "finalize", expect=400)  # not APPROVED yet

    async def test_reopen_is_refused_once_a_payment_batch_exists(self, client, engine, org):
        run = await new_run(client, org)
        await through_finalize(client, org, run)
        async with AsyncSession(engine) as s:
            s.add(PaymentBatch(tenant_id=org["org"], payroll_run_id=uuid.UUID(run), total_amount=1, created_by_id=org["user"]))
            await s.commit()
        await step(client, org, run, "reopen", {"reason": "too late"}, expect=409)
        assert await sources(engine, org) == (Decimal("11000"), LoanStatus.ACTIVE, BonusStatus.PAID)


class TestTwoOpenRuns:
    async def test_second_open_run_does_not_take_the_same_money(self, client, engine, org):
        async with AsyncSession(engine) as s:
            loan = await s.get(PayrollLoan, org["loan"])
            loan.remaining_balance = Decimal("1500")
            await s.commit()
        sept, octo = await new_run(client, org, SEPT), await new_run(client, org, OCT)
        await step(client, org, sept, "generate")
        await step(client, org, octo, "generate")
        assert await net_of(engine, sept) == Decimal("104000.00")   # 1,000 loan + 5,000 bonus
        assert await net_of(engine, octo) == Decimal("99500.00")    # only the 500 left, no bonus again


class TestNoOverlappingRuns:
    async def test_a_second_run_over_the_same_days_is_refused(self, client, org):
        await new_run(client, org, SEPT)
        r = await client.post("/api/v1/payroll/runs", headers=H(org), json={**SEPT, "name": "Sept again",
                                                                             "period_start": "2026-09-15", "period_end": "2026-10-14"})
        assert r.status_code == 409, r.text

    async def test_a_reversed_run_frees_its_period(self, client, org):
        run = await new_run(client, org, SEPT)
        await step(client, org, run, "reverse", {"reason": "created by mistake"})
        await new_run(client, org, SEPT)

    async def test_editing_a_draft_into_another_runs_period_is_refused(self, client, org):
        await new_run(client, org, SEPT)
        octo = await new_run(client, org, OCT)
        r = await client.patch(f"/api/v1/payroll/runs/{octo}", headers=H(org), json={"period_start": "2026-09-20"})
        assert r.status_code == 409, r.text

    async def test_end_before_start_is_rejected(self, client, org):
        r = await client.post("/api/v1/payroll/runs", headers=H(org), json={**SEPT, "period_end": "2026-08-01"})
        assert r.status_code == 400


class TestFinalizeIsAllOrNothing:
    async def test_a_loan_changed_after_generation_stops_finalize_and_nothing_is_applied(self, client, engine, org):
        run = await new_run(client, org)
        await step(client, org, run, "generate")
        await step(client, org, run, "approve", {"decision": "approved"})
        async with AsyncSession(engine) as s:
            loan = await s.get(PayrollLoan, org["loan"])
            loan.status = LoanStatus.CANCELLED
            await s.commit()
        await step(client, org, run, "finalize", expect=409)
        _, _, bonus_status = await sources(engine, org)
        assert bonus_status == BonusStatus.APPROVED  # the bonus was not half-applied
