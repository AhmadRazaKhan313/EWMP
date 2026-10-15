"""
Daily attendance sheet: shift-based Present / Absent, like OrangeHRM.

Regression for "attendance isn't in sync and every employee shows as present":
  * the page sent ?date=... but GET /attendance ignored it, so it listed the
    newest records of ALL days and counted each as Present;
  * Absent could never happen: no punch = no row = invisible.

Real HTTP stack + live Postgres (TEST_DATABASE_URL), like the other *_postgres
tests. The status rules are tested against a frozen clock.
"""

import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.attendance import (
    AttendanceRecord, AttendanceStatus, Holiday, LeaveRequest, LeaveRequestStatus, LeaveType, Shift,
)
from app.models.employee import Employee, EmploymentStatus
from app.models.organization import Organization
from app.models.organization_structure import Department
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
pytestmark = pytest.mark.asyncio

# Organisation timezone is Asia/Karachi (UTC+5), all days below are in it.
FRI, SAT, SUN, MON, TUE = (date(2026, 10, d) for d in (2, 3, 4, 5, 6))
# Monday 10:00 local: the 09:00-18:00 shift has started, 10 minutes of grace is over.
NOW_MON_10AM = datetime(2026, 10, 5, 5, 0, tzinfo=UTC)
NOW_MON_7AM = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)    # before the shift
NOW_MON_7PM = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)   # after the shift


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


