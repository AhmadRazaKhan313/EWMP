"""Finance Phase 2a: customers, invoices, payments. Live Postgres, real HTTP."""
from decimal import Decimal

import pytest

from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _tb(client, h):
    return {a["name"]: Decimal(a["balance"]) for a in (await client.get(f"{API}/trial-balance", headers=h)).json()["accounts"]}


async def _cust(client, h, **kw):
    r = await client.post(f"{API}/customers", headers=h, json={"name": "Acme Ltd", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _inv(cid, price="1000", qty="1", date="2026-11-01", **kw):
    return {"customer_id": cid, "issue_date": date, "lines": [{"description": "Web work", "quantity": qty, "unit_price": price}], **kw}


async def test_send_posts_ar_income_and_tax_then_payment_clears_it(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h)
    tax = (await client.post(f"{API}/tax-rates", headers=h, json={"name": "GST 10", "percent": "10"})).json()
    body = _inv(c["id"], "1000", send=True)
    body["lines"][0]["tax_rate_id"] = tax["id"]
    r = await client.post(f"{API}/invoices", headers=h, json=body)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["number"] == "INV-000001" and inv["status"] == "sent"
    assert Decimal(inv["total"]) == 1100 and Decimal(inv["tax_total"]) == 100 and Decimal(inv["balance"]) == 1100
    tb = await _tb(client, h)
    assert tb["Accounts Receivable"] == 1100 and tb["Client Payments"] == -1000 and tb["Tax Payable"] == -100

    p = await client.post(f"{API}/payments", headers=h, json={
        "customer_id": c["id"], "payment_date": "2026-11-05", "amount": "1100", "deposit_account_id": accs["Bank"],
        "allocations": [{"invoice_id": inv["id"], "amount": "1100"}]})
    assert p.status_code == 201, p.text
    assert p.json()["number"] == "PAY-000001" and Decimal(p.json()["unapplied"]) == 0
    got = (await client.get(f"{API}/invoices/{inv['id']}", headers=h)).json()
    assert got["status"] == "paid" and Decimal(got["balance"]) == 0 and got["payments"][0]["number"] == "PAY-000001"
    tb = await _tb(client, h)
    assert tb["Accounts Receivable"] == 0 and tb["Bank"] == 1100


async def test_partial_payment_overpay_and_void_rules(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h)
    inv = (await client.post(f"{API}/invoices", headers=h, json=_inv(c["id"], "1000", send=True))).json()
    pay = lambda amt, alloc: client.post(f"{API}/payments", headers=h, json={  # noqa: E731
        "customer_id": c["id"], "payment_date": "2026-11-05", "amount": amt, "deposit_account_id": accs["Bank"],
        "allocations": [{"invoice_id": inv["id"], "amount": alloc}]})
    assert (await pay("2000", "1500")).status_code == 422          # exceeds balance
    assert (await pay("100", "200")).status_code == 422            # exceeds payment
    p = (await pay("400", "400")).json()
    got = (await client.get(f"{API}/invoices/{inv['id']}", headers=h)).json()
    assert got["status"] == "partially_paid" and Decimal(got["balance"]) == 600
    assert (await client.post(f"{API}/invoices/{inv['id']}/void", headers=h, json={})).status_code == 409
    assert (await client.post(f"{API}/payments/{p['id']}/void", headers=h, json={})).status_code == 200
    got = (await client.get(f"{API}/invoices/{inv['id']}", headers=h)).json()
    assert got["status"] == "sent" and Decimal(got["balance"]) == 1000
    assert (await _tb(client, h))["Bank"] == 0
    assert (await client.post(f"{API}/invoices/{inv['id']}/void", headers=h, json={})).status_code == 200
    tb = await _tb(client, h)
    assert tb["Accounts Receivable"] == 0 and tb["Client Payments"] == 0
    assert (await pay("10", "10")).status_code == 422              # void invoice cannot be paid


async def test_unapplied_payment_is_customer_credit(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h)
    p = await client.post(f"{API}/payments", headers=h, json={
        "customer_id": c["id"], "payment_date": "2026-11-05", "amount": "250", "deposit_account_id": accs["Bank"]})
    assert p.status_code == 201 and Decimal(p.json()["unapplied"]) == 250
    assert (await _tb(client, h))["Accounts Receivable"] == -250
    st = (await client.get(f"{API}/customers/{c['id']}/statement", headers=h)).json()
    assert Decimal(next(iter(st["balances"].values()))) == -250


async def test_foreign_currency_invoice_and_realized_fx(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    assert (await client.put(f"{API}/exchange-rates", headers=h, json={"currency": "EUR", "on_date": "2026-10-01", "rate": "1.10"})).status_code == 200
    c = await _cust(client, h, currency="EUR")
    inv = (await client.post(f"{API}/invoices", headers=h, json=_inv(c["id"], "100", send=True))).json()
    assert inv["currency"] == "EUR" and Decimal(inv["exchange_rate"]) == Decimal("1.1")
    tb = await _tb(client, h)
    assert tb["Accounts Receivable"] == 110 and tb["Client Payments"] == -110
    p = await client.post(f"{API}/payments", headers=h, json={
        "customer_id": c["id"], "payment_date": "2026-11-05", "amount": "100", "currency": "EUR", "rate": "1.20",
        "deposit_account_id": accs["Bank"], "allocations": [{"invoice_id": inv["id"], "amount": "100"}]})
    assert p.status_code == 201, p.text
    tb = await _tb(client, h)
    assert tb["Bank"] == 120 and tb["Accounts Receivable"] == 0 and tb["Exchange Gain / Loss"] == -10   # gain = credit
    # a loss goes the other way
    inv2 = (await client.post(f"{API}/invoices", headers=h, json=_inv(c["id"], "100", send=True))).json()
    await client.post(f"{API}/payments", headers=h, json={
        "customer_id": c["id"], "payment_date": "2026-11-06", "amount": "100", "currency": "EUR", "rate": "1.05",
        "deposit_account_id": accs["Bank"], "allocations": [{"invoice_id": inv2["id"], "amount": "100"}]})
    tb = await _tb(client, h)
    assert tb["Exchange Gain / Loss"] == -10 + 5 and tb["Accounts Receivable"] == 0
    # payment currency must match the invoice
    inv3 = (await client.post(f"{API}/invoices", headers=h, json=_inv(c["id"], "50", send=True))).json()
    bad = await client.post(f"{API}/payments", headers=h, json={
        "customer_id": c["id"], "payment_date": "2026-11-06", "amount": "50", "currency": "USD",
        "deposit_account_id": accs["Bank"], "allocations": [{"invoice_id": inv3["id"], "amount": "50"}]})
    assert bad.status_code == 422


async def test_draft_lifecycle(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h, payment_terms_days=14)
    d = (await client.post(f"{API}/invoices", headers=h, json=_inv(c["id"], "100", qty="3"))).json()
    assert d["status"] == "draft" and Decimal(d["total"]) == 300 and d["due_date"] == "2026-11-15"
    assert (await _tb(client, h))["Accounts Receivable"] == 0          # drafts never touch the books
    e = await client.patch(f"{API}/invoices/{d['id']}", headers=h, json={"lines": [{"description": "x", "unit_price": "50", "discount_percent": "10"}]})
    assert e.status_code == 200 and Decimal(e.json()["total"]) == 45
    assert (await client.post(f"{API}/invoices/{d['id']}/send", headers=h)).json()["status"] == "sent"
    assert (await client.post(f"{API}/invoices/{d['id']}/send", headers=h)).status_code == 409
    assert (await client.patch(f"{API}/invoices/{d['id']}", headers=h, json={"notes": "n"})).status_code == 409
    assert (await client.delete(f"{API}/invoices/{d['id']}", headers=h)).status_code == 409
    d2 = (await client.post(f"{API}/invoices", headers=h, json=_inv(c["id"]))).json()
    assert (await client.delete(f"{API}/invoices/{d2['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/invoices/{d2['id']}", headers=h)).status_code == 404
    assert (await client.post(f"{API}/invoices", headers=h, json={**_inv(c["id"]), "due_date": "2026-10-01"})).status_code == 422


async def test_overdue_filter_and_customer_balance(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h)
    await client.post(f"{API}/invoices", headers=h, json=_inv(c["id"], "700", date="2025-01-01", due_date="2025-01-31", send=True))
    await client.post(f"{API}/invoices", headers=h, json=_inv(c["id"], "300", date="2099-01-01", send=True))
    od = (await client.get(f"{API}/invoices", headers=h, params={"status": "overdue"})).json()
    assert od["total"] == 1 and od["items"][0]["is_overdue"] and od["items"][0]["status"] == "sent"
    cs = (await client.get(f"{API}/customers", headers=h)).json()["items"]
    assert Decimal(cs[0]["balance"]) == 1000
    assert (await client.get(f"{API}/invoices", headers=h, params={"search": "acme"})).json()["total"] == 2


async def test_permissions_and_tenant_isolation(client, org, other_org, engine):
    accs = await _setup(client, org)
    other = await _setup(client, other_org)
    h, ho = _h(org["owner"]), _h(other_org["owner"])
    c = await _cust(client, h)
    inv = (await client.post(f"{API}/invoices", headers=h, json=_inv(c["id"], send=True))).json()
    viewer = _h(await _role_user(engine, org, ["finance.view"], "Viewer"))
    assert (await client.get(f"{API}/invoices", headers=viewer)).status_code == 200
    assert (await client.post(f"{API}/customers", headers=viewer, json={"name": "x"})).status_code == 403
    assert (await client.post(f"{API}/invoices/{inv['id']}/void", headers=viewer, json={})).status_code == 403
    assert (await client.get(f"{API}/invoices", headers=ho)).json()["total"] == 0
    assert (await client.get(f"{API}/invoices/{inv['id']}", headers=ho)).status_code == 404
    assert (await client.get(f"{API}/customers/{c['id']}/statement", headers=ho)).status_code == 404
    r = await client.post(f"{API}/payments", headers=ho, json={"customer_id": c["id"], "payment_date": "2026-11-05",
                          "amount": "5", "deposit_account_id": other["Bank"]})
    assert r.status_code == 404
    r = await client.post(f"{API}/payments", headers=h, json={"customer_id": c["id"], "payment_date": "2026-11-05",
                          "amount": "5", "deposit_account_id": other["Bank"]})
    assert r.status_code == 422                                          # other org's account
