"""
Devices screen leads with WHO has the machine, not the device name.

Live Postgres + real HTTP stack (TEST_DATABASE_URL), like the other *_postgres tests.
"""
import os
import uuid
from datetime import date

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token, create_device_enrollment_token, hash_password
from app.main import app
from tests._device_factory import make_device
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.organization_structure import Department, Designation
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
pytestmark = pytest.mark.asyncio


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
        s.add(Organization(id=org_id, name="Dev Org", slug=f"dev-{org_id.hex[:8]}",
                           email=f"d-{org_id.hex[:8]}@example.com"))
        await s.flush()

        def mk(first, last, **kw):
            e = f"{first.lower()}-{uuid.uuid4().hex[:6]}@example.com"
            return User(organization_id=org_id, email=e, email_normalized=e, password_hash=hash_password("x"),
                        first_name=first, last_name=last, is_active=True, is_email_verified=True, **kw)

        admin, worker = mk("Adm", "In"), mk("Sara", "Khan", phone="0300-1111111", avatar_url="/files/sara.png")
        s.add_all([admin, worker])
        dept = Department(tenant_id=org_id, name="Engineering")
        desig = Designation(tenant_id=org_id, name="Senior Developer")
        s.add_all([dept, desig])
        await s.flush()
        (await s.get(Organization, org_id)).owner_id = admin.id
        emp = Employee(tenant_id=org_id, user_id=worker.id, employee_code="EMP-0042",
                       department_id=dept.id, designation_id=desig.id, date_of_joining=date(2026, 1, 1))
        s.add(emp)
        await s.flush()
        ids = {"org": org_id, "admin": admin.id, "worker_email": worker.email, "emp": emp.id}
        await s.commit()
    yield ids
    async with AsyncSession(engine) as s:
        for tbl in ("device_screenshots", "device_metrics", "device_alerts"):
            await s.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :o"), {"o": org_id})
        for sql in (
            "DELETE FROM attendance_records WHERE tenant_id = :o",
            "DELETE FROM devices WHERE tenant_id = :o",
            "UPDATE organizations SET owner_id = NULL WHERE id = :o",
            "DELETE FROM employees WHERE tenant_id = :o",
            "DELETE FROM departments WHERE tenant_id = :o",
            "DELETE FROM designations WHERE tenant_id = :o",
            "DELETE FROM users WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            await s.execute(text(sql), {"o": org_id})
        await s.commit()


def _h(org):
    return {"Authorization": f"Bearer {create_access_token(str(org['admin']))}"}


async def _device(client, org, host) -> str:
    return (await make_device(org, host))["device_id"]


async def test_list_shows_the_person_who_holds_each_device(client, org):
    mine = await _device(client, org, "SARA-LAPTOP")
    spare = await _device(client, org, "SPARE-PC")
    r = await client.post(f"/api/v1/devices/{mine}/assign", json={"employee_id": str(org["emp"])}, headers=_h(org))
    assert r.status_code == 200, r.text

    items = {i["id"]: i for i in (await client.get("/api/v1/devices", headers=_h(org))).json()["items"]}
    e = items[mine]["assigned_employee"]
    assert e["full_name"] == "Sara Khan" and e["employee_code"] == "EMP-0042"
    assert e["department"] == "Engineering" and e["designation"] == "Senior Developer"
    assert e["email"] == org["worker_email"] and e["phone"] == "0300-1111111"
    assert e["avatar_url"] == "/files/sara.png"
    assert items[spare]["assigned_employee"] is None


async def test_detail_has_the_same_employee_card(client, org):
    d = await _device(client, org, "SARA-LAPTOP")
    await client.post(f"/api/v1/devices/{d}/assign", json={"employee_id": str(org["emp"])}, headers=_h(org))
    body = (await client.get(f"/api/v1/devices/{d}", headers=_h(org))).json()
    e = body["assigned_employee"]
    assert e["full_name"] == "Sara Khan" and e["department"] == "Engineering"
    assert e["designation"] == "Senior Developer" and e["email"] == org["worker_email"]
    await client.post(f"/api/v1/devices/{d}/unassign", headers=_h(org))
    assert (await client.get(f"/api/v1/devices/{d}", headers=_h(org))).json()["assigned_employee"] is None


async def test_alerts_name_the_employee(client, org, engine):
    d = await _device(client, org, "SARA-LAPTOP")
    await client.post(f"/api/v1/devices/{d}/assign", json={"employee_id": str(org["emp"])}, headers=_h(org))
    async with AsyncSession(engine) as s:
        await s.execute(text(
            "INSERT INTO device_alerts (id, tenant_id, device_id, alert_type, matched_term, detail, occurred_at,"
            " is_acknowledged, is_deleted, created_at, updated_at) VALUES (:i, :o, :d, 'FLAGGED_BROWSING',"
            " 'facebook.com', 'facebook.com', now(), false, false, now(), now())"),
            {"i": uuid.uuid4(), "o": org["org"], "d": uuid.UUID(d)})
        await s.commit()
    for url in ("/api/v1/devices/alerts", "/api/v1/devices/alerts/recent"):
        items = (await client.get(url, headers=_h(org))).json()["items"]
        assert items and items[0]["employee_name"] == "Sara Khan", url
        assert items[0]["employee_code"] == "EMP-0042" and items[0]["department"] == "Engineering"
        assert items[0]["device_name"] == "SARA-LAPTOP"


async def test_unassigned_device_alert_has_no_employee(client, org, engine):
    d = await _device(client, org, "LOOSE-PC")
    async with AsyncSession(engine) as s:
        await s.execute(text(
            "INSERT INTO device_alerts (id, tenant_id, device_id, alert_type, matched_term, detail, occurred_at,"
            " is_acknowledged, is_deleted, created_at, updated_at) VALUES (:i, :o, :d, 'FLAGGED_BROWSING',"
            " 'x.com', 'x.com', now(), false, false, now(), now())"),
            {"i": uuid.uuid4(), "o": org["org"], "d": uuid.UUID(d)})
        await s.commit()
    item = (await client.get("/api/v1/devices/alerts", headers=_h(org))).json()["items"][0]
    assert item["employee_name"] is None and item["employee_code"] is None


async def test_attendance_of_the_device_holder(client, org, engine):
    from datetime import datetime, timedelta, timezone
    from app.core.timezones import local_today, org_zone
    from app.models.attendance import AttendanceRecord, AttendanceSource, AttendanceStatus

    d = await _device(client, org, "SARA-LAPTOP")
    r = await client.get(f"/api/v1/devices/{d}/attendance", headers=_h(org))  # nobody holds it yet
    assert r.status_code == 200 and r.json()["assigned"] is False
    await client.post(f"/api/v1/devices/{d}/assign", json={"employee_id": str(org["emp"])}, headers=_h(org))

    now = datetime.now(timezone.utc)
    async with AsyncSession(engine) as s:
        today = local_today(await org_zone(s, org["org"]))
        for back, status, minutes in ((0, AttendanceStatus.PRESENT, None), (1, AttendanceStatus.LATE, 480),
                                      (2, AttendanceStatus.ABSENT, None), (3, AttendanceStatus.PRESENT, 540)):
            absent = status == AttendanceStatus.ABSENT
            s.add(AttendanceRecord(
                tenant_id=org["org"], employee_id=org["emp"], date=today - timedelta(days=back),
                check_in=None if absent else now - timedelta(hours=2),
                check_out=None if (absent or back == 0) else now,
                check_in_source=AttendanceSource.DESKTOP_AGENT, status=status, total_minutes=minutes))
        await s.commit()

    body = (await client.get(f"/api/v1/devices/{d}/attendance?days=7", headers=_h(org))).json()
    assert body["assigned"] is True and len(body["days"]) == 4
    assert body["today"]["is_working"] is True and body["today"]["total_minutes"] >= 119  # live, still checked in
    assert body["summary"]["present"] == 3 and body["summary"]["late"] == 1 and body["summary"]["absent"] == 1
    assert body["summary"]["avg_minutes"] > 0
