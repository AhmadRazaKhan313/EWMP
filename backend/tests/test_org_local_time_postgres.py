"""
Regression tests for audit finding H-1: wall-clock questions ("which day is
it", "is this check-in late", "when does this shift end") were answered in
UTC instead of the organisation's timezone.

Part 1 is pure (no database): the app.core.timezones helpers and the cutoff
math. Part 2 goes through the real HTTP stack and the punch service against
a live Postgres (TEST_DATABASE_URL, same convention as the other *_postgres
tests) with the clock pinned to fixed instants.

Reference: Asia/Karachi = UTC+5, no daylight saving.
"""

import os
import uuid
from datetime import UTC, date, datetime, time

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.timezones import (
    local_date_of,
    local_to_utc,
    local_today,
    minutes_late,
    nearest_shift_start,
    zone_from_name,
)
from app.services.attendance_punches import _resolve_shift_end, compute_cutoff_at

KARACHI = zone_from_name("Asia/Karachi")


def utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


class _Shift:
    def __init__(self, start, end, grace=10, overnight=False):
        self.start_time, self.end_time = start, end
        self.late_grace_minutes, self.is_overnight = grace, overnight


DAY_SHIFT = _Shift(time(9, 0), time(18, 0), grace=10)
NIGHT_SHIFT = _Shift(time(22, 0), time(6, 0), grace=0, overnight=True)


# ── Part 1: pure time math ───────────────────────────────────────────────────

class TestLateness:
    def test_late_in_karachi_is_actually_late(self):
        """THE bug: 09:30 in Karachi is 04:30 UTC, which the old formula
        compared to 09:00 and called 'early'."""
        assert minutes_late(DAY_SHIFT, utc("2026-09-17T04:30:00"), KARACHI) == 20

    def test_within_grace_is_on_time(self):
        assert minutes_late(DAY_SHIFT, utc("2026-09-17T04:05:00"), KARACHI) == 0

    def test_early_is_zero(self):
        assert minutes_late(DAY_SHIFT, utc("2026-09-17T03:30:00"), KARACHI) == 0

    def test_overnight_arrival_after_midnight_is_late_against_last_nights_start(self):
        # 00:30 local on the 18th vs the 22:00 start on the 17th → 150 min.
        assert minutes_late(NIGHT_SHIFT, utc("2026-09-17T19:30:00"), KARACHI) == 150

    def test_overnight_arrival_before_start_is_on_time(self):
        assert minutes_late(NIGHT_SHIFT, utc("2026-09-17T16:50:00"), KARACHI) == 0  # 21:50 local

    def test_nearest_start_picks_the_right_evening(self):
        start = nearest_shift_start(utc("2026-09-17T19:30:00"), time(22, 0), KARACHI)
        assert start == utc("2026-09-17T17:00:00")  # 22:00 PKT on the 17th


class TestCalendarDay:
    def test_early_morning_belongs_to_the_local_day(self):
        # 01:30 PKT on the 18th = 20:30 UTC on the 17th.
        assert local_date_of(utc("2026-09-17T20:30:00"), KARACHI) == date(2026, 9, 18)

    def test_local_today_uses_the_zone(self):
        assert local_today(KARACHI, now=utc("2026-09-17T20:30:00")) == date(2026, 9, 18)

    def test_wall_clock_to_utc(self):
        assert local_to_utc(date(2026, 9, 17), time(9, 15), KARACHI) == utc("2026-09-17T04:15:00")

    @pytest.mark.parametrize("name", [None, "", "Mars/Olympus", "GMT+5"])
    def test_bad_zone_names_fall_back_to_utc(self, name):
        assert str(zone_from_name(name)) == "UTC"


class TestShiftEndAndCutoff:
    def test_shift_end_is_the_local_end(self):
        # Punch at 09:00 PKT; shift ends 18:00 PKT = 13:00 UTC (not 18:00 UTC).
        assert _resolve_shift_end(utc("2026-09-17T04:00:00"), DAY_SHIFT, KARACHI) == utc("2026-09-17T13:00:00")

    def test_cutoff_uses_the_local_shift_end(self):
        # Shift end 13:00Z + 4h grace = 17:00Z, earlier than the 14h cap (18:00Z).
        assert compute_cutoff_at(utc("2026-09-17T04:00:00"), DAY_SHIFT, zone=KARACHI) == utc("2026-09-17T17:00:00")

    def test_overnight_local_end_is_next_morning(self):
        # 22:30 PKT punch → shift ends 06:00 PKT next day = 01:00 UTC on the 18th.
        assert _resolve_shift_end(utc("2026-09-17T17:30:00"), NIGHT_SHIFT, KARACHI) == utc("2026-09-18T01:00:00")


