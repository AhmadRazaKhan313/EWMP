"""N-01: offers, onboarding templates/cases/tasks, pre-boarding, confirmation,
offboarding checklist, dashboard and the daily sweep. Live Postgres, real HTTP."""
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import rate_limit
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.organization import Organization
from app.models.rbac import Permission, Role
from app.models.user import User
from app.workers.tasks import email as email_tasks
from app.workers.tasks import notifications as notification_tasks
from app.workers.tasks import onboarding as onboarding_tasks

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp"
)
pytestmark = pytest.mark.asyncio
API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(email_tasks.send_verification_email, "delay", lambda *a, **k: None)
    monkeypatch.setattr(notification_tasks.trigger_workflow_event, "delay", lambda *a, **k: None)
    for t in (onboarding_tasks.send_offer_email, onboarding_tasks.send_preboarding_email,
              onboarding_tasks.send_welcome_email):
        monkeypatch.setattr(t, "delay", lambda *a, **k: None)
    monkeypatch.setattr(rate_limit, "_limiter", None)  # fresh in-memory counters per test


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
        s.add(Organization(id=org_id, name="Onboard Org", slug=f"ob-{org_id.hex[:8]}",
                           email=f"o-{org_id.hex[:8]}@example.com", timezone="Asia/Karachi"))
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
            "DELETE FROM onboarding_case_documents WHERE tenant_id = :o",
            "DELETE FROM onboarding_case_tasks WHERE tenant_id = :o",
            "DELETE FROM onboarding_cases WHERE tenant_id = :o",
            "DELETE FROM offers WHERE tenant_id = :o",
            "DELETE FROM onboarding_template_tasks WHERE tenant_id = :o",
            "DELETE FROM onboarding_templates WHERE tenant_id = :o",
            "DELETE FROM auth_refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE organization_id = :o)",
            "DELETE FROM notifications WHERE tenant_id = :o",
            "DELETE FROM employee_contracts WHERE tenant_id = :o",
            "DELETE FROM employee_status_history WHERE tenant_id = :o",
            "DELETE FROM employee_documents WHERE tenant_id = :o",
            "DELETE FROM employees WHERE tenant_id = :o",
            "DELETE FROM designations WHERE tenant_id = :o",
            "DELETE FROM departments WHERE tenant_id = :o",
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


async def _grant_role(engine, org, perms, name="Role") -> uuid.UUID:
    from app.database.seeds.permissions import PERMISSIONS_BY_CODENAME

    async with AsyncSession(engine, expire_on_commit=False) as s:
        wanted = list((await s.execute(select(Permission).where(Permission.codename.in_(perms)))).scalars().all())
        for codename in set(perms) - {p.codename for p in wanted}:
            d = PERMISSIONS_BY_CODENAME[codename]
            row = Permission(resource=d["resource"], action=d["action"], codename=codename, label=d["label"],
                             category=d["category"], is_sensitive=d.get("is_sensitive", False))
            s.add(row)
            wanted.append(row)
        role = Role(organization_id=org["org"], name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:5]}")
        role.permissions = list(wanted)
        s.add(role)
        await s.flush()
        rid = role.id
        await s.commit()
    return rid


async def _role_user(engine, org, perms, name="Hr") -> uuid.UUID:
    rid = await _grant_role(engine, org, perms, name)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        email = f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.com"
        u = User(organization_id=org["org"], email=email, email_normalized=email,
                 password_hash=hash_password("x"), first_name=name, last_name="User",
                 is_active=True, is_email_verified=True)
        u.roles.append(await s.get(Role, rid))
        s.add(u)
        await s.flush()
        uid = u.id
        await s.commit()
    return uid


def _offer_payload(**kw) -> dict:
    base = {
        "candidate_name": "Ayesha Khan", "candidate_email": f"ayesha-{uuid.uuid4().hex[:8]}@example.com",
        "job_title": "Backend Engineer", "salary": 150000, "currency": "PKR", "probation_months": 3,
        "joining_date": (date.today() + timedelta(days=14)).isoformat(),
    }
    base.update(kw)
    return base


async def _offer(client, org, **kw) -> dict:
    r = await client.post(f"{API}/onboarding/offers", headers=_h(org["owner"]), json=_offer_payload(**kw))
    assert r.status_code == 201, r.text
    return r.json()


async def _accepted_offer(client, org, **kw) -> dict:
    o = await _offer(client, org, **kw)
    h = _h(org["owner"])
    assert (await client.post(f"{API}/onboarding/offers/{o['id']}/submit", headers=h)).status_code == 200
    r = await client.post(f"{API}/onboarding/offers/{o['id']}/send", headers=h)
    assert r.status_code == 200, r.text
    token = r.json()["link"].rsplit("/", 1)[1]
    r = await client.post(f"{API}/public/offers/{token}/accept",
                          json={"full_name": o["candidate_name"], "agree": True})
    assert r.status_code == 200, r.text
    return {**o, "token": token}


async def _convert(client, org, offer_id, role_id=None, **kw) -> dict:
    r = await client.post(f"{API}/onboarding/offers/{offer_id}/convert", headers=_h(org["owner"]),
                          json={"role_id": str(role_id or org["role"]), **kw})
    assert r.status_code == 200, r.text
    return r.json()


async def _defaults(client, org):
    r = await client.post(f"{API}/onboarding/templates/defaults", headers=_h(org["owner"]))
    assert r.status_code == 200, r.text
    return r.json()


async def _user_of_employee(engine, employee_id) -> uuid.UUID:
    async with AsyncSession(engine) as s:
        return (await s.execute(text("SELECT user_id FROM employees WHERE id = :e"), {"e": employee_id})).scalar_one()


