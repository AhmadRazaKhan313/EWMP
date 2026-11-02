"""
E-06: employee document title is required only for type "Other" (real HTTP, live Postgres).
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
            "DELETE FROM employee_documents WHERE tenant_id = :o",
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



PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


async def _upload(client, org, emp, document_type, title=None):
    data = {"document_type": document_type}
    if title is not None:
        data["title"] = title
    return await client.post(
        f"/api/v1/employees/{emp['id']}/documents", headers=_h(org["owner"]),
        data=data, files={"file": ("scan.pdf", PDF, "application/pdf")},
    )


class TestOtherNeedsATitle:
    async def test_other_without_title_is_rejected(self, client, engine, org):
        emp = await _employee(client, engine, org, "Docs")
        for blank in (None, "", "   "):
            r = await _upload(client, org, emp, "other", blank)
            assert r.status_code == 400, r.text
            assert "title" in r.text.lower()

    async def test_other_with_title_is_stored_trimmed(self, client, engine, org):
        emp = await _employee(client, engine, org, "Docs")
        r = await _upload(client, org, emp, "other", "  Signed addendum ")
        assert r.status_code == 201, r.text
        assert r.json()["title"] == "Signed addendum"

    async def test_other_types_need_no_title_and_default_to_the_type(self, client, engine, org):
        emp = await _employee(client, engine, org, "Docs")
        r = await _upload(client, org, emp, "passport")
        assert r.status_code == 201, r.text
        assert r.json()["title"] == "Passport"
        r = await _upload(client, org, emp, "passport", "Passport page 2")
        assert r.json()["title"] == "Passport page 2"
