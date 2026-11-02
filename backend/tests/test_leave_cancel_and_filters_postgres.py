"""
B-02 / B-03: leave cancel endpoint + leave list filters (real HTTP stack, live Postgres).
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


async def _shift(client, org, name="Day", start="09:00", end="18:00", **kw) -> str:
    r = await client.post("/api/v1/shifts", headers=_h(org["owner"]),
                          json={"name": name, "code": name[:3].upper(), "start_time": start, "end_time": end, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _employee(client, org, name) -> dict:
    r = await client.post("/api/v1/employees", headers=_h(org["owner"]), json={"first_name": name, "last_name": "Hire", "email": f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.com", "date_of_joining": "2026-01-01", "role_id": str(org["role"])})
    assert r.status_code == 201, r.text
    return {"id": r.json()["id"]}


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




async def _leave_type(client, org, days=10) -> str:
    r = await client.post("/api/v1/leave/types", headers=_h(org["owner"]), json={"name": "Annual", "code": f"AL{uuid.uuid4().hex[:4]}", "days_per_year": days})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _worker(client, engine, org, name, perms=("leave.apply",)):
    """An employee (with a login) holding `perms`."""
    uid = await _role_user(engine, org, list(perms), name)
    async with AsyncSession(engine) as s:
        email = (await s.execute(text("SELECT email FROM users WHERE id = :u"), {"u": uid})).scalar_one()
        await s.execute(text("INSERT INTO employees (id, tenant_id, user_id, employee_code, employment_type, employment_status, job_nature, date_of_joining, currency, is_remote, is_deleted, created_at, updated_at) "
                             "VALUES (:i, :t, :u, :c, 'FULL_TIME', 'ACTIVE', 'PERMANENT', '2026-01-01', 'PKR', false, false, now(), now())"),
                        {"i": uuid.uuid4(), "t": org["org"], "u": uid, "c": f"E-{uuid.uuid4().hex[:6]}"})
        eid = (await s.execute(text("SELECT id FROM employees WHERE user_id = :u"), {"u": uid})).scalar_one()
        await s.commit()
    return {"user": uid, "emp": str(eid)}


async def _apply(client, who, lt, start, end):
    r = await client.post("/api/v1/leave/requests", headers=_h(who["user"]),
                          json={"leave_type_id": lt, "start_date": start, "end_date": end, "reason": "t"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _balance(client, org, who):
    r = await client.get("/api/v1/leave/balances", headers=_h(org["owner"]), params={"employee_id": who["emp"], "year": 2030})
    assert r.status_code == 200, r.text
    items = r.json() if isinstance(r.json(), list) else r.json().get("items", r.json())
    return items[0] if isinstance(items, list) else items


async def test_employee_can_cancel_a_pending_request_and_gets_the_days_back(client, engine, org):
    lt = await _leave_type(client, org)
    me = await _worker(client, engine, org, "Emp")
    rid = await _apply(client, me, lt, "2030-03-04", "2030-03-05")
    assert (await _balance(client, org, me))["pending_days"] == 2
    r = await client.post(f"/api/v1/leave/requests/{rid}/cancel", headers=_h(me["user"]))
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    assert (await _balance(client, org, me))["pending_days"] == 0
    # cancelling twice is refused, not a silent double refund
    assert (await client.post(f"/api/v1/leave/requests/{rid}/cancel", headers=_h(me["user"]))).status_code == 409


async def test_nobody_else_can_cancel_it(client, engine, org):
    lt = await _leave_type(client, org)
    me = await _worker(client, engine, org, "Emp")
    other = await _worker(client, engine, org, "Other")
    rid = await _apply(client, me, lt, "2030-03-04", "2030-03-04")
    assert (await client.post(f"/api/v1/leave/requests/{rid}/cancel", headers=_h(other["user"]))).status_code == 403
    assert (await client.post(f"/api/v1/leave/requests/{rid}/cancel", headers=_h(uuid.uuid4()))).status_code in (401, 403)


async def test_approved_future_leave_can_be_cancelled_and_used_days_come_back(client, engine, org):
    lt = await _leave_type(client, org)
    me = await _worker(client, engine, org, "Emp")
    rid = await _apply(client, me, lt, "2030-03-04", "2030-03-05")
    assert (await client.post(f"/api/v1/leave/requests/{rid}/approve", headers=_h(org["owner"]))).status_code == 200
    assert (await _balance(client, org, me))["used_days"] == 2
    r = await client.post(f"/api/v1/leave/requests/{rid}/cancel", headers=_h(me["user"]))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    b = await _balance(client, org, me)
    assert (b["used_days"], b["pending_days"]) == (0, 0)


async def test_manager_cancelling_an_approved_request_marks_it_revoked(client, engine, org):
    lt = await _leave_type(client, org)
    me = await _worker(client, engine, org, "Emp")
    rid = await _apply(client, me, lt, "2030-03-04", "2030-03-04")
    await client.post(f"/api/v1/leave/requests/{rid}/approve", headers=_h(org["owner"]))
    r = await client.post(f"/api/v1/leave/requests/{rid}/cancel", headers=_h(org["owner"]))
    assert r.status_code == 200 and r.json()["status"] == "revoked"


async def test_leave_that_already_started_cannot_be_cancelled(client, engine, org):
    lt = await _leave_type(client, org, days=400)
    me = await _worker(client, engine, org, "Emp")
    rid = await _apply(client, me, lt, "2026-01-05", "2026-01-05")     # in the past
    await client.post(f"/api/v1/leave/requests/{rid}/approve", headers=_h(org["owner"]))
    assert (await client.post(f"/api/v1/leave/requests/{rid}/cancel", headers=_h(me["user"]))).status_code == 409


async def test_rejected_request_cannot_be_cancelled(client, engine, org):
    lt = await _leave_type(client, org)
    me = await _worker(client, engine, org, "Emp")
    rid = await _apply(client, me, lt, "2030-03-04", "2030-03-04")
    await client.post(f"/api/v1/leave/requests/{rid}/reject", headers=_h(org["owner"]), json={"reason": "no"})
    assert (await client.post(f"/api/v1/leave/requests/{rid}/cancel", headers=_h(me["user"]))).status_code == 409


async def test_list_filters_by_leave_type_dates_and_status(client, engine, org):
    sick = await _leave_type(client, org)
    annual = await _leave_type(client, org)
    me = await _worker(client, engine, org, "Emp")
    march = await _apply(client, me, sick, "2030-03-04", "2030-03-06")
    june = await _apply(client, me, annual, "2030-06-10", "2030-06-10")
    await client.post(f"/api/v1/leave/requests/{june}/approve", headers=_h(org["owner"]))

    async def ids(**params):
        r = await client.get("/api/v1/leave/requests", headers=_h(org["owner"]), params=params)
        assert r.status_code == 200, r.text
        return {i["id"] for i in r.json()["items"]}

    assert await ids() == {march, june}
    assert await ids(leave_type_id=sick) == {march}
    assert await ids(date_from="2030-06-01", date_to="2030-06-30") == {june}
    assert await ids(date_from="2030-03-06") == {march, june}           # overlaps: march ends on the 6th
    assert await ids(date_to="2030-03-03") == set()
    assert await ids(status="approved") == {june}
    assert await ids(status="approved", leave_type_id=sick) == set()
    bad = await client.get("/api/v1/leave/requests", headers=_h(org["owner"]), params={"status": "bogus"})
    assert bad.status_code == 422
    bad = await client.get("/api/v1/leave/requests", headers=_h(org["owner"]), params={"date_from": "2030-07-01", "date_to": "2030-06-01"})
    assert bad.status_code in (400, 422)
