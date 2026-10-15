"""
Assigning shifts to employees.

Before: Employee.default_shift_id was accepted by the create schema and then
silently dropped, there was no screen or bulk endpoint to set it, and the
shifts list could not say who works a shift -- so no employee ever had a shift
and attendance fell back to the organisation's generic work week.

Real HTTP stack + live Postgres (TEST_DATABASE_URL), like the other *_postgres
tests.
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
            "DELETE FROM attendance_records WHERE tenant_id = :o",
            "DELETE FROM employees WHERE tenant_id = :o",
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


async def _shift(client, org, name="Day", start="09:00", end="18:00", **kw) -> str:
    r = await client.post("/api/v1/shifts", headers=_h(org["owner"]),
                          json={"name": name, "code": name[:3].upper(), "start_time": start, "end_time": end, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _employee(client, org, name, shift_id=None) -> dict:
    payload = {"first_name": name, "last_name": "Hire", "email": f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.com",
               "date_of_joining": "2026-01-01", "role_id": str(org["role"])}
    if shift_id:
        payload["default_shift_id"] = shift_id
    r = await client.post("/api/v1/employees", headers=_h(org["owner"]), json=payload)
    assert r.status_code == 201, r.text
    return {"id": r.json()["id"], "name": name}


async def _detail(client, org, emp) -> dict:
    r = await client.get(f"/api/v1/employees/{emp['id']}", headers=_h(org["owner"]))
    assert r.status_code == 200, r.text
    return r.json()


async def _roster(client, org, shift_id, **params) -> dict:
    r = await client.get(f"/api/v1/shifts/{shift_id}/employees", headers=_h(org["owner"]), params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def _set_roster(client, org, shift_id, ids):
    return await client.put(f"/api/v1/shifts/{shift_id}/employees", headers=_h(org["owner"]),
                            json={"employee_ids": [e["id"] for e in ids]})


def _ids(rows) -> set:
    return {r["id"] for r in rows}


# ── Setting a shift when creating / editing an employee ───────────────────────

class TestEmployeeShiftField:
    async def test_create_with_a_shift_saves_it(self, client, org):
        """THE bug: the shift in the create form was accepted and dropped."""
        day = await _shift(client, org)
        emp = await _employee(client, org, "Ann", shift_id=day)
        assert (await _detail(client, org, emp))["default_shift_id"] == day

    async def test_create_without_a_shift_leaves_it_empty(self, client, org):
        emp = await _employee(client, org, "Ben")
        assert (await _detail(client, org, emp))["default_shift_id"] is None

    async def test_a_shift_from_another_organization_is_refused(self, client, org, other_org):
        foreign = await _shift(client, other_org, "Foreign")
        r = await client.post("/api/v1/employees", headers=_h(org["owner"]), json={
            "first_name": "Cy", "last_name": "Hire", "email": f"cy-{uuid.uuid4().hex[:6]}@example.com",
            "date_of_joining": "2026-01-01", "role_id": str(org["role"]), "default_shift_id": foreign})
        assert r.status_code == 404, r.text
        listing = await client.get("/api/v1/employees", headers=_h(org["owner"]))
        assert listing.json()["total"] == 0, "the employee was created despite the bad shift"

    async def test_edit_changes_and_clears_the_shift(self, client, org):
        day, night = await _shift(client, org), await _shift(client, org, "Night", "22:00", "06:00", is_overnight=True)
        emp = await _employee(client, org, "Dee", shift_id=day)
        r = await client.patch(f"/api/v1/employees/{emp['id']}", headers=_h(org["owner"]), json={"default_shift_id": night})
        assert r.status_code == 200, r.text
        assert (await _detail(client, org, emp))["default_shift_id"] == night
        await client.patch(f"/api/v1/employees/{emp['id']}", headers=_h(org["owner"]), json={"default_shift_id": None})
        assert (await _detail(client, org, emp))["default_shift_id"] is None

    async def test_edit_refuses_a_foreign_shift(self, client, org, other_org):
        foreign = await _shift(client, other_org, "Foreign")
        emp = await _employee(client, org, "Eve")
        r = await client.patch(f"/api/v1/employees/{emp['id']}", headers=_h(org["owner"]), json={"default_shift_id": foreign})
        assert r.status_code == 404
        assert (await _detail(client, org, emp))["default_shift_id"] is None


# ── Assigning many employees to a shift ───────────────────────────────────────

class TestShiftRoster:
    async def test_the_shifts_list_counts_employees(self, client, org):
        day = await _shift(client, org)
        await _shift(client, org, "Night", "22:00", "06:00", is_overnight=True)
        await _employee(client, org, "A", shift_id=day)
        await _employee(client, org, "B", shift_id=day)
        items = {s["name"]: s for s in (await client.get("/api/v1/shifts", headers=_h(org["owner"]))).json()["items"]}
        assert items["Day"]["employee_count"] == 2 and items["Night"]["employee_count"] == 0

    async def test_roster_splits_assigned_from_others_and_names_their_current_shift(self, client, org):
        day, night = await _shift(client, org), await _shift(client, org, "Night", "22:00", "06:00", is_overnight=True)
        a = await _employee(client, org, "Ada", shift_id=day)
        n = await _employee(client, org, "Nick", shift_id=night)
        f = await _employee(client, org, "Free")
        body = await _roster(client, org, day)
        assert _ids(body["assigned"]) == {a["id"]}
        others = {r["id"]: r for r in body["others"]}
        assert set(others) == {n["id"], f["id"]}
        assert others[n["id"]]["current_shift_name"] == "Night" and others[f["id"]]["current_shift_name"] is None

    async def test_roster_search(self, client, org):
        day = await _shift(client, org)
        await _employee(client, org, "Zorblax")
        await _employee(client, org, "Other")
        body = await _roster(client, org, day, search="zorblax")
        assert [r["name"].split()[0] for r in body["assigned"] + body["others"]] == ["Zorblax"]

    async def test_put_sets_exactly_the_given_roster(self, client, org):
        day = await _shift(client, org)
        a = await _employee(client, org, "A", shift_id=day)
        b = await _employee(client, org, "B", shift_id=day)
        c = await _employee(client, org, "C")
        r = await _set_roster(client, org, day, [b, c])  # A leaves, C joins, B stays
        assert r.status_code == 200, r.text
        assert (r.json()["assigned"], r.json()["cleared"]) == (2, 1)
        assert (await _detail(client, org, a))["default_shift_id"] is None
        assert (await _detail(client, org, b))["default_shift_id"] == day
        assert (await _detail(client, org, c))["default_shift_id"] == day

    async def test_moving_someone_removes_them_from_their_old_shift(self, client, org):
        day, night = await _shift(client, org), await _shift(client, org, "Night", "22:00", "06:00", is_overnight=True)
        n = await _employee(client, org, "Nick", shift_id=night)
        await _set_roster(client, org, day, [n])
        assert (await _detail(client, org, n))["default_shift_id"] == day
        assert _ids((await _roster(client, org, night))["assigned"]) == set()

    async def test_an_empty_list_takes_everyone_off_the_shift(self, client, org):
        day = await _shift(client, org)
        a = await _employee(client, org, "A", shift_id=day)
        assert (await _set_roster(client, org, day, [])).status_code == 200
        assert (await _detail(client, org, a))["default_shift_id"] is None

    async def test_an_employee_from_another_organization_changes_nothing(self, client, org, other_org):
        day = await _shift(client, org)
        mine = await _employee(client, org, "Mine", shift_id=day)
        foreign = await _employee(client, other_org, "Foreign")
        r = await _set_roster(client, org, day, [mine, foreign])
        assert r.status_code == 404
        assert (await _detail(client, org, mine))["default_shift_id"] == day  # untouched
        assert (await _detail(client, other_org, foreign))["default_shift_id"] is None

    async def test_other_organizations_shifts_cannot_be_read_or_changed(self, client, org, other_org):
        foreign = await _shift(client, other_org, "Foreign")
        assert (await client.get(f"/api/v1/shifts/{foreign}/employees", headers=_h(org["owner"]))).status_code == 404
        assert (await _set_roster(client, org, foreign, [])).status_code == 404

    async def test_changing_a_roster_needs_the_regularize_permission(self, client, engine, org):
        day = await _shift(client, org)
        e = await _employee(client, org, "Plain")
        async with AsyncSession(engine) as s:  # a normal employee login: no attendance.regularize
            uid = (await s.execute(text("SELECT user_id FROM employees WHERE id = :e"), {"e": e["id"]})).scalar_one()
            await s.execute(text("UPDATE users SET must_change_password = false, is_email_verified = true WHERE id = :u"), {"u": uid})
            await s.commit()
        r = await client.put(f"/api/v1/shifts/{day}/employees", headers=_h(uid), json={"employee_ids": []})
        assert r.status_code == 403


# ── The assigned shift is what attendance uses ────────────────────────────────

class TestAttendanceUsesTheAssignedShift:
    async def test_the_daily_sheet_shows_each_employees_shift(self, client, org):
        day = await _shift(client, org)
        d = date.today() - timedelta(days=3)
        while d.weekday() > 4:
            d -= timedelta(days=1)
        a = await _employee(client, org, "Shifted", shift_id=day)
        b = await _employee(client, org, "Unshifted")
        r = await client.get("/api/v1/attendance/daily", params={"date": str(d)}, headers=_h(org["owner"]))
        assert r.status_code == 200, r.text
        rows = {i["employee_id"]: i for i in r.json()["items"]}
        assert rows[a["id"]]["shift_name"] == "Day" and rows[a["id"]]["shift_start"] == "09:00"
        assert rows[b["id"]]["shift_name"] is None