class World:
    """An organisation with a day shift (Mon-Fri 09:00-18:00), a night shift
    (22:00-06:00) and helpers to add employees."""

    def __init__(self, engine):
        self.engine = engine
        self.org_id = uuid.uuid4()
        self.admin_id = None
        self.day_shift = None
        self.night_shift = None
        self.leave_type = None
        self.n = 0

    async def setup(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as s:
            s.add(Organization(id=self.org_id, name="Sheet Org", slug=f"sheet-{self.org_id.hex[:8]}",
                               email=f"s-{self.org_id.hex[:8]}@example.com", timezone="Asia/Karachi"))
            await s.flush()
            admin = await self._user(s, "Admin")
            (await s.get(Organization, self.org_id)).owner_id = admin.id  # owner => full access
            self.admin_id = admin.id
            day = Shift(tenant_id=self.org_id, name="Day", code="DAY", start_time=time(9, 0), end_time=time(18, 0),
                        late_grace_minutes=10, work_days=["mon", "tue", "wed", "thu", "fri"])
            night = Shift(tenant_id=self.org_id, name="Night", code="NGT", start_time=time(22, 0), end_time=time(6, 0),
                          is_overnight=True, work_days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
            s.add_all([day, night])
            await s.flush()
            self.day_shift, self.night_shift = day.id, night.id
            await s.commit()
        # a leave type for leave rows
        async with AsyncSession(self.engine, expire_on_commit=False) as s:
            lt = LeaveType(tenant_id=self.org_id, name="Casual", code="CL", days_per_year=12, is_paid=True)
            s.add(lt)
            await s.commit()
            self.leave_type = lt.id

    async def _user(self, s, name):
        self.n += 1
        email = f"{name.lower()}{self.n}-{uuid.uuid4().hex[:6]}@example.com"
        u = User(organization_id=self.org_id, email=email, email_normalized=email,
                 password_hash=hash_password("x"), first_name=name, last_name="Tester",
                 is_active=True, is_email_verified=True)
        s.add(u)
        await s.flush()
        return u

    async def employee(self, name, *, shift="day", joined=date(2026, 1, 1), left=None, status=None,
                       record=None, department=None):
        """Create an employee; `record` = (date, AttendanceStatus[, late_minutes])."""
        async with AsyncSession(self.engine, expire_on_commit=False) as s:
            u = await self._user(s, name)
            emp = Employee(tenant_id=self.org_id, user_id=u.id, employee_code=f"E{self.n:04d}",
                           date_of_joining=joined, date_of_leaving=left,
                           default_shift_id={"day": self.day_shift, "night": self.night_shift, None: None}[shift],
                           department_id=department)
            if status is not None:
                emp.employment_status = status
            s.add(emp)
            await s.flush()
            if record:
                s.add(AttendanceRecord(tenant_id=self.org_id, employee_id=emp.id, date=record[0], status=record[1],
                                       late_minutes=record[2] if len(record) > 2 else None,
                                       check_in=datetime.combine(record[0], time(4, 0), tzinfo=UTC)))
            await s.commit()
            return {"employee": emp.id, "user": u.id, "name": name}

    async def holiday(self, day, branch=None):
        async with AsyncSession(self.engine) as s:
            s.add(Holiday(tenant_id=self.org_id, name="Test Holiday", date=day, branch_id=branch))
            await s.commit()

    async def leave(self, emp_id, start, end, status=LeaveRequestStatus.APPROVED):
        async with AsyncSession(self.engine) as s:
            s.add(LeaveRequest(tenant_id=self.org_id, employee_id=emp_id, leave_type_id=self.leave_type,
                               start_date=start, end_date=end, total_days=(end - start).days + 1, status=status))
            await s.commit()

    async def sheet(self, day, now, **kw):
        from app.services.attendance_daily import build_daily_sheet
        async with AsyncSession(self.engine) as s:
            _, rows = await build_daily_sheet(s, self.org_id, day, now=now, **kw)
        return {r.employee_name.split()[0]: r for r in rows}

    def admin_headers(self):
        return {"Authorization": f"Bearer {create_access_token(str(self.admin_id))}"}

    def headers(self, user_id):
        return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}

    async def teardown(self):
        async with AsyncSession(self.engine) as s:
            o = {"o": self.org_id}
            for sql in (
                "DELETE FROM break_records WHERE tenant_id = :o",
                "DELETE FROM attendance_punches WHERE tenant_id = :o",
                "DELETE FROM work_sessions WHERE tenant_id = :o",
                "DELETE FROM attendance_records WHERE tenant_id = :o",
                "DELETE FROM leave_requests WHERE tenant_id = :o",
                "DELETE FROM leave_types WHERE tenant_id = :o",
                "DELETE FROM holidays WHERE tenant_id = :o",
                "DELETE FROM employees WHERE tenant_id = :o",
                "DELETE FROM shifts WHERE tenant_id = :o",
                "UPDATE organizations SET owner_id = NULL WHERE id = :o",
                "DELETE FROM users WHERE organization_id = :o",
                "DELETE FROM departments WHERE tenant_id = :o",
                "DELETE FROM organizations WHERE id = :o",
            ):
                await s.execute(text(sql), o)
            await s.commit()


@pytest_asyncio.fixture
async def world(engine):
    w = World(engine)
    await w.setup()
    yield w
    await w.teardown()


# ── Status rules (frozen clock) ───────────────────────────────────────────────

class TestStatusRules:
    async def test_punches_make_people_present_or_late(self, world):
        await world.employee("Pam", record=(MON, AttendanceStatus.PRESENT))
        await world.employee("Lou", record=(MON, AttendanceStatus.LATE, 25))
        rows = await world.sheet(MON, NOW_MON_10AM)
        assert rows["Pam"].status.value == "present"
        assert rows["Lou"].status.value == "late" and rows["Lou"].late_minutes == 25

    async def test_nobody_is_present_without_a_punch(self, world):
        """THE regression: employees who haven't punched must not be Present."""
        for n in ("A", "B", "C"):
            await world.employee(n)
        rows = await world.sheet(MON, NOW_MON_10AM)
        assert {r.status.value for r in rows.values()} == {"not_checked_in"}

    async def test_default_present_row_without_check_in_is_not_present(self, world):
        """The day row is created with default status PRESENT. Without a real
        check-in it must NOT show Present (regression: everyone was Present)."""
        emp = await world.employee("Ghost")
        async with AsyncSession(world.engine) as s:
            s.add(AttendanceRecord(tenant_id=world.org_id, employee_id=emp["employee"], date=MON))
            await s.commit()
        assert (await world.sheet(MON, NOW_MON_10AM))["Ghost"].status.value == "not_checked_in"
        assert (await world.sheet(MON, NOW_MON_7PM))["Ghost"].status.value == "absent"

    async def test_hr_explicit_mark_without_times_still_counts(self, world):
        emp = await world.employee("Hera")
        async with AsyncSession(world.engine) as s:
            s.add(AttendanceRecord(tenant_id=world.org_id, employee_id=emp["employee"], date=MON,
                                   status=AttendanceStatus.WORK_FROM_HOME, is_regularized=True))
            await s.commit()
        assert (await world.sheet(MON, NOW_MON_10AM))["Hera"].status.value == "work_from_home"

    async def test_dashboard_present_today_needs_a_check_in(self, world):
        from app.services.dashboard import get_dashboard_stats
        a = await world.employee("Real")
        g = await world.employee("Ghost2")
        today = datetime.now(UTC).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Karachi")).date()
        async with AsyncSession(world.engine) as s:
            s.add(AttendanceRecord(tenant_id=world.org_id, employee_id=a["employee"], date=today,
                                   check_in=datetime.now(UTC)))
            s.add(AttendanceRecord(tenant_id=world.org_id, employee_id=g["employee"], date=today))
            await s.commit()
        async with AsyncSession(world.engine) as s:
            stats = await get_dashboard_stats(s, world.org_id)
        assert stats["present_today"] == 1

    async def test_a_working_day_in_progress_is_not_absent_yet(self, world):
        await world.employee("Ned")
        assert (await world.sheet(MON, NOW_MON_10AM))["Ned"].status.value == "not_checked_in"

    async def test_before_the_shift_starts_it_is_just_scheduled(self, world):
        await world.employee("Ned")
        assert (await world.sheet(MON, NOW_MON_7AM))["Ned"].status.value == "scheduled"

    async def test_after_the_shift_ends_without_a_punch_is_absent(self, world):
        await world.employee("Ned")
        assert (await world.sheet(MON, NOW_MON_7PM))["Ned"].status.value == "absent"

    async def test_a_past_working_day_without_a_punch_is_absent(self, world):
        await world.employee("Ned")
        assert (await world.sheet(FRI, NOW_MON_10AM))["Ned"].status.value == "absent"

    async def test_a_future_day_is_scheduled_not_absent(self, world):
        await world.employee("Ned")
        assert (await world.sheet(TUE, NOW_MON_10AM))["Ned"].status.value == "scheduled"

    async def test_the_weekly_off_is_not_absent(self, world):
        await world.employee("Ned")
        assert (await world.sheet(SUN, NOW_MON_10AM))["Ned"].status.value == "weekly_off"

    async def test_working_on_an_off_day_still_counts_as_present(self, world):
        await world.employee("Wes", record=(SAT, AttendanceStatus.PRESENT))
        assert (await world.sheet(SAT, NOW_MON_10AM))["Wes"].status.value == "present"

    async def test_holidays(self, world):
        await world.employee("Hal")
        await world.employee("Hugh", record=(FRI, AttendanceStatus.PRESENT))
        await world.holiday(FRI)
        rows = await world.sheet(FRI, NOW_MON_10AM)
        assert rows["Hal"].status.value == "holiday" and rows["Hal"].detail == "Test Holiday"
        assert rows["Hugh"].status.value == "present"  # worked on the holiday

    async def test_only_approved_leave_excuses_a_day(self, world):
        ok = await world.employee("Ola")
        pending = await world.employee("Pat")
        rejected = await world.employee("Rex")
        await world.leave(ok["employee"], FRI, FRI)
        await world.leave(pending["employee"], FRI, FRI, LeaveRequestStatus.PENDING)
        await world.leave(rejected["employee"], FRI, FRI, LeaveRequestStatus.REJECTED)
        rows = await world.sheet(FRI, NOW_MON_10AM)
        assert rows["Ola"].status.value == "on_leave"
        assert rows["Pat"].status.value == "absent" and rows["Rex"].status.value == "absent"

    async def test_hr_explicit_calls_on_a_record_are_honoured(self, world):
        await world.employee("Ann", record=(FRI, AttendanceStatus.ABSENT))
        await world.employee("Lea", record=(FRI, AttendanceStatus.ON_LEAVE))
        await world.employee("Hal", record=(FRI, AttendanceStatus.HALF_DAY))
        rows = await world.sheet(FRI, NOW_MON_10AM)
        assert (rows["Ann"].status.value, rows["Lea"].status.value, rows["Hal"].status.value) == (
            "absent", "on_leave", "half_day")

    async def test_a_new_signup_is_not_present_and_not_absent_before_joining(self, world):
        """Someone who just signed up must not show up as present -- and is not
        absent for days before they joined, nor listed before their start date."""
        await world.employee("Newt", joined=MON)
        await world.employee("Later", joined=TUE)
        today = await world.sheet(MON, NOW_MON_10AM)
        assert today["Newt"].status.value == "not_checked_in"   # joined today, hasn't punched
        assert "Later" not in today                              # starts tomorrow
        assert "Newt" not in await world.sheet(FRI, NOW_MON_10AM)  # not employed on Friday

    async def test_people_who_left_are_not_listed_afterwards(self, world):
        await world.employee("Gone", left=date(2026, 10, 1))
        await world.employee("Stale", status=EmploymentStatus.TERMINATED)  # no leaving date: unplaceable
        assert "Gone" not in await world.sheet(FRI, NOW_MON_10AM)
        assert "Stale" not in await world.sheet(FRI, NOW_MON_10AM)
        assert "Gone" in await world.sheet(date(2026, 9, 30), NOW_MON_10AM)

    async def test_no_shift_means_the_org_work_week_and_end_of_day(self, world):
        await world.employee("Free", shift=None)
        assert (await world.sheet(FRI, NOW_MON_10AM))["Free"].status.value == "absent"
        assert (await world.sheet(MON, NOW_MON_7PM))["Free"].status.value == "not_checked_in"  # day not over
        assert (await world.sheet(SUN, NOW_MON_10AM))["Free"].status.value == "weekly_off"

    async def test_a_night_shift_is_not_absent_until_it_has_ended(self, world):
        await world.employee("Nia", shift="night")
        mid_shift = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)   # Mon 01:00 local; Sunday's shift runs to 06:00
        after = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)        # Mon 07:00 local: it has ended
        assert (await world.sheet(SUN, mid_shift))["Nia"].status.value == "not_checked_in"
        assert (await world.sheet(SUN, after))["Nia"].status.value == "absent"

    async def test_summary_and_filters(self, world):
        from app.services.attendance_daily import build_daily_sheet, summarize
        await world.employee("P1", record=(FRI, AttendanceStatus.PRESENT))
        await world.employee("L1", record=(FRI, AttendanceStatus.LATE, 5))
        await world.employee("A1")
        await world.employee("Zorblax")  # a name nothing else (incl. random e-mail hex) can match
        async with AsyncSession(world.engine) as s:
            _, rows = await build_daily_sheet(s, world.org_id, FRI, now=NOW_MON_10AM)
            summary = summarize(rows)
            _, one = await build_daily_sheet(s, world.org_id, FRI, now=NOW_MON_10AM, search="zorblax")
        assert (summary["present"], summary["late"], summary["absent"]) == (1, 1, 2)
        assert summary["present_total"] == 2 and summary["expected"] == 4 and summary["total"] == 4
        assert [r.employee_name.split()[0] for r in one] == ["Zorblax"]


