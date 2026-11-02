"""
Midnight auto-checkout: a forgotten check-out is closed at 12 AM (office clock)
and the hours up to then are CREDITED; overnight-shift employees run to their
shift end. Asia/Karachi = UTC+5, live Postgres via TEST_DATABASE_URL.
"""

import asyncio
import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.attendance import AttendancePunch, AttendanceRecord, AttendanceStatus, Shift
from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.organization import Organization
from app.models.user import User
from app.models.work_session import BreakRecord, WorkSession, WorkSessionStatus
from app.services.attendance_punches import get_open_punch, lock_employee_attendance, open_punch
from app.services.attendance_sync import sweep_stale_attendance

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio


def pkt(day: int, hh: int, mm: int = 0) -> datetime:
    """A wall-clock time in Karachi (Sept 2026) as a UTC instant."""
    return datetime(2026, 9, day, hh, mm, tzinfo=UTC) - timedelta(hours=5)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def org(engine):
    org_id = uuid.uuid4()
    ids = {"org": org_id}
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Sweep Co", slug=f"sweep-{org_id.hex[:8]}",
                           email=f"sweep-{org_id.hex[:8]}@example.com", timezone="Asia/Karachi"))
        await s.flush()
        day = Shift(tenant_id=org_id, name="Day", code=f"D{org_id.hex[:4]}", start_time=time(9, 0),
                    end_time=time(18, 0), weekly_hours=45)
        night = Shift(tenant_id=org_id, name="Night", code=f"N{org_id.hex[:4]}", start_time=time(22, 0),
                      end_time=time(6, 0), weekly_hours=45, is_overnight=True)
        s.add_all([day, night])
        await s.flush()
        for name, shift in (("day", day), ("night", night), ("noshift", None)):
            email = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
            u = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                     first_name=name, last_name="T", is_active=True, is_email_verified=True)
            s.add(u)
            await s.flush()
            e = Employee(tenant_id=org_id, user_id=u.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                         employment_type=EmploymentType.FULL_TIME, employment_status=EmploymentStatus.ACTIVE,
                         date_of_joining=date(2026, 1, 1), default_shift_id=shift.id if shift else None)
            s.add(e)
            await s.flush()
            ids[name] = e.id
            ids[f"{name}_shift"] = shift.id if shift else None
        await s.commit()
    yield ids
    async with AsyncSession(engine) as s:
        sessions = select(WorkSession.id).where(WorkSession.tenant_id == org_id)
        await s.execute(delete(BreakRecord).where(BreakRecord.work_session_id.in_(sessions)))
        for model in (AttendancePunch, AttendanceRecord, WorkSession, Employee, Shift):
            await s.execute(delete(model).where(model.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


async def check_in(engine, org, who, at, with_timer=True, open_break_at=None):
    """Punch in (as both apps do) and start the timer, at a fixed instant."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        punch, _ = await open_punch(s, org["org"], org[who], at=at, shift_id=org[f"{who}_shift"])
        if with_timer:
            ws = WorkSession(tenant_id=org["org"], employee_id=org[who], started_at=at,
                             status=WorkSessionStatus.ON_BREAK if open_break_at else WorkSessionStatus.ACTIVE)
            s.add(ws)
            await s.flush()
            if open_break_at:
                s.add(BreakRecord(tenant_id=org["org"], work_session_id=ws.id, started_at=open_break_at))
        await s.commit()
        return punch.id


async def sweep(engine, now):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await sweep_stale_attendance(s, now=now)
        await s.commit()
        return result


async def state(engine, employee_id):
    async with AsyncSession(engine) as s:
        punch = (await s.execute(select(AttendancePunch).where(AttendancePunch.employee_id == employee_id))).scalar_one()
        day = (await s.execute(select(AttendanceRecord).where(AttendanceRecord.employee_id == employee_id))).scalar_one()
        timer = (await s.execute(select(WorkSession).where(WorkSession.employee_id == employee_id))).scalar_one_or_none()
        breaks = []
        if timer:
            breaks = (await s.execute(select(BreakRecord).where(BreakRecord.work_session_id == timer.id))).scalars().all()
        return punch, day, timer, breaks



class TestMidnightCutoff:
    async def test_day_shift_closed_at_midnight_with_hours_credited(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        result = await sweep(engine, pkt(18, 0, 1))
        punch, day, timer, _ = await state(engine, org["day"])
        assert (result.punches_closed, result.timers_stopped) == (1, 1)
        assert punch.punch_out == pkt(18, 0) and punch.duration_minutes == 15 * 60
        assert day.total_minutes == 15 * 60 and day.status != AttendanceStatus.MISSED_PUNCH
        assert timer.status == WorkSessionStatus.ENDED and timer.ended_at == pkt(18, 0)
        assert timer.total_minutes == 15 * 60

    async def test_breaks_are_not_credited(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        async with AsyncSession(engine, expire_on_commit=False) as s:
            ws = (await s.execute(select(WorkSession).where(WorkSession.employee_id == org["day"]))).scalar_one()
            s.add(BreakRecord(tenant_id=org["org"], work_session_id=ws.id, started_at=pkt(17, 13), ended_at=pkt(17, 14)))
            await s.commit()
        await sweep(engine, pkt(18, 1))
        punch, day, timer, _ = await state(engine, org["day"])
        assert punch.duration_minutes == 14 * 60 and timer.total_minutes == 14 * 60

    async def test_open_break_at_midnight_is_closed_and_excluded(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9), open_break_at=pkt(17, 23))
        await sweep(engine, pkt(18, 1))
        punch, _, timer, breaks = await state(engine, org["day"])
        assert punch.duration_minutes == 14 * 60 and timer.total_minutes == 14 * 60
        assert all(b.ended_at == pkt(18, 0) for b in breaks)

    async def test_nothing_before_midnight(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        result = await sweep(engine, pkt(17, 23, 59))
        punch, _, timer, _ = await state(engine, org["day"])
        assert result.punches_closed == 0 and punch.punch_out is None
        assert timer.status == WorkSessionStatus.ACTIVE

    async def test_no_shift_employee_also_stops_at_midnight(self, engine, org):
        await check_in(engine, org, "noshift", pkt(17, 20))
        await sweep(engine, pkt(18, 0, 5))
        punch, day, _, _ = await state(engine, org["noshift"])
        assert punch.punch_out == pkt(18, 0) and day.total_minutes == 4 * 60

    async def test_night_shift_is_not_cut_at_midnight_but_at_shift_end(self, engine, org):
        await check_in(engine, org, "night", pkt(17, 22))
        r1 = await sweep(engine, pkt(18, 0, 30))
        assert r1.punches_closed == 0
        r2 = await sweep(engine, pkt(18, 6, 1))
        punch, day, timer, _ = await state(engine, org["night"])
        assert r2.punches_closed == 1
        assert punch.punch_out == pkt(18, 6) and day.total_minutes == 8 * 60
        assert timer.ended_at == pkt(18, 6) and timer.total_minutes == 8 * 60

    async def test_orphan_timer_without_punch_stops_at_midnight(self, engine, org):
        async with AsyncSession(engine, expire_on_commit=False) as s:
            s.add(WorkSession(tenant_id=org["org"], employee_id=org["noshift"], started_at=pkt(17, 10),
                              status=WorkSessionStatus.ACTIVE))
            await s.commit()
        result = await sweep(engine, pkt(18, 0, 5))
        async with AsyncSession(engine) as s:
            ws = (await s.execute(select(WorkSession).where(WorkSession.employee_id == org["noshift"]))).scalar_one()
        assert result.orphan_timers_stopped == 1
        assert ws.ended_at == pkt(18, 0) and ws.total_minutes == 14 * 60

    async def test_idempotent(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        await sweep(engine, pkt(18, 1))
        again = await sweep(engine, pkt(18, 2))
        assert (again.punches_closed, again.timers_stopped) == (0, 0)

    async def test_employee_scope_only_touches_that_employee(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        await check_in(engine, org, "noshift", pkt(17, 10))
        async with AsyncSession(engine, expire_on_commit=False) as s:
            res = await sweep_stale_attendance(s, now=pkt(18, 1), employee_id=org["day"])
            await s.commit()
        assert res.punches_closed == 1
        punch, _, timer, _ = await state(engine, org["noshift"])
        assert punch.punch_out is None and timer.status == WorkSessionStatus.ACTIVE


class TestLazyEnforcement:
    async def test_get_open_punch_closes_a_stale_punch_without_any_scheduler(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        async with AsyncSession(engine, expire_on_commit=False) as s:
            assert await get_open_punch(s, org["org"], org["day"], now=pkt(18, 10)) is None
            await s.commit()
        punch, day, timer, _ = await state(engine, org["day"])
        assert punch.punch_out == pkt(18, 0) and day.total_minutes == 15 * 60
        assert timer.status == WorkSessionStatus.ENDED and timer.ended_at == pkt(18, 0)

    async def test_get_open_punch_leaves_a_fresh_punch_alone(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        async with AsyncSession(engine, expire_on_commit=False) as s:
            assert await get_open_punch(s, org["org"], org["day"], now=pkt(17, 15)) is not None

    async def test_new_day_check_in_after_a_forgotten_one(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        async with AsyncSession(engine, expire_on_commit=False) as s:
            assert await get_open_punch(s, org["org"], org["day"], now=pkt(18, 9)) is None
            punch, _ = await open_punch(s, org["org"], org["day"], at=pkt(18, 9), shift_id=org["day_shift"])
            await s.commit()
        async with AsyncSession(engine) as s:
            punches = (await s.execute(select(AttendancePunch).where(AttendancePunch.employee_id == org["day"]).order_by(AttendancePunch.punch_in))).scalars().all()
        assert len(punches) == 2 and punches[0].punch_out == pkt(18, 0) and punches[1].punch_out is None
