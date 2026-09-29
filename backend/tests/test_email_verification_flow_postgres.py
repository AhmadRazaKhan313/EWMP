"""
Regression tests for audit finding C-3: with REQUIRE_EMAIL_VERIFICATION on
(the default, and the production setting) the whole verification flow was a
dead end.

  * Admin-created accounts (POST /employees, POST /auth/register-employee)
    got no verification token and no email.
  * /auth/change-password required a VERIFIED user, so an invited employee
    couldn't even replace their temporary password.
  * There was no way to resend a verification email.
  * A password-reset link (which also proves inbox ownership) didn't count.
  * Email links pointed at a hardcoded https://app.ewmp.io.

Runs the real HTTP stack against a live Postgres (TEST_DATABASE_URL, same
convention as the other *_postgres tests). Emails are captured, never sent.
"""

import os
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.rbac import Permission, Role
from app.models.user import User
from app.workers.tasks import email as email_tasks

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def verification_on(monkeypatch):
    """The production default — the setting the dev .env had turned off."""
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)


@pytest.fixture
def sent_emails(monkeypatch):
    """Capture queued verification emails instead of hitting Celery/SMTP."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        email_tasks.send_verification_email, "delay", lambda to, token: sent.append((to, token))
    )
    return sent


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


async def _permission(session, codename):
    perm = (await session.execute(select(Permission).where(Permission.codename == codename))).scalar_one_or_none()
    if perm is None:
        resource, action = codename.split(".", 1)
        perm = Permission(resource=resource, action=action, codename=codename, label=codename, category=resource)
        session.add(perm)
        await session.flush()
    return perm


@pytest_asyncio.fixture
async def org(engine):
    """An org whose (verified) owner creates employees; a 'Staff' role that
    can view the employee list — the permission-gated call we probe."""
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Verify Org", slug=f"verify-{org_id.hex[:8]}",
                           email=f"verify-{org_id.hex[:8]}@example.com"))
        await s.flush()
        staff = Role(organization_id=org_id, name="Staff", slug="staff",
                     permissions=[await _permission(s, "employees.view")])
        s.add(staff)
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        owner = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                     first_name="Owner", last_name="Test", is_active=True, is_email_verified=True)
        s.add(owner)
        await s.flush()
        (await s.get(Organization, org_id)).owner_id = owner.id
        ids = {"org": org_id, "owner": owner.id, "staff_role": staff.id}
        await s.commit()
    yield ids
    async with AsyncSession(engine) as s:
        await s.execute(delete(Employee).where(Employee.tenant_id == org_id))
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


def _auth(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


async def _invite_employee(client, engine, org) -> dict:
    """Owner adds an employee the normal way (POST /employees)."""
    email = f"new-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/v1/employees", headers=_auth(org["owner"]), json={
        "first_name": "New", "last_name": "Hire", "email": email,
        "date_of_joining": "2026-01-01", "role_id": str(org["staff_role"]),
    })
    assert r.status_code == 201, r.text
    async with AsyncSession(engine) as s:
        user_id = (await s.execute(select(User.id).where(User.email == email))).scalar_one()
    return {"email": email, "user_id": str(user_id), "temp_password": r.json()["temporary_password"]}


async def _user(engine, user_id) -> User:
    async with AsyncSession(engine) as s:
        return await s.get(User, uuid.UUID(str(user_id)))


class TestInvitedEmployeeCanGetIn:
    async def test_invite_sends_a_verification_email_with_a_real_token(self, client, engine, org, sent_emails):
        emp = await _invite_employee(client, engine, org)
        user = await _user(engine, emp["user_id"])
        assert user.is_email_verified is False
        assert user.email_verification_token
        assert sent_emails == [(emp["email"], user.email_verification_token)]

    async def test_register_employee_endpoint_also_sends_it(self, client, engine, org, sent_emails):
        email = f"reg-{uuid.uuid4().hex[:8]}@example.com"
        r = await client.post("/api/v1/auth/register-employee", headers=_auth(org["owner"]),
                              json={"first_name": "Reg", "last_name": "User", "email": email})
        assert r.status_code in (200, 201), r.text
        user = await _user(engine, r.json()["user_id"])
        assert sent_emails == [(email, user.email_verification_token)]

    async def test_unverified_employee_can_replace_the_temporary_password(self, client, engine, org, sent_emails):
        """THE dead end: the force-change screen answered EMAIL_NOT_VERIFIED."""
        emp = await _invite_employee(client, engine, org)
        r = await client.post("/api/v1/auth/change-password", headers=_auth(emp["user_id"]), json={
            "current_password": emp["temp_password"],
            "new_password": "MyOwnPass123", "confirm_password": "MyOwnPass123",
        })
        assert r.status_code == 200, r.text

    async def test_gate_still_applies_until_verified_then_opens(self, client, engine, org, sent_emails):
        """Verification is NOT bypassed — it becomes completable."""
        emp = await _invite_employee(client, engine, org)
        blocked = await client.get("/api/v1/employees", headers=_auth(emp["user_id"]))
        assert blocked.status_code == 403
        assert blocked.json()["error"] == "EMAIL_NOT_VERIFIED"

        _, token = sent_emails[-1]
        assert (await client.post("/api/v1/auth/verify-email", json={"token": token})).status_code == 200

        allowed = await client.get("/api/v1/employees", headers=_auth(emp["user_id"]))
        assert allowed.status_code == 200, allowed.text


class TestResendVerification:
    async def test_resend_issues_a_new_token_and_retires_the_old_one(self, client, engine, org, sent_emails):
        emp = await _invite_employee(client, engine, org)
        _, old_token = sent_emails[-1]

        r = await client.post("/api/v1/auth/resend-verification", headers=_auth(emp["user_id"]))
        assert r.status_code == 200, r.text
        _, new_token = sent_emails[-1]
        assert new_token != old_token

        assert (await client.post("/api/v1/auth/verify-email", json={"token": old_token})).status_code == 401
        assert (await client.post("/api/v1/auth/verify-email", json={"token": new_token})).status_code == 200

    async def test_already_verified_user_is_not_emailed(self, client, engine, org, sent_emails):
        r = await client.post("/api/v1/auth/resend-verification", headers=_auth(org["owner"]))
        assert r.status_code == 200
        assert "already verified" in r.json()["message"]
        assert sent_emails == []

    async def test_resend_is_rate_limited_per_user(self, client, engine, org, sent_emails, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
        emp = await _invite_employee(client, engine, org)
        codes = [
            (await client.post("/api/v1/auth/resend-verification", headers=_auth(emp["user_id"]))).status_code
            for _ in range(4)
        ]
        assert codes == [200, 200, 200, 429]

    async def test_resend_requires_sign_in(self, client):
        assert (await client.post("/api/v1/auth/resend-verification")).status_code == 401


class TestPasswordResetProvesTheInbox:
    async def test_reset_link_verifies_email_and_clears_forced_change(self, client, engine, org, sent_emails):
        emp = await _invite_employee(client, engine, org)
        reset_token = uuid.uuid4().hex
        async with AsyncSession(engine) as s:
            user = await s.get(User, uuid.UUID(emp["user_id"]))
            from datetime import UTC, datetime, timedelta
            user.password_reset_token = reset_token
            user.password_reset_expires_at = datetime.now(UTC) + timedelta(hours=1)
            await s.commit()

        r = await client.post("/api/v1/auth/reset-password", json={
            "token": reset_token, "new_password": "ChosenPass123", "confirm_password": "ChosenPass123",
        })
        assert r.status_code == 200, r.text
        user = await _user(engine, emp["user_id"])
        assert user.is_email_verified is True
        assert user.must_change_password is False
        assert user.email_verification_token is None


class TestMeExposesVerificationState:
    async def test_me_reports_state_for_the_banner(self, client, engine, org, sent_emails):
        emp = await _invite_employee(client, engine, org)
        me = (await client.get("/api/v1/auth/me", headers=_auth(emp["user_id"]))).json()
        assert me["is_email_verified"] is False
        assert me["email_verification_required"] is True
        assert me["must_change_password"] is True

    async def test_banner_not_required_when_the_server_does_not_enforce(self, client, engine, org, monkeypatch):
        monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", False)
        me = (await client.get("/api/v1/auth/me", headers=_auth(org["owner"]))).json()
        assert me["email_verification_required"] is False


class TestEmailLinks:
    @pytest.mark.parametrize("task, path", [
        (email_tasks.send_verification_email, "/verify-email?token=TOKEN123"),
        (email_tasks.send_password_reset_email, "/reset-password?token=TOKEN123"),
    ])
    def test_links_use_frontend_url(self, monkeypatch, task, path):
        captured = {}
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://hr.example.pk")
        monkeypatch.setattr(email_tasks, "_send_smtp", lambda to, subject, body: captured.update(body=body))
        task.run("someone@example.com", "TOKEN123")
        assert f"https://hr.example.pk{path}" in captured["body"]
        assert "app.ewmp.io" not in captured["body"]

    def test_invite_email_escapes_the_name(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(email_tasks, "_send_smtp", lambda to, subject, body: captured.update(body=body))
        email_tasks.send_employee_invite_email.run("x@example.com", "<script>alert(1)</script>", "T")
        assert "<script>alert(1)</script>" not in captured["body"]
        assert "&lt;script&gt;" in captured["body"]
