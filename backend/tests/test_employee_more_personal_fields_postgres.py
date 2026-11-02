"""
E-03: tax / EOBI / PF / visa numbers and more personal details, saved on
Add and Edit, with the ID-class numbers visible only to the person
themselves or to someone with employees.update. Live Postgres, real HTTP.
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

NEW = dict(
    national_id_type="cnic", tax_number="NTN-123", social_security_number="EOBI-9",
    provident_fund_number="PF-7", visa_number="V-55", visa_expiry="2030-05-01",
    religion="Islam", place_of_birth="Bahawalpur", home_phone="062-111",
    previous_employee_id="OLD-1", referral_source="LinkedIn", hobbies="Cricket",
    tshirt_size="L", social_links={"linkedin": "https://linkedin.com/in/x"},
)


async def _make(client, org, **extra):
    r = await client.post("/api/v1/employees", headers=_h(org["owner"]), json={
        "first_name": "Eve", "last_name": "Test", "email": f"e-{uuid.uuid4().hex[:6]}@example.com",
        "date_of_joining": "2026-01-01", "role_id": str(org["role"]), **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_add_saves_new_fields_and_edit_changes_them(client, org):
    emp_id = await _make(client, org, **NEW)
    h = _h(org["owner"])
    d = (await client.get(f"/api/v1/employees/{emp_id}", headers=h)).json()
    for k, v in NEW.items():
        assert d[k] == v, k
    r = await client.patch(f"/api/v1/employees/{emp_id}", headers=h,
                           json={"tax_number": "NTN-999", "hobbies": None})
    assert r.status_code == 200, r.text
    d = (await client.get(f"/api/v1/employees/{emp_id}", headers=h)).json()
    assert d["tax_number"] == "NTN-999" and d["hobbies"] is None and d["religion"] == "Islam"


async def test_id_numbers_hidden_from_view_only_users(client, engine, org):
    emp_id = await _make(client, org, **NEW)
    viewer = await _role_user(engine, org, ["employees.view"], "Viewer")
    editor = await _role_user(engine, org, ["employees.view", "employees.update"], "Edit")
    gated = ("tax_number", "social_security_number", "provident_fund_number", "visa_number")
    d = (await client.get(f"/api/v1/employees/{emp_id}", headers=_h(viewer))).json()
    assert all(d[k] is None for k in gated)
    d = (await client.get(f"/api/v1/employees/{emp_id}", headers=_h(editor))).json()
    assert all(d[k] == NEW[k] for k in gated)


async def test_too_long_value_is_rejected(client, org):
    r = await client.post("/api/v1/employees", headers=_h(org["owner"]), json={
        "first_name": "Eve", "last_name": "Test", "email": f"e-{uuid.uuid4().hex[:6]}@example.com",
        "date_of_joining": "2026-01-01", "role_id": str(org["role"]), "tshirt_size": "XXXXXXX"})
    assert r.status_code in (400, 422)
