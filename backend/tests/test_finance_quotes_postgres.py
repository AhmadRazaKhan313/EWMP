"""Finance Phase 2b: quotes. Live Postgres, real HTTP."""
from decimal import Decimal

import pytest

from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _cust(client, h, **kw):
    r = await client.post(f"{API}/customers", headers=h, json={"name": "Acme Ltd", **kw})
    return r.json()


def _q(cid, price="500", qty="2", **kw):
    return {"customer_id": cid, "issue_date": "2026-11-01", "lines": [{"description": "Design", "quantity": qty, "unit_price": price}], **kw}


async def _tb(client, h):
    return {a["name"]: Decimal(a["balance"]) for a in (await client.get(f"{API}/trial-balance", headers=h)).json()["accounts"]}


async def test_quote_never_touches_the_books_and_numbers_up(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h)
    tax = (await client.post(f"{API}/tax-rates", headers=h, json={"name": "GST", "percent": "10"})).json()
    body = _q(c["id"])
    body["lines"][0]["tax_rate_id"] = tax["id"]
    r = await client.post(f"{API}/quotes", headers=h, json=body)
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["number"] == "QUO-000001" and q["status"] == "draft" and q["valid_until"] == "2026-12-01"
    assert Decimal(q["total"]) == 1100 and len(q["lines"]) == 1
    assert (await client.post(f"{API}/quotes", headers=h, json=_q(c["id"]))).json()["number"] == "QUO-000002"
    tb = await _tb(client, h)
    assert tb.get("Accounts Receivable", 0) == 0 and tb.get("Client Payments", 0) == 0


async def test_status_flow_and_edit_rules(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h)
    q = (await client.post(f"{API}/quotes", headers=h, json=_q(c["id"]))).json()
    qid = q["id"]
    assert (await client.post(f"{API}/quotes/{qid}/accept", headers=h)).status_code == 409      # not sent yet
    e = await client.patch(f"{API}/quotes/{qid}", headers=h, json={"lines": [{"description": "x", "unit_price": "100"}]})
    assert e.status_code == 200 and Decimal(e.json()["total"]) == 100
    assert (await client.post(f"{API}/quotes/{qid}/send", headers=h)).json()["status"] == "sent"
    assert (await client.patch(f"{API}/quotes/{qid}", headers=h, json={"notes": "n"})).status_code == 409
    assert (await client.delete(f"{API}/quotes/{qid}", headers=h)).status_code == 409
    assert (await client.post(f"{API}/quotes/{qid}/accept", headers=h)).json()["status"] == "accepted"
    assert (await client.post(f"{API}/quotes/{qid}/decline", headers=h)).status_code == 409
    d = (await client.post(f"{API}/quotes", headers=h, json=_q(c["id"]))).json()
    assert (await client.delete(f"{API}/quotes/{d['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/quotes/{d['id']}", headers=h)).status_code == 404
    assert (await client.post(f"{API}/quotes", headers=h, json={**_q(c["id"]), "valid_until": "2026-10-01"})).status_code == 422


async def test_convert_creates_a_draft_invoice_once(client, org):
    await _setup(client, org)
    h = _h(org["owner"])
    c = await _cust(client, h, payment_terms_days=10)
    tax = (await client.post(f"{API}/tax-rates", headers=h, json={"name": "GST", "percent": "10"})).json()
    body = _q(c["id"], send=True)
    body["lines"][0]["tax_rate_id"] = tax["id"]
    q = (await client.post(f"{API}/quotes", headers=h, json=body)).json()
    assert q["status"] == "sent"
    r = await client.post(f"{API}/quotes/{q['id']}/convert", headers=h, json={"issue_date": "2026-11-05"})
    assert r.status_code == 200, r.text
    inv = r.json()["invoice"]
    assert inv["status"] == "draft" and Decimal(inv["total"]) == 1100 and inv["reference"] == q["number"]
    assert inv["due_date"] == "2026-11-15" and inv["lines"][0]["tax_rate_id"] == tax["id"]
    assert r.json()["quote"]["status"] == "invoiced" and r.json()["quote"]["invoice_id"] == inv["id"]
    assert (await client.post(f"{API}/quotes/{q['id']}/convert", headers=h)).status_code == 409
    assert (await _tb(client, h)).get("Accounts Receivable", 0) == 0                       # still a draft
    # if the draft is deleted, the quote can be converted again
    assert (await client.delete(f"{API}/invoices/{inv['id']}", headers=h)).status_code == 204
    assert (await client.post(f"{API}/quotes/{q['id']}/convert", headers=h)).status_code == 200
    draft = (await client.post(f"{API}/quotes", headers=h, json=_q(c["id"]))).json()
    assert (await client.post(f"{API}/quotes/{draft['id']}/convert", headers=h)).status_code == 409   # must be sent first


async def test_expired_filter_search_permissions_isolation(client, org, other_org, engine):
    await _setup(client, org)
    await _setup(client, other_org)
    h, ho = _h(org["owner"]), _h(other_org["owner"])
    c = await _cust(client, h)
    old = (await client.post(f"{API}/quotes", headers=h, json={**_q(c["id"]), "issue_date": "2025-01-01", "valid_until": "2025-02-01", "send": True})).json()
    await client.post(f"{API}/quotes", headers=h, json={**_q(c["id"]), "issue_date": "2099-01-01", "send": True})
    ex = (await client.get(f"{API}/quotes", headers=h, params={"status": "expired"})).json()
    assert ex["total"] == 1 and ex["items"][0]["id"] == old["id"] and ex["items"][0]["is_expired"]
    assert (await client.get(f"{API}/quotes", headers=h, params={"search": "acme"})).json()["total"] == 2
    viewer = _h(await _role_user(engine, org, ["finance.view"], "Viewer"))
    assert (await client.get(f"{API}/quotes", headers=viewer)).status_code == 200
    assert (await client.post(f"{API}/quotes", headers=viewer, json=_q(c["id"]))).status_code == 403
    assert (await client.get(f"{API}/quotes", headers=ho)).json()["total"] == 0
    assert (await client.get(f"{API}/quotes/{old['id']}", headers=ho)).status_code == 404
    assert (await client.post(f"{API}/quotes/{old['id']}/convert", headers=ho)).status_code == 404
