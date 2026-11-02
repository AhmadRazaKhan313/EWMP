"""
Regression tests for audit findings C-5 and H-3: values that belong to ONE
organisation were unique across the WHOLE platform.

  * Helpdesk: ticket numbers are generated per organisation (TKT-00001, ...)
    but support_tickets.ticket_number was globally unique, so every
    organisation after the first got HTTP 500 on its first ticket. Numbers
    were count(*)+1 (racy), and tickets were saved without a requester.
  * Assets: asset_tag / serial_number globally unique — two companies could
    not both own "LAPTOP-001"; a duplicate inside one company was a 500.
  * Devices: serial_number globally unique (no code writes it yet, so this
    is checked at the database level).

Migration c4e95883fb29 makes these per-organisation. Runs against a live
Postgres with migrations applied — same TEST_DATABASE_URL convention as the
other *_postgres tests. Permission rows are created if missing.
"""

import asyncio
import os
import uuid
from datetime import date

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.devices import Asset, Device, DeviceOS, DeviceStatus
from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.helpdesk import SupportTicket
from app.models.organization import Organization
from app.models.rbac import Permission, Role
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

PERMS = ["helpdesk.create", "helpdesk.view", "helpdesk.manage", "assets.manage", "assets.view"]


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


async def _permission(session: AsyncSession, codename: str) -> Permission:
    perm = (
        await session.execute(select(Permission).where(Permission.codename == codename))
    ).scalar_one_or_none()
    if perm is None:
        resource, action = codename.split(".", 1)
        perm = Permission(resource=resource, action=action, codename=codename,
                          label=codename, category=resource)
        session.add(perm)
        await session.flush()
    return perm


async def _make_org(engine, label):
    """An org with one IT user (helpdesk + assets permissions) who also has
    an employee profile, so ticket requester can be checked."""
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name=f"Uniq {label}", slug=f"uniq-{label}-{org_id.hex[:8]}",
                           email=f"uniq-{org_id.hex[:8]}@example.com"))
        await s.flush()
        role = Role(organization_id=org_id, name="IT", slug="it",
                    permissions=[await _permission(s, c) for c in PERMS])
        s.add(role)
        await s.flush()
        email = f"it-{uuid.uuid4().hex[:8]}@example.com"
        user = User(organization_id=org_id, email=email, email_normalized=email, password_hash="x",
                    first_name="IT", last_name="User", is_active=True, is_email_verified=True,
                    roles=[role])
        s.add(user)
        await s.flush()
        emp = Employee(tenant_id=org_id, user_id=user.id, employee_code=f"E-{uuid.uuid4().hex[:6]}",
                       employment_type=EmploymentType.FULL_TIME,
                       employment_status=EmploymentStatus.ACTIVE, date_of_joining=date(2026, 1, 1))
        s.add(emp)
        await s.flush()
        ids = {"org": org_id, "user": user.id, "emp": emp.id}
        await s.commit()
    return ids


async def _drop_org(engine, org_id):
    async with AsyncSession(engine) as s:
        for model in (SupportTicket, Asset, Device, Employee):
            await s.execute(delete(model).where(model.tenant_id == org_id))
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


# ── Helpdesk ─────────────────────────────────────────────────────────────────

class TestTicketNumbers:
    async def test_two_organisations_can_each_have_ticket_one(self, client, orgs):
        """THE bug: the second organisation's first ticket was a 500."""
        a, b = orgs
        ra = await client.post("/api/v1/helpdesk/tickets", json={"title": "VPN down"}, headers=_auth(a["user"]))
        rb = await client.post("/api/v1/helpdesk/tickets", json={"title": "Printer"}, headers=_auth(b["user"]))
        assert ra.status_code == 201, ra.text
        assert rb.status_code == 201, rb.text
        assert ra.json()["ticket_number"] == rb.json()["ticket_number"] == "TKT-00001"

    async def test_numbers_are_sequential_and_never_reused_after_delete(self, client, orgs):
        a, _ = orgs
        h = _auth(a["user"])
        first = (await client.post("/api/v1/helpdesk/tickets", json={"title": "1"}, headers=h)).json()
        second = (await client.post("/api/v1/helpdesk/tickets", json={"title": "2"}, headers=h)).json()
        assert (first["ticket_number"], second["ticket_number"]) == ("TKT-00001", "TKT-00002")

        assert (await client.delete(f"/api/v1/helpdesk/tickets/{second['id']}", headers=h)).status_code == 204
        third = (await client.post("/api/v1/helpdesk/tickets", json={"title": "3"}, headers=h)).json()
        assert third["ticket_number"] == "TKT-00003"

    async def test_concurrent_creates_all_succeed_with_distinct_numbers(self, client, orgs):
        a, _ = orgs
        h = _auth(a["user"])
        responses = await asyncio.gather(*[
            client.post("/api/v1/helpdesk/tickets", json={"title": f"t{i}"}, headers=h) for i in range(5)
        ])
        assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
        numbers = {r.json()["ticket_number"] for r in responses}
        assert numbers == {f"TKT-{n:05d}" for n in range(1, 6)}

    async def test_requester_is_recorded(self, client, engine, orgs):
        a, _ = orgs
        r = await client.post("/api/v1/helpdesk/tickets", json={"title": "Laptop"}, headers=_auth(a["user"]))
        async with AsyncSession(engine) as s:
            ticket = await s.get(SupportTicket, uuid.UUID(r.json()["id"]))
            assert ticket.requester_id == a["emp"]


