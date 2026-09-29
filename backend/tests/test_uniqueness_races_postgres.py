"""
Regression tests for audit finding H-2: nothing in the database stopped a
second row being created for things that must be unique, and a second row
turned every later read into HTTP 500 (MultipleResultsFound).

These fire requests truly CONCURRENTLY (asyncio.gather over the real HTTP
stack, each request with its own database connection), so the check-then-
insert races actually happen — exactly like a double-click or the web and
desktop apps acting at the same moment. Plus direct database checks that
the new unique indexes are the backstop.

Live Postgres via TEST_DATABASE_URL (same convention as the other
*_postgres tests); migrations must be applied.
"""

import asyncio
import os
import uuid
from datetime import date, time

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.attendance import (
    AttendancePunch, AttendanceRecord, AttendanceStatus, LeaveBalance, LeaveRequest, LeaveType, Shift,
)
from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.organization import Organization
from app.models.payroll import PayrollRun, Payslip
from app.models.rbac import Permission, Role
from app.models.user import User
from app.models.work_session import WorkSession, WorkSessionStatus

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

PERMS = ["leave.apply", "roles.manage", "payroll.process"]


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL, pool_size=10, max_overflow=10)
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
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Races", slug=f"race-{org_id.hex[:8]}",
                           email=f"race-{org_id.hex[:8]}@example.com", timezone="Asia/Karachi"))
        await s.flush()
        role = Role(organization_id=org_id, name="Staff", slug="staff",
                    permissions=[await _permission(s, c) for c in PERMS])
        shift = Shift(tenant_id=org_id, name="Day", code=f"D{org_id.hex[:4]}", start_time=time(9, 0),
                      end_time=time(18, 0), weekly_hours=45, late_grace_minutes=10)
        leave_type = LeaveType(tenant_id=org_id, name="Annual", code="AL", days_per_year=14,
                               max_carry_forward_days=0, min_days_per_request=0.5)
        s.add_all([role, shift, leave_type])
        await s.flush()
        email = f"race-{uuid.uuid4().hex[:8]}@example.com"
        user = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                    first_name="R", last_name="T", is_active=True, is_email_verified=True, roles=[role])
        s.add(user)
        await s.flush()
        emp = Employee(tenant_id=org_id, user_id=user.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                       employment_type=EmploymentType.FULL_TIME, employment_status=EmploymentStatus.ACTIVE,
                       date_of_joining=date(2026, 1, 1), default_shift_id=shift.id)
        s.add(emp)
        await s.flush()
        ids = {"org": org_id, "user": user.id, "emp": emp.id, "leave_type": leave_type.id}
        await s.commit()
    yield ids
    async with AsyncSession(engine) as s:
        for model in (Payslip, PayrollRun, LeaveRequest, LeaveBalance, AttendancePunch, AttendanceRecord,
                      WorkSession, Employee, LeaveType, Shift):
            await s.execute(delete(model).where(model.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


def H(org) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(org['user']))}"}


async def _count(engine, stmt) -> int:
    async with AsyncSession(engine) as s:
        return (await s.execute(stmt)).scalar_one()


def _no_500(responses):
    assert all(r.status_code < 500 for r in responses), [(r.status_code, r.text[:200]) for r in responses]


class TestConcurrentTimerAndCheckIn:
    async def test_double_clicked_desktop_start_makes_one_timer(self, client, engine, org):
        rs = await asyncio.gather(*[client.post("/api/v1/work-sessions/start", headers=H(org)) for _ in range(5)])
        _no_500(rs)
        assert len({r.json()["id"] for r in rs}) == 1
        assert await _count(engine, select(func.count()).select_from(WorkSession).where(
            WorkSession.employee_id == org["emp"], WorkSession.status != WorkSessionStatus.ENDED)) == 1
        # …and reading it afterwards works (it used to be a 500 forever).
        assert (await client.get("/api/v1/work-sessions/me/active", headers=H(org))).status_code == 200

    async def test_double_clicked_web_check_in_makes_one_punch_and_one_day(self, client, engine, org):
        rs = await asyncio.gather(*[
            client.post("/api/v1/attendance/check-in", json={"method": "manual"}, headers=H(org)) for _ in range(5)
        ])
        _no_500(rs)
        assert await _count(engine, select(func.count()).select_from(AttendancePunch).where(
            AttendancePunch.employee_id == org["emp"], AttendancePunch.punch_out.is_(None))) == 1
        assert await _count(engine, select(func.count()).select_from(AttendanceRecord).where(
            AttendanceRecord.employee_id == org["emp"])) == 1

    async def test_web_and_desktop_at_the_same_moment(self, client, engine, org):
        rs = await asyncio.gather(
            client.post("/api/v1/attendance/check-in", json={"method": "manual"}, headers=H(org)),
            client.post("/api/v1/work-sessions/start", headers=H(org)),
            client.post("/api/v1/attendance/check-in", json={"method": "manual"}, headers=H(org)),
            client.post("/api/v1/work-sessions/start", headers=H(org)),
        )
        _no_500(rs)
        assert await _count(engine, select(func.count()).select_from(AttendancePunch).where(
            AttendancePunch.employee_id == org["emp"], AttendancePunch.punch_out.is_(None))) == 1
        assert await _count(engine, select(func.count()).select_from(WorkSession).where(
            WorkSession.employee_id == org["emp"], WorkSession.status != WorkSessionStatus.ENDED)) == 1
        assert await _count(engine, select(func.count()).select_from(AttendanceRecord).where(
            AttendanceRecord.employee_id == org["emp"])) == 1


