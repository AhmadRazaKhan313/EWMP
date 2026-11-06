"""Finance Phase 2c: recurring invoices and payment reminders. Live Postgres, real HTTP."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services import finance_mail
from app.services.finance_recurring import step_date
from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _cust(client, h, **kw):
    return (await client.post(f"{API}/customers", headers=h, json={"name": "Acme Ltd", **kw})).json()


def _rec(cid, start, freq="monthly", price="1000", **kw):
    return {"title": "Web retainer", "customer_id": cid, "frequency": freq, "start_date": start.isoformat(),
            "lines": [{"description": "Retainer", "unit_price": price}], **kw}


async def _tb(client, h):
    return {a["name"]: Decimal(a["balance"]) for a in (await client.get(f"{API}/trial-balance", headers=h)).json()["accounts"]}


def test_step_date_never_drifts_and_clamps_month_ends():
    assert step_date(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)
    assert step_date(date(2026, 1, 31), "monthly", 2) == date(2026, 3, 31)       # back to the 31st, no drift
    assert step_date(date(2024, 1, 31), "monthly", 1) == date(2024, 2, 29)
    assert step_date(date(2026, 11, 15), "quarterly", 1) == date(2027, 2, 15)
    assert step_date(date(2024, 2, 29), "yearly", 1) == date(2025, 2, 28)
    assert step_date(date(2026, 11, 5), "weekly", 3) == date(2026, 11, 26)


async def test_run_creates_every_missed_invoice_once(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h, payment_terms_days=10)
    start = date.today() - timedelta(days=75)
    r = await client.post(f"{API}/recurring", headers=h, json=_rec(c["id"], start))
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["next_run_date"] == start.isoformat() and Decimal(r.json()["amount"]) == 1000
    run = (await client.post(f"{API}/recurring/run", headers=h)).json()
    due = sum(1 for n in range(0, 4) if step_date(start, "monthly", n) <= date.today())
    assert run["created"] == due and run["failed"] == []
    again = (await client.post(f"{API}/recurring/run", headers=h)).json()
    assert again["created"] == 0                                                   # idempotent
    invs = (await client.get(f"{API}/invoices", headers=h, params={"page_size": 50})).json()["items"]
    assert len(invs) == due and all(i["status"] == "draft" and i["recurring_id"] == rid for i in invs)
    assert sorted(i["issue_date"] for i in invs)[0] == start.isoformat()
    assert sorted(i["due_date"] for i in invs)[0] == (start + timedelta(days=10)).isoformat()
    one = (await client.get(f"{API}/recurring/{rid}", headers=h)).json()
    assert one["run_count"] == due and one["next_run_date"] > date.today().isoformat() and one["status"] == "active"
    assert (await _tb(client, h)).get("Accounts Receivable", 0) == 0               # drafts: books untouched


async def test_auto_send_posts_to_the_ledger(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h)
    await client.post(f"{API}/recurring", headers=h, json=_rec(c["id"], date.today(), auto_send=True, price="700"))
    assert (await client.post(f"{API}/recurring/run", headers=h)).json()["created"] == 1
    inv = (await client.get(f"{API}/invoices", headers=h)).json()["items"][0]
    assert inv["status"] == "sent"
    tb = await _tb(client, h)
    assert tb["Accounts Receivable"] == 700 and tb["Client Payments"] == -700


async def test_end_date_pause_resume_and_delete(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h)
    s = date.today() - timedelta(days=14)
    r = (await client.post(f"{API}/recurring", headers=h, json=_rec(c["id"], s, "weekly", end_date=(s + timedelta(days=7)).isoformat()))).json()
    run = (await client.post(f"{API}/recurring/run", headers=h)).json()
    assert run["created"] == 2                                                     # s and s+7, then it ends
    assert (await client.get(f"{API}/recurring/{r['id']}", headers=h)).json()["status"] == "ended"
    assert (await client.post(f"{API}/recurring/{r['id']}/pause", headers=h)).status_code == 409

    p = (await client.post(f"{API}/recurring", headers=h, json=_rec(c["id"], s, "weekly"))).json()
    assert (await client.post(f"{API}/recurring/{p['id']}/pause", headers=h)).json()["status"] == "paused"
    assert (await client.post(f"{API}/recurring/run", headers=h)).json()["created"] == 0   # paused: nothing
    res = (await client.post(f"{API}/recurring/{p['id']}/resume", headers=h)).json()
    assert res["status"] == "active" and res["next_run_date"] >= date.today().isoformat()  # no back-fill of the pause
    assert (await client.post(f"{API}/recurring/{p['id']}/resume", headers=h)).status_code == 409
    assert (await client.delete(f"{API}/recurring/{p['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/recurring/{p['id']}", headers=h)).status_code == 404
    assert (await client.post(f"{API}/recurring", headers=h, json=_rec(c["id"], s, end_date=(s - timedelta(days=1)).isoformat()))).status_code == 422


async def test_edit_lines_and_frequency_rules(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h)
    r = (await client.post(f"{API}/recurring", headers=h, json=_rec(c["id"], date.today() + timedelta(days=5)))).json()
    e = await client.patch(f"{API}/recurring/{r['id']}", headers=h, json={"frequency": "yearly", "lines": [{"description": "x", "unit_price": "250"}]})
    assert e.status_code == 200 and e.json()["frequency"] == "yearly" and Decimal(e.json()["amount"]) == 250
    r2 = (await client.post(f"{API}/recurring", headers=h, json=_rec(c["id"], date.today()))).json()
    await client.post(f"{API}/recurring/run", headers=h)
    assert (await client.patch(f"{API}/recurring/{r2['id']}", headers=h, json={"frequency": "weekly"})).status_code == 409


async def test_a_broken_template_is_recorded_not_fatal(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    good = await _cust(client, h)
    eur = await _cust(client, h, name="Euro Co", currency="EUR")            # no EUR rate saved: generation fails for it
    await client.post(f"{API}/recurring", headers=h, json=_rec(eur["id"], date.today()))
    await client.post(f"{API}/recurring", headers=h, json=_rec(good["id"], date.today()))
    run = (await client.post(f"{API}/recurring/run", headers=h)).json()
    assert run["created"] == 1 and len(run["failed"]) == 1 and "exchange rate" in run["failed"][0]["error"].lower()
    items = (await client.get(f"{API}/recurring", headers=h)).json()["items"]
    bad = next(i for i in items if i["customer_name"] == "Euro Co")
    assert bad["last_error"] and bad["status"] == "active" and bad["run_count"] == 0


@pytest.fixture
def outbox(monkeypatch):
    sent = []

    async def fake(to, subject, body):
        sent.append((to, subject, body))
    monkeypatch.setattr(finance_mail, "deliver", fake)
    return sent


async def _overdue_invoice(client, h, cid, price="500"):
    d = (date.today() - timedelta(days=20)).isoformat()
    due = (date.today() - timedelta(days=5)).isoformat()
    r = await client.post(f"{API}/invoices", headers=h, json={"customer_id": cid, "issue_date": d, "due_date": due, "send": True,
                          "lines": [{"description": "Work", "unit_price": price}]})
    return r.json()


async def test_manual_reminder_sends_email_and_counts(client, org, outbox):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h, email="acme@example.com")
    inv = await _overdue_invoice(client, h, c["id"])
    r = await client.post(f"{API}/invoices/{inv['id']}/remind", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["reminder_count"] == 1 and r.json()["last_reminded_at"]
    to, subject, body = outbox[0]
    assert to == "acme@example.com" and inv["number"] in subject and "5 days overdue" in subject and "500.00" in body
    nomail = await _cust(client, h, name="No Mail")
    inv2 = await _overdue_invoice(client, h, nomail["id"])
    assert (await client.post(f"{API}/invoices/{inv2['id']}/remind", headers=h)).status_code == 422
    draft = (await client.post(f"{API}/invoices", headers=h, json={"customer_id": c["id"], "issue_date": "2026-11-01",
             "lines": [{"description": "d", "unit_price": "1"}]})).json()
    assert (await client.post(f"{API}/invoices/{draft['id']}/remind", headers=h)).status_code == 409
    assert len(outbox) == 1


async def test_failed_delivery_is_reported_and_not_counted(client, org, monkeypatch):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h, email="a@example.com")
    inv = await _overdue_invoice(client, h, c["id"])

    async def boom(*a):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(finance_mail, "deliver", boom)
    r = await client.post(f"{API}/invoices/{inv['id']}/remind", headers=h)
    assert r.status_code == 422 and "smtp down" in r.text
    assert (await client.get(f"{API}/invoices/{inv['id']}", headers=h)).json()["reminder_count"] == 0


async def test_sweep_only_reminds_opted_in_customers_with_spacing(client, org, outbox, engine):
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.finance_recurring import sweep_reminders
    await _setup(client, org)
    h = _h(org["owner"])
    opted = await _cust(client, h, name="Opted", email="o@example.com", auto_remind=True)
    quiet = await _cust(client, h, name="Quiet", email="q@example.com")
    await _overdue_invoice(client, h, opted["id"])
    await _overdue_invoice(client, h, quiet["id"])

    async def sweep():
        async with AsyncSession(engine) as s:
            out = await sweep_reminders(s, tenant_id=org["org"])
            await s.commit()
            return out
    assert (await sweep())["sent"] == 1 and outbox[0][0] == "o@example.com"
    assert (await sweep())["sent"] == 0                                    # reminded just now: wait a week
    assert len(outbox) == 1