# ── Assets ───────────────────────────────────────────────────────────────────

def _asset(tag="LAPTOP-001", serial=""):
    return {"name": "ThinkPad", "asset_tag": tag, "category": "laptop", "serial_number": serial}


class TestAssetUniqueness:
    async def test_two_organisations_can_use_the_same_tag_and_serial(self, client, orgs):
        a, b = orgs
        ra = await client.post("/api/v1/assets", json=_asset(serial="SN-123"), headers=_auth(a["user"]))
        rb = await client.post("/api/v1/assets", json=_asset(serial="SN-123"), headers=_auth(b["user"]))
        assert ra.status_code == 201, ra.text
        assert rb.status_code == 201, rb.text

    async def test_duplicate_tag_in_one_organisation_is_a_409(self, client, orgs):
        a, _ = orgs
        h = _auth(a["user"])
        assert (await client.post("/api/v1/assets", json=_asset(), headers=h)).status_code == 201
        # Same tag, different case and stray whitespace — still the same tag.
        r = await client.post("/api/v1/assets", json=_asset(tag="  laptop-001 "), headers=h)
        assert r.status_code == 409, r.text

    async def test_duplicate_serial_in_one_organisation_is_a_409(self, client, orgs):
        a, _ = orgs
        h = _auth(a["user"])
        assert (await client.post("/api/v1/assets", json=_asset("A-1", "SN-9"), headers=h)).status_code == 201
        r = await client.post("/api/v1/assets", json=_asset("A-2", "SN-9"), headers=h)
        assert r.status_code == 409, r.text

    async def test_deleted_assets_tag_can_be_reused(self, client, orgs):
        a, _ = orgs
        h = _auth(a["user"])
        created = await client.post("/api/v1/assets", json=_asset(), headers=h)
        assert (await client.delete(f"/api/v1/assets/{created.json()['id']}", headers=h)).status_code == 204
        again = await client.post("/api/v1/assets", json=_asset(), headers=h)
        assert again.status_code == 201, again.text

    async def test_assets_without_serial_numbers_do_not_collide(self, client, orgs):
        a, _ = orgs
        h = _auth(a["user"])
        assert (await client.post("/api/v1/assets", json=_asset("A-1"), headers=h)).status_code == 201
        assert (await client.post("/api/v1/assets", json=_asset("A-2"), headers=h)).status_code == 201


# ── Devices (database level: no code path writes serial_number yet) ─────────

def _device(tenant_id, serial):
    return Device(tenant_id=tenant_id, hostname=f"host-{uuid.uuid4().hex[:6]}",
                  agent_id=uuid.uuid4().hex, agent_token_hash="x",
                  os_type=DeviceOS.WINDOWS, status=DeviceStatus.OFFLINE, serial_number=serial)


class TestDeviceSerialUniqueness:
    async def test_same_serial_allowed_in_different_organisations(self, engine, orgs):
        a, b = orgs
        async with AsyncSession(engine) as s:
            s.add_all([_device(a["org"], "PF-1"), _device(b["org"], "PF-1")])
            await s.commit()

    async def test_same_serial_rejected_twice_in_one_organisation(self, engine, orgs):
        a, _ = orgs
        async with AsyncSession(engine) as s:
            s.add(_device(a["org"], "PF-2"))
            await s.commit()
        async with AsyncSession(engine) as s:
            s.add(_device(a["org"], "PF-2"))
            with pytest.raises(IntegrityError):
                await s.commit()

    async def test_decommissioned_device_does_not_block_re_enrolment(self, engine, orgs):
        a, _ = orgs
        async with AsyncSession(engine) as s:
            old = _device(a["org"], "PF-3")
            s.add(old)
            await s.flush()
            old.soft_delete()
            s.add(_device(a["org"], "PF-3"))
            await s.commit()
