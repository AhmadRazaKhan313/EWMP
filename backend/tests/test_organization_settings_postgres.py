"""
Regression tests for audit finding H-17: an organisation's settings could not
be changed after registration (no endpoint; Settings → General was a mock).

Covers GET/PATCH /organization: permissions, validation (422, never 500),
partial updates, tenant isolation, and — because Organization.settings is a
JSON blob shared with the AI feature — that the encrypted AI key is never
returned and survives every save. Also checks that leave's existing
"standard_work_hours_per_day" reader sees the value this endpoint writes.

Live Postgres via TEST_DATABASE_URL, same convention as the other
*_postgres tests.
"""

import os
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.organization import Organization
from app.models.rbac import Permission, Role
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

URL = "/api/v1/organization"
AI_SETTINGS = {"provider": "openai", "model": "gpt-4o", "api_key_encrypted": "gAAAA-secret-ciphertext"}


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


async def _make_org(engine, label):
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(
            id=org_id, name=f"Org {label}", slug=f"orgset-{label}-{org_id.hex[:8]}",
            email=f"org-{org_id.hex[:8]}@example.com", timezone="UTC", currency="USD",
            settings={"ai": dict(AI_SETTINGS)},
        ))
        await s.flush()
        admin_role = Role(organization_id=org_id, name="Admin", slug="admin",
                          permissions=[await _permission(s, "settings.manage")])
        s.add(admin_role)
        await s.flush()
        ids = {"org": org_id}
        for name, roles in (("admin", [admin_role]), ("member", [])):
            email = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
            u = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                     first_name=name, last_name="T", is_active=True, is_email_verified=True, roles=roles)
            s.add(u)
            await s.flush()
            ids[name] = u.id
        await s.commit()
    return ids


async def _drop_org(engine, org_id):
    async with AsyncSession(engine) as s:
        await s.execute(delete(User).where(User.organization_id == org_id))
        await s.execute(delete(Role).where(Role.organization_id == org_id))
        await s.execute(delete(Organization).where(Organization.id == org_id))
        await s.commit()


@pytest_asyncio.fixture
async def orgs(engine):
    a = await _make_org(engine, "a")
    b = await _make_org(engine, "b")
    yield a, b
    await _drop_org(engine, a["org"])
    await _drop_org(engine, b["org"])


def _auth(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


async def _org(engine, org_id) -> Organization:
    async with AsyncSession(engine) as s:
        return await s.get(Organization, org_id)


class TestRead:
    async def test_any_member_can_read_with_sensible_defaults(self, client, orgs):
        a, _ = orgs
        r = await client.get(URL, headers=_auth(a["member"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == str(a["org"])
        assert body["timezone"] == "UTC" and body["currency"] == "USD"
        assert body["work_days"] == ["mon", "tue", "wed", "thu", "fri"]
        assert body["standard_work_hours_per_day"] == 8.0

    async def test_never_exposes_the_settings_blob_or_ai_key(self, client, orgs):
        a, _ = orgs
        raw = (await client.get(URL, headers=_auth(a["admin"]))).text
        assert "api_key" not in raw and "secret-ciphertext" not in raw and '"ai"' not in raw

    async def test_each_user_sees_only_their_own_organization(self, client, orgs):
        a, b = orgs
        assert (await client.get(URL, headers=_auth(a["member"]))).json()["id"] == str(a["org"])
        assert (await client.get(URL, headers=_auth(b["member"]))).json()["id"] == str(b["org"])

    async def test_requires_sign_in(self, client):
        assert (await client.get(URL)).status_code == 401


class TestUpdate:
    async def test_member_without_settings_manage_cannot_change_anything(self, client, engine, orgs):
        a, _ = orgs
        r = await client.patch(URL, json={"timezone": "Asia/Karachi"}, headers=_auth(a["member"]))
        assert r.status_code == 403
        assert (await _org(engine, a["org"])).timezone == "UTC"

    async def test_admin_updates_and_values_are_normalised(self, client, engine, orgs):
        a, _ = orgs
        r = await client.patch(URL, headers=_auth(a["admin"]), json={
            "name": "  Decibels Pvt Ltd  ", "timezone": "Asia/Karachi", "currency": "pkr",
            "work_days": ["sat", "mon", "tue", "wed", "thu", "fri", "mon"],
            "standard_work_hours_per_day": 7.5, "website": "https://example.pk",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Decibels Pvt Ltd"
        assert body["currency"] == "PKR"
        assert body["work_days"] == ["mon", "tue", "wed", "thu", "fri", "sat"]
        assert body["standard_work_hours_per_day"] == 7.5

        org = await _org(engine, a["org"])
        assert (org.timezone, org.currency) == ("Asia/Karachi", "PKR")

    async def test_partial_update_leaves_other_fields_alone(self, client, engine, orgs):
        a, _ = orgs
        await client.patch(URL, json={"phone": "+92 300 0000000"}, headers=_auth(a["admin"]))
        org = await _org(engine, a["org"])
        assert org.phone == "+92 300 0000000"
        assert org.name == "Org a" and org.timezone == "UTC"

    async def test_saving_does_not_wipe_the_ai_configuration(self, client, engine, orgs):
        """settings is shared JSON: updating work_days must MERGE into it."""
        a, _ = orgs
        r = await client.patch(URL, headers=_auth(a["admin"]),
                               json={"work_days": ["mon", "tue"], "standard_work_hours_per_day": 6})
        assert r.status_code == 200, r.text
        org = await _org(engine, a["org"])
        assert org.settings["ai"] == AI_SETTINGS
        assert org.settings["work_days"] == ["mon", "tue"]

    async def test_one_org_cannot_touch_another(self, client, engine, orgs):
        a, b = orgs
        await client.patch(URL, json={"currency": "EUR"}, headers=_auth(a["admin"]))
        assert (await _org(engine, b["org"])).currency == "USD"


class TestValidation:
    @pytest.mark.parametrize("body", [
        {"timezone": "Asia/Lahore"},
        {"timezone": "GMT+5"},
        {"currency": "RUPEE"},
        {"currency": "12A"},
        {"work_days": ["funday"]},
        {"work_days": []},
        {"standard_work_hours_per_day": 0},
        {"standard_work_hours_per_day": 25},
        {"name": None},
        {"name": "   "},
        {"timezone": None},
        {"email": "not-an-email"},
        {"website": "javascript:alert(1)"},
    ])
    async def test_bad_input_is_a_422_not_a_500(self, client, engine, orgs, body):
        a, _ = orgs
        r = await client.patch(URL, json=body, headers=_auth(a["admin"]))
        assert r.status_code == 422, r.text
        org = await _org(engine, a["org"])
        assert org.name == "Org a" and org.timezone == "UTC" and org.currency == "USD"

    async def test_timezone_error_message_is_helpful(self, client, orgs):
        a, _ = orgs
        r = await client.patch(URL, json={"timezone": "Asia/Lahore"}, headers=_auth(a["admin"]))
        assert "valid IANA timezone" in r.text


class TestConsumers:
    async def test_leave_reads_the_hours_this_endpoint_writes(self, client, engine, orgs):
        from app.api.v1.hrms.leave import _hours_per_day

        a, _ = orgs
        await client.patch(URL, json={"standard_work_hours_per_day": 6}, headers=_auth(a["admin"]))
        async with AsyncSession(engine) as s:
            assert str(await _hours_per_day(s, a["org"])) == "6.0"
