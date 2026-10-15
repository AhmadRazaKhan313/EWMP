"""
Employee creation -> temporary password -> first login -> change password.

Regression for: "the employee is saved, but the admin sees a generic error and
never gets the temporary password". The create handler queued the verification
email through Celery's blocking .delay() inside the request, so a slow or
unreachable broker held the response for 20s+ (the browser gave up at 30s)
although the row was already written.

Real HTTP stack + live Postgres (TEST_DATABASE_URL), like the other
*_postgres tests.
"""

import os
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.main import app
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.rbac import Role
from app.models.user import User
from app.workers.tasks import email as email_tasks

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
pytestmark = pytest.mark.asyncio

OWNER_PASSWORD = "Str0ngPassw0rd!x"
NEW_PASSWORD = "MyNewPerm4nent!Pass"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_EMAIL_PER_MINUTE", 1000)
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_IP_PER_MINUTE", 1000)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE", 1000)
    # Only used by the fixed code (a no-op attribute on the old one).
    monkeypatch.setattr(settings, "EMAIL_QUEUE_TIMEOUT_SECONDS", 0.3, raising=False)


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


@pytest_asyncio.fixture
async def org(engine):
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Create Org", slug=f"create-{org_id.hex[:8]}",
                           email=f"c-{org_id.hex[:8]}@example.com"))
        await s.flush()
        staff = Role(organization_id=org_id, name="Staff", slug="staff", permissions=[])
        s.add(staff)
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        owner = User(organization_id=org_id, email=email, email_normalized=email,
                     password_hash=hash_password(OWNER_PASSWORD), first_name="Owner",
                     last_name="Test", is_active=True, is_email_verified=True)
        s.add(owner)
        await s.flush()
        (await s.get(Organization, org_id)).owner_id = owner.id
        ids = {"org": org_id, "owner": owner.id, "owner_email": email, "role": staff.id}
        await s.commit()
    yield ids
    async with AsyncSession(engine) as s:
        await s.execute(text(
            "DELETE FROM auth_refresh_tokens WHERE user_id IN "
            "(SELECT id FROM users WHERE organization_id = :o)"), {"o": org_id})
        await s.execute(delete(Employee).where(Employee.tenant_id == org_id))
        await s.execute(text("UPDATE organizations SET owner_id = NULL WHERE id = :o"), {"o": org_id})
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


