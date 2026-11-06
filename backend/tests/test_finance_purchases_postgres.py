"""Finance Phase 3a: vendors, bills, payments made. Live Postgres, real HTTP."""
from decimal import Decimal

import pytest

from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _tb(client, h):
    return {a["name"]: Decimal(a["balance"]) for a in (await client.get(f"{API}/trial-balance", headers=h)).json()["accounts"]}


async def _vendor(client, h, **kw):
    r = await client.post(f"{API}/vendors", headers=h, json={"name": "Alpha Supplies", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _bill(vid, accs, price="1000", qty="1", date="2026-11-01", cat="Utilities", **kw):
    line = {"description": "Internet", "quantity": qty, "unit_price": price}
    if cat:
        line["expense_account_id"] = accs[cat]
    return {"vendor_id": vid, "issue_date": date, "lines": [line], **kw}


async def test_posting_a_bill_and_paying_it(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    v = await _vendor(client, h)
    tax = (await client.post(f"{API}/tax-rates", headers=h, json={"name": "GST 10", "percent": "10"})).json()
    body = _bill(v["id"], accs, post=True, vendor_ref="SUP-77")
    body["lines"][0]["tax_rate_id"] = tax["id"]
    r = await client.post(f"{API}/bills", headers=h, json=body)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["number"] == "BILL-000001" and b["status"] == "open" and b["vendor_ref"] == "SUP-77"
    assert Decimal(b["total"]) == 1100 and Decimal(b["balance"]) == 1100
    tb = await _tb(client, h)
    assert tb["Utilities"] == 1000 and tb["Input Tax Receivable"] == 100 and tb["Accounts Payable"] == -1100

    p = await client.post(f"{API}/bill-payments", headers=h, json={
        "vendor_id": v["id"], "payment_date": "2026-11-05", "amount": "1100", "paid_from_account_id": accs["Bank"],
        "allocations": [{"bill_id": b["id"], "amount": "1100"}]})
    assert p.status_code == 201, p.text
    assert p.json()["number"] == "BPAY-000001" and Decimal(p.json()["unapplied"]) == 0
    got = (await client.get(f"{API}/bills/{b['id']}", headers=h)).json()
    assert got["status"] == "paid" and Decimal(got["balance"]) == 0 and got["payments"][0]["number"] == "BPAY-000001"
    tb = await _tb(client, h)
    assert tb["Accounts Payable"] == 0 and tb["Bank"] == -1100


async def test_partial_payment_overpay_and_void_rules(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    v = await _vendor(client, h)
    b = (await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs, post=True))).json()
    pay = lambda amt, alloc: client.post(f"{API}/bill-payments", headers=h, json={  # noqa: E731
        "vendor_id": v["id"], "payment_date": "2026-11-05", "amount": amt, "paid_from_account_id": accs["Cash"],
        "allocations": [{"bill_id": b["id"], "amount": alloc}]})
    assert (await pay("2000", "1500")).status_code == 422
    assert (await pay("100", "200")).status_code == 422
    p = (await pay("400", "400")).json()
    got = (await client.get(f"{API}/bills/{b['id']}", headers=h)).json()
    assert got["status"] == "partially_paid" and Decimal(got["balance"]) == 600
    assert (await client.post(f"{API}/bills/{b['id']}/void", headers=h, json={})).status_code == 409
    assert (await client.post(f"{API}/bill-payments/{p['id']}/void", headers=h, json={})).status_code == 200
    got = (await client.get(f"{API}/bills/{b['id']}", headers=h)).json()
    assert got["status"] == "open" and Decimal(got["balance"]) == 1000
    assert (await _tb(client, h))["Cash"] == 0
    assert (await client.post(f"{API}/bills/{b['id']}/void", headers=h, json={})).status_code == 200
    tb = await _tb(client, h)
    assert tb["Accounts Payable"] == 0 and tb["Utilities"] == 0
    assert (await pay("10", "10")).status_code == 422


async def test_advance_to_a_vendor_sits_as_a_debit_on_payables(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    v = await _vendor(client, h)
    p = await client.post(f"{API}/bill-payments", headers=h, json={
        "vendor_id": v["id"], "payment_date": "2026-11-05", "amount": "250", "paid_from_account_id": accs["Bank"]})
    assert p.status_code == 201 and Decimal(p.json()["unapplied"]) == 250
    assert (await _tb(client, h))["Accounts Payable"] == 250
    st = (await client.get(f"{API}/vendors/{v['id']}/statement", headers=h)).json()
    assert Decimal(next(iter(st["balances"].values()))) == -250


async def test_foreign_currency_bill_and_realized_fx(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    assert (await client.put(f"{API}/exchange-rates", headers=h, json={"currency": "EUR", "on_date": "2026-10-01", "rate": "1.10"})).status_code == 200
    v = await _vendor(client, h, currency="EUR")
    b = (await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs, "100", post=True))).json()
    assert b["currency"] == "EUR"
    tb = await _tb(client, h)
    assert tb["Accounts Payable"] == -110 and tb["Utilities"] == 110
    p = await client.post(f"{API}/bill-payments", headers=h, json={
        "vendor_id": v["id"], "payment_date": "2026-11-05", "amount": "100", "currency": "EUR", "rate": "1.05",
        "paid_from_account_id": accs["Bank"], "allocations": [{"bill_id": b["id"], "amount": "100"}]})
    assert p.status_code == 201, p.text
    tb = await _tb(client, h)
    assert tb["Bank"] == -105 and tb["Accounts Payable"] == 0 and tb["Exchange Gain / Loss"] == -5     # paid less: gain
    b2 = (await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs, "100", post=True))).json()
    await client.post(f"{API}/bill-payments", headers=h, json={
        "vendor_id": v["id"], "payment_date": "2026-11-06", "amount": "100", "currency": "EUR", "rate": "1.20",
        "paid_from_account_id": accs["Bank"], "allocations": [{"bill_id": b2["id"], "amount": "100"}]})
    assert (await _tb(client, h))["Exchange Gain / Loss"] == -5 + 10                                    # paid more: loss
    b3 = (await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs, "50", post=True))).json()
    bad = await client.post(f"{API}/bill-payments", headers=h, json={
        "vendor_id": v["id"], "payment_date": "2026-11-06", "amount": "50", "currency": "USD",
        "paid_from_account_id": accs["Bank"], "allocations": [{"bill_id": b3["id"], "amount": "50"}]})
    assert bad.status_code == 422