class TestConcurrentLeaveRequests:
    async def test_simultaneous_requests_share_one_balance(self, client, engine, org):
        days = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]
        rs = await asyncio.gather(*[
            client.post("/api/v1/leave/requests", headers=H(org), json={
                "leave_type_id": str(org["leave_type"]), "start_date": d, "end_date": d, "reason": "x"})
            for d in days
        ])
        _no_500(rs)
        assert all(r.status_code == 201 for r in rs), [r.text for r in rs]
        async with AsyncSession(engine) as s:
            balances = (await s.execute(select(LeaveBalance).where(LeaveBalance.employee_id == org["emp"]))).scalars().all()
        assert len(balances) == 1
        assert balances[0].pending_days == 4


class TestConcurrentRoleCreate:
    async def test_same_name_twice_is_one_role_and_a_409(self, client, engine, org):
        rs = await asyncio.gather(*[
            client.post("/api/v1/roles", headers=H(org), json={"name": "Shift Lead"}) for _ in range(4)
        ])
        _no_500(rs)
        assert sorted(r.status_code for r in rs) == [201, 409, 409, 409]
        assert await _count(engine, select(func.count()).select_from(Role).where(
            Role.organization_id == org["org"], Role.slug == "shift-lead")) == 1


class TestConcurrentPayrollGenerate:
    async def test_generate_waits_for_a_run_that_is_being_generated(self, client, engine, org):
        """Deterministic version of "two Generate clicks": another connection
        holds the run's row lock (as a generation in progress would). The
        endpoint must WAIT for it — then see the run is no longer DRAFT and
        stop — instead of generating a second set of payslips alongside."""
        from sqlalchemy import update

        async with AsyncSession(engine, expire_on_commit=False) as s:
            run = PayrollRun(tenant_id=org["org"], name="Oct", period_start=date(2026, 10, 1),
                             period_end=date(2026, 10, 31), pay_date=date(2026, 10, 31),
                             total_gross=0, total_deductions=0, total_net=0)
            s.add(run)
            await s.commit()

        async with AsyncSession(engine) as holder:
            await holder.execute(select(PayrollRun).where(PayrollRun.id == run.id).with_for_update())
            request = asyncio.create_task(
                client.post(f"/api/v1/payroll/runs/{run.id}/generate", headers=H(org))
            )
            await asyncio.sleep(1.0)
            assert not request.done(), "generate must wait for the run's row lock"
            # The "other" generation finishes: the run leaves DRAFT.
            from app.models.payroll import PayrollRunStatus
            await holder.execute(update(PayrollRun).where(PayrollRun.id == run.id)
                                 .values(status=PayrollRunStatus.REVIEW))
            await holder.commit()

        response = await asyncio.wait_for(request, timeout=10)
        assert response.status_code == 400, response.text


class TestDatabaseBackstops:
    async def test_second_live_attendance_row_for_a_day_is_rejected(self, engine, org):
        async with AsyncSession(engine) as s:
            s.add(AttendanceRecord(tenant_id=org["org"], employee_id=org["emp"], date=date(2026, 9, 1),
                                   status=AttendanceStatus.PRESENT))
            await s.commit()
        async with AsyncSession(engine) as s:
            s.add(AttendanceRecord(tenant_id=org["org"], employee_id=org["emp"], date=date(2026, 9, 1),
                                   status=AttendanceStatus.PRESENT))
            with pytest.raises(IntegrityError):
                await s.commit()

    async def test_soft_deleted_attendance_row_does_not_block(self, engine, org):
        async with AsyncSession(engine) as s:
            old = AttendanceRecord(tenant_id=org["org"], employee_id=org["emp"], date=date(2026, 9, 2),
                                   status=AttendanceStatus.PRESENT)
            s.add(old)
            await s.flush()
            old.soft_delete()
            s.add(AttendanceRecord(tenant_id=org["org"], employee_id=org["emp"], date=date(2026, 9, 2),
                                   status=AttendanceStatus.PRESENT))
            await s.commit()

    async def test_second_running_timer_is_rejected(self, engine, org):
        from datetime import UTC, datetime
        async with AsyncSession(engine) as s:
            s.add(WorkSession(tenant_id=org["org"], employee_id=org["emp"], started_at=datetime.now(UTC),
                              status=WorkSessionStatus.ACTIVE))
            await s.commit()
        async with AsyncSession(engine) as s:
            s.add(WorkSession(tenant_id=org["org"], employee_id=org["emp"], started_at=datetime.now(UTC),
                              status=WorkSessionStatus.ON_BREAK))
            with pytest.raises(IntegrityError):
                await s.commit()

    async def test_second_payslip_for_the_same_run_is_rejected(self, engine, org):
        async with AsyncSession(engine, expire_on_commit=False) as s:
            run = PayrollRun(tenant_id=org["org"], name="Nov", period_start=date(2026, 11, 1),
                             period_end=date(2026, 11, 30), pay_date=date(2026, 11, 30),
                             total_gross=0, total_deductions=0, total_net=0)
            s.add(run)
            await s.flush()
            slip = dict(tenant_id=org["org"], payroll_run_id=run.id, employee_id=org["emp"], working_days=22,
                        present_days=22, absent_days=0, leave_days=0, overtime_hours=0,
                        gross_salary=1, total_deductions=0, net_salary=1)
            s.add(Payslip(**slip))
            await s.commit()
        async with AsyncSession(engine) as s:
            s.add(Payslip(**slip))
            with pytest.raises(IntegrityError):
                await s.commit()
