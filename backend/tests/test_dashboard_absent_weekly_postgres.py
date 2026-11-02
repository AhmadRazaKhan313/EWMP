"""
D-01 / D-02: dashboard Absent card + weekly-hours graph (real HTTP, live Postgres).
"""

import os
import uuid
from datetime import date, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.organization import Organization
from app.models.rbac import Role
from app.models.user import User
from app.workers.tasks import email as email_tasks

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _no_email(monkeypatch):
    monkeypatch.setattr(email_tasks.send_verification_email, "delay", lambda to, token: None)


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


async def _make_org(engine) -> dict:
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Shift Org", slug=f"shift-{org_id.hex[:8]}",
                           email=f"s-{org_id.hex[:8]}@example.com", timezone="Asia/Karachi"))
        await s.flush()
        staff = Role(organization_id=org_id, name="Staff", slug="staff", permissions=[])
        s.add(staff)
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        owner = User(organization_id=org_id, email=email, email_normalized=email,
                     password_hash=hash_password("x"), first_name="Owner", last_name="Test",
                     is_active=True, is_email_verified=True)
        s.add(owner)
        await s.flush()
        (await s.get(Organization, org_id)).owner_id = owner.id
        ids = {"org": org_id, "owner": owner.id, "role": staff.id}
        await s.commit()
    return ids


