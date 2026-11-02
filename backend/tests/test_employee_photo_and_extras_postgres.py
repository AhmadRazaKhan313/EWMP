"""
Employee profile photo (HR uploads / replaces / removes it) and the OrangeHRM-style
extras (dependents, skills, languages, certifications, driving licence,
probation / confirmation dates), through the real HTTP stack + live Postgres
(TEST_DATABASE_URL), like the other *_postgres tests.
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
from datetime import date
from app.core.storage import get_storage
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.rbac import Permission, Role
from app.models.user import User

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




PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _payload(org, **extra) -> dict:
    return {"first_name": "New", "last_name": "Hire", "email": f"new-{uuid.uuid4().hex[:8]}@example.com",
            "date_of_joining": "2026-01-01", "role_id": str(org["role"]), **extra}


@pytest_asyncio.fixture
async def photos():
    """Remember whose photo files a test wrote so they are removed afterwards."""
    users: list[str] = []
    yield users
    for uid in users:
        for ext in ("png", "jpg", "webp"):
            await get_storage().delete(f"avatars/{uid}.{ext}")


async def _create(client, org, h, **extra) -> str:
    r = await client.post("/api/v1/employees", headers=h, json=_payload(org, **extra))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _get(client, h, emp_id) -> dict:
    r = await client.get(f"/api/v1/employees/{emp_id}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _upload(client, h, emp_id, content, ctype="image/png"):
    return client.post(f"/api/v1/employees/{emp_id}/avatar", headers=h, files={"file": ("p.bin", content, ctype)})


class TestProfilePhoto:
    async def test_upload_then_it_is_served_and_shown_on_the_profile(self, client, org, photos):
        h = await _owner_headers(client, org)
        emp_id = await _create(client, org, h)
        user_id = (await _get(client, h, emp_id))["id"]  # employee id, replaced below
        r = await _upload(client, h, emp_id, PNG)
        assert r.status_code == 200, r.text
        url = r.json()["avatar_url"]
        assert "/api/v1/auth/avatar/" in url and "?v=" in url
        uid = url.split("/avatar/")[1].split("?")[0]
        photos.append(uid)
        served = await client.get(f"/api/v1/auth/avatar/{uid}")
        assert served.status_code == 200 and served.content == PNG
        assert served.headers["content-type"] == "image/png"
        assert (await _get(client, h, emp_id))["avatar_url"] == url

    async def test_replacing_with_another_format_serves_the_new_picture(self, client, org, photos):
        """The serve route tries png, jpg, webp in order - a leftover .png must not win."""
        h = await _owner_headers(client, org)
        emp_id = await _create(client, org, h)
        first = (await _upload(client, h, emp_id, PNG)).json()["avatar_url"]
        uid = first.split("/avatar/")[1].split("?")[0]
        photos.append(uid)
        assert (await _upload(client, h, emp_id, JPG, "image/jpeg")).status_code == 200
        served = await client.get(f"/api/v1/auth/avatar/{uid}")
        assert served.content == JPG and served.headers["content-type"] == "image/jpeg"

    async def test_remove_clears_the_photo(self, client, org, photos):
        h = await _owner_headers(client, org)
        emp_id = await _create(client, org, h)
        url = (await _upload(client, h, emp_id, PNG)).json()["avatar_url"]
        uid = url.split("/avatar/")[1].split("?")[0]
        photos.append(uid)
        assert (await client.delete(f"/api/v1/employees/{emp_id}/avatar", headers=h)).status_code == 204
        assert (await client.get(f"/api/v1/auth/avatar/{uid}")).status_code == 404
        assert (await _get(client, h, emp_id))["avatar_url"] is None

    async def test_the_file_itself_must_be_an_image(self, client, org):
        h = await _owner_headers(client, org)
        emp_id = await _create(client, org, h)
        # Claims to be a PNG, is a script.
        r = await _upload(client, h, emp_id, b"<script>alert(1)</script>", "image/png")
        assert r.status_code == 400
        assert (await _upload(client, h, emp_id, b"", "image/png")).status_code == 400
        assert (await _upload(client, h, emp_id, PNG + b"0" * (5 * 1024 * 1024))).status_code == 400
        assert (await _get(client, h, emp_id))["avatar_url"] is None

    async def test_unknown_employee_is_404(self, client, org):
        h = await _owner_headers(client, org)
        assert (await _upload(client, h, uuid.uuid4(), PNG)).status_code == 404

    async def test_only_hr_or_the_person_can_change_a_photo(self, client, engine, org, photos):
        h = await _owner_headers(client, org)
        other_id = await _create(client, org, h)
        async with AsyncSession(engine, expire_on_commit=False) as s:
            perm = (await s.execute(select(Permission).where(Permission.codename == "employees.view"))).scalar_one_or_none()
            if perm is None:
                perm = Permission(resource="employees", action="view", codename="employees.view", label="v", category="employees")
                s.add(perm)
                await s.flush()
            role = Role(organization_id=org["org"], name="Viewer", slug="viewer", permissions=[perm])
            email = f"viewer-{uuid.uuid4().hex[:8]}@example.com"
            user = User(organization_id=org["org"], email=email, email_normalized=email,
                        password_hash=hash_password(OWNER_PASSWORD), first_name="V", last_name="W",
                        is_active=True, is_email_verified=True, roles=[role])
            s.add(user)
            await s.flush()
            me = Employee(tenant_id=org["org"], user_id=user.id, employee_code="E-VIEW", date_of_joining=date(2026, 1, 1))
            s.add(me)
            await s.flush()
            my_emp_id, my_user_id = str(me.id), str(user.id)
            await s.commit()
        photos.append(my_user_id)
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": OWNER_PASSWORD})
        vh = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
        assert (await _upload(client, vh, other_id, PNG)).status_code == 403
        assert (await client.delete(f"/api/v1/employees/{other_id}/avatar", headers=vh)).status_code == 403
        assert (await _upload(client, vh, my_emp_id, PNG)).status_code == 200      # their own


class TestExtras:
    async def test_dependents_skills_languages_certifications_and_licence_are_saved(self, client, org):
        h = await _owner_headers(client, org)
        emp = await _get(client, h, await _create(
            client, org, h,
            dependents=[{"name": "Ayesha", "relationship": "child", "date_of_birth": "2015-05-05"}],
            skills=[{"name": "Python", "level": "expert"}, {"name": "Excel"}],
            languages=[{"name": "Urdu", "fluency": "native"}, {"name": "English", "fluency": "fluent"}],
            certifications=[{"name": "PMP", "issued_by": "PMI", "issued_date": "2023-01-01", "expiry_date": "2026-01-01"}],
            driving_license_number="LHR-123", driving_license_expiry="2030-02-02",
            probation_end_date="2026-04-01", date_of_confirmation="2026-04-02", notice_period_days=45,
        ))
        assert emp["dependents"][0]["name"] == "Ayesha"
        assert [s["name"] for s in emp["skills"]] == ["Python", "Excel"]
        assert emp["languages"][1]["fluency"] == "fluent"
        assert emp["certifications"][0]["expiry_date"] == "2026-01-01"
        assert emp["driving_license_number"] == "LHR-123" and emp["driving_license_expiry"] == "2030-02-02"
        assert emp["probation_end_date"] == "2026-04-01" and emp["date_of_confirmation"] == "2026-04-02"
        assert emp["notice_period_days"] == 45

    async def test_reports_to_shows_the_managers_name(self, client, org):
        h = await _owner_headers(client, org)
        boss = await _create(client, org, h, first_name="Big", last_name="Boss")
        emp = await _get(client, h, await _create(client, org, h, manager_id=boss))
        assert emp["manager_id"] == boss and emp["manager_name"] == "Big Boss"
        assert (await _get(client, h, boss))["manager_name"] is None

    async def test_edit_replaces_and_clears_them(self, client, org):
        h = await _owner_headers(client, org)
        emp_id = await _create(client, org, h, skills=[{"name": "Python"}], dependents=[{"name": "A"}])
        r = await client.patch(f"/api/v1/employees/{emp_id}", headers=h,
                               json={"skills": [{"name": "Go", "level": "beginner"}], "dependents": []})
        assert r.status_code == 200, r.text
        emp = await _get(client, h, emp_id)
        assert [s["name"] for s in emp["skills"]] == ["Go"] and emp["dependents"] == []

    async def test_bad_values_are_rejected(self, client, org):
        h = await _owner_headers(client, org)
        for extra in (
            {"skills": [{"name": "X", "level": "godlike"}]},
            {"languages": [{"name": "Urdu", "fluency": "perfect"}]},
            {"dependents": [{"relationship": "child"}]},
            {"notice_period_days": -1},
        ):
            r = await client.post("/api/v1/employees", headers=h, json=_payload(org, **extra))
            assert r.status_code == 422, extra
