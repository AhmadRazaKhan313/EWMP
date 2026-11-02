"""Break-time lock (K-01) — live Postgres, real HTTP stack."""
import os
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.organization_structure import Department
from app.models.user import User

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp")
pytestmark = pytest.mark.asyncio
B = "/api/v1/break"


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


async def _mk_org(engine, tag):
    oid = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=oid, name=f"Brk {tag}", slug=f"brk-{oid.hex[:8]}", email=f"b-{oid.hex[:8]}@example.com",
                           timezone="UTC"))
        await s.flush()

        def mk(first):
            e = f"{first.lower()}-{uuid.uuid4().hex[:6]}@example.com"
            return User(organization_id=oid, email=e, email_normalized=e, password_hash=hash_password("x"),
                        first_name=first, last_name="T", is_active=True, is_email_verified=True)

        admin, worker, other = mk("Adm"), mk("Wrk"), mk("Oth")
        s.add_all([admin, worker, other])
        dept = Department(tenant_id=oid, name="Eng")
        s.add(dept)
        await s.flush()
        (await s.get(Organization, oid)).owner_id = admin.id
        emp = Employee(tenant_id=oid, user_id=worker.id, employee_code="EMP-7", department_id=dept.id,
                       date_of_joining=date(2026, 1, 1))
        emp2 = Employee(tenant_id=oid, user_id=other.id, employee_code="EMP-8", date_of_joining=date(2026, 1, 1))
        s.add_all([emp, emp2])
        await s.flush()
        ids = dict(org=oid, admin=admin.id, worker=worker.id, other=other.id, emp=emp.id, emp2=emp2.id, dept=dept.id)
        await s.commit()
    return ids