async def _drop_org(engine, ids):
    async with AsyncSession(engine) as s:
        o = {"o": ids["org"]}
        for sql in (
            "DELETE FROM auth_refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE organization_id = :o)",
            "DELETE FROM attendance_punches WHERE tenant_id = :o",
            "DELETE FROM attendance_records WHERE tenant_id = :o",
            "DELETE FROM employees WHERE tenant_id = :o",
            "DELETE FROM leave_requests WHERE tenant_id = :o",
            "DELETE FROM leave_balances WHERE tenant_id = :o",
            "DELETE FROM leave_types WHERE tenant_id = :o",
            "DELETE FROM holidays WHERE tenant_id = :o",
            "DELETE FROM applicants WHERE tenant_id = :o",
            "DELETE FROM job_postings WHERE tenant_id = :o",
            "DELETE FROM goals WHERE tenant_id = :o",
            "DELETE FROM performance_reviews WHERE tenant_id = :o",
            "DELETE FROM support_tickets WHERE tenant_id = :o",
            "DELETE FROM shifts WHERE tenant_id = :o",
            "UPDATE organizations SET owner_id = NULL WHERE id = :o",
            "DELETE FROM users WHERE organization_id = :o",
            "DELETE FROM roles WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            await s.execute(text(sql), o)
        await s.commit()


@pytest_asyncio.fixture
async def org(engine):
    ids = await _make_org(engine)
    yield ids
    await _drop_org(engine, ids)


@pytest_asyncio.fixture
async def other_org(engine):
    ids = await _make_org(engine)
    yield ids
    await _drop_org(engine, ids)


def _h(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}




def _h(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


async def _employee(client, engine, org, name, shift_id=None) -> dict:
    body = {"first_name": name, "last_name": "Hire", "email": f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.com",
            "date_of_joining": "2026-01-01", "role_id": str(org["role"])}
    if shift_id:
        body["default_shift_id"] = shift_id
    r = await client.post("/api/v1/employees", headers=_h(org["owner"]), json=body)
    assert r.status_code == 201, r.text
    eid = uuid.UUID(r.json()["id"])
    async with AsyncSession(engine) as s:
        from sqlalchemy import select
        from app.models.employee import Employee
        emp = (await s.execute(select(Employee).where(Employee.id == eid))).scalar_one()
        user_id = emp.user_id
        await s.execute(text("UPDATE users SET must_change_password = false WHERE id = :u"), {"u": user_id})
        await s.commit()
    return {"id": eid, "user": user_id}


async def _record(engine, org, emp, day, minutes, status="PRESENT"):
    from datetime import datetime, timezone
    async with AsyncSession(engine) as s:
        await s.execute(text(
            "INSERT INTO attendance_records (id, tenant_id, employee_id, date, check_in, status, total_minutes, "
            "is_regularized, is_deleted, created_at, updated_at, check_in_source) VALUES "
            "(:i, :t, :e, :d, :ci, CAST(:st AS attendance_status_enum), :m, false, false, now(), now(), 'MANUAL')"),
            {"i": uuid.uuid4(), "t": org["org"], "e": emp["id"], "d": day,
             "ci": datetime(day.year, day.month, day.day, 9, tzinfo=timezone.utc), "st": status, "m": minutes})
        await s.commit()


async def _role_user(engine, org, perms, name="Hr"):
    """A user in `org` whose role grants exactly `perms`."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        from sqlalchemy import select
        from app.models.rbac import Permission

        from app.database.seeds.permissions import PERMISSIONS_BY_CODENAME

        wanted = list((await s.execute(select(Permission).where(Permission.codename.in_(perms)))).scalars().all())
        for codename in set(perms) - {p.codename for p in wanted}:  # same rows `seed --permissions` creates
            d = PERMISSIONS_BY_CODENAME[codename]
            row = Permission(resource=d["resource"], action=d["action"], codename=codename, label=d["label"],
                             category=d["category"], is_sensitive=d.get("is_sensitive", False))
            s.add(row)
            wanted.append(row)
        role = Role(organization_id=org["org"], name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:5]}")
        role.permissions = list(wanted)
        s.add(role)
        await s.flush()
        email = f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.com"
        u = User(organization_id=org["org"], email=email, email_normalized=email,
                 password_hash=hash_password("x"), first_name=name, last_name="User",
                 is_active=True, is_email_verified=True)
        u.roles.append(role)
        s.add(u)
        await s.flush()
        uid = u.id
        await s.commit()
    return uid


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


class TestAbsentToday:
    async def test_absent_excludes_present_leave_holiday_and_needs_permission(self, client, engine, org, other_org):
        from app.services.dashboard import get_absent_today
        from datetime import datetime, timezone

        sh = await client.post("/api/v1/shifts", headers=_h(org["owner"]),
                               json={"name": "Early", "code": "ERL", "start_time": "09:00", "end_time": "16:00"})
        assert sh.status_code == 201, sh.text
        a = await _employee(client, engine, org, "Absentee", shift_id=sh.json()["id"])
        p = await _employee(client, engine, org, "Present", shift_id=sh.json()["id"])
        n = await _employee(client, engine, org, "Noshift")
        # Fixed "now": Wednesday 17:00 Karachi -> the 09:00-16:00 shift is over.
        now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        day = date(2026, 10, 14)
        await _record(engine, org, p, day, 480)
        async with AsyncSession(engine) as s:
            res = await get_absent_today(s, org["org"], now=now)
        names = {e["employee_name"]: e["status"] for e in res["employees"]}
        assert names.get("Absentee Hire") == "absent"
        # No shift: the day is not over yet, so "yet to check in", not absent.
        assert names.get("Noshift Hire") == "not_checked_in"
        assert "Present Hire" not in names
        assert res["absent"] == 1 and res["not_checked_in"] == 1 and res["total"] == len(res["employees"])

    async def test_weekend_is_not_absent_but_checkin_counts(self, client, engine, org):
        from app.services.dashboard import get_absent_today, get_weekly_hours
        from datetime import datetime, timezone

        w = await _employee(client, engine, org, "Weekender")
        quiet = await _employee(client, engine, org, "Quiet")
        sat = date(2026, 10, 17)  # Saturday
        now = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
        await _record(engine, org, w, sat, 300)
        async with AsyncSession(engine) as s:
            res = await get_absent_today(s, org["org"], now=now)
            wk = await get_weekly_hours(s, org["org"], employee_id=w["id"], week_start=sat, now=now)
        assert res["employees"] == []  # off day: nobody absent, even the one who did not come
        satrow = next(d for d in wk["days"] if d["date"] == "2026-10-17")
        assert satrow["hours"] == 5.0 and satrow["extra_day"] is True and satrow["is_working_day"] is False
        assert wk["total_hours"] == 5.0

    async def test_holiday_excluded_and_endpoint_permission(self, client, engine, org):
        await _employee(client, engine, org, "Someone")
        today = date.today()
        r = await client.post("/api/v1/holidays", headers=_h(org["owner"]),
                              json={"name": "Today off", "date": today.isoformat()})
        assert r.status_code in (200, 201), r.text
        r = await client.get("/api/v1/dashboard/absent", headers=_h(org["owner"]))
        assert r.status_code == 200 and r.json()["employees"] == []
        nobody = await _role_user(engine, org, [], name="Plain")
        async with AsyncSession(engine) as s:
            await s.execute(text("UPDATE users SET must_change_password = false WHERE id = :u"), {"u": nobody})
            await s.commit()
        assert (await client.get("/api/v1/dashboard/absent", headers=_h(nobody))).status_code == 403
        hr = await _role_user(engine, org, ["attendance.view"], name="Viewer")
        assert (await client.get("/api/v1/dashboard/absent", headers=_h(hr))).status_code == 200


class TestWeeklyHours:
    async def test_seven_days_target_40_empty_days_zero_and_clamped(self, client, engine, org):
        e = await _employee(client, engine, org, "Worker")
        mon = _monday(date.today())
        await _record(engine, org, e, mon, 480)
        await _record(engine, org, e, mon + timedelta(days=1), 99999)  # garbage -> clamped to 24h
        r = await client.get(f"/api/v1/dashboard/weekly-hours?week_start={mon}", headers=_h(e["user"]))
        assert r.status_code == 200, r.text
        j = r.json()
        assert len(j["days"]) == 7 and j["days"][0]["weekday"] == "mon" and j["days"][6]["weekday"] == "sun"
        assert j["target_hours"] == 40.0 and j["working_days"] == 5
        assert j["days"][0]["hours"] == 8.0
        assert j["days"][1]["hours"] == 24.0
        assert all(0 <= d["hours"] <= 24 for d in j["days"])
        assert j["days"][3]["hours"] == 0 and j["days"][5]["extra_day"] is False
        assert j["total_hours"] == 32.0

    async def test_scope_team_needs_permission_and_averages(self, client, engine, org, other_org):
        a = await _employee(client, engine, org, "Aa")
        b = await _employee(client, engine, org, "Bb")
        mon = _monday(date.today())
        await _record(engine, org, a, mon, 360)
        await _record(engine, org, b, mon, 600)
        r = await client.get(f"/api/v1/dashboard/weekly-hours?scope=team&week_start={mon}", headers=_h(org["owner"]))
        assert r.status_code == 200
        assert r.json()["days"][0]["hours"] == 8.0 and r.json()["days"][0]["people"] == 2
        assert (await client.get("/api/v1/dashboard/weekly-hours?scope=team", headers=_h(a["user"]))).status_code == 403
        # a foreign employee id is a 404, not a data leak
        foreign = await _employee(client, engine, other_org, "Foreign")
        r = await client.get(f"/api/v1/dashboard/weekly-hours?employee_id={foreign['id']}", headers=_h(org["owner"]))
        assert r.status_code == 404

    async def test_shift_sets_target_and_work_days(self, client, engine, org):
        r = await client.post("/api/v1/shifts", headers=_h(org["owner"]),
                              json={"name": "Six", "code": "SIX", "start_time": "09:00", "end_time": "17:00",
                                    "work_days": ["mon", "tue", "wed", "thu", "fri", "sat"], "weekly_hours": 48})
        assert r.status_code == 201, r.text
        e = await _employee(client, engine, org, "Shifty", shift_id=r.json()["id"])
        j = (await client.get("/api/v1/dashboard/weekly-hours", headers=_h(e["user"]))).json()
        assert j["target_hours"] == 48.0 and j["working_days"] == 6
        assert next(d for d in j["days"] if d["weekday"] == "sat")["is_working_day"] is True
