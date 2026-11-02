"""
T-01: an admin with attendance.edit edits or deletes any day directly (no
approval): reason mandatory, audit row written, hours recalculated, a locked
payroll period refuses the change unless the owner overrides. Live Postgres,
real HTTP.
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
            "DELETE FROM audit_logs WHERE tenant_id = :o",
            "DELETE FROM payroll_runs WHERE tenant_id = :o",
            "DELETE FROM attendance_regularizations WHERE tenant_id = :o",
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

DAY = "2026-09-01"


async def _day(client, org, check_in="09:00", check_out="17:00", on=DAY):
    emp = await _employee(client, org, "Dana")
    r = await client.post("/api/v1/attendance", headers=_h(org["owner"]), params={
        "employee_id": emp["id"], "date": on, "check_in": check_in, "check_out": check_out})
    assert r.status_code == 201, r.text
    return emp["id"], r.json()["id"]


async def _audit_rows(engine, org, action):
    async with AsyncSession(engine) as s:
        return (await s.execute(text(
            "SELECT user_id, action, resource_id, before_data, after_data, changed_fields "
            "FROM audit_logs WHERE tenant_id = :o AND action = :a"), {"o": org["org"], "a": action})).all()


async def test_admin_edit_changes_times_hours_and_writes_audit(client, engine, org):
    _, rec = await _day(client, org)
    editor = await _role_user(engine, org, ["attendance.edit"], "Editor")
    r = await client.patch(f"/api/v1/attendance/{rec}", headers=_h(editor),
                           json={"check_in": "10:00", "check_out": "15:30", "reason": "Forgot to punch"})
    assert r.status_code == 200, r.text
    assert r.json()["total_minutes"] == 330
    rows = await _audit_rows(engine, org, "attendance.edit")
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == editor and row.resource_id == rec
    assert row.after_data["reason"] == "Forgot to punch"
    assert row.before_data["total_minutes"] == 480 and row.after_data["total_minutes"] == 330
    assert "total_minutes" in row.changed_fields


async def test_without_attendance_edit_it_is_403(client, engine, org):
    _, rec = await _day(client, org)
    viewer = await _role_user(engine, org, ["attendance.view", "attendance.regularize"], "Viewer")
    body = {"check_out": "16:00", "reason": "nope nope"}
    assert (await client.patch(f"/api/v1/attendance/{rec}", headers=_h(viewer), json=body)).status_code == 403
    assert (await client.delete(f"/api/v1/attendance/{rec}", headers=_h(viewer),
                                params={"reason": "nope nope"})).status_code == 403


async def test_reason_is_mandatory(client, engine, org):
    _, rec = await _day(client, org)
    h = _h(org["owner"])
    assert (await client.patch(f"/api/v1/attendance/{rec}", headers=h, json={"check_out": "16:00"})).status_code == 422
    assert (await client.patch(f"/api/v1/attendance/{rec}", headers=h,
                               json={"check_out": "16:00", "reason": "  "})).status_code in (400, 422)
    assert (await client.delete(f"/api/v1/attendance/{rec}", headers=h)).status_code == 422


async def test_status_only_edit_and_bad_times(client, engine, org):
    _, rec = await _day(client, org)
    h = _h(org["owner"])
    r = await client.patch(f"/api/v1/attendance/{rec}", headers=h, json={"status": "absent", "reason": "Wrongly marked"})
    assert r.status_code == 200 and r.json()["status"] == "absent"
    r = await client.patch(f"/api/v1/attendance/{rec}", headers=h, json={"check_in": "17:00", "check_out": "09:00", "reason": "typo"})
    assert r.status_code == 400
    r = await client.patch(f"/api/v1/attendance/{rec}", headers=h, json={"reason": "nothing"})
    assert r.status_code == 400


async def test_delete_is_soft_audited_and_the_day_can_be_recorded_again(client, engine, org):
    emp, rec = await _day(client, org)
    editor = await _role_user(engine, org, ["attendance.edit"], "Editor")
    r = await client.delete(f"/api/v1/attendance/{rec}", headers=_h(editor), params={"reason": "Duplicate entry"})
    assert r.status_code == 204, r.text
    async with AsyncSession(engine) as s:
        row = (await s.execute(text("SELECT is_deleted, deleted_at FROM attendance_records WHERE id = :i"), {"i": rec})).one()
        punches = (await s.execute(text("SELECT bool_and(is_deleted) FROM attendance_punches WHERE attendance_record_id = :i"), {"i": rec})).scalar_one()
    assert row.is_deleted and row.deleted_at is not None and punches is True
    assert (await client.patch(f"/api/v1/attendance/{rec}", headers=_h(editor),
                               json={"check_out": "16:00", "reason": "after delete"})).status_code == 404
    rows = await _audit_rows(engine, org, "attendance.delete")
    assert len(rows) == 1 and rows[0].after_data["reason"] == "Duplicate entry" and rows[0].before_data["date"] == DAY
    again = await client.post("/api/v1/attendance", headers=_h(org["owner"]), params={
        "employee_id": emp, "date": DAY, "check_in": "09:30", "check_out": "17:30"})
    assert again.status_code == 201 and again.json()["id"] != rec


async def test_locked_payroll_blocks_everyone_but_the_owner_override(client, engine, org):
    _, rec = await _day(client, org)
    async with AsyncSession(engine) as s:
        from datetime import date
        from app.models.payroll import PayrollRun, PayrollRunStatus
        s.add(PayrollRun(tenant_id=org["org"], name="Sep 2026", period_start=date(2026, 9, 1),
                         period_end=date(2026, 9, 30), pay_date=date(2026, 10, 1),
                         status=PayrollRunStatus.LOCKED, processed_by_id=uuid.uuid4()))
        await s.commit()
    editor = await _role_user(engine, org, ["attendance.edit"], "Editor")
    body = {"check_out": "16:00", "reason": "late fix"}
    r = await client.patch(f"/api/v1/attendance/{rec}", headers=_h(editor), json=body)
    assert r.status_code == 409 and r.json()["error"] == "PAYROLL_LOCKED"
    assert r.json()["detail"]["can_override"] is False
    r = await client.patch(f"/api/v1/attendance/{rec}", headers=_h(editor), json={**body, "override_payroll_lock": True})
    assert r.status_code == 409                                    # an editor can't override
    r = await client.patch(f"/api/v1/attendance/{rec}", headers=_h(org["owner"]), json=body)
    assert r.status_code == 409 and r.json()["detail"]["can_override"] is True
    r = await client.patch(f"/api/v1/attendance/{rec}", headers=_h(org["owner"]), json={**body, "override_payroll_lock": True})
    assert r.status_code == 200 and r.json()["total_minutes"] == 420
    assert (await client.delete(f"/api/v1/attendance/{rec}", headers=_h(editor),
                                params={"reason": "locked delete"})).status_code == 409


async def test_another_organizations_record_is_404(client, engine, org):
    other = await _make_org(engine)
    try:
        _, rec = await _day(client, other)
        assert (await client.patch(f"/api/v1/attendance/{rec}", headers=_h(org["owner"]),
                                   json={"check_out": "16:00", "reason": "sneaky"})).status_code == 404
        assert (await client.delete(f"/api/v1/attendance/{rec}", headers=_h(org["owner"]),
                                    params={"reason": "sneaky"})).status_code == 404
    finally:
        await _drop_org(engine, other)


async def test_admin_marks_a_whole_day_with_reason_audit_and_tag(client, engine, org):
    emp = (await _employee(client, org, "Mark"))["id"]
    h = _h(org["owner"])
    for status_, extra in (("absent", {}), ("work_from_home", {})):
        day = "2026-09-02" if status_ == "absent" else "2026-09-03"
        r = await client.post("/api/v1/attendance", headers=h, params={
            "employee_id": emp, "date": day, "attendance_status": status_, "reason": "Called in sick", **extra})
        assert r.status_code == 201, r.text
    r = await client.post("/api/v1/attendance", headers=h, params={
        "employee_id": emp, "date": "2026-09-04", "check_in": "09:00", "check_out": "17:00",
        "reason": "Laptop was down"})
    assert r.status_code == 201
    listing = (await client.get("/api/v1/attendance", headers=h, params={"employee_id": emp})).json()["items"]
    by_date = {i["date"]: i for i in listing}
    assert by_date["2026-09-02"]["status"] == "absent" and by_date["2026-09-02"]["marked_by_admin"] is True
    assert by_date["2026-09-03"]["status"] == "work_from_home"
    assert by_date["2026-09-04"]["total_minutes"] == 480
    rows = await _audit_rows(engine, org, "attendance.mark")
    assert len(rows) == 3 and {r.after_data["reason"] for r in rows} == {"Called in sick", "Laptop was down"}