async def _drop(engine, o):
    async with AsyncSession(engine) as s:
        for sql in (
            "DELETE FROM notifications WHERE tenant_id = :o",
            "DELETE FROM break_unlock_requests WHERE tenant_id = :o",
            "DELETE FROM break_overrides WHERE tenant_id = :o",
            "DELETE FROM break_policies WHERE tenant_id = :o",
            "UPDATE organizations SET owner_id = NULL WHERE id = :o",
            "DELETE FROM employees WHERE tenant_id = :o",
            "DELETE FROM departments WHERE tenant_id = :o",
            "DELETE FROM users WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            await s.execute(text(sql), {"o": o})
        await s.commit()


@pytest_asyncio.fixture
async def org(engine):
    ids = await _mk_org(engine, "A")
    yield ids
    await _drop(engine, ids["org"])


@pytest_asyncio.fixture
async def org_b(engine):
    ids = await _mk_org(engine, "B")
    yield ids
    await _drop(engine, ids["org"])


def H(uid):
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


async def _eff(client, org, emp, d):
    r = await client.get(f"{B}/effective", params={"employee_id": str(emp), "date": d}, headers=H(org["admin"]))
    assert r.status_code == 200, r.text
    return r.json()


async def test_resolution_order(client, org):
    a, D = H(org["admin"]), "2026-11-02"  # a Monday
    assert (await _eff(client, org, org["emp"], D))["has_break"] is False

    r = await client.put(f"{B}/policy", json={"start_time": "13:00", "duration_minutes": 60}, headers=a)
    assert r.status_code == 200, r.text
    e = await _eff(client, org, org["emp"], D)
    assert (e["source"], e["start_time"]) == ("organization", "13:00")
    assert e["start"].startswith("2026-11-02T13:00") and e["end"].startswith("2026-11-02T14:00")

    r = await client.post(f"{B}/policies", json={"scope": "department", "scope_id": str(org["dept"]),
                                                 "start_time": "12:30", "duration_minutes": 45}, headers=a)
    assert r.status_code == 201, r.text
    assert (await _eff(client, org, org["emp"], D))["source"] == "department"
    assert (await _eff(client, org, org["emp2"], D))["source"] == "organization"  # no dept

    r = await client.post(f"{B}/policies", json={"scope": "employee", "scope_id": str(org["emp"]),
                                                 "start_time": "12:00", "days": [0]}, headers=a)
    assert r.status_code == 201
    assert (await _eff(client, org, org["emp"], D))["source"] == "employee"
    assert (await _eff(client, org, org["emp"], "2026-11-03"))["source"] == "department"  # Tuesday: days=[0] skips

    r = await client.post(f"{B}/overrides", json={"department_id": str(org["dept"]), "on_date": D,
                                                  "start_time": "15:00", "duration_minutes": 30}, headers=a)
    assert r.status_code == 201, r.text
    e = await _eff(client, org, org["emp"], D)
    assert (e["source"], e["start_time"], e["duration_minutes"]) == ("override_department", "15:00", 30)

    r = await client.post(f"{B}/overrides", json={"employee_ids": [str(org["emp"])], "on_date": D}, headers=a)
    assert r.status_code == 201
    assert (await _eff(client, org, org["emp"], D))["has_break"] is False  # "no break today"
    assert (await _eff(client, org, org["emp"], "2026-11-03"))["has_break"] is True

    # edit + delete any time
    pid = (await client.get(f"{B}/policies", headers=a)).json()
    emp_pol = next(p for p in pid if p["scope"] == "employee")
    r = await client.put(f"{B}/policies/{emp_pol['id']}", json={"scope": "employee", "scope_id": str(org["emp"]),
                                                                "start_time": "11:00"}, headers=a)
    assert r.json()["start_time"] == "11:00"
    assert (await client.delete(f"{B}/policies/{emp_pol['id']}", headers=a)).status_code == 204
    assert all(p["id"] != emp_pol["id"] for p in (await client.get(f"{B}/policies", headers=a)).json())


async def test_validation_and_tenant_isolation(client, org, org_b):
    a = H(org["admin"])
    assert (await client.post(f"{B}/policies", json={"scope": "employee", "start_time": "12:00"}, headers=a)).status_code == 422
    # other tenant's employee / department cannot be targeted
    r = await client.post(f"{B}/policies", json={"scope": "employee", "scope_id": str(org_b["emp"]),
                                                 "start_time": "12:00"}, headers=a)
    assert r.status_code == 404
    r = await client.post(f"{B}/overrides", json={"employee_ids": [str(org_b["emp"])], "on_date": "2026-11-02"}, headers=a)
    assert r.status_code == 404
    assert (await client.get(f"{B}/effective", params={"employee_id": str(org_b["emp"])}, headers=a)).status_code == 404


async def test_non_admin_is_forbidden(client, org):
    w = H(org["worker"])
    assert (await client.get(f"{B}/policies", headers=w)).status_code == 403
    assert (await client.put(f"{B}/policy", json={"start_time": "12:00"}, headers=w)).status_code == 403
    assert (await client.get(f"{B}/unlock-requests", headers=w)).status_code == 403


def _now_window(minutes_ago=10, duration=60):
    n = datetime.now(UTC)
    if not (timedelta(minutes=70) < timedelta(hours=n.hour, minutes=n.minute) < timedelta(hours=23)):
        pytest.skip("too close to midnight UTC for a relative-window test")
    return (n - timedelta(minutes=minutes_ago)).strftime("%H:%M"), duration


async def test_lock_request_approve_and_deny(client, org, org_b):
    a, w = H(org["admin"]), H(org["worker"])
    start, dur = _now_window()
    assert (await client.put(f"{B}/policy", json={"start_time": start, "duration_minutes": dur}, headers=a)).status_code == 200

    st = (await client.get(f"{B}/me", headers=w)).json()
    assert st["phase"] == "active" and st["locked"] is True and st["seconds_to_end"] > 0 and st["server_time"]

    r = await client.post(f"{B}/unlock-requests", json={"reason": "deadline"}, headers=w)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert (await client.post(f"{B}/unlock-requests", json={}, headers=w)).status_code == 409  # one pending at a time
    assert (await client.get(f"{B}/me", headers=w)).json()["locked"] is True  # still locked until decided

    lst = (await client.get(f"{B}/unlock-requests", params={"status": "pending"}, headers=a)).json()
    assert lst["pending_count"] == 1 and lst["items"][0]["employee_code"] == "EMP-7"

    # a non-approver and another tenant's admin cannot decide
    assert (await client.post(f"{B}/unlock-requests/{rid}/approve", headers=w)).status_code == 403
    assert (await client.post(f"{B}/unlock-requests/{rid}/approve", headers=H(org_b["admin"]))).status_code == 404

    # deny keeps the machine locked
    assert (await client.post(f"{B}/unlock-requests/{rid}/deny", headers=a)).json()["status"] == "denied"
    me = (await client.get(f"{B}/me", headers=w)).json()
    assert me["locked"] is True and me["request"]["status"] == "denied"
    assert (await client.post(f"{B}/unlock-requests/{rid}/approve", headers=a)).status_code == 409  # already decided

    # ask again → approve → unlocked until break end
    rid2 = (await client.post(f"{B}/unlock-requests", json={}, headers=w)).json()["id"]
    assert (await client.post(f"{B}/unlock-requests/{rid2}/approve", headers=a)).json()["status"] == "approved"
    me = (await client.get(f"{B}/me", headers=w)).json()
    assert me["locked"] is False and me["unlocked_by_admin"] is True and me["phase"] == "active"


async def test_no_unlock_request_outside_break(client, org):
    start, _ = _now_window(minutes_ago=-30)  # starts in 30 minutes
    await client.put(f"{B}/policy", json={"start_time": start, "duration_minutes": 60}, headers=H(org["admin"]))
    me = (await client.get(f"{B}/me", headers=H(org["worker"]))).json()
    assert me["phase"] == "upcoming" and me["locked"] is False
    assert (await client.post(f"{B}/unlock-requests", json={}, headers=H(org["worker"]))).status_code == 400


async def test_warning_phase_and_over(client, org):
    a, w = H(org["admin"]), H(org["worker"])
    start, _ = _now_window(minutes_ago=-3)
    await client.put(f"{B}/policy", json={"start_time": start, "duration_minutes": 30}, headers=a)
    assert (await client.get(f"{B}/me", headers=w)).json()["phase"] == "warning"
    start, _ = _now_window(minutes_ago=90)
    await client.put(f"{B}/policy", json={"start_time": start, "duration_minutes": 30}, headers=a)
    me = (await client.get(f"{B}/me", headers=w)).json()
    assert me["phase"] == "over" and me["locked"] is False
