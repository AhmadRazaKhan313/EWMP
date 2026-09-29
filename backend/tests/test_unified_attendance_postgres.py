"""
Regression tests for audit finding C-4: the web and the desktop app wrote
attendance through two different mechanisms and disagreed.

  * Web check-in wrote AttendanceRecord.check_in directly (no punch); the
    desktop app worked through AttendancePunch. So: web in → desktop out left
    the day open forever; desktop in → web out left the punch open; after any
    desktop session the web refused to check in ("Already checked in").
  * Desktop end-of-session never passed break minutes, so attendance counted
    breaks as work.
  * The desktop path never computed lateness at all.

All of it now goes through punches. Real HTTP stack against a live Postgres
(TEST_DATABASE_URL, same convention as the other *_postgres tests), with the
clock pinned in both the web and the desktop routers.
"""

import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.attendance import AttendancePunch, AttendanceRecord, AttendanceStatus, Shift
from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.organization import Organization
from app.models.user import User
from app.models.work_session import BreakRecord, WorkSession, WorkSessionStatus

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 17, 4, 30, tzinfo=UTC)  # 09:30 in Asia/Karachi


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


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


@pytest.fixture
def clock(monkeypatch):
    """Pin datetime.now() in the web and desktop routers; call clock(t)."""
    import app.api.v1.hrms.attendance as web
    import app.api.v1.hrms.work_sessions as desktop

    def _set(instant: datetime):
        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant if tz is None else instant.astimezone(tz)
        for module in (web, desktop):
            monkeypatch.setattr(module, "datetime", _Frozen)
    return _set


@pytest_asyncio.fixture
async def emp(engine):
    """One employee in an Asia/Karachi org, 09:00–18:00 shift, 10-min grace."""
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="C4 Org", slug=f"c4-{org_id.hex[:8]}",
                           email=f"c4-{org_id.hex[:8]}@example.com", timezone="Asia/Karachi"))
        await s.flush()
        shift = Shift(tenant_id=org_id, name="Day", code=f"D{org_id.hex[:4]}", start_time=time(9, 0),
                      end_time=time(18, 0), weekly_hours=45, late_grace_minutes=10)
        s.add(shift)
        email = f"c4-{uuid.uuid4().hex[:8]}@example.com"
        user = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                    first_name="C4", last_name="T", is_active=True, is_email_verified=True)
        s.add(user)
        await s.flush()
        e = Employee(tenant_id=org_id, user_id=user.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                     employment_type=EmploymentType.FULL_TIME, employment_status=EmploymentStatus.ACTIVE,
                     date_of_joining=date(2026, 1, 1), default_shift_id=shift.id)
        s.add(e)
        await s.flush()
        ids = {"org": org_id, "user": user.id, "emp": e.id}
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


def H(emp) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(emp['user']))}"}


async def web_in(client, emp):
    return await client.post("/api/v1/attendance/check-in", json={"method": "manual"}, headers=H(emp))


async def web_out(client, emp):
    return await client.post("/api/v1/attendance/check-out", json={}, headers=H(emp))


async def desktop_start(client, emp):
    r = await client.post("/api/v1/work-sessions/start", headers=H(emp))
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def desktop_end(client, emp, session_id):
    return await client.post(f"/api/v1/work-sessions/{session_id}/end", headers=H(emp))


async def active_session(client, emp):
    return (await client.get("/api/v1/work-sessions/me/active", headers=H(emp))).json()


async def state(engine, emp):
    async with AsyncSession(engine) as s:
        record = (await s.execute(select(AttendanceRecord).where(AttendanceRecord.employee_id == emp["emp"]))).scalar_one()
        punches = (await s.execute(
            select(AttendancePunch).where(AttendancePunch.employee_id == emp["emp"]).order_by(AttendancePunch.punch_in)
        )).scalars().all()
        open_count = sum(1 for p in punches if p.punch_out is None and not p.is_forced_checkout)
        return record, punches, open_count