async def _owner_headers(client, org) -> dict:
    r = await client.post("/api/v1/auth/login", json={"email": org["owner_email"], "password": OWNER_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}


def _payload(org, email=None) -> dict:
    return {"first_name": "New", "last_name": "Hire",
            "email": email or f"new-{uuid.uuid4().hex[:8]}@example.com",
            "date_of_joining": "2026-01-01", "role_id": str(org["role"])}


# ── The bug: a slow / broken broker must not hold up or fail the create ───────

class TestCreateDoesNotDependOnTheBroker:
    async def test_a_hanging_broker_does_not_hold_the_response(self, client, org, monkeypatch):
        """THE regression. The broker call blocks for 3s; the admin's response
        (with the temporary password) must not wait for it."""
        monkeypatch.setattr(email_tasks.send_verification_email, "delay",
                            lambda to, token: time.sleep(3))
        h = await _owner_headers(client, org)
        t0 = time.monotonic()
        r = await client.post("/api/v1/employees", headers=h, json=_payload(org))
        elapsed = time.monotonic() - t0
        assert r.status_code == 201, r.text
        assert r.json()["temporary_password"]
        assert elapsed < 1.5, f"the response waited {elapsed:.1f}s for the email broker"

    async def test_a_failing_broker_still_returns_the_password(self, client, org, monkeypatch):
        def boom(to, token):
            raise RuntimeError("broker down")
        monkeypatch.setattr(email_tasks.send_verification_email, "delay", boom)
        h = await _owner_headers(client, org)
        r = await client.post("/api/v1/employees", headers=h, json=_payload(org))
        assert r.status_code == 201, r.text
        assert r.json()["temporary_password"]

    async def test_a_healthy_broker_still_gets_the_verification_email(self, client, org, monkeypatch):
        sent = []
        monkeypatch.setattr(email_tasks.send_verification_email, "delay",
                            lambda to, token: sent.append((to, token)))
        h = await _owner_headers(client, org)
        payload = _payload(org)
        assert (await client.post("/api/v1/employees", headers=h, json=payload)).status_code == 201
        assert len(sent) == 1 and sent[0][0] == payload["email"] and sent[0][1]


# ── The password is exposed once, and only in the create response ─────────────

class TestTemporaryPasswordExposure:
    async def test_only_the_create_response_carries_it_and_it_is_never_stored_plain(
        self, client, engine, org, monkeypatch
    ):
        monkeypatch.setattr(email_tasks.send_verification_email, "delay", lambda to, token: None)
        h = await _owner_headers(client, org)
        payload = _payload(org)
        r = await client.post("/api/v1/employees", headers=h, json=payload)
        assert r.status_code == 201
        temp, emp_id = r.json()["temporary_password"], r.json()["id"]

        for url in ("/api/v1/employees", f"/api/v1/employees/{emp_id}"):
            body = (await client.get(url, headers=h)).text
            assert temp not in body and "temporary_password" not in body, url

        async with AsyncSession(engine) as s:
            user = (await s.execute(select(User).where(User.email == payload["email"]))).scalar_one()
        assert user.password_hash != temp and temp not in user.password_hash
        assert verify_password(temp, user.password_hash)
        assert user.must_change_password is True


# ── First login -> forced change -> normal login ──────────────────────────────

class TestFirstLoginFlow:
    async def _new_employee(self, client, org, monkeypatch):
        monkeypatch.setattr(email_tasks.send_verification_email, "delay", lambda to, token: None)
        h = await _owner_headers(client, org)
        payload = _payload(org)
        r = await client.post("/api/v1/employees", headers=h, json=payload)
        assert r.status_code == 201, r.text
        return payload["email"], r.json()["temporary_password"]

    async def test_temp_login_is_flagged_and_only_the_change_flow_works(self, client, org, monkeypatch):
        email, temp = await self._new_employee(client, org, monkeypatch)
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": temp})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["must_change_password"] is True
        h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
        assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 200
        blocked = await client.get("/api/v1/employees", headers=h)
        assert blocked.status_code == 403 and "PASSWORD_CHANGE_REQUIRED" in blocked.text

    async def test_changing_it_clears_the_flag_and_normal_login_follows(self, client, org, monkeypatch):
        email, temp = await self._new_employee(client, org, monkeypatch)
        login = (await client.post("/api/v1/auth/login", json={"email": email, "password": temp})).json()
        h = {"Authorization": f"Bearer {login['tokens']['access_token']}"}
        r = await client.post("/api/v1/auth/change-password", headers=h, json={
            "current_password": temp, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD})
        assert r.status_code == 200, r.text
        again = await client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
        assert again.status_code == 200 and again.json()["user"]["must_change_password"] is False
        old = await client.post("/api/v1/auth/login", json={"email": email, "password": temp})
        assert old.status_code == 401

    async def test_an_existing_employee_is_not_forced_to_reset(self, client, org):
        r = await client.post("/api/v1/auth/login",
                              json={"email": org["owner_email"], "password": OWNER_PASSWORD})
        assert r.status_code == 200 and r.json()["user"]["must_change_password"] is False


# ── A genuine failure is reported as what it is ───────────────────────────────

class TestGenuineFailures:
    async def test_duplicate_email_is_a_clear_409_with_a_message(self, client, org, monkeypatch):
        monkeypatch.setattr(email_tasks.send_verification_email, "delay", lambda to, token: None)
        h = await _owner_headers(client, org)
        payload = _payload(org)
        assert (await client.post("/api/v1/employees", headers=h, json=payload)).status_code == 201
        dup = await client.post("/api/v1/employees", headers=h, json=payload)
        assert dup.status_code == 409
        assert "already exists" in dup.json()["message"]