# ── The endpoints ─────────────────────────────────────────────────────────────

def _past_workday() -> date:
    d = date.today() - timedelta(days=3)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d


class TestListEndpointHonoursDate:
    async def test_date_param_filters_to_one_day(self, client, world):
        """THE page bug: ?date= was ignored and every day's records came back."""
        d1, d2 = _past_workday(), _past_workday() - timedelta(days=1)
        await world.employee("One", record=(d1, AttendanceStatus.PRESENT))
        await world.employee("Two", record=(d2, AttendanceStatus.PRESENT))
        r = await client.get("/api/v1/attendance", params={"date": str(d1)}, headers=world.admin_headers())
        assert r.status_code == 200, r.text
        names = {i["employee_name"].split()[0] for i in r.json()["items"]}
        assert names == {"One"}, f"records from other days leaked in: {names}"


class TestDailyEndpoint:
    async def test_absentees_appear_and_counts_are_right(self, client, world):
        day = _past_workday()
        await world.employee("Here", record=(day, AttendanceStatus.PRESENT))
        await world.employee("Gone1")
        await world.employee("Gone2")
        r = await client.get("/api/v1/attendance/daily", params={"date": str(day)}, headers=world.admin_headers())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["date"] == str(day)
        assert body["summary"]["present_total"] == 1 and body["summary"]["absent"] == 2
        assert {i["status"] for i in body["items"]} == {"present", "absent"}
        assert body["items"][0]["shift_name"] == "Day" and body["items"][0]["shift_start"] == "09:00"

    async def test_status_filter_and_pagination_keep_the_summary_whole(self, client, world):
        day = _past_workday()
        await world.employee("Here", record=(day, AttendanceStatus.PRESENT))
        for n in ("G1", "G2", "G3"):
            await world.employee(n)
        r = await client.get("/api/v1/attendance/daily", headers=world.admin_headers(),
                             params={"date": str(day), "status": "absent", "page_size": 2})
        body = r.json()
        assert body["total"] == 3 and len(body["items"]) == 2 and body["total_pages"] == 2
        assert body["summary"]["present_total"] == 1 and body["summary"]["total"] == 4  # not narrowed by the filter

    async def test_status_filter_accepts_a_comma_separated_group(self, client, world):
        day = _past_workday()
        await world.employee("Here", record=(day, AttendanceStatus.PRESENT))
        await world.employee("Late", record=(day, AttendanceStatus.LATE, 5))
        await world.employee("Gone")
        r = await client.get("/api/v1/attendance/daily", headers=world.admin_headers(),
                             params={"date": str(day), "status": "present,late"})
        assert {i["status"] for i in r.json()["items"]} == {"present", "late"}

    async def test_unknown_status_is_a_422(self, client, world):
        r = await client.get("/api/v1/attendance/daily", params={"status": "bogus"}, headers=world.admin_headers())
        assert r.status_code == 422

    async def test_a_user_without_attendance_permission_is_refused(self, client, world):
        nobody = await world.employee("Nobody")
        r = await client.get("/api/v1/attendance/daily", headers=world.headers(nobody["user"]))
        assert r.status_code == 403


