"""
Finance Phase 0: per-organization double-entry ledger. Live Postgres, real HTTP.
"""
import os
import uuid
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.database.seeds.permissions import PERMISSIONS_BY_CODENAME
from app.main import app
from app.models.finance import FinJournalLine
from app.models.organization import Organization
from app.models.rbac import Permission, Role
from app.models.user import User

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp")
pytestmark = pytest.mark.asyncio
API = "/api/v1/finance"


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


async def _make_org(engine, currency="PKR") -> dict:
    org_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Fin Org", slug=f"fin-{org_id.hex[:8]}",
                           email=f"f-{org_id.hex[:8]}@example.com", timezone="Asia/Karachi", currency=currency))
        await s.flush()
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        owner = User(organization_id=org_id, email=email, email_normalized=email, password_hash=hash_password("x"),
                     first_name="Owner", last_name="Test", is_active=True, is_email_verified=True)
        s.add(owner)
        await s.flush()
        (await s.get(Organization, org_id)).owner_id = owner.id
        ids = {"org": org_id, "owner": owner.id}
        await s.commit()
    return ids


async def _drop_org(engine, ids):
    async with AsyncSession(engine) as s:
        o = {"o": ids["org"]}
        for sql in (
            "DELETE FROM fin_tax_rates WHERE tenant_id = :o",
            "DELETE FROM fin_journal_lines WHERE tenant_id = :o",
            "DELETE FROM fin_journal_entries WHERE tenant_id = :o",
            "DELETE FROM fin_exchange_rates WHERE tenant_id = :o",
            "DELETE FROM fin_accounts WHERE tenant_id = :o",
            "DELETE FROM audit_logs WHERE tenant_id = :o",
            "DELETE FROM auth_refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE organization_id = :o)",
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


@pytest_asyncio.fixture
async def usd_org(engine):
    ids = await _make_org(engine, currency="USD")
    yield ids
    await _drop_org(engine, ids)


def _h(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


async def _role_user(engine, org, perms, name="Acct"):
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
        email = f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.com"
        u = User(organization_id=org["org"], email=email, email_normalized=email, password_hash=hash_password("x"),
                 first_name=name, last_name="User", is_active=True, is_email_verified=True)
        u.roles = [role]
        s.add(u)
        await s.flush()
        uid = u.id
        await s.commit()
    return uid


async def _setup(client, org) -> dict:
    r = await client.post(f"{API}/setup", headers=_h(org["owner"]))
    assert r.status_code == 200, r.text
    r = await client.get(f"{API}/accounts", headers=_h(org["owner"]))
    return {a["name"]: a["id"] for a in r.json()["items"]}


def _entry(accs, amount="1000", cur=None, rate=None, dr="Cash", cr="Client Payments"):
    extra = {k: v for k, v in (("currency", cur), ("rate", rate)) if v}
    return {"entry_date": "2026-11-01", "memo": "test", "lines": [
        {"account_id": accs[dr], "side": "debit", "amount": amount, **extra},
        {"account_id": accs[cr], "side": "credit", "amount": amount, **extra}]}


async def test_setup_is_idempotent_and_seeds_user_categories(client, org):
    accs = await _setup(client, org)
    for name in ("Cash", "Bank", "Mobile Wallet", "Upwork Income", "Upwork Connects", "Founders Capital", "Loans", "Grocery"):
        assert name in accs
    again = await client.post(f"{API}/setup", headers=_h(org["owner"]))
    assert again.json()["created"] == 0
    assert again.json()["base_currency"] == "PKR"
    assert len((await client.get(f"{API}/accounts", headers=_h(org["owner"]))).json()["items"]) == len(accs)


async def test_balanced_entry_posts_and_unbalanced_is_rejected(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    r = await client.post(f"{API}/journal", headers=h, json=_entry(accs, "1500.50"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["number"] == "JE-000001"
    assert sum(Decimal(l["debit"]) for l in body["lines"]) == sum(Decimal(l["credit"]) for l in body["lines"]) == Decimal("1500.50")

    bad = _entry(accs, "100")
    bad["lines"][1]["amount"] = "90"
    r = await client.post(f"{API}/journal", headers=h, json=bad)
    assert r.status_code == 422 and "not balanced" in r.text
    assert (await client.get(f"{API}/journal", headers=h)).json()["total"] == 1  # nothing partial saved


async def test_validation_rules(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    one_line = {"entry_date": "2026-11-01", "lines": [{"account_id": accs["Cash"], "side": "debit", "amount": "5"}]}
    assert (await client.post(f"{API}/journal", headers=h, json=one_line)).status_code == 422
    neg = _entry(accs, "-5")
    assert (await client.post(f"{API}/journal", headers=h, json=neg)).status_code == 422
    ghost = _entry(accs, "5")
    ghost["lines"][0]["account_id"] = str(uuid.uuid4())
    r = await client.post(f"{API}/journal", headers=h, json=ghost)
    assert r.status_code == 422 and "account not found" in r.text
    # inactive account refused
    await client.patch(f"{API}/accounts/{accs['Gifts']}", headers=h, json={"is_active": False})
    r = await client.post(f"{API}/journal", headers=h, json=_entry(accs, "5", dr="Gifts", cr="Cash"))
    assert r.status_code == 422 and "inactive" in r.text


async def test_void_creates_reversal_that_nets_to_zero(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    e = (await client.post(f"{API}/journal", headers=h, json=_entry(accs, "2500"))).json()
    rev = await client.post(f"{API}/journal/{e['id']}/void", headers=h, json={"reason": "typo"})
    assert rev.status_code == 200, rev.text
    assert rev.json()["reverses_id"] == e["id"]
    orig = (await client.get(f"{API}/journal/{e['id']}", headers=h)).json()
    assert orig["status"] == "reversed" and orig["reversed_by_id"] == rev.json()["id"]
    tb = (await client.get(f"{API}/trial-balance", headers=h)).json()
    assert tb["balanced"] is True
    assert all(Decimal(a["balance"]) == 0 for a in tb["accounts"])
    # cannot void twice, nor void the reversal
    assert (await client.post(f"{API}/journal/{e['id']}/void", headers=h, json={})).status_code == 422
    assert (await client.post(f"{API}/journal/{rev.json()['id']}/void", headers=h, json={})).status_code == 422


async def test_trial_balance_and_as_of(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await client.post(f"{API}/journal", headers=h, json=_entry(accs, "1000"))
    late = _entry(accs, "400", dr="Grocery", cr="Cash")
    late["entry_date"] = "2026-12-01"
    await client.post(f"{API}/journal", headers=h, json=late)
    tb = (await client.get(f"{API}/trial-balance", headers=h)).json()
    by = {a["name"]: a for a in tb["accounts"]}
    assert tb["balanced"] and Decimal(tb["total_debit"]) == Decimal("1400")
    assert Decimal(by["Cash"]["balance"]) == Decimal("600")
    assert Decimal(by["Grocery"]["balance"]) == Decimal("400")
    early = (await client.get(f"{API}/trial-balance", headers=h, params={"as_of": "2026-11-30"})).json()
    by = {a["name"]: a for a in early["accounts"]}
    assert Decimal(by["Cash"]["balance"]) == Decimal("1000") and Decimal(by["Grocery"]["balance"]) == 0
    assert "Grocery" in by  # account still listed


async def test_multi_currency_converts_and_keeps_original(client, usd_org):
    accs = await _setup(client, usd_org)
    h = _h(usd_org["owner"])
    # no rate yet -> refused
    r = await client.post(f"{API}/journal", headers=h, json=_entry(accs, "100", cur="EUR"))
    assert r.status_code == 422 and "exchange rate" in r.text
    assert (await client.put(f"{API}/exchange-rates", headers=h, json={"currency": "EUR", "on_date": "2026-10-01", "rate": "1.10"})).status_code == 200
    r = await client.post(f"{API}/journal", headers=h, json=_entry(accs, "100", cur="EUR"))
    assert r.status_code == 201, r.text
    ln = r.json()["lines"][0]
    assert ln["currency"] == "EUR" and Decimal(ln["amount_original"]) == 100
    assert Decimal(ln["debit"]) == Decimal("110.00") and Decimal(ln["exchange_rate"]) == Decimal("1.1")
    # explicit rate wins
    r = await client.post(f"{API}/journal", headers=h, json=_entry(accs, "100", cur="EUR", rate="1.2"))
    assert Decimal(r.json()["lines"][0]["debit"]) == Decimal("120.00")
    # base currency rate cannot be set
    r = await client.put(f"{API}/exchange-rates", headers=h, json={"currency": "USD", "on_date": "2026-10-01", "rate": "1"})
    assert r.status_code == 409


async def test_tenants_are_isolated(client, org, other_org):
    accs = await _setup(client, org)
    other = await _setup(client, other_org)
    h, ho = _h(org["owner"]), _h(other_org["owner"])
    e = (await client.post(f"{API}/journal", headers=h, json=_entry(accs, "100"))).json()
    assert (await client.get(f"{API}/journal", headers=ho)).json()["total"] == 0
    assert (await client.get(f"{API}/journal/{e['id']}", headers=ho)).status_code == 404
    assert (await client.post(f"{API}/journal/{e['id']}/void", headers=ho, json={})).status_code == 404
    # cannot post into another org's accounts
    r = await client.post(f"{API}/journal", headers=ho, json=_entry(accs, "5"))
    assert r.status_code == 422
    # both orgs number from 1 independently
    e2 = (await client.post(f"{API}/journal", headers=ho, json=_entry(other, "5"))).json()
    assert e2["number"] == "JE-000001"
    assert (await client.patch(f"{API}/accounts/{accs['Cash']}", headers=ho, json={"name": "x"})).status_code == 404


async def test_permissions_are_separate(client, engine, org):
    accs = await _setup(client, org)
    viewer = await _role_user(engine, org, ["finance.view"], "Viewer")
    poster = await _role_user(engine, org, ["finance.view", "finance.post"], "Poster")
    nobody = await _role_user(engine, org, [], "Nobody")
    body = _entry(accs, "10")
    assert (await client.get(f"{API}/accounts", headers=_h(nobody))).status_code == 403
    assert (await client.get(f"{API}/accounts", headers=_h(viewer))).status_code == 200
    assert (await client.post(f"{API}/journal", headers=_h(viewer), json=body)).status_code == 403
    r = await client.post(f"{API}/journal", headers=_h(poster), json=body)
    assert r.status_code == 201
    assert (await client.post(f"{API}/journal/{r.json()['id']}/void", headers=_h(poster), json={})).status_code == 403
    assert (await client.post(f"{API}/setup", headers=_h(poster))).status_code == 403
    assert (await client.post(f"{API}/accounts", headers=_h(poster), json={"code": "9", "name": "x", "type": "asset"})).status_code == 403


async def test_account_rules_and_tax_rates(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    r = await client.post(f"{API}/accounts", headers=h, json={"code": "1010", "name": "dup", "type": "asset"})
    assert r.status_code == 409
    r = await client.post(f"{API}/accounts", headers=h, json={"code": "1011", "name": "Petty Cash", "type": "asset", "parent_id": accs["Cash"]})
    assert r.status_code == 201
    r = await client.post(f"{API}/accounts", headers=h, json={"code": "1012", "name": "bad", "type": "expense", "parent_id": accs["Cash"]})
    assert r.status_code == 409
    r = await client.post(f"{API}/tax-rates", headers=h, json={"name": "Custom 10%", "percent": "10", "kind": "sales"})
    assert r.status_code == 201
    assert len((await client.get(f"{API}/tax-rates", headers=h)).json()["items"]) == 1


async def test_db_rejects_two_sided_line(engine, client, org):
    accs = await _setup(client, org)
    e = (await client.post(f"{API}/journal", headers=_h(org["owner"]), json=_entry(accs, "10"))).json()
    async with AsyncSession(engine) as s:
        s.add(FinJournalLine(tenant_id=org["org"], entry_id=uuid.UUID(e["id"]), account_id=uuid.UUID(accs["Cash"]),
                             debit=Decimal("5"), credit=Decimal("5"), currency="PKR", amount_original=Decimal("5")))
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()