# ═══ offers ════════════════════════════════════════════════════════════════
async def test_offer_full_lifecycle_to_employee(client, engine, org):
    await _defaults(client, org)
    o = await _accepted_offer(client, org)
    h = _h(org["owner"])
    detail = (await client.get(f"{API}/onboarding/offers/{o['id']}", headers=h)).json()
    assert detail["status"] == "accepted" and detail["accepted_name"] == "Ayesha Khan"

    conv = await _convert(client, org, o["id"])
    assert conv["employee_code"] and conv["case"]["kind"] == "onboarding"
    assert conv["case"]["status"] == "pre_boarding" and conv["case"]["preboarding_link"]
    emp = (await client.get(f"{API}/employees/{conv['employee_id']}", headers=h)).json()
    assert emp["current_salary"] in (150000, 150000.0, "150000.00", "150000")
    assert (await client.get(f"{API}/onboarding/offers/{o['id']}", headers=h)).json()["employee_id"] == conv["employee_id"]

    again = await client.post(f"{API}/onboarding/offers/{o['id']}/convert", headers=h, json={"role_id": str(org["role"])})
    assert again.status_code == 409


async def test_cannot_convert_unaccepted_offer_or_without_employee_permission(client, engine, org):
    o = await _offer(client, org)
    h = _h(org["owner"])
    r = await client.post(f"{API}/onboarding/offers/{o['id']}/convert", headers=h, json={"role_id": str(org["role"])})
    assert r.status_code == 409
    acc = await _accepted_offer(client, org)
    hr = await _role_user(engine, org, ["offers.manage"])
    r = await client.post(f"{API}/onboarding/offers/{acc['id']}/convert", headers=_h(hr), json={"role_id": str(org["role"])})
    assert r.status_code == 403  # creating an employee needs employees.create too


async def test_approval_chain_in_order_and_rejection(client, engine, org):
    a1 = await _role_user(engine, org, ["offers.approve"], "Ap1")
    a2 = await _role_user(engine, org, ["offers.approve"], "Ap2")
    outsider = await _role_user(engine, org, ["offers.approve"], "Out")
    h = _h(org["owner"])
    o = await _offer(client, org, approver_ids=[str(a1), str(a2)])
    assert (await client.post(f"{API}/onboarding/offers/{o['id']}/submit", headers=h)).json()["status"] == "pending_approval"
    # cannot send before it is approved
    assert (await client.post(f"{API}/onboarding/offers/{o['id']}/send", headers=h)).status_code == 409
    # second approver (or an outsider) cannot jump the queue
    for who in (a2, outsider):
        r = await client.post(f"{API}/onboarding/offers/{o['id']}/decision", headers=_h(who), json={"decision": "approved"})
        assert r.status_code == 403
    assert (await client.post(f"{API}/onboarding/offers/{o['id']}/decision", headers=_h(a1),
                              json={"decision": "approved"})).json()["status"] == "pending_approval"
    done = await client.post(f"{API}/onboarding/offers/{o['id']}/decision", headers=_h(a2), json={"decision": "approved"})
    assert done.json()["status"] == "approved" and len(done.json()["approvals"]) == 2

    o2 = await _offer(client, org, approver_ids=[str(a1)])
    await client.post(f"{API}/onboarding/offers/{o2['id']}/submit", headers=h)
    rej = await client.post(f"{API}/onboarding/offers/{o2['id']}/decision", headers=_h(a1),
                            json={"decision": "rejected", "note": "too high"})
    assert rej.json()["status"] == "draft"
    # editable again, and resubmitting restarts the chain
    assert (await client.patch(f"{API}/onboarding/offers/{o2['id']}", headers=h, json={"salary": 120000})).status_code == 200
    again = await client.post(f"{API}/onboarding/offers/{o2['id']}/submit", headers=h)
    assert again.json()["status"] == "pending_approval" and again.json()["approvals"] == []


async def test_public_link_security_and_states(client, engine, org):
    o = await _offer(client, org)
    h = _h(org["owner"])
    await client.post(f"{API}/onboarding/offers/{o['id']}/submit", headers=h)
    sent = (await client.post(f"{API}/onboarding/offers/{o['id']}/send", headers=h)).json()
    token = sent["link"].rsplit("/", 1)[1]
    assert (await client.get(f"{API}/public/offers/not-a-real-token")).status_code == 404
    # only a hash is stored, never the token itself
    async with AsyncSession(engine) as s:
        stored = (await s.execute(text("SELECT token_hash FROM offers WHERE id = :i"), {"i": o["id"]})).scalar_one()
    assert stored != token and len(stored) == 64

    view = await client.get(f"{API}/public/offers/{token}")
    assert view.status_code == 200 and view.json()["can_respond"] is True
    assert (await client.get(f"{API}/onboarding/offers/{o['id']}", headers=h)).json()["status"] == "viewed"
    assert "candidate_email" not in view.json()  # public view exposes only the offer itself

    bad = await client.post(f"{API}/public/offers/{token}/accept", json={"full_name": "Someone Else", "agree": True})
    assert bad.status_code == 400
    noagree = await client.post(f"{API}/public/offers/{token}/accept", json={"full_name": "Ayesha Khan", "agree": False})
    assert noagree.status_code == 400
    ok = await client.post(f"{API}/public/offers/{token}/accept", json={"full_name": "  ayesha   KHAN ", "agree": True})
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"
    assert (await client.post(f"{API}/public/offers/{token}/accept", json={"full_name": "Ayesha Khan", "agree": True})).status_code == 409
    assert (await client.post(f"{API}/public/offers/{token}/decline", json={})).status_code == 409


async def test_decline_notifies_hr(client, engine, org):
    o = await _offer(client, org)
    h = _h(org["owner"])
    await client.post(f"{API}/onboarding/offers/{o['id']}/submit", headers=h)
    token = (await client.post(f"{API}/onboarding/offers/{o['id']}/send", headers=h)).json()["link"].rsplit("/", 1)[1]
    r = await client.post(f"{API}/public/offers/{token}/decline", json={"reason": "Got another offer"})
    assert r.status_code == 200 and r.json()["status"] == "declined"
    d = (await client.get(f"{API}/onboarding/offers/{o['id']}", headers=h)).json()
    assert d["decline_reason"] == "Got another offer"
    async with AsyncSession(engine) as s:
        n = (await s.execute(text("SELECT count(*) FROM notifications WHERE tenant_id=:o AND type='offer_declined'"),
                             {"o": org["org"]})).scalar_one()
    assert n >= 1