async def test_draft_lifecycle_and_account_rules(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    v = await _vendor(client, h, payment_terms_days=14)
    d = (await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs, "100", qty="3", cat=None))).json()
    assert d["status"] == "draft" and Decimal(d["total"]) == 300 and d["due_date"] == "2026-11-15"
    assert d["lines"][0]["expense_account_id"] == accs["Other Expenses"]                      # default when none picked
    assert (await _tb(client, h)).get("Accounts Payable", 0) == 0
    e = await client.patch(f"{API}/bills/{d['id']}", headers=h, json={"lines": [{"description": "x", "unit_price": "50", "discount_percent": "10"}]})
    assert e.status_code == 200 and Decimal(e.json()["total"]) == 45
    assert (await client.post(f"{API}/bills/{d['id']}/post", headers=h)).json()["status"] == "open"
    assert (await client.post(f"{API}/bills/{d['id']}/post", headers=h)).status_code == 409
    assert (await client.patch(f"{API}/bills/{d['id']}", headers=h, json={"notes": "n"})).status_code == 409
    assert (await client.delete(f"{API}/bills/{d['id']}", headers=h)).status_code == 409
    d2 = (await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs))).json()
    assert (await client.delete(f"{API}/bills/{d2['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/bills/{d2['id']}", headers=h)).status_code == 404
    # lines must hit an expense / fixed-asset account, never cash, bank, receivables or income
    for bad in ("Cash", "Bank", "Accounts Receivable", "Client Payments"):
        r = await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs, cat=bad))
        assert r.status_code == 422, bad
    assert (await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs, cat="Fixed Assets"))).status_code == 201
    assert (await client.post(f"{API}/bills", headers=h, json={**_bill(v["id"], accs), "due_date": "2026-10-01"})).status_code == 422
    pay_bad = await client.post(f"{API}/bill-payments", headers=h, json={
        "vendor_id": v["id"], "payment_date": "2026-11-05", "amount": "5", "paid_from_account_id": accs["Utilities"]})
    assert pay_bad.status_code == 422


async def test_overdue_vendor_balance_permissions_and_isolation(client, org, other_org, engine):
    accs = await _setup(client, org)
    other = await _setup(client, other_org)
    h, ho = _h(org["owner"]), _h(other_org["owner"])
    v = await _vendor(client, h)
    await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs, "700", date="2025-01-01", due_date="2025-01-31", post=True))
    b2 = (await client.post(f"{API}/bills", headers=h, json=_bill(v["id"], accs, "300", date="2099-01-01", post=True))).json()
    od = (await client.get(f"{API}/bills", headers=h, params={"status": "overdue"})).json()
    assert od["total"] == 1 and od["items"][0]["is_overdue"] and od["items"][0]["status"] == "open"
    assert Decimal((await client.get(f"{API}/vendors", headers=h)).json()["items"][0]["balance"]) == 1000
    assert (await client.get(f"{API}/bills", headers=h, params={"search": "alpha"})).json()["total"] == 2
    viewer = _h(await _role_user(engine, org, ["finance.view"], "Viewer"))
    assert (await client.get(f"{API}/bills", headers=viewer)).status_code == 200
    assert (await client.post(f"{API}/vendors", headers=viewer, json={"name": "x"})).status_code == 403
    assert (await client.post(f"{API}/bills/{b2['id']}/void", headers=viewer, json={})).status_code == 403
    assert (await client.get(f"{API}/bills", headers=ho)).json()["total"] == 0
    assert (await client.get(f"{API}/bills/{b2['id']}", headers=ho)).status_code == 404
    assert (await client.get(f"{API}/vendors/{v['id']}/statement", headers=ho)).status_code == 404
    r = await client.post(f"{API}/bill-payments", headers=h, json={"vendor_id": v["id"], "payment_date": "2026-11-05",
                          "amount": "5", "paid_from_account_id": other["Bank"]})
    assert r.status_code == 422