# ── Desktop <-> web stay in sync ──────────────────────────────────────────────

WORKED = {"present", "late", "half_day", "work_from_home", "missed_punch"}


class TestDesktopAndWebAgree:
    async def _row(self, client, world, who):
        r = await client.get("/api/v1/attendance/daily", headers=world.admin_headers())
        assert r.status_code == 200, r.text
        return next(i for i in r.json()["items"] if i["employee_id"] == str(who["employee"]))

    async def test_a_desktop_check_in_shows_up_on_the_web_sheet(self, client, world):
        me = await world.employee("Desk")
        idle = await world.employee("Idle")
        assert (await self._row(client, world, me))["status"] not in WORKED
        r = await client.post("/api/v1/work-sessions/start", headers=world.headers(me["user"]))  # desktop timer
        assert r.status_code in (200, 201), r.text
        row = await self._row(client, world, me)
        assert row["status"] in WORKED and row["check_in"] is not None
        assert (await self._row(client, world, idle))["status"] not in WORKED  # nobody else changed

    async def test_a_desktop_check_out_closes_the_web_attendance_day(self, client, world):
        me = await world.employee("Desk")
        h = world.headers(me["user"])
        sid = (await client.post("/api/v1/work-sessions/start", headers=h)).json()["id"]
        assert (await client.post(f"/api/v1/work-sessions/{sid}/end", headers=h)).status_code == 200
        row = await self._row(client, world, me)
        assert row["check_in"] is not None and row["check_out"] is not None

    async def test_a_web_check_in_starts_the_desktop_timer(self, client, world):
        me = await world.employee("Web")
        h = world.headers(me["user"])
        r = await client.post("/api/v1/attendance/check-in", headers=h, json={"method": "manual"})
        assert r.status_code == 201, r.text
        active = await client.get("/api/v1/work-sessions/me/active", headers=h)
        assert active.status_code == 200 and active.json(), "the desktop timer did not see the web check-in"
        assert (await self._row(client, world, me))["status"] in WORKED

    async def test_a_web_check_out_stops_the_desktop_timer(self, client, world):
        me = await world.employee("Web")
        h = world.headers(me["user"])
        await client.post("/api/v1/attendance/check-in", headers=h, json={"method": "manual"})
        out = await client.post("/api/v1/attendance/check-out", headers=h, json={})
        assert out.status_code == 200, out.text
        active = await client.get("/api/v1/work-sessions/me/active", headers=h)
        assert not active.json(), "the desktop timer kept running after a web check-out"
