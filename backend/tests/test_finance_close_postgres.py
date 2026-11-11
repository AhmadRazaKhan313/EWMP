"""Finance Phase 6: month / year close, opening balances, tax report. Live Postgres, real HTTP."""
from decimal import Decimal

import pytest

from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio
D = Decimal


def _je(accs, date, amount="100", dr="Cash", cr="Client Payments"):
    return {"entry_date": date, "memo": "t", "lines": [
        {"account_id": accs[dr], "side": "debit", "amount": amount}, {"account_id": accs[cr], "side": "credit", "amount": amount}]}


async def _post(client, h, accs, date, **kw):
    return await client.post(f"{API}/journal", headers=h, json=_je(accs, date, **kw))


async def _close(client, h, kind, date, **extra):
    return await client.post(f"{API}/close", headers=h, json={"period_type": kind, "date": date, **extra})


async def test_close_locks_every_posting_path_and_reopen_unlocks(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    assert (await _post(client, h, accs, "2026-09-10", amount="500")).status_code == 201
    inside = (await _post(client, h, accs, "2026-10-20", amount="300")).json()

    pv = (await client.get(f"{API}/close/preview", headers=h, params={"period_type": "month", "date": "2026-09-15"})).json()
    assert pv["can_close"] and pv["income"] == "500.00" and pv["net_profit"] == "500.00" and pv["blockers"] == []

    r = await _close(client, h, "month", "2026-09-15", note="September done")
    assert r.status_code == 200, r.text
    assert r.json()["period_end"] == "2026-09-30" and r.json()["net_profit"] == "500.00"
    st = (await client.get(f"{API}/close", headers=h)).json()
    assert st["locked_through"] == "2026-09-30" and len(st["closes"]) == 1
    assert st["suggested"]["period_end"] == "2026-10-31"

    for d in ("2026-09-30", "2026-09-01"):  # the boundary day is locked too
        r = await _post(client, h, accs, d)
        assert r.status_code == 409 and "closed through 2026-09-30" in r.text
    assert (await _post(client, h, accs, "2026-10-01")).status_code == 201

    # a void whose reversal would land in the closed period is refused; moving it to an open date works
    first = (await client.get(f"{API}/journal", headers=h, params={"page_size": 50})).json()["items"]
    sep = next(e for e in first if e["entry_date"] == "2026-09-10")
    assert (await client.post(f"{API}/journal/{sep['id']}/void", headers=h, json={})).status_code == 409
    ok = await client.post(f"{API}/journal/{sep['id']}/void", headers=h, json={"on": "2026-10-05"})
    assert ok.status_code in (200, 201), ok.text

    # closing again, out of order, or a period that has not ended
    assert (await _close(client, h, "month", "2026-09-20")).status_code == 422
    assert (await _close(client, h, "month", "2026-11-05")).status_code == 422  # still running
    assert (await client.get(f"{API}/close/preview", headers=h, params={"period_type": "month", "date": "2026-11-05"})).json()["can_close"] is False

    assert (await client.post(f"{API}/close/reopen", headers=h)).status_code == 200
    assert (await client.get(f"{API}/close", headers=h)).json()["locked_through"] is None
    assert (await _post(client, h, accs, "2026-09-12")).status_code == 201
    assert (await client.post(f"{API}/close/reopen", headers=h)).status_code == 404
    assert inside["number"]


async def test_cannot_skip_a_month_and_year_close_covers_all_modules(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    assert (await _post(client, h, accs, "2026-07-10")).status_code == 201
    assert (await _close(client, h, "month", "2026-08-15")).status_code == 200   # first close may start anywhere
    r = await _close(client, h, "month", "2026-10-15")                           # September missing
    assert r.status_code == 422 and "2026-09-01" in r.text
    assert (await _close(client, h, "month", "2026-09-15")).status_code == 200

    # financial year 2025-26 ended 30 Jun 2026; closing it locks everything through that date, even though Aug is closed already
    assert (await _close(client, h, "year", "2026-01-15")).status_code == 422    # already inside the lock
    # a transaction (income) is blocked by the lock because it goes through post_entry
    t = await client.post(f"{API}/transactions", headers=h, json={"type": "income", "date": "2026-08-20", "amount": "50",
                                                                   "account_id": accs["Cash"], "category_id": accs["Client Payments"], "description": "late"})
    assert t.status_code == 409 and "closed through 2026-09-30" in t.text
    # invoices too
    c = (await client.post(f"{API}/customers", headers=h, json={"name": "Acme"})).json()
    inv = await client.post(f"{API}/invoices", headers=h, json={
        "customer_id": c["id"], "issue_date": "2026-09-05", "send": True, "lines": [{"description": "x", "quantity": "1", "unit_price": "10"}]})
    assert inv.status_code == 409


async def test_opening_balances_balance_through_equity_and_replace(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    assert (await client.get(f"{API}/opening-balances", headers=h)).json()["items"] == []
    body = {"as_of": "2026-07-01", "items": [
        {"account_id": accs["Cash"], "amount": "10000"}, {"account_id": accs["Bank"], "amount": "40000"},
        {"account_id": accs["Loans"], "amount": "15000"}]}
    r = await client.put(f"{API}/opening-balances", headers=h, json=body)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["as_of"] == "2026-07-01" and got["balancing"] == "35000.00"
    assert {i["name"]: i["amount"] for i in got["items"]} == {"Cash": "10000.00", "Bank": "40000.00", "Loans": "15000.00"}
    tb = {a["name"]: D(a["balance"]) for a in (await client.get(f"{API}/trial-balance", headers=h)).json()["accounts"]}
    assert tb["Cash"] == 10000 and tb["Bank"] == 40000 and tb["Loans"] == -15000 and tb["Opening Balance Equity"] == -35000

    # replacing voids the old entry; nothing double counts
    r = await client.put(f"{API}/opening-balances", headers=h, json={"as_of": "2026-07-01", "items": [{"account_id": accs["Cash"], "amount": "2000"}]})
    assert r.status_code == 200 and r.json()["balancing"] == "2000.00"
    tb = {a["name"]: D(a["balance"]) for a in (await client.get(f"{API}/trial-balance", headers=h)).json()["accounts"]}
    assert tb["Cash"] == 2000 and tb.get("Bank", 0) == 0 and tb["Opening Balance Equity"] == -2000

    # a negative amount flips the side (an overdrawn bank)
    r = await client.put(f"{API}/opening-balances", headers=h, json={"as_of": "2026-07-01", "items": [{"account_id": accs["Bank"], "amount": "-700"}]})
    assert r.status_code == 200 and r.json()["balancing"] == "-700.00"

    for bad in ({"as_of": "2026-07-01", "items": []},
                {"as_of": "2026-07-01", "items": [{"account_id": accs["Cash"], "amount": "0"}]},
                {"as_of": "2026-07-01", "items": [{"account_id": accs["Cash"], "amount": "1"}, {"account_id": accs["Cash"], "amount": "2"}]},
                {"as_of": "2026-07-01", "items": [{"account_id": accs["Opening Balance Equity"], "amount": "5"}]}):
        assert (await client.put(f"{API}/opening-balances", headers=h, json=bad)).status_code == 422
    assert (await client.put(f"{API}/opening-balances", headers=h, json={"as_of": "2026-07-01", "items": [{"account_id": accs["Cash"], "amount": "1e30"}]})).status_code == 422

    assert (await client.delete(f"{API}/opening-balances", headers=h)).status_code == 200
    assert (await client.get(f"{API}/opening-balances", headers=h)).json()["items"] == []
    assert (await client.delete(f"{API}/opening-balances", headers=h)).status_code == 404


async def test_opening_balances_blocked_in_a_closed_period(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    assert (await _close(client, h, "month", "2026-07-15")).status_code == 200
    r = await client.put(f"{API}/opening-balances", headers=h, json={"as_of": "2026-07-01", "items": [{"account_id": accs["Cash"], "amount": "5"}]})
    assert r.status_code == 409


async def test_tax_report_by_rate_skips_drafts_and_voids_and_exports(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    g10 = (await client.post(f"{API}/tax-rates", headers=h, json={"name": "GST 10", "percent": "10"})).json()
    g5 = (await client.post(f"{API}/tax-rates", headers=h, json={"name": "GST 5", "percent": "5"})).json()
    c = (await client.post(f"{API}/customers", headers=h, json={"name": "Acme"})).json()
    v = (await client.post(f"{API}/vendors", headers=h, json={"name": "Alpha"})).json()

    async def inv(price, rate=None, date="2026-10-10", **kw):
        line = {"description": "x", "quantity": "1", "unit_price": price, **({"tax_rate_id": rate["id"]} if rate else {})}
        r = await client.post(f"{API}/invoices", headers=h, json={"customer_id": c["id"], "issue_date": date, "lines": [line], **kw})
        assert r.status_code == 201, r.text
        return r.json()

    await inv("1000", g10, send=True)
    await inv("2000", g10, send=True)
    await inv("400", g5, send=True)
    await inv("999", g10)                                     # draft: not counted
    gone = await inv("5000", g10, send=True)
    assert (await client.post(f"{API}/invoices/{gone['id']}/void", headers=h, json={})).status_code == 200
    await inv("700", g10, date="2026-09-30", send=True)       # outside the period

    line = {"description": "net", "quantity": "1", "unit_price": "1500", "expense_account_id": accs["Utilities"], "tax_rate_id": g10["id"]}
    b = await client.post(f"{API}/bills", headers=h, json={"vendor_id": v["id"], "issue_date": "2026-10-12", "lines": [line]})
    assert b.status_code == 201, b.text
    assert (await client.post(f"{API}/bills/{b.json()['id']}/post", headers=h)).status_code == 200

    r = await client.get(f"{API}/reports/taxes", headers=h, params={"date_from": "2026-10-01", "date_to": "2026-10-31"})
    assert r.status_code == 200, r.text
    d = r.json()
    rows = {x["name"]: x for x in d["sales"]["rows"]}
    assert rows["GST 10"]["taxable"] == "3000.00" and rows["GST 10"]["tax"] == "300.00" and rows["GST 10"]["documents"] == 2
    assert rows["GST 5"]["taxable"] == "400.00" and rows["GST 5"]["tax"] == "20.00"
    assert d["sales"]["tax"] == "320.00" and d["purchases"]["tax"] == "150.00" and d["purchases"]["taxable"] == "1500.00"
    assert d["net_tax_payable"] == "170.00"
    assert (await client.get(f"{API}/reports/taxes", headers=h, params={"date_from": "2026-11-01", "date_to": "2026-10-01"})).status_code == 422

    x = await client.get(f"{API}/reports/export", headers=h, params={"report": "taxes", "format": "csv", "date_from": "2026-10-01", "date_to": "2026-10-31"})
    assert x.status_code == 200 and "GST 10" in x.text and "170.00" in x.text
    xl = await client.get(f"{API}/reports/export", headers=h, params={"report": "taxes", "format": "xlsx", "date_from": "2026-10-01", "date_to": "2026-10-31"})
    assert xl.status_code == 200 and xl.content[:2] == b"PK"


async def test_permissions_and_tenant_isolation(client, org, other_org, engine):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    viewer = _h(await _role_user(engine, org, ["finance.view"], name="Viewer"))
    assert (await client.get(f"{API}/close", headers=viewer)).status_code == 200
    assert (await client.get(f"{API}/opening-balances", headers=viewer)).status_code == 200
    assert (await client.get(f"{API}/reports/taxes", headers=viewer)).status_code == 200
    assert (await _close(client, viewer, "month", "2026-09-15")).status_code == 403
    assert (await client.post(f"{API}/close/reopen", headers=viewer)).status_code == 403
    assert (await client.put(f"{API}/opening-balances", headers=viewer, json={"as_of": "2026-07-01", "items": [{"account_id": accs["Cash"], "amount": "1"}]})).status_code == 403
    assert (await client.delete(f"{API}/opening-balances", headers=viewer)).status_code == 403
    nox = _h(await _role_user(engine, org, ["finance.view"], name="Nox"))
    assert (await client.get(f"{API}/reports/export", headers=nox, params={"report": "taxes"})).status_code == 403

    # one tenant's lock never touches another's books
    assert (await _close(client, h, "month", "2026-09-15")).status_code == 200
    other_h = _h(other_org["owner"])
    other_accs = await _setup(client, other_org)
    assert (await _post(client, other_h, other_accs, "2026-09-10")).status_code == 201
    assert (await client.get(f"{API}/close", headers=other_h)).json()["locked_through"] is None