async def test_offer_expiry_lazy_and_sweep(client, engine, org):
    from app.services.onboarding import run_daily_sweep

    o = await _offer(client, org)
    h = _h(org["owner"])
    await client.post(f"{API}/onboarding/offers/{o['id']}/submit", headers=h)
    token = (await client.post(f"{API}/onboarding/offers/{o['id']}/send", headers=h)).json()["link"].rsplit("/", 1)[1]
    async with AsyncSession(engine) as s:
        await s.execute(text("UPDATE offers SET expires_at = now() - interval '1 hour' WHERE id = :i"), {"i": o["id"]})
        await s.commit()
    # past its expiry the candidate sees "expired" (every time) and cannot respond
    for _ in range(2):
        gone = await client.get(f"{API}/public/offers/{token}")
        assert gone.status_code == 200 and gone.json()["status"] == "expired" and gone.json()["can_respond"] is False
    late = await client.post(f"{API}/public/offers/{token}/accept", json={"full_name": "Ayesha Khan", "agree": True})
    assert late.status_code == 409

    o2 = await _offer(client, org)
    await client.post(f"{API}/onboarding/offers/{o2['id']}/submit", headers=h)
    await client.post(f"{API}/onboarding/offers/{o2['id']}/send", headers=h)
    async with AsyncSession(engine) as s:
        await s.execute(text("UPDATE offers SET expires_at = now() - interval '1 hour' WHERE id = :i"), {"i": o2["id"]})
        await s.commit()
    async with AsyncSession(engine) as s:
        result = await run_daily_sweep(s)
        await s.commit()
    assert result["offers_expired"] >= 1
    assert (await client.get(f"{API}/onboarding/offers/{o2['id']}", headers=h)).json()["status"] == "expired"


async def test_revise_and_revoke(client, org):
    h = _h(org["owner"])
    o = await _offer(client, org)
    await client.post(f"{API}/onboarding/offers/{o['id']}/submit", headers=h)
    token = (await client.post(f"{API}/onboarding/offers/{o['id']}/send", headers=h)).json()["link"].rsplit("/", 1)[1]
    rev = await client.post(f"{API}/onboarding/offers/{o['id']}/revise", headers=h, json={"salary": 175000})
    assert rev.status_code == 200, rev.text
    v2 = rev.json()
    assert v2["version"] == 2 and v2["status"] == "draft" and v2["salary"] == 175000
    assert v2["parent_offer_id"] == o["id"]
    assert (await client.get(f"{API}/onboarding/offers/{o['id']}", headers=h)).json()["status"] == "revised"
    assert (await client.get(f"{API}/public/offers/{token}")).status_code == 404  # old link is dead
    hist = (await client.get(f"{API}/onboarding/offers/{v2['id']}", headers=h)).json()["history"]
    assert [x["version"] for x in hist] == [1, 2]

    await client.post(f"{API}/onboarding/offers/{v2['id']}/submit", headers=h)
    t2 = (await client.post(f"{API}/onboarding/offers/{v2['id']}/send", headers=h)).json()["link"].rsplit("/", 1)[1]
    assert (await client.post(f"{API}/onboarding/offers/{v2['id']}/revoke", headers=h)).json()["status"] == "revoked"
    assert (await client.get(f"{API}/public/offers/{t2}")).status_code == 404


async def test_offer_validation(client, org):
    h = _h(org["owner"])
    past = _offer_payload(joining_date=(date.today() - timedelta(days=1)).isoformat())
    assert (await client.post(f"{API}/onboarding/offers", headers=h, json=past)).status_code == 400
    noname = _offer_payload(candidate_name="A")
    assert (await client.post(f"{API}/onboarding/offers", headers=h, json=noname)).status_code == 422
    nosal = await _offer(client, org, salary=None)
    assert (await client.post(f"{API}/onboarding/offers/{nosal['id']}/submit", headers=h)).status_code == 400
    bogus = _offer_payload(department_id=str(uuid.uuid4()))
    assert (await client.post(f"{API}/onboarding/offers", headers=h, json=bogus)).status_code == 400


async def test_resend_replaces_the_link(client, org):
    h = _h(org["owner"])
    o = await _offer(client, org)
    await client.post(f"{API}/onboarding/offers/{o['id']}/submit", headers=h)
    t1 = (await client.post(f"{API}/onboarding/offers/{o['id']}/send", headers=h)).json()["link"].rsplit("/", 1)[1]
    t2 = (await client.post(f"{API}/onboarding/offers/{o['id']}/send", headers=h)).json()["link"].rsplit("/", 1)[1]
    assert t1 != t2
    assert (await client.get(f"{API}/public/offers/{t1}")).status_code == 404
    assert (await client.get(f"{API}/public/offers/{t2}")).status_code == 200


async def test_public_endpoints_are_rate_limited(client, monkeypatch):
    from app.api.v1.hrms import onboarding_public

    monkeypatch.setattr(onboarding_public, "PER_MINUTE", 3)
    codes = [(await client.get(f"{API}/public/offers/guess-{i}")).status_code for i in range(6)]
    assert codes[:3] == [404, 404, 404] and 429 in codes[3:]