class TestMixingApps:
    async def test_web_in_then_desktop_out_closes_the_day(self, client, engine, emp, clock):
        clock(at(0))
        assert (await web_in(client, emp)).status_code == 201
        session = await active_session(client, emp)
        assert session is not None, "web check-in must start the desktop timer"

        clock(at(240))
        assert (await desktop_end(client, emp, session["id"])).status_code == 200
        record, punches, open_count = await state(engine, emp)
        assert open_count == 0
        assert record.check_out == at(240)
        assert record.total_minutes == 240

    async def test_desktop_in_then_web_out_closes_the_punch(self, client, engine, emp, clock):
        clock(at(0))
        await desktop_start(client, emp)
        clock(at(120))
        r = await web_out(client, emp)
        assert r.status_code == 200, r.text
        assert r.json()["total_minutes"] == 120
        _, _, open_count = await state(engine, emp)
        assert open_count == 0
        assert await active_session(client, emp) is None

    async def test_web_check_in_works_after_a_desktop_session(self, client, engine, emp, clock):
        """The old web code refused: 'Already checked in for today'."""
        clock(at(0))
        sid = await desktop_start(client, emp)
        clock(at(180))
        await desktop_end(client, emp, sid)

        clock(at(240))
        r = await web_in(client, emp)
        assert r.status_code == 201, r.text
        clock(at(300))
        await web_out(client, emp)
        record, punches, _ = await state(engine, emp)
        assert len(punches) == 2
        assert record.total_minutes == 180 + 60
        assert record.check_in == at(0)

    async def test_two_web_check_ins_without_check_out_are_refused(self, client, emp, clock):
        clock(at(0))
        assert (await web_in(client, emp)).status_code == 201
        assert (await web_in(client, emp)).status_code == 400

    async def test_web_check_out_without_check_in_is_refused(self, client, emp, clock):
        clock(at(0))
        assert (await web_out(client, emp)).status_code == 400


class TestBreaks:
    async def test_desktop_breaks_are_not_counted_as_attendance(self, client, engine, emp, clock):
        clock(at(0))
        sid = await desktop_start(client, emp)
        clock(at(60))
        assert (await client.post(f"/api/v1/work-sessions/{sid}/break/start", json={}, headers=H(emp))).status_code in (200, 201)
        clock(at(90))
        assert (await client.post(f"/api/v1/work-sessions/{sid}/break/end", headers=H(emp))).status_code == 200
        clock(at(240))
        await desktop_end(client, emp, sid)

        record, punches, _ = await state(engine, emp)
        assert punches[0].duration_minutes == 210  # 240 wall − 30 break
        assert record.total_minutes == 210

    async def test_web_check_out_also_excludes_desktop_breaks(self, client, engine, emp, clock):
        clock(at(0))
        sid = await desktop_start(client, emp)
        clock(at(60))
        await client.post(f"/api/v1/work-sessions/{sid}/break/start", json={}, headers=H(emp))
        clock(at(75))
        await client.post(f"/api/v1/work-sessions/{sid}/break/end", headers=H(emp))
        clock(at(120))
        r = await web_out(client, emp)
        assert r.json()["total_minutes"] == 105


class TestLatenessIsTheSameEverywhere:
    async def test_desktop_check_in_is_marked_late(self, client, engine, emp, clock):
        clock(at(0))  # 09:30 in Karachi; shift 09:00 + 10 min grace
        await desktop_start(client, emp)
        record, _, _ = await state(engine, emp)
        assert record.status == AttendanceStatus.LATE
        assert record.late_minutes == 20

    async def test_web_check_in_is_marked_late(self, client, engine, emp, clock):
        clock(at(0))
        r = await web_in(client, emp)
        assert (r.json()["status"], r.json()["late_minutes"]) == ("late", 20)

    async def test_on_time_is_present(self, client, engine, emp, clock):
        clock(at(-25))  # 09:05
        await desktop_start(client, emp)
        record, _, _ = await state(engine, emp)
        assert (record.status, record.late_minutes) == (AttendanceStatus.PRESENT, 0)


class TestLeftoverTimer:
    async def test_web_check_out_stops_a_timer_that_has_no_punch(self, client, engine, emp, clock):
        """Data left by the old code: a running timer with no attendance
        punch. Check-out must stop it, not answer 400 forever."""
        async with AsyncSession(engine) as s:
            s.add(WorkSession(tenant_id=emp["org"], employee_id=emp["emp"], started_at=at(0),
                              status=WorkSessionStatus.ACTIVE))
            await s.commit()
        clock(at(60))
        r = await web_out(client, emp)
        assert r.status_code == 200, r.text
        assert await active_session(client, emp) is None
        async with AsyncSession(engine) as s:
            assert (await s.execute(select(func.count()).select_from(AttendancePunch)
                                    .where(AttendancePunch.employee_id == emp["emp"]))).scalar_one() == 0