# ── Part 2: through the app, against Postgres ───────────────────────────────

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    from app.core.database import get_db
    from app.main import app

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
async def karachi_org(engine):
    """Org in Asia/Karachi with an HR user (attendance.regularize) and one
    employee on a 09:00–18:00 shift with a 10-minute grace."""
    from app.models.attendance import AttendancePunch, AttendanceRecord, Shift
    from app.models.employee import Employee, EmploymentStatus, EmploymentType
    from app.models.organization import Organization
    from app.models.rbac import Permission, Role
    from app.models.user import User
    from app.models.work_session import WorkSession

    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Karachi Co", slug=f"khi-{org_id.hex[:8]}",
                           email=f"khi-{org_id.hex[:8]}@example.com", timezone="Asia/Karachi"))
        await s.flush()
        perm = (await s.execute(select(Permission).where(Permission.codename == "attendance.regularize"))).scalar_one_or_none()
        if perm is None:
            perm = Permission(resource="attendance", action="regularize", codename="attendance.regularize",
                              label="x", category="attendance")
            s.add(perm)
            await s.flush()
        hr_role = Role(organization_id=org_id, name="HR", slug="hr", permissions=[perm])
        shift = Shift(tenant_id=org_id, name="Day", code=f"D{org_id.hex[:4]}", start_time=time(9, 0),
                      end_time=time(18, 0), weekly_hours=45, late_grace_minutes=10)
        s.add_all([hr_role, shift])
        await s.flush()
        ids = {"org": org_id}
        for name, roles in (("hr", [hr_role]), ("emp", [])):
            email = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
            u = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                     first_name=name, last_name="T", is_active=True, is_email_verified=True, roles=roles)
            s.add(u)
            await s.flush()
            e = Employee(tenant_id=org_id, user_id=u.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                         employment_type=EmploymentType.FULL_TIME, employment_status=EmploymentStatus.ACTIVE,
                         date_of_joining=date(2026, 1, 1), default_shift_id=shift.id)
            s.add(e)
            await s.flush()
            ids[name], ids[f"{name}_emp"] = u.id, e.id
        await s.commit()
    yield ids
    async with AsyncSession(engine) as s:
        for model in (AttendancePunch, AttendanceRecord, WorkSession, Employee, Shift):
            await s.execute(delete(model).where(model.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


def _auth(user_id) -> dict:
    from app.core.security import create_access_token
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


@pytest.fixture
def pin_clock(monkeypatch):
    """Freeze datetime.now() inside the attendance router."""
    import app.api.v1.hrms.attendance as attendance_module

    def _pin(instant: datetime):
        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant if tz is None else instant.astimezone(tz)
        monkeypatch.setattr(attendance_module, "datetime", _Frozen)
    return _pin


async def _record(engine, employee_id):
    from app.models.attendance import AttendanceRecord
    async with AsyncSession(engine) as s:
        return (await s.execute(
            select(AttendanceRecord).where(AttendanceRecord.employee_id == employee_id)
        )).scalar_one()


@pytest.mark.asyncio
class TestThroughTheApp:
    async def test_web_check_in_at_0930_karachi_is_late(self, client, engine, karachi_org, pin_clock):
        pin_clock(utc("2026-09-17T04:30:00"))  # 09:30 PKT
        r = await client.post("/api/v1/attendance/check-in", json={"method": "manual"},
                              headers=_auth(karachi_org["emp"]))
        assert r.status_code == 201, r.text
        assert r.json()["late_minutes"] == 20
        assert r.json()["status"] == "late"

    async def test_web_check_in_after_local_midnight_is_filed_under_the_local_day(
        self, client, engine, karachi_org, pin_clock
    ):
        pin_clock(utc("2026-09-17T20:30:00"))  # 01:30 PKT on the 18th
        r = await client.post("/api/v1/attendance/check-in", json={"method": "manual"},
                              headers=_auth(karachi_org["emp"]))
        assert r.status_code == 201, r.text
        assert (await _record(engine, karachi_org["emp_emp"])).date == date(2026, 9, 18)

    async def test_hr_manual_time_means_office_clock_time(self, client, engine, karachi_org):
        r = await client.post(
            "/api/v1/attendance", headers=_auth(karachi_org["hr"]),
            params={"employee_id": str(karachi_org["emp_emp"]), "date": "2026-09-17",
                    "check_in": "09:15", "check_out": "18:00"},
        )
        assert r.status_code in (200, 201), r.text
        record = await _record(engine, karachi_org["emp_emp"])
        assert record.check_in == utc("2026-09-17T04:15:00")
        assert record.check_out == utc("2026-09-17T13:00:00")

    async def test_desktop_punch_is_filed_under_the_local_day(self, engine, karachi_org):
        from app.services.attendance_punches import open_punch
        async with AsyncSession(engine, expire_on_commit=False) as s:
            _, record = await open_punch(s, karachi_org["org"], karachi_org["emp_emp"],
                                         at=utc("2026-09-17T20:30:00"))  # 01:30 PKT, 18th
            await s.commit()
        assert record.date == date(2026, 9, 18)