# ═══ tenant isolation / permissions ════════════════════════════════════════
async def test_other_tenant_cannot_see_or_touch_anything(client, engine, org, other_org):
    await _defaults(client, org)
    o = await _accepted_offer(client, org)
    conv = await _convert(client, org, o["id"])
    them = _h(other_org["owner"])
    tmpl = (await client.get(f"{API}/onboarding/templates", headers=_h(org["owner"]))).json()["items"][0]
    for method, url in (
        ("get", f"{API}/onboarding/offers/{o['id']}"), ("post", f"{API}/onboarding/offers/{o['id']}/revoke"),
        ("get", f"{API}/onboarding/cases/{conv['case']['id']}"),
        ("post", f"{API}/onboarding/cases/{conv['case']['id']}/cancel"),
        ("get", f"{API}/onboarding/templates/{tmpl['id']}"),
    ):
        assert (await getattr(client, method)(url, headers=them)).status_code == 404, url
    assert (await client.get(f"{API}/onboarding/offers", headers=them)).json()["total"] == 0
    assert (await client.get(f"{API}/onboarding/cases", headers=them)).json()["total"] == 0
    # a case cannot be opened for another tenant's employee, nor use their template
    r = await client.post(f"{API}/onboarding/cases", headers=them, json={"employee_id": conv["employee_id"]})
    assert r.status_code == 404


async def test_permissions_are_enforced(client, engine, org):
    nobody = await _role_user(engine, org, [], "Nobody")
    for method, url, body in (
        ("get", f"{API}/onboarding/dashboard", None), ("get", f"{API}/onboarding/offers", None),
        ("get", f"{API}/onboarding/templates", None), ("get", f"{API}/onboarding/cases", None),
        ("get", f"{API}/onboarding/tasks/mine", None),
        ("post", f"{API}/onboarding/templates/defaults", {}),
    ):
        r = await getattr(client, method)(url, headers=_h(nobody), **({"json": body} if body is not None else {}))
        assert r.status_code == 403, url
    viewer = await _role_user(engine, org, ["onboarding.view"], "Viewer")
    assert (await client.get(f"{API}/onboarding/dashboard", headers=_h(viewer))).status_code == 200
    assert (await client.post(f"{API}/onboarding/templates/defaults", headers=_h(viewer))).status_code == 403
    assert (await client.get(f"{API}/onboarding/tasks/mine", headers=_h(viewer))).status_code == 403
    mine = await _role_user(engine, org, ["onboarding.view_own"], "Own")
    assert (await client.get(f"{API}/onboarding/tasks/mine", headers=_h(mine))).status_code == 200
    anon = await client.get(f"{API}/onboarding/dashboard")
    assert anon.status_code in (401, 403)


# ═══ templates ═════════════════════════════════════════════════════════════
async def test_default_templates_seed_once_and_validate(client, org):
    h = _h(org["owner"])
    first = (await _defaults(client, org))["created"]
    assert {t["kind"] for t in first} == {"onboarding", "offboarding"}
    assert (await _defaults(client, org))["created"] == []  # idempotent
    listing = (await client.get(f"{API}/onboarding/templates", headers=h)).json()["items"]
    assert len(listing) == 2 and all(t["task_count"] > 0 for t in listing)

    loop = {"name": "Loop", "kind": "onboarding", "tasks": [
        {"order": 0, "title": "A one", "depends_on_order": 1}, {"order": 1, "title": "B two", "depends_on_order": 0}]}
    assert (await client.post(f"{API}/onboarding/templates", headers=h, json=loop)).status_code == 400
    dup = {"name": "Dup", "kind": "onboarding", "tasks": [{"order": 0, "title": "A one"}, {"order": 0, "title": "B two"}]}
    assert (await client.post(f"{API}/onboarding/templates", headers=h, json=dup)).status_code == 400
    bad_owner = {"name": "Bad", "kind": "onboarding", "tasks": [{"order": 0, "title": "A one", "owner_role": "ceo"}]}
    assert (await client.post(f"{API}/onboarding/templates", headers=h, json=bad_owner)).status_code == 400
    ghost = {"name": "Ghost", "kind": "onboarding", "tasks": [{"order": 0, "title": "A one", "depends_on_order": 9}]}
    assert (await client.post(f"{API}/onboarding/templates", headers=h, json=ghost)).status_code == 400


async def test_template_edit_replaces_tasks_and_single_default(client, org):
    h = _h(org["owner"])
    t = (await client.post(f"{API}/onboarding/templates", headers=h, json={
        "name": "Mine", "kind": "onboarding", "is_default": True,
        "tasks": [{"order": 0, "title": "Only task"}]})).json()
    assert len(t["tasks"]) == 1
    up = await client.patch(f"{API}/onboarding/templates/{t['id']}", headers=h, json={
        "tasks": [{"order": 0, "title": "First"}, {"order": 1, "title": "Second", "depends_on_order": 0}]})
    assert [x["title"] for x in up.json()["tasks"]] == ["First", "Second"]
    t2 = (await client.post(f"{API}/onboarding/templates", headers=h, json={
        "name": "Newer", "kind": "onboarding", "is_default": True, "tasks": [{"order": 0, "title": "X task"}]})).json()
    defaults = [x for x in (await client.get(f"{API}/onboarding/templates?kind=onboarding", headers=h)).json()["items"]
                if x["is_default"]]
    assert [d["id"] for d in defaults] == [t2["id"]]


async def test_template_matching_prefers_the_most_specific(client, engine, org):
    h = _h(org["owner"])
    dept = (await client.post(f"{API}/departments", headers=h, json={"name": "Engineering", "code": "ENG"}))
    assert dept.status_code in (200, 201), dept.text
    dept_id = dept.json()["id"]
    generic = (await client.post(f"{API}/onboarding/templates", headers=h, json={
        "name": "Generic", "kind": "onboarding", "is_default": True, "tasks": [{"order": 0, "title": "Generic task"}]})).json()
    eng = (await client.post(f"{API}/onboarding/templates", headers=h, json={
        "name": "Engineering", "kind": "onboarding", "department_id": dept_id,
        "tasks": [{"order": 0, "title": "Eng task"}]})).json()
    o_eng = await _accepted_offer(client, org, department_id=dept_id)
    c1 = (await _convert(client, org, o_eng["id"]))["case"]
    assert c1["template_id"] == eng["id"]
    o_plain = await _accepted_offer(client, org)
    c2 = (await _convert(client, org, o_plain["id"]))["case"]
    assert c2["template_id"] == generic["id"]


