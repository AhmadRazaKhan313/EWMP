"""
Tests for audit finding M-7 (part A): ONE auto-close policy for forgotten
check-outs, scheduled, and consistent between attendance and the timer.

Before: the only scheduled job closed timers AND attendance at local
midnight, CREDITING the hours up to it (a 22:00–06:00 night shift was cut at
00:00 and paid 2 hours; a forgotten check-out was paid until midnight). The
shift-aware cutoff that credits nothing existed only as a CLI command, and
it could overwrite a check-out happening at the same moment.

Now `sweep_stale_attendance` is that single policy (Celery beat every 15 min
and `manage.py attendance-cutoff`). Asia/Karachi = UTC+5. Live Postgres via
TEST_DATABASE_URL, same convention as the other *_postgres tests.
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
from app.services.attendance_punches import lock_employee_attendance, open_punch
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


class TestForgottenCheckOut:
    async def test_morning_shift_is_closed_at_midnight_crediting_nothing(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9), open_break_at=pkt(17, 13))
        result = await sweep(engine, pkt(18, 0, 1))  # morning shift -> 00:00 that night

        punch, day, timer, breaks = await state(engine, org["day"])
        assert (result.punches_closed, result.timers_stopped) == (1, 1)
        assert punch.is_forced_checkout and punch.punch_out is None and punch.duration_minutes == 0
        assert day.status == AttendanceStatus.MISSED_PUNCH and day.total_minutes == 0
        # The timer stops at the same cutoff instant and is not credited either.
        assert timer.status == WorkSessionStatus.ENDED
        assert timer.ended_at == pkt(18, 0) and timer.total_minutes == 0
        assert all(b.ended_at is not None for b in breaks)

    async def test_nothing_happens_before_the_cutoff(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        result = await sweep(engine, pkt(17, 23, 59))
        punch, day, timer, _ = await state(engine, org["day"])
        assert result.punches_closed == 0
        assert punch.punch_out is None and not punch.is_forced_checkout
        assert timer.status == WorkSessionStatus.ACTIVE

    async def test_sweeping_twice_changes_nothing_more(self, engine, org):
        await check_in(engine, org, "day", pkt(17, 9))
        await sweep(engine, pkt(18, 0, 5))
        again = await sweep(engine, pkt(18, 0, 30))
        assert (again.punches_closed, again.timers_stopped, again.orphan_timers_stopped) == (0, 0, 0)


class TestNightShift:
    async def test_night_shift_is_not_cut_at_midnight(self, engine, org):
        """THE midnight-policy bug: 22:00–06:00 used to be closed at 00:00."""
        await check_in(engine, org, "night", pkt(17, 22))
        result = await sweep(engine, pkt(18, 0, 30))
        punch, _, timer, _ = await state(engine, org["night"])
        assert result.punches_closed == 0
        assert punch.punch_out is None and timer.status == WorkSessionStatus.ACTIVE

    async def test_forgotten_night_shift_closes_after_its_own_end(self, engine, org):
        await check_in(engine, org, "night", pkt(17, 22))
        await sweep(engine, pkt(18, 9, 1))  # evening/night shift -> 09:00 next morning
        punch, day, timer, _ = await state(engine, org["night"])
        assert punch.is_forced_checkout
        assert day.status == AttendanceStatus.MISSED_PUNCH
        assert timer.ended_at == pkt(18, 9)


class TestTimersWithoutAPunch:
    async def test_timer_with_no_punch_is_stopped_after_the_hard_cap(self, engine, org):
        """The real-data case: a timer running for 402 hours with no punch."""
        async with AsyncSession(engine) as s:
            s.add(WorkSession(tenant_id=org["org"], employee_id=org["noshift"], started_at=pkt(10, 9),
                              status=WorkSessionStatus.ACTIVE))
            await s.commit()
        result = await sweep(engine, pkt(27, 9))
        assert result.orphan_timers_stopped == 1
        async with AsyncSession(engine) as s:
            timer = (await s.execute(select(WorkSession).where(WorkSession.employee_id == org["noshift"]))).scalar_one()
        assert timer.status == WorkSessionStatus.ENDED
        assert timer.ended_at == pkt(10, 9) + timedelta(hours=14) and timer.total_minutes == 0

    async def test_a_young_timer_with_no_punch_is_left_alone(self, engine, org):
        async with AsyncSession(engine) as s:
            s.add(WorkSession(tenant_id=org["org"], employee_id=org["noshift"], started_at=pkt(17, 9),
                              status=WorkSessionStatus.ACTIVE))
            await s.commit()
        assert (await sweep(engine, pkt(17, 20))).orphan_timers_stopped == 0


class TestCheckOutRacingTheSweep:
    async def test_a_real_check_out_at_the_same_moment_is_never_overwritten(self, engine, org):
        """The employee's check-out holds the per-employee lock (as the
        endpoints do) while the sweep reaches the same punch. The sweep must
        wait, see the punch is closed, and leave it alone."""
        punch_id = await check_in(engine, org, "day", pkt(17, 9), with_timer=False)

        async with AsyncSession(engine) as checkout:
            await lock_employee_attendance(checkout, org["day"])
            running = asyncio.create_task(sweep(engine, pkt(18, 0, 30)))
            await asyncio.sleep(1.0)
            assert not running.done(), "the sweep must wait for the employee's check-out"
            punch = await checkout.get(AttendancePunch, punch_id)
            punch.punch_out = pkt(17, 23, 45)
            punch.duration_minutes = 14 * 60 + 45
            await checkout.commit()

        result = await asyncio.wait_for(running, timeout=10)
        async with AsyncSession(engine) as s:
            punch = await s.get(AttendancePunch, punch_id)
        assert result.punches_closed == 0
        assert not punch.is_forced_checkout
        assert punch.punch_out == pkt(17, 23, 45) and punch.duration_minutes == 885


def test_beat_runs_the_sweep_and_not_the_midnight_task():
    from app.workers.celery_app import celery_app

    tasks = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert "attendance.sweep_stale_attendance" in tasks
    assert "work_sessions.auto_close_overnight_sessions" not in tasks
