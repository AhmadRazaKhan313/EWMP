"""
E-02/E-07/E-08: employee search, CSV export/import, status history, real
offboarding, and contracts with renewal reminders. Live Postgres, real HTTP.
"""


import os
import uuid
from datetime import date, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.organization import Organization
from app.models.rbac import Role
from app.models.user import User
from app.workers.tasks import email as email_tasks
from app.workers.tasks import notifications as notification_tasks

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _no_email(monkeypatch):
    monkeypatch.setattr(email_tasks.send_verification_email, "delay", lambda to, token: None)
    # No broker in tests: offboarding fires a workflow event; stub it so nothing waits on Redis.
    monkeypatch.setattr(notification_tasks.trigger_workflow_event, "delay", lambda *a, **k: None)


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
            "DELETE FROM notifications WHERE tenant_id = :o",
            "DELETE FROM employee_contracts WHERE tenant_id = :o",
            "DELETE FROM employee_status_history WHERE tenant_id = :o",
            "DELETE FROM employee_documents WHERE tenant_id = :o",
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


API = "/api/v1/employees"


async def _hire(client, org, first, last="Hire", **extra):
    r = await client.post(API, headers=_h(org["owner"]), json={
        "first_name": first, "last_name": last, "email": f"{''.join(ch for ch in first.lower() if ch.isalnum())}-{uuid.uuid4().hex[:6]}@example.com",
        "date_of_joining": "2026-01-01", "role_id": str(org["role"]), "job_nature": "permanent", **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _iso(d):
    return d.isoformat()


# ── search ───────────────────────────────────────────────────────────────────
async def test_search_matches_name_and_email_within_own_org_only(client, org, other_org):
    a = await _hire(client, org, "Zainab", "Qureshi")
    await _hire(client, org, "Omar", "Different")
    await _hire(client, other_org, "Zainab", "Elsewhere")
    h = _h(org["owner"])
    for q in ("zainab", "QURESHI", "zainab qureshi", "zainab-"):
        r = await client.get(API, headers=h, params={"query": q})
        assert r.status_code == 200
        ids = [i["id"] for i in r.json()["items"]]
        assert ids == [a], (q, r.json())
    assert (await client.get(API, headers=h, params={"query": "nobody-here"})).json()["total"] == 0


# ── offboarding + history ───────────────────────────────────────────────────
async def test_offboard_resignation_vs_termination_and_timeline(client, engine, org):
    h = _h(org["owner"])
    resign, fire = await _hire(client, org, "Resign"), await _hire(client, org, "Fire")
    r = await client.post(f"{API}/{resign}/offboard", headers=h,
                          params={"date_of_leaving": "2026-03-01", "exit_reason": "Moving abroad", "reason_type": "resignation"})
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/{fire}/offboard", headers=h,
                          params={"date_of_leaving": "2026-03-02", "exit_reason": "Policy breach", "reason_type": "termination"})
    assert r.status_code == 200, r.text
    assert (await client.get(f"{API}/{resign}", headers=h)).json()["employment_status"] == "resigned"
    assert (await client.get(f"{API}/{fire}", headers=h)).json()["employment_status"] == "terminated"

    tl = (await client.get(f"{API}/{resign}/history", headers=h)).json()
    assert [(t["from_status"], t["to_status"], t["source"]) for t in tl] == [
        ("active", "resigned", "offboard"), (None, "active", "created")]
    assert "Moving abroad" in tl[0]["reason"] and tl[0]["changed_by"] == "Owner Test"
    # already offboarded -> 409; second call must not add a timeline row
    again = await client.post(f"{API}/{resign}/offboard", headers=h,
                              params={"date_of_leaving": "2026-03-05", "exit_reason": "x", "reason_type": "resignation"})
    assert again.status_code == 409
    assert len((await client.get(f"{API}/{resign}/history", headers=h)).json()) == 2


async def test_offboard_validates_reason_and_type(client, org):
    h = _h(org["owner"])
    e = await _hire(client, org, "Val")
    base = {"date_of_leaving": "2026-03-01"}
    bad_type = await client.post(f"{API}/{e}/offboard", headers=h, params={**base, "exit_reason": "x", "reason_type": "vanished"})
    blank = await client.post(f"{API}/{e}/offboard", headers=h, params={**base, "exit_reason": "   ", "reason_type": "other"})
    assert bad_type.status_code == 400 and blank.status_code == 400
    assert (await client.get(f"{API}/{e}", headers=h)).json()["employment_status"] == "active"


async def test_status_change_via_edit_is_recorded_but_same_status_is_not(client, org):
    h = _h(org["owner"])
    e = await _hire(client, org, "Edit")
    assert (await client.patch(f"{API}/{e}", headers=h, json={"employment_status": "on_leave"})).status_code == 200
    assert (await client.patch(f"{API}/{e}", headers=h, json={"employment_status": "on_leave"})).status_code == 200
    tl = (await client.get(f"{API}/{e}/history", headers=h)).json()
    assert [(t["from_status"], t["to_status"]) for t in tl] == [("active", "on_leave"), (None, "active")]


async def test_history_is_tenant_scoped(client, org, other_org):
    e = await _hire(client, other_org, "Else")
    assert (await client.get(f"{API}/{e}/history", headers=_h(org["owner"]))).status_code == 404


async def test_offboarding_ends_the_active_contract(client, org):
    h = _h(org["owner"])
    e = await _hire(client, org, "Leaver")
    c = (await client.post(f"{API}/{e}/contracts", headers=h, json={
        "contract_type": "fixed_term", "start_date": "2026-01-01", "end_date": "2099-01-01"})).json()
    await client.post(f"{API}/{e}/offboard", headers=h, params={
        "date_of_leaving": "2026-03-01", "exit_reason": "Gone", "reason_type": "resignation"})
    rows = (await client.get(f"{API}/{e}/contracts", headers=h)).json()["items"]
    assert [(r["id"], r["status"]) for r in rows] == [(c["id"], "terminated")]


# ── contracts ───────────────────────────────────────────────────────────────
async def test_contract_rules(client, org):
    h = _h(org["owner"])
    e = await _hire(client, org, "Con")
    url = f"{API}/{e}/contracts"
    assert (await client.post(url, headers=h, json={"contract_type": "fixed_term", "start_date": "2026-01-01"})).status_code == 400
    assert (await client.post(url, headers=h, json={"contract_type": "fixed_term", "start_date": "2026-05-01", "end_date": "2026-05-01"})).status_code == 400
    assert (await client.post(url, headers=h, json={"contract_type": "weird", "start_date": "2026-05-01", "end_date": "2026-09-01"})).status_code == 400
    perm = await client.post(url, headers=h, json={"contract_type": "permanent", "start_date": "2026-01-01", "end_date": "2030-01-01"})
    assert perm.status_code == 201 and perm.json()["end_date"] is None and perm.json()["state"] == "active"
    # one active contract per employee
    second = await client.post(url, headers=h, json={"contract_type": "fixed_term", "start_date": "2026-01-01", "end_date": "2027-01-01"})
    assert second.status_code == 409


async def test_renew_terminate_edit_and_delete(client, org):
    h = _h(org["owner"])
    e = await _hire(client, org, "Cycle")
    first = (await client.post(f"{API}/{e}/contracts", headers=h, json={
        "contract_type": "fixed_term", "start_date": "2026-01-01", "end_date": "2026-06-30"})).json()
    renewed = await client.post(f"{API}/contracts/{first['id']}/renew", headers=h, json={"end_date": "2026-12-31"})
    assert renewed.status_code == 200, renewed.text
    new = renewed.json()
    assert new["start_date"] == "2026-07-01" and new["renewed_from_id"] == first["id"] and new["status"] == "active"
    rows = {r["id"]: r for r in (await client.get(f"{API}/{e}/contracts", headers=h)).json()["items"]}
    assert rows[first["id"]]["status"] == "renewed" and rows[new["id"]]["status"] == "active"
    # an old (renewed) contract is read-only
    assert (await client.patch(f"{API}/contracts/{first['id']}", headers=h, json={"notes": "x"})).status_code == 409
    assert (await client.post(f"{API}/contracts/{first['id']}/renew", headers=h, json={"end_date": "2027-01-01"})).status_code == 409
    edited = await client.patch(f"{API}/contracts/{new['id']}", headers=h, json={"end_date": "2027-03-31", "notes": "Extended"})
    assert edited.status_code == 200 and edited.json()["end_date"] == "2027-03-31"
    assert (await client.patch(f"{API}/contracts/{new['id']}", headers=h, json={"end_date": "2026-01-01"})).status_code == 400
    term = await client.post(f"{API}/contracts/{new['id']}/terminate", headers=h, json={"reason": "Project cancelled"})
    assert term.status_code == 200 and term.json()["state"] == "terminated" and "Project cancelled" in term.json()["notes"]
    assert (await client.post(f"{API}/contracts/{new['id']}/terminate", headers=h, json={})).status_code == 409
    # a terminated employee can be given a fresh contract
    assert (await client.post(f"{API}/{e}/contracts", headers=h, json={
        "contract_type": "permanent", "start_date": "2026-09-01"})).status_code == 201
    assert (await client.delete(f"{API}/contracts/{first['id']}", headers=h)).status_code == 204
    left = (await client.get(f"{API}/{e}/contracts", headers=h)).json()["items"]
    assert first["id"] not in [r["id"] for r in left]


async def test_contract_document_must_belong_to_that_employee(client, engine, org):
    h = _h(org["owner"])
    a, b = await _hire(client, org, "DocA"), await _hire(client, org, "DocB")
    doc_id = uuid.uuid4()
    async with AsyncSession(engine) as s:
        await s.execute(text(
            "INSERT INTO employee_documents (id, tenant_id, employee_id, document_type, title, storage_key, "
            "original_file_name, file_size_bytes, mime_type, created_at, updated_at, is_deleted) "
            "SELECT :i, :o, :e, 'OTHER', 'Contract scan', 'k', 'c.pdf', 10, 'application/pdf', now(), now(), false"
        ), {"i": doc_id, "o": org["org"], "e": uuid.UUID(b)})
        await s.commit()
    bad = await client.post(f"{API}/{a}/contracts", headers=h, json={
        "contract_type": "permanent", "start_date": "2026-01-01", "document_id": str(doc_id)})
    assert bad.status_code == 400
    ok = await client.post(f"{API}/{b}/contracts", headers=h, json={
        "contract_type": "permanent", "start_date": "2026-01-01", "document_id": str(doc_id)})
    assert ok.status_code == 201 and ok.json()["document_id"] == str(doc_id)


async def test_contracts_are_tenant_scoped_and_permission_gated(client, engine, org, other_org):
    owner = _h(org["owner"])
    e = await _hire(client, org, "Scoped")
    c = (await client.post(f"{API}/{e}/contracts", headers=owner, json={"contract_type": "permanent", "start_date": "2026-01-01"})).json()
    stranger = _h(other_org["owner"])
    assert (await client.patch(f"{API}/contracts/{c['id']}", headers=stranger, json={"notes": "x"})).status_code == 404
    assert (await client.post(f"{API}/contracts/{c['id']}/terminate", headers=stranger, json={})).status_code == 404
    assert (await client.get(f"{API}/{e}/contracts", headers=stranger)).status_code == 404
    assert (await client.get(f"{API}/contracts", headers=stranger)).json()["total"] == 0
    viewer = _h(await _role_user(engine, org, ["employees.view"], "Viewer"))
    assert (await client.get(f"{API}/{e}/contracts", headers=viewer)).status_code == 200
    assert (await client.post(f"{API}/{e}/contracts", headers=viewer, json={"contract_type": "permanent", "start_date": "2026-01-01"})).status_code == 403
    assert (await client.delete(f"{API}/contracts/{c['id']}", headers=viewer)).status_code == 403


async def test_contract_list_filters_and_derived_state(client, org):
    h = _h(org["owner"])
    today = date.today()
    mk = {}
    for name, ctype, start, end, alert in (
        ("Soon", "fixed_term", today - timedelta(days=100), today + timedelta(days=10), 30),
        ("Later", "fixed_term", today - timedelta(days=10), today + timedelta(days=200), 30),
        ("Past", "fixed_term", today - timedelta(days=200), today - timedelta(days=3), 30),
        ("Perm", "permanent", today - timedelta(days=50), None, 30),
    ):
        e = await _hire(client, org, name)
        r = await client.post(f"{API}/{e}/contracts", headers=h, json={
            "contract_type": ctype, "start_date": _iso(start), "end_date": _iso(end) if end else None, "renewal_alert_days": alert})
        assert r.status_code == 201, r.text
        mk[name] = r.json()
    assert {n: c["state"] for n, c in mk.items()} == {"Soon": "expiring", "Later": "active", "Past": "expired", "Perm": "active"}
    assert mk["Soon"]["days_left"] == 10

    def names(r):
        return [i["employee_name"].split()[0] for i in r.json()["items"]]
    assert names(await client.get(f"{API}/contracts", headers=h, params={"state": "expiring"})) == ["Soon"]
    assert names(await client.get(f"{API}/contracts", headers=h, params={"state": "expired"})) == ["Past"]
    assert sorted(names(await client.get(f"{API}/contracts", headers=h, params={"state": "active"}))) == ["Later", "Perm"]
    assert names(await client.get(f"{API}/contracts", headers=h, params={"expiring_within_days": 15})) == ["Past", "Soon"]
    assert (await client.get(f"{API}/contracts", headers=h, params={"state": "bogus"})).status_code == 400
    everything = (await client.get(f"{API}/contracts", headers=h)).json()
    assert everything["total"] == 4 and everything["items"][0]["employee_code"]


async def test_expiry_reminders_go_to_hr_once_a_week(client, engine, org):
    from app.models.workflows import Notification
    from app.services.employee_contracts import notify_expiring_contracts

    h = _h(org["owner"])
    today = date.today()
    soon, far = await _hire(client, org, "Soon"), await _hire(client, org, "Far")
    await client.post(f"{API}/{soon}/contracts", headers=h, json={
        "contract_type": "fixed_term", "start_date": _iso(today - timedelta(days=300)), "end_date": _iso(today + timedelta(days=5))})
    await client.post(f"{API}/{far}/contracts", headers=h, json={
        "contract_type": "fixed_term", "start_date": _iso(today), "end_date": _iso(today + timedelta(days=300))})
    hr = await _role_user(engine, org, ["employees.update"], "Hrx")
    nobody = await _role_user(engine, org, ["employees.view"], "Nobody")

    async def run(on):
        async with AsyncSession(engine, expire_on_commit=False) as s:
            res = await notify_expiring_contracts(s, today=on)
            await s.commit()
            return res

    async def mine(uid):
        async with AsyncSession(engine) as s:
            return (await s.execute(select(Notification).where(Notification.user_id == uid, Notification.type == "contract_expiry"))).scalars().all()

    first = await run(today)
    assert first["contracts"] == 1 and first["notifications"] == 2  # owner + HR, only the contract inside its window
    assert len(await mine(org["owner"])) == 1 and len(await mine(hr)) == 1 and await mine(nobody) == []
    again = await run(today + timedelta(days=3))
    assert again["contracts"] == 0
    week = await run(today + timedelta(days=7))
    assert week["contracts"] == 1 and len(await mine(org["owner"])) == 2
    note = (await mine(org["owner"]))[0]
    assert "Soon" in note.body and note.action_url.startswith(f"/employees/{soon}")


async def test_editing_the_end_date_resets_the_reminder(client, engine, org):
    from app.services.employee_contracts import notify_expiring_contracts

    h = _h(org["owner"])
    today = date.today()
    e = await _hire(client, org, "Reset")
    c = (await client.post(f"{API}/{e}/contracts", headers=h, json={
        "contract_type": "fixed_term", "start_date": _iso(today - timedelta(days=300)), "end_date": _iso(today + timedelta(days=5))})).json()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        assert (await notify_expiring_contracts(s, today=today))["contracts"] == 1
        await s.commit()
    await client.patch(f"{API}/contracts/{c['id']}", headers=h, json={"end_date": _iso(today + timedelta(days=4))})
    async with AsyncSession(engine, expire_on_commit=False) as s:
        assert (await notify_expiring_contracts(s, today=today))["contracts"] == 1
        await s.commit()


# ── export ──────────────────────────────────────────────────────────────────
async def test_export_csv_filters_neutralizes_formulas_and_needs_permission(client, engine, org):
    import csv, io

    h = _h(org["owner"])
    await _hire(client, org, "=HYPERLINK(\"http://evil\")", "Cell")
    await _hire(client, org, "Normal", "Person")
    r = await client.get(f"{API}/export", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 2 and rows[0]["employee_code"]
    assert all(not v.startswith("=") for row in rows for v in row.values())
    assert any(row["first_name"].startswith("'=") for row in rows)
    filt = list(csv.DictReader(io.StringIO((await client.get(f"{API}/export", headers=h, params={"query": "normal"})).text)))
    assert [x["first_name"] for x in filt] == ["Normal"]
    none = list(csv.DictReader(io.StringIO((await client.get(f"{API}/export", headers=h, params={"status": "resigned"})).text)))
    assert none == []
    viewer = _h(await _role_user(engine, org, ["employees.view"], "Viewer"))
    assert (await client.get(f"{API}/export", headers=viewer)).status_code == 403


async def test_export_never_includes_another_orgs_people(client, org, other_org):
    await _hire(client, other_org, "Secret", "Elsewhere")
    r = await client.get(f"{API}/export", headers=_h(org["owner"]))
    assert "Secret" not in r.text


# ── import ──────────────────────────────────────────────────────────────────
HEADER = "first_name,last_name,email,role,date_of_joining,employment_type,job_nature,department,phone,is_remote\n"


async def _import(client, h, body, dry):
    return await client.post(f"{API}/import", headers=h, params={"dry_run": str(dry).lower()},
                             files={"file": ("e.csv", body.encode(), "text/csv")})


async def test_import_dry_run_creates_nothing_then_real_run_creates_good_rows_only(client, engine, org):
    h = _h(org["owner"])
    async with AsyncSession(engine) as s:
        await s.execute(text("INSERT INTO departments (id, tenant_id, name, created_at, updated_at, is_deleted) VALUES (:i, :o, 'Engineering', now(), now(), false)"),
                        {"i": uuid.uuid4(), "o": org["org"]})
        await s.commit()
    tag = uuid.uuid4().hex[:6]
    csv_body = HEADER + (
        f"Ali,Raza,ali-{tag}@example.com,Staff,2026-02-01,full_time,permanent,Engineering,+92 300 1,yes\n"
        f"Bad,Role,bad-{tag}@example.com,Nope,2026-02-01,,,,,\n"
        f"Bad,Date,date-{tag}@example.com,Staff,not-a-date,,,,,\n"
        f"Dup,One,ali-{tag}@example.com,Staff,2026-02-01,,,,,\n"
        f"Bad,Dept,dept-{tag}@example.com,Staff,2026-02-01,,,Ghost,,\n"
        f"Sana,Malik,sana-{tag}@example.com,Staff,2026-02-02,,,,,\n"
    )
    dry = await _import(client, h, csv_body, True)
    assert dry.status_code == 200, dry.text
    d = dry.json()
    assert d["dry_run"] and d["total"] == 6 and d["created"] == 2 and d["failed"] == 4
    assert (await client.get(API, headers=h)).json()["total"] == 0           # nothing written
    errs = {r["row"]: r["error"] for r in d["rows"] if not r["ok"]}
    assert "Unknown role" in errs[3] and "date_of_joining" in errs[4] and "Duplicate" in errs[5] and "Unknown department" in errs[6]
    assert "temporary_password" not in dry.text

    real = (await _import(client, h, csv_body, False)).json()
    assert real["created"] == 2 and real["failed"] == 4
    ok = [r for r in real["rows"] if r["ok"]]
    assert all(r["employee_code"] and len(r["temporary_password"]) >= 12 for r in ok)
    listing = (await client.get(API, headers=h)).json()
    assert listing["total"] == 2
    ali = next(i for i in listing["items"] if i["first_name"] == "Ali")
    assert ali["job_nature"] == "permanent" and ali["employment_type"] == "full_time"
    tl = (await client.get(f"{API}/{ali['id']}/history", headers=h)).json()
    assert [(t["to_status"], t["source"]) for t in tl] == [("active", "import")]
    # running the same file again: everything that worked is now a duplicate
    again = (await _import(client, h, csv_body, False)).json()
    assert again["created"] == 0 and again["failed"] == 6


async def test_import_input_checks_and_permission(client, engine, org):
    h = _h(org["owner"])
    assert (await _import(client, h, "first_name,last_name\nA,B\n", True)).status_code == 400   # missing columns
    assert (await _import(client, h, HEADER, True)).status_code == 400                           # no rows
    many = HEADER + "".join(f"U{i},X,u{i}@example.com,Staff,2026-01-01,,,,,\n" for i in range(501))
    assert (await _import(client, h, many, True)).status_code == 400                             # too many
    viewer = _h(await _role_user(engine, org, ["employees.view"], "Viewer"))
    assert (await _import(client, viewer, HEADER + "A,B,a@example.com,Staff,2026-01-01,,,,,\n", False)).status_code == 403
    creator = _h(await _role_user(engine, org, ["employees.create"], "Creator"))
    t = await client.get(f"{API}/import/template", headers=creator)
    assert t.status_code == 200 and t.text.splitlines()[0].startswith("first_name,last_name,email,role")


async def test_import_cannot_hand_out_a_role_the_importer_does_not_hold(client, engine, org):
    """Same guard as Add Employee: a creator cannot mint an owner/super account via CSV."""
    async with AsyncSession(engine) as s:
        await s.execute(text("INSERT INTO roles (id, organization_id, name, slug, is_super, created_at, updated_at) "
                             "VALUES (:i, :o, 'SuperRole', 'superrole', true, now(), now())"),
                        {"i": uuid.uuid4(), "o": org["org"]})
        await s.commit()
    creator = _h(await _role_user(engine, org, ["employees.create"], "Creator"))
    r = (await _import(client, creator, HEADER + f"A,B,a-{uuid.uuid4().hex[:5]}@example.com,SuperRole,2026-01-01,,,,,\n", False)).json()
    assert r["created"] == 0 and r["failed"] == 1