async def test_no_template_gives_a_clear_error(client, org):
    o = await _accepted_offer(client, org)
    r = await client.post(f"{API}/onboarding/offers/{o['id']}/convert", headers=_h(org["owner"]),
                          json={"role_id": str(org["role"])})
    assert r.status_code == 400 and "template" in r.json()["message"].lower()
    # nothing was created: the offer is still waiting to be converted
    assert (await client.get(f"{API}/onboarding/offers/{o['id']}", headers=_h(org["owner"]))).json()["employee_id"] is None
    await _defaults(client, org)
    assert (await client.post(f"{API}/onboarding/offers/{o['id']}/convert", headers=_h(org["owner"]),
                              json={"role_id": str(org["role"])})).status_code == 200


# ═══ cases and tasks ═══════════════════════════════════════════════════════
async def test_case_tasks_dates_dependencies_and_auto_account(client, engine, org):
    await _defaults(client, org)
    o = await _accepted_offer(client, org)
    conv = await _convert(client, org, o["id"])
    case = (await client.get(f"{API}/onboarding/cases/{conv['case']['id']}", headers=_h(org["owner"]))).json()
    anchor = date.fromisoformat(case["anchor_date"])
    assert anchor == date.fromisoformat(o["joining_date"])
    tasks = {t["title"]: t for t in case["tasks"]}
    assert date.fromisoformat(tasks["30-day check-in"]["due_date"]) == anchor + timedelta(days=30)
    assert date.fromisoformat(tasks["Send welcome message"]["due_date"]) == anchor - timedelta(days=5)
    assert tasks["Create login account"]["status"] == "done"  # the account exists already
    assert tasks["Enroll the device"]["blocked"] is True  # waits for "Assign laptop and equipment"
    assert len(case["documents"]) >= 3 and case["status"] == "pre_boarding"

    h = _h(org["owner"])
    blocked = await client.patch(f"{API}/onboarding/tasks/{tasks['Enroll the device']['id']}", headers=h, json={"status": "done"})
    assert blocked.status_code == 409
    assert (await client.patch(f"{API}/onboarding/tasks/{tasks['Assign laptop and equipment']['id']}", headers=h,
                               json={"status": "done"})).status_code == 200
    assert (await client.patch(f"{API}/onboarding/tasks/{tasks['Enroll the device']['id']}", headers=h,
                               json={"status": "done"})).status_code == 200
    prog = (await client.get(f"{API}/onboarding/cases/{case['id']}", headers=h)).json()["progress"]
    assert prog["done"] == 3 and prog["total"] == 17 and prog["percent"] == 18


async def test_one_open_case_per_employee_and_cancel(client, org):
    await _defaults(client, org)
    h = _h(org["owner"])
    o = await _accepted_offer(client, org)
    conv = await _convert(client, org, o["id"])
    dup = await client.post(f"{API}/onboarding/cases", headers=h, json={"employee_id": conv["employee_id"]})
    assert dup.status_code == 409
    assert (await client.post(f"{API}/onboarding/cases/{conv['case']['id']}/cancel", headers=h)).json()["status"] == "cancelled"
    again = await client.post(f"{API}/onboarding/cases", headers=h, json={"employee_id": conv["employee_id"]})
    assert again.status_code == 201
    assert (await client.post(f"{API}/onboarding/cases/{conv['case']['id']}/cancel", headers=h)).status_code == 200


async def test_task_permissions_assignee_and_manager(client, engine, org):
    await _defaults(client, org)
    h = _h(org["owner"])
    hire_role = await _grant_role(engine, org, ["onboarding.view_own"], "NewHire")
    mgr_user = await _role_user(engine, org, ["onboarding.view_own"], "Boss")
    # make an employee record for the manager
    mgr_emp = (await client.post(f"{API}/employees", headers=h, json={
        "first_name": "Mgr", "last_name": "One", "email": f"mgr-{uuid.uuid4().hex[:6]}@example.com",
        "date_of_joining": "2026-01-01", "role_id": str(org["role"])})).json()["id"]
    o = await _accepted_offer(client, org)
    conv = await _convert(client, org, o["id"], role_id=hire_role, manager_id=mgr_emp)
    hire_user = await _user_of_employee(engine, conv["employee_id"])
    async with AsyncSession(engine) as s:  # the hire has already chosen their own password
        await s.execute(text("UPDATE users SET must_change_password = false, is_email_verified = true WHERE id = :u"), {"u": hire_user})
        await s.commit()
    case = (await client.get(f"{API}/onboarding/cases/{conv['case']['id']}", headers=h)).json()
    t = {x["title"]: x for x in case["tasks"]}
    assert t["Introduce the buddy and the team"]["assignee_user_id"] is not None  # the manager's login
    assert t["Fill in personal details (pre-boarding form)"]["assignee_user_id"] == str(hire_user)

    mine = (await client.get(f"{API}/onboarding/tasks/mine", headers=_h(hire_user))).json()["items"]
    assert {x["title"] for x in mine} >= {"Fill in personal details (pre-boarding form)", "Complete orientation / training"}

    own = t["Complete orientation / training"]["id"]
    assert (await client.patch(f"{API}/onboarding/tasks/{own}", headers=_h(hire_user), json={"status": "done"})).status_code == 200
    hr_task = t["Verify submitted documents"]["id"]
    assert (await client.patch(f"{API}/onboarding/tasks/{hr_task}", headers=_h(hire_user), json={"status": "done"})).status_code == 403
    assert (await client.patch(f"{API}/onboarding/tasks/{own}", headers=_h(hire_user), json={"status": "skipped"})).status_code == 403
    assert (await client.patch(f"{API}/onboarding/tasks/{own}", headers=_h(hire_user),
                               json={"assignee_user_id": str(hire_user)})).status_code == 403
    # a user with no relation to the case cannot touch it
    stranger = await _role_user(engine, org, ["onboarding.view_own"], "Stranger")
    assert (await client.patch(f"{API}/onboarding/tasks/{own}", headers=_h(stranger), json={"status": "pending"})).status_code == 403
    # HR can reassign; the new assignee is notified
    r = await client.patch(f"{API}/onboarding/tasks/{hr_task}", headers=h, json={"assignee_user_id": str(mgr_user)})
    assert r.status_code == 200 and r.json()["assignee_user_id"] == str(mgr_user)


