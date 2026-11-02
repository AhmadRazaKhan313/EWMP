"""
Phase 1 security fixes (S-01 ... S-05), real HTTP stack + live Postgres.

S-01 holidays.manage is in the registry (and the seed is idempotent)
S-02 shift create/update/delete need shifts.manage, not attendance.view
S-03 salary / national id only for self, employees.update or view_salary
S-04 ids from another organization are refused (recruitment, performance, helpdesk)
S-05 an unknown status/priority is a 422, never a 500
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


# ── S-01 ─────────────────────────────────────────────────────────────────────
def test_every_permission_used_by_a_route_is_in_the_registry():
    import pathlib, re
    from app.database.seeds.permissions import PERMISSIONS_BY_CODENAME

    used = set()
    for f in pathlib.Path("app").rglob("*.py"):
        used |= set(re.findall(r'require_permission\(\s*["\']([a-z_]+\.[a-z_]+)["\']', f.read_text(encoding="utf-8")))
    assert used - set(PERMISSIONS_BY_CODENAME) == set()
    assert {"holidays.manage", "shifts.manage"} <= set(PERMISSIONS_BY_CODENAME)


async def test_seeding_permissions_twice_does_not_duplicate(engine):
    import subprocess, sys

    # A fresh process each time (like `python manage.py seed --permissions`):
    # manage.py uses the app's global engine, which is bound to whichever event
    # loop first used it, so it can't be awaited from inside another test's loop.
    for _ in range(2):
        done = subprocess.run(
            [sys.executable, "-c", "import asyncio, manage; asyncio.run(manage.seed_permissions())"],
            capture_output=True, text=True, timeout=120,
        )
        assert done.returncode == 0, done.stderr[-800:]
    async with AsyncSession(engine) as s:
        n = (await s.execute(text("SELECT count(*) FROM permissions WHERE codename IN ('holidays.manage','shifts.manage')"))).scalar_one()
    assert n == 2


async def test_hr_role_with_holidays_manage_can_add_edit_delete(client, engine, org):
    hr = await _role_user(engine, org, ["holidays.manage"])
    nobody = await _role_user(engine, org, ["attendance.view"], "Viewer")
    r = await client.post("/api/v1/holidays", headers=_h(nobody), json={"name": "X", "date": "2026-12-25"})
    assert r.status_code == 403
    r = await client.post("/api/v1/holidays", headers=_h(hr), json={"name": "Christmas", "date": "2026-12-25"})
    assert r.status_code == 201, r.text
    hid = r.json()["id"]
    assert (await client.patch(f"/api/v1/holidays/{hid}", headers=_h(hr), json={"name": "Quaid Day"})).status_code == 200
    assert (await client.delete(f"/api/v1/holidays/{hid}", headers=_h(nobody))).status_code == 403
    assert (await client.delete(f"/api/v1/holidays/{hid}", headers=_h(hr))).status_code == 204


# ── S-02 ─────────────────────────────────────────────────────────────────────
async def test_shift_writes_need_shifts_manage_not_attendance_view(client, engine, org):
    viewer = await _role_user(engine, org, ["attendance.view"], "Viewer")
    manager = await _role_user(engine, org, ["shifts.manage", "attendance.view"], "Mgr")
    sid = await _shift(client, org)
    body = {"name": "Night", "code": "NGT", "start_time": "21:00", "end_time": "05:00"}
    assert (await client.get("/api/v1/shifts", headers=_h(viewer))).status_code == 200
    assert (await client.post("/api/v1/shifts", headers=_h(viewer), json=body)).status_code == 403
    assert (await client.patch(f"/api/v1/shifts/{sid}", headers=_h(viewer), json={"name": "Z"})).status_code == 403
    assert (await client.delete(f"/api/v1/shifts/{sid}", headers=_h(viewer))).status_code == 403
    assert (await client.post("/api/v1/shifts", headers=_h(manager), json=body)).status_code == 201
    assert (await client.patch(f"/api/v1/shifts/{sid}", headers=_h(manager), json={"name": "Z"})).status_code == 200
    assert (await client.delete(f"/api/v1/shifts/{sid}", headers=_h(manager))).status_code == 204


# ── S-03 ─────────────────────────────────────────────────────────────────────
async def test_salary_and_national_id_are_gated(client, engine, org):
    r = await client.post("/api/v1/employees", headers=_h(org["owner"]), json={
        "first_name": "Zed", "last_name": "Target", "email": f"zed-{uuid.uuid4().hex[:6]}@example.com",
        "date_of_joining": "2026-01-01", "role_id": str(org["role"]),
        "current_salary": "125000", "national_id": "35202-1234567-1", "passport_number": "AB123"})
    assert r.status_code == 201, r.text
    emp_id = r.json()["id"]
    async with AsyncSession(engine) as s:
        target_user = (await s.execute(text("SELECT user_id FROM employees WHERE id = :i"), {"i": emp_id})).scalar_one()
        await s.execute(text("UPDATE users SET must_change_password = false WHERE id = :u"), {"u": target_user})
        await s.commit()

    viewer = await _role_user(engine, org, ["employees.view"], "Viewer")
    payroll = await _role_user(engine, org, ["employees.view", "employees.view_salary"], "Pay")
    editor = await _role_user(engine, org, ["employees.view", "employees.update"], "Edit")

    async def get(uid):
        r = await client.get(f"/api/v1/employees/{emp_id}", headers=_h(uid))
        assert r.status_code == 200, r.text
        return r.json()

    d = await get(viewer)
    assert d["current_salary"] is None and d["national_id"] is None and d["passport_number"] is None
    assert "bank_name" not in d
    d = await get(payroll)
    assert d["current_salary"] == "125000.00" or d["current_salary"] == "125000"
    assert d["national_id"] is None
    d = await get(editor)
    assert d["current_salary"] and d["national_id"] == "35202-1234567-1" and d["passport_number"] == "AB123"
    d = await get(target_user)  # the person themselves
    assert d["current_salary"] and d["national_id"] == "35202-1234567-1"


# ── S-04 / S-05 ──────────────────────────────────────────────────────────────
async def test_recruitment_refuses_other_orgs_ids_and_bad_status(client, org, other_org):
    me, foe = _h(org["owner"]), _h(other_org["owner"])
    foreign_job = (await client.post("/api/v1/recruitment/jobs", headers=foe, json={"title": "Secret"})).json()["id"]
    own_job = (await client.post("/api/v1/recruitment/jobs", headers=me, json={"title": "Mine"})).json()["id"]
    applicant = {"first_name": "A", "last_name": "B", "email": "a@b.com"}

    r = await client.post("/api/v1/recruitment/applicants", headers=me, json={**applicant, "job_posting_id": foreign_job})
    assert r.status_code == 404
    r = await client.patch(f"/api/v1/recruitment/jobs/{foreign_job}", headers=me, json={"title": "hijack"})
    assert r.status_code == 404
    r = await client.post("/api/v1/recruitment/jobs", headers=me, json={"title": "T", "department_id": str(uuid.uuid4())})
    assert r.status_code == 404

    r = await client.post("/api/v1/recruitment/applicants", headers=me, json={**applicant, "job_posting_id": own_job})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert (await client.patch(f"/api/v1/recruitment/applicants/{aid}/stage", headers=me, json={"status": "nonsense"})).status_code == 422
    assert (await client.patch(f"/api/v1/recruitment/jobs/{own_job}", headers=me, json={"status": "nonsense"})).status_code == 422
    assert (await client.get("/api/v1/recruitment/jobs", headers=me, params={"status": "nonsense"})).status_code == 422
    assert (await client.patch(f"/api/v1/recruitment/applicants/{aid}/stage", headers=me, json={"status": "interview"})).status_code == 200
    assert (await client.patch(f"/api/v1/recruitment/jobs/{own_job}", headers=me, json={"status": "closed"})).status_code == 200


async def test_performance_refuses_other_orgs_employees_and_bad_status(client, org, other_org):
    me = _h(org["owner"])
    foreign = await _employee(client, other_org, "Foe")
    mine = await _employee(client, org, "Mine")
    other_mine = await _employee(client, org, "Rev")

    r = await client.post("/api/v1/performance/goals", headers=me, json={"employee_id": foreign["id"], "title": "g"})
    assert r.status_code == 404
    review = {"review_period": "H1", "review_year": 2026}
    r = await client.post("/api/v1/performance/reviews", headers=me, json={**review, "employee_id": foreign["id"], "reviewer_id": other_mine["id"]})
    assert r.status_code == 404
    r = await client.post("/api/v1/performance/reviews", headers=me, json={**review, "employee_id": mine["id"], "reviewer_id": foreign["id"]})
    assert r.status_code == 404
    r = await client.post("/api/v1/performance/reviews", headers=me, json={**review, "employee_id": mine["id"], "reviewer_id": other_mine["id"]})
    assert r.status_code == 201, r.text

    gid = (await client.post("/api/v1/performance/goals", headers=me, json={"employee_id": mine["id"], "title": "g"})).json()["id"]
    assert (await client.patch(f"/api/v1/performance/goals/{gid}", headers=me, json={"status": "bogus"})).status_code == 422
    assert (await client.get("/api/v1/performance/goals", headers=me, params={"status": "bogus"})).status_code == 422
    assert (await client.patch(f"/api/v1/performance/goals/{gid}", headers=me, json={"status": "in_progress"})).status_code == 200


async def test_helpdesk_refuses_bad_priority_status_and_foreign_ids(client, org, other_org):
    me = _h(org["owner"])
    foreign = await _employee(client, other_org, "Foe")
    r = await client.post("/api/v1/helpdesk/tickets", headers=me, json={"title": "t", "priority": "urgent!!"})
    assert r.status_code == 422
    r = await client.post("/api/v1/helpdesk/tickets", headers=me, json={"title": "t", "device_id": str(uuid.uuid4())})
    assert r.status_code == 404
    r = await client.post("/api/v1/helpdesk/tickets", headers=me, json={"title": "t", "priority": "high"})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert (await client.patch(f"/api/v1/helpdesk/tickets/{tid}", headers=me, json={"status": "bogus"})).status_code == 422
    assert (await client.patch(f"/api/v1/helpdesk/tickets/{tid}", headers=me, json={"priority": "bogus"})).status_code == 422
    assert (await client.get("/api/v1/helpdesk/tickets", headers=me, params={"priority": "bogus"})).status_code == 422
    assert (await client.patch(f"/api/v1/helpdesk/tickets/{tid}", headers=me, json={"assignee_id": foreign["id"]})).status_code == 404
    r = await client.patch(f"/api/v1/helpdesk/tickets/{tid}", headers=me, json={"status": "resolved"})
    assert r.status_code == 200