async def test_changing_manager_and_date_reassigns_and_reschedules(client, engine, org):
    await _defaults(client, org)
    h = _h(org["owner"])
    mgr_emp = (await client.post(f"{API}/employees", headers=h, json={
        "first_name": "Mgr", "last_name": "Two", "email": f"mgr2-{uuid.uuid4().hex[:6]}@example.com",
        "date_of_joining": "2026-01-01", "role_id": str(org["role"])})).json()["id"]
    o = await _accepted_offer(client, org)
    conv = await _convert(client, org, o["id"])
    cid = conv["case"]["id"]
    new_anchor = (date.today() + timedelta(days=30)).isoformat()
    r = await client.patch(f"{API}/onboarding/cases/{cid}", headers=h, json={"manager_id": mgr_emp, "anchor_date": new_anchor})
    assert r.status_code == 200, r.text
    case = (await client.get(f"{API}/onboarding/cases/{cid}", headers=h)).json()
    t = {x["title"]: x for x in case["tasks"]}
    assert t["30-day check-in"]["due_date"] == (date.fromisoformat(new_anchor) + timedelta(days=30)).isoformat()
    assert t["Introduce the buddy and the team"]["assignee_user_id"] == str(await _user_of_employee(engine, mgr_emp))
    # the employee's joining date follows while they have not started
    emp = (await client.get(f"{API}/employees/{conv['employee_id']}", headers=h)).json()
    assert emp["date_of_joining"] == new_anchor
    selfmgr = await client.patch(f"{API}/onboarding/cases/{cid}", headers=h, json={"buddy_id": conv["employee_id"]})
    assert selfmgr.status_code == 400


# ═══ pre-boarding ══════════════════════════════════════════════════════════
async def _preboarding_token(client, org, **offer_kw):
    await _defaults(client, org)
    o = await _accepted_offer(client, org, **offer_kw)
    conv = await _convert(client, org, o["id"])
    return conv, conv["case"]["preboarding_link"].rsplit("/", 1)[1]


async def test_preboarding_form_applies_to_employee_and_completes_tasks(client, engine, org):
    h = _h(org["owner"])
    conv, token = await _preboarding_token(client, org)
    view = await client.get(f"{API}/public/preboarding/{token}")
    assert view.status_code == 200 and view.json()["first_name"] == "Ayesha" and view.json()["submitted"] is False

    assert (await client.get(f"{API}/public/preboarding/wrong")).status_code == 404
    draft = await client.put(f"{API}/public/preboarding/{token}", json={"form": {"personal_phone": "0300-1111111"}})
    assert draft.status_code == 200
    # nothing is written to the employee until the form is submitted
    emp = (await client.get(f"{API}/employees/{conv['employee_id']}", headers=h)).json()
    assert not emp.get("personal_phone")

    short = await client.put(f"{API}/public/preboarding/{token}", json={"form": {}, "submit": True})
    assert short.status_code == 400 and "emergency" in short.json()["message"].lower()
    bad = await client.put(f"{API}/public/preboarding/{token}", json={"form": {"gender": "robot"}})
    assert bad.status_code == 400
    bad2 = await client.put(f"{API}/public/preboarding/{token}",
                            json={"form": {"emergency_contacts": [{"name": "Only name"}]}})
    assert bad2.status_code == 400

    full = {
        "address": "House 1, Bahawalpur", "national_id": "31202-1234567-1", "national_id_type": "cnic",
        "bank_name": "Faysal Bank", "bank_account_number": "0011223344", "date_of_birth": "1998-04-02",
        "gender": "female",
        "emergency_contacts": [{"name": "Brother", "phone": "0300-2222222", "relationship": "Sibling"}],
        "is_admin": True, "employee_code": "HACKED",  # unknown keys must be ignored
    }
    done = await client.put(f"{API}/public/preboarding/{token}",
                            json={"form": full, "submit": True, "acknowledge_policy": True})
    assert done.status_code == 200, done.text
    assert done.json()["submitted"] is True
    emp = (await client.get(f"{API}/employees/{conv['employee_id']}", headers=h)).json()
    assert emp["personal_phone"] == "0300-1111111" and emp["national_id"] == "31202-1234567-1"
    assert emp["bank_name"] == "Faysal Bank" and emp["employee_code"] != "HACKED"
    assert emp["emergency_contacts"][0]["name"] == "Brother"

    case = (await client.get(f"{API}/onboarding/cases/{conv['case']['id']}", headers=h)).json()
    t = {x["title"]: x for x in case["tasks"]}
    assert t["Fill in personal details (pre-boarding form)"]["status"] == "done"
    assert t["Acknowledge company policies"]["status"] == "done"
    again = await client.put(f"{API}/public/preboarding/{token}", json={"form": {"address": "Elsewhere"}})
    assert again.status_code == 409


async def test_preboarding_documents_upload_review_and_reject(client, engine, org):
    h = _h(org["owner"])
    conv, token = await _preboarding_token(client, org)
    docs = (await client.get(f"{API}/public/preboarding/{token}")).json()["documents"]
    required = [d for d in docs if d["is_required"]]
    assert required

    exe = await client.post(f"{API}/public/preboarding/{token}/documents/{required[0]['id']}",
                            files={"file": ("virus.png", b"MZ\x90\x00not-an-image", "image/png")})
    assert exe.status_code == 400  # content is sniffed, the filename/Content-Type are not trusted
    for d in required:
        up = await client.post(f"{API}/public/preboarding/{token}/documents/{d['id']}",
                               files={"file": ("scan.png", PNG, "image/png")})
        assert up.status_code == 200, up.text
        assert up.json()["status"] == "uploaded"
    case = (await client.get(f"{API}/onboarding/cases/{conv['case']['id']}", headers=h)).json()
    assert {x["title"]: x for x in case["tasks"]}["Upload required documents"]["status"] == "done"
    docs_after = (await client.get(f"{API}/employees/{conv['employee_id']}/documents", headers=h)).json()
    items = docs_after["items"] if isinstance(docs_after, dict) and "items" in docs_after else docs_after
    assert len(items) >= len(required)

    first = required[0]["id"]
    noreason = await client.post(f"{API}/onboarding/documents/{first}/review", headers=h, json={"approve": False})
    assert noreason.status_code == 400
    rej = await client.post(f"{API}/onboarding/documents/{first}/review", headers=h,
                            json={"approve": False, "reason": "Blurry"})
    assert rej.json()["status"] == "rejected"
    shown = (await client.get(f"{API}/public/preboarding/{token}")).json()["documents"]
    assert [d for d in shown if d["id"] == first][0]["rejection_reason"] == "Blurry"
    # the new hire can upload a replacement, HR then verifies it
    re_up = await client.post(f"{API}/public/preboarding/{token}/documents/{first}",
                              files={"file": ("scan2.png", PNG, "image/png")})
    assert re_up.json()["status"] == "uploaded"
    ok = await client.post(f"{API}/onboarding/documents/{first}/review", headers=h, json={"approve": True})
    assert ok.json()["status"] == "verified"
    locked = await client.post(f"{API}/public/preboarding/{token}/documents/{first}",
                               files={"file": ("scan3.png", PNG, "image/png")})
    assert locked.status_code == 409  # verified documents are final
    # a document id from some other case is not reachable with this token
    other = await client.post(f"{API}/public/preboarding/{token}/documents/{uuid.uuid4()}",
                              files={"file": ("x.png", PNG, "image/png")})
    assert other.status_code == 404


async def test_preboarding_link_reissue_and_expiry(client, engine, org):
    h = _h(org["owner"])
    conv, token = await _preboarding_token(client, org)
    new = (await client.post(f"{API}/onboarding/cases/{conv['case']['id']}/preboarding-link", headers=h)).json()["link"]
    new_token = new.rsplit("/", 1)[1]
    assert new_token != token
    assert (await client.get(f"{API}/public/preboarding/{token}")).status_code == 404
    assert (await client.get(f"{API}/public/preboarding/{new_token}")).status_code == 200
    async with AsyncSession(engine) as s:
        await s.execute(text("UPDATE onboarding_cases SET preboarding_expires_at = now() - interval '1 day' WHERE id = :i"),
                        {"i": conv["case"]["id"]})
        await s.commit()
    assert (await client.get(f"{API}/public/preboarding/{new_token}")).status_code == 404
    cancelled = await client.post(f"{API}/onboarding/cases/{conv['case']['id']}/cancel", headers=h)
    assert cancelled.status_code == 200
    assert (await client.get(f"{API}/public/preboarding/{new_token}")).status_code == 404


async def test_welcome_message_completes_its_task(client, engine, org):
    h = _h(org["owner"])
    conv, _ = await _preboarding_token(client, org)
    r = await client.post(f"{API}/onboarding/cases/{conv['case']['id']}/welcome", headers=h,
                          json={"message": "Glad to have you!"})
    assert r.status_code == 200
    assert r.json()["welcome_sent_at"] and {x["title"]: x for x in r.json()["tasks"]}["Send welcome message"]["status"] == "done"
    user_id = await _user_of_employee(engine, conv["employee_id"])
    async with AsyncSession(engine) as s:
        n = (await s.execute(text("SELECT count(*) FROM notifications WHERE user_id = :u AND type='onboarding_welcome'"),
                             {"u": user_id})).scalar_one()
    assert n == 1


# ═══ confirmation, offboarding, sweep, dashboard ═══════════════════════════
async def test_probation_confirmation(client, engine, org):
    h = _h(org["owner"])
    await _defaults(client, org)
    o = await _accepted_offer(client, org, job_nature="probationary")
    conv = await _convert(client, org, o["id"])
    emp = (await client.get(f"{API}/employees/{conv['employee_id']}", headers=h)).json()
    assert emp["employment_status"] == "probation" and emp["probation_end_date"]
    cid = conv["case"]["id"]
    early = await client.post(f"{API}/onboarding/cases/{cid}/confirm", headers=h, json={})
    assert early.status_code == 400  # they have not even started yet
    async with AsyncSession(engine) as s:  # ... 90 days later
        await s.execute(text("UPDATE employees SET date_of_joining = :d WHERE id = :e"),
                        {"d": date.today() - timedelta(days=90), "e": conv["employee_id"]})
        await s.commit()
    early = await client.post(f"{API}/onboarding/cases/{cid}/confirm", headers=h,
                              json={"confirmed_on": (date.today() - timedelta(days=400)).isoformat()})
    assert early.status_code == 400  # before the joining date
    r = await client.post(f"{API}/onboarding/cases/{cid}/confirm", headers=h, json={"note": "Great work"})
    assert r.status_code == 200, r.text
    emp = (await client.get(f"{API}/employees/{conv['employee_id']}", headers=h)).json()
    assert emp["job_nature"] == "permanent" and emp["employment_status"] == "active"
    assert emp["date_of_confirmation"] == date.today().isoformat()
    rows = (await client.get(f"{API}/employees/{conv['employee_id']}/history", headers=h)).json()
    assert any(x.get("source") == "confirmed" and x["to_status"] == "active" for x in rows)
    assert (await client.post(f"{API}/onboarding/cases/{cid}/confirm", headers=h, json={})).status_code == 409
    noperm = await _role_user(engine, org, ["onboarding.manage"], "OnlyOb")
    o2 = await _accepted_offer(client, org)
    c2 = await _convert(client, org, o2["id"])
    assert (await client.post(f"{API}/onboarding/cases/{c2['case']['id']}/confirm", headers=_h(noperm), json={})).status_code == 403


async def test_offboarding_case_completes_when_every_task_is_done(client, engine, org):
    h = _h(org["owner"])
    await _defaults(client, org)
    o = await _accepted_offer(client, org)
    conv = await _convert(client, org, o["id"])
    last_day = (date.today() + timedelta(days=20)).isoformat()
    r = await client.post(f"{API}/onboarding/cases", headers=h,
                          json={"employee_id": conv["employee_id"], "kind": "offboarding", "anchor_date": last_day})
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["kind"] == "offboarding" and case["status"] == "active" and "preboarding_link" not in case
    assert case["documents"] == []
    tasks = case["tasks"]
    by = {t["title"]: t for t in tasks}
    assert by["Prepare final settlement"]["due_date"] == (date.fromisoformat(last_day) + timedelta(days=3)).isoformat()
    for t in sorted(tasks, key=lambda x: x["order"]):  # dependencies are satisfied in order
        res = await client.patch(f"{API}/onboarding/tasks/{t['id']}", headers=h, json={"status": "done"})
        assert res.status_code == 200, res.text
    final = (await client.get(f"{API}/onboarding/cases/{case['id']}", headers=h)).json()
    assert final["status"] == "completed" and final["completed_at"]
    closed = await client.patch(f"{API}/onboarding/tasks/{tasks[0]['id']}", headers=h, json={"status": "pending"})
    assert closed.status_code == 409


async def test_daily_sweep_activates_reminds_and_escalates_once(client, engine, org):
    from app.services.onboarding import run_daily_sweep

    h = _h(org["owner"])
    await _defaults(client, org)
    o = await _accepted_offer(client, org)
    conv = await _convert(client, org, o["id"])
    cid = conv["case"]["id"]
    async with AsyncSession(engine) as s:  # the first day arrives and tasks are now 10 days late
        await s.execute(text("UPDATE onboarding_cases SET anchor_date = :d WHERE id = :i"),
                        {"d": date.today() - timedelta(days=10), "i": cid})
        await s.execute(text("UPDATE onboarding_case_tasks SET due_date = :d WHERE case_id = :i AND title = 'Assign laptop and equipment'"),
                        {"d": date.today() - timedelta(days=5), "i": cid})
        await s.commit()
    async with AsyncSession(engine) as s:
        first = await run_daily_sweep(s)
        await s.commit()
    assert first["activated"] >= 1 and first["reminded"] >= 1 and first["escalated"] >= 1
    assert (await client.get(f"{API}/onboarding/cases/{cid}", headers=h)).json()["status"] == "active"
    async with AsyncSession(engine) as s:
        again = await run_daily_sweep(s)  # same day: no second reminder or escalation for those tasks
        await s.commit()
    assert again["activated"] == 0 and again["reminded"] == 0 and again["escalated"] == 0
    async with AsyncSession(engine) as s:
        later = await run_daily_sweep(s, today=date.today() + timedelta(days=2))
        await s.commit()
    assert later["reminded"] >= 1 and later["escalated"] == 0  # reminded again after 2 days, escalated only once
    async with AsyncSession(engine) as s:
        n = (await s.execute(text("SELECT count(*) FROM notifications WHERE tenant_id=:o AND type='onboarding_escalation'"),
                             {"o": org["org"]})).scalar_one()
    assert n >= 1


async def test_sweep_does_not_nag_for_blocked_tasks(client, engine, org):
    from app.services.onboarding import run_daily_sweep

    await _defaults(client, org)
    o = await _accepted_offer(client, org)
    conv = await _convert(client, org, o["id"])
    async with AsyncSession(engine) as s:
        # only the blocked task ("Enroll the device") is overdue; its dependency is still open and not yet due
        await s.execute(text("UPDATE onboarding_case_tasks SET due_date = :future WHERE case_id = :i"),
                        {"future": date.today() + timedelta(days=90), "i": conv["case"]["id"]})
        await s.execute(text("UPDATE onboarding_case_tasks SET due_date = :past WHERE case_id = :i AND title = 'Enroll the device'"),
                        {"past": date.today() - timedelta(days=9), "i": conv["case"]["id"]})
        await s.commit()
    async with AsyncSession(engine) as s:
        res = await run_daily_sweep(s)
        await s.commit()
    assert res["reminded"] == 0 and res["escalated"] == 0


async def test_dashboard_numbers_and_bottlenecks(client, engine, org):
    h = _h(org["owner"])
    await _defaults(client, org)
    o = await _accepted_offer(client, org)
    conv = await _convert(client, org, o["id"])
    async with AsyncSession(engine) as s:
        await s.execute(text("UPDATE onboarding_case_tasks SET due_date = :d WHERE case_id = :i AND owner_role = 'it'"),
                        {"d": date.today() - timedelta(days=4), "i": conv["case"]["id"]})
        await s.commit()
    d = (await client.get(f"{API}/onboarding/dashboard", headers=h)).json()
    assert d["totals"]["open_onboarding"] == 1 and d["totals"]["overdue_tasks"] == 2
    assert d["bottlenecks"]["by_owner_role"][0] == {"owner_role": "it", "overdue": 2}
    assert {x["title"] for x in d["bottlenecks"]["by_task"]} == {"Assign laptop and equipment", "Enroll the device"}
    assert len(d["upcoming_joiners"]) == 1 and d["upcoming_joiners"][0]["progress"]["overdue"] == 2
    overdue_only = (await client.get(f"{API}/onboarding/cases?overdue=true", headers=h)).json()
    assert overdue_only["total"] == 1
    search = (await client.get(f"{API}/onboarding/cases?search=ayesha", headers=h)).json()
    assert search["total"] == 1 and (await client.get(f"{API}/onboarding/cases?search=zzzz", headers=h)).json()["total"] == 0
