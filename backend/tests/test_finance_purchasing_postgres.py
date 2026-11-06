"""Finance Phase 3b: approvals, attachments, purchase orders, recurring bills. Live Postgres, real HTTP."""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.services import finance_purchasing as pp
from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


async def _vendor(client, h, **kw):
    r = await client.post(f"{API}/vendors", headers=h, json={"name": "Alpha Supplies", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _lines(accs, price="1000", cat="Utilities"):
    return [{"description": "Internet", "quantity": "1", "unit_price": price, "expense_account_id": accs[cat]}]


async def _tb(client, h):
    return {a["name"]: Decimal(a["balance"]) for a in (await client.get(f"{API}/trial-balance", headers=h)).json()["accounts"]}


async def test_approval_flow_blocks_posting_until_someone_else_approves(client, engine, org):
    accs = await _setup(client, org)
    owner = _h(org["owner"])
    clerk = _h(await _role_user(engine, org, ["finance.view", "finance.post"], "Clerk"))
    boss = _h(await _role_user(engine, org, ["finance.view", "finance.post", "finance.manage"], "Boss"))
    v = await _vendor(client, owner)

    assert (await client.put(f"{API}/purchase-settings", headers=clerk, json={"approval_threshold": "5000"})).status_code == 403
    assert (await client.put(f"{API}/purchase-settings", headers=boss, json={"approval_threshold": "5000"})).json()["approval_threshold"] == "5000.00"
    assert (await client.put(f"{API}/purchase-settings", headers=boss, json={"approval_threshold": "0"})).status_code == 422

    small = await client.post(f"{API}/bills", headers=clerk, json={"vendor_id": v["id"], "issue_date": "2026-11-01", "lines": _lines(accs, "4999.99"), "post": True})
    assert small.status_code == 201 and small.json()["status"] == "open"           # under the limit: posts directly

    big = await client.post(f"{API}/bills", headers=clerk, json={"vendor_id": v["id"], "issue_date": "2026-11-01", "lines": _lines(accs, "8000")})
    b = big.json()
    assert big.status_code == 201 and b["status"] == "draft" and b["approval_status"] == "none"
    r = await client.post(f"{API}/bills/{b['id']}/post", headers=clerk)
    assert r.status_code == 409 and "approval" in r.text.lower()
    assert (await client.post(f"{API}/bills", headers=clerk, json={"vendor_id": v["id"], "issue_date": "2026-11-01", "lines": _lines(accs, "8000"), "post": True})).status_code == 409
    assert (await client.post(f"{API}/bills/{small.json()['id']}/request-approval", headers=clerk)).status_code == 409   # posted already

    assert (await client.post(f"{API}/bills/{b['id']}/request-approval", headers=clerk)).json()["approval_status"] == "pending"
    assert (await client.post(f"{API}/bills/{b['id']}/request-approval", headers=clerk)).status_code == 409
    assert (await client.post(f"{API}/bills/{b['id']}/approve", headers=clerk)).status_code == 403               # needs finance.manage
    # a pending bill that is edited has to be approved again
    await client.patch(f"{API}/bills/{b['id']}", headers=clerk, json={"notes": "changed"})
    assert (await client.get(f"{API}/bills/{b['id']}", headers=clerk)).json()["approval_status"] == "none"
    await client.post(f"{API}/bills/{b['id']}/request-approval", headers=boss)
    assert (await client.post(f"{API}/bills/{b['id']}/approve", headers=boss)).status_code == 409               # requester cannot approve own

    # the requester may withdraw (reject) their own request; editing resets approval; then resubmit and reject by a manager
    assert (await client.post(f"{API}/bills/{b['id']}/reject", headers=boss, json={"reason": "withdrawn"})).status_code == 200
    await client.patch(f"{API}/bills/{b['id']}", headers=boss, json={"notes": "fixed"})
    await client.post(f"{API}/bills/{b['id']}/request-approval", headers=clerk)
    rj = await client.post(f"{API}/bills/{b['id']}/reject", headers=boss, json={"reason": "wrong vendor"})
    assert rj.json()["approval_status"] == "rejected" and rj.json()["rejection_reason"] == "wrong vendor"
    await client.post(f"{API}/bills/{b['id']}/request-approval", headers=clerk)
    ok = await client.post(f"{API}/bills/{b['id']}/approve", headers=boss)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "open" and ok.json()["approval_status"] == "approved"
    tb = await _tb(client, owner)
    assert tb["Accounts Payable"] == -(Decimal("4999.99") + 8000)

    # approvals off again: anything posts
    await client.put(f"{API}/purchase-settings", headers=boss, json={"approval_threshold": None})
    assert (await client.post(f"{API}/bills", headers=clerk, json={"vendor_id": v["id"], "issue_date": "2026-11-01", "lines": _lines(accs, "9000"), "post": True})).status_code == 201


async def test_threshold_uses_base_currency(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    v = await _vendor(client, h)
    await client.put(f"{API}/purchase-settings", headers=h, json={"approval_threshold": "10000"})
    r = await client.post(f"{API}/bills", headers=h, json={"vendor_id": v["id"], "issue_date": "2026-11-01", "currency": "USD", "rate": "280",
                                                           "lines": _lines(accs, "50"), "post": True})        # 50 USD = 14000 base
    assert r.status_code == 409, r.text
    r = await client.post(f"{API}/bills", headers=h, json={"vendor_id": v["id"], "issue_date": "2026-11-01", "currency": "USD", "rate": "280",
                                                           "lines": _lines(accs, "30"), "post": True})        # 8400 base
    assert r.status_code == 201, r.text


async def test_attachments_validate_type_and_stay_inside_the_tenant(client, engine, org, other_org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    v = await _vendor(client, h)
    b = (await client.post(f"{API}/bills", headers=h, json={"vendor_id": v["id"], "issue_date": "2026-11-01", "lines": _lines(accs)})).json()
    url = f"{API}/bills/{b['id']}/attachments"
    up = await client.post(url, headers=h, files={"file": ("../../scan 1.pdf", PDF, "application/pdf")})
    assert up.status_code == 201, up.text
    att = up.json()
    assert att["mime_type"] == "application/pdf" and "/" not in att["file_name"] and att["size_bytes"] == len(PDF)
    assert [a["id"] for a in (await client.get(url, headers=h)).json()["items"]] == [att["id"]]
    dl = await client.get(f"{url}/{att['id']}", headers=h)
    assert dl.status_code == 200 and dl.content == PDF and dl.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in dl.headers["content-disposition"]

    bad = await client.post(url, headers=h, files={"file": ("run.exe", b"MZ....", "application/octet-stream")})
    assert bad.status_code == 400
    fake = await client.post(url, headers=h, files={"file": ("evil.pdf", b"<html><script>alert(1)</script>", "application/pdf")})
    assert fake.status_code == 400                                                        # bytes must match the extension
    assert (await client.post(url, headers=h, files={"file": ("empty.pdf", b"", "application/pdf")})).status_code == 400
    assert (await client.post(url, headers=h, files={"file": ("big.pdf", PDF + b"0" * (10 * 1024 * 1024), "application/pdf")})).status_code == 400

    # another organisation cannot see, download or delete it
    oh = _h(other_org["owner"])
    assert (await client.get(url, headers=oh)).status_code == 404
    assert (await client.get(f"{url}/{att['id']}", headers=oh)).status_code == 404
    assert (await client.delete(f"{url}/{att['id']}", headers=oh)).status_code == 404

    assert (await client.delete(f"{url}/{att['id']}", headers=h)).status_code == 204
    assert (await client.get(url, headers=h)).json()["items"] == []
    assert (await client.get(f"{url}/{att['id']}", headers=h)).status_code == 404


async def test_purchase_order_lifecycle_and_convert_to_bill(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    v = await _vendor(client, h)
    body = {"vendor_id": v["id"], "issue_date": "2026-11-01", "expected_date": "2026-11-10", "lines": _lines(accs, "250") + _lines(accs, "100", "Grocery")}
    assert (await client.post(f"{API}/purchase-orders", headers=h, json={**body, "expected_date": "2026-10-01"})).status_code == 422
    r = await client.post(f"{API}/purchase-orders", headers=h, json=body)
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["number"] == "PO-000001" and o["status"] == "draft" and Decimal(o["total"]) == 350
    assert (await client.post(f"{API}/purchase-orders/{o['id']}/convert", headers=h)).status_code == 409        # not sent yet
    assert (await client.post(f"{API}/purchase-orders/{o['id']}/received", headers=h)).status_code == 409
    assert (await client.patch(f"{API}/purchase-orders/{o['id']}", headers=h, json={"notes": "rush"})).json()["notes"] == "rush"
    assert (await client.post(f"{API}/purchase-orders/{o['id']}/sent", headers=h)).json()["status"] == "sent"
    assert (await client.patch(f"{API}/purchase-orders/{o['id']}", headers=h, json={"notes": "late"})).status_code == 409
    assert (await client.post(f"{API}/purchase-orders/{o['id']}/received", headers=h)).json()["status"] == "received"

    c = await client.post(f"{API}/purchase-orders/{o['id']}/convert", headers=h, json={"issue_date": "2026-11-12"})
    assert c.status_code == 200, c.text
    bill, order = c.json()["bill"], c.json()["order"]
    assert bill["status"] == "draft" and Decimal(bill["total"]) == 350 and order["status"] == "billed" and order["bill_id"] == bill["id"]
    assert bill["issue_date"] == "2026-11-12" and "PO-000001" in (bill["notes"] or "")
    assert (await client.post(f"{API}/purchase-orders/{o['id']}/convert", headers=h)).status_code == 409      # only once
    assert (await client.post(f"{API}/purchase-orders/{o['id']}/cancelled", headers=h)).status_code == 409
    assert (await _tb(client, h)).get("Accounts Payable", 0) == 0                                              # POs never post

    o2 = (await client.post(f"{API}/purchase-orders", headers=h, json=body)).json()
    assert o2["number"] == "PO-000002"
    assert (await client.delete(f"{API}/purchase-orders/{o2['id']}", headers=h)).status_code == 204
    o3 = (await client.post(f"{API}/purchase-orders", headers=h, json={**body, "send": True})).json()
    assert o3["status"] == "sent"
    assert (await client.delete(f"{API}/purchase-orders/{o3['id']}", headers=h)).status_code == 409
    assert (await client.post(f"{API}/purchase-orders/{o3['id']}/cancelled", headers=h)).json()["status"] == "cancelled"
    listed = (await client.get(f"{API}/purchase-orders", headers=h, params={"status": "billed"})).json()
    assert [x["number"] for x in listed["items"]] == ["PO-000001"] and listed["total"] == 1


async def test_purchase_order_permissions_and_tenancy(client, engine, org, other_org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    viewer = _h(await _role_user(engine, org, ["finance.view"], "Viewer"))
    v = await _vendor(client, h)
    body = {"vendor_id": v["id"], "issue_date": "2026-11-01", "lines": _lines(accs)}
    assert (await client.post(f"{API}/purchase-orders", headers=viewer, json=body)).status_code == 403
    o = (await client.post(f"{API}/purchase-orders", headers=h, json=body)).json()
    assert (await client.get(f"{API}/purchase-orders/{o['id']}", headers=viewer)).status_code == 200
    assert (await client.get(f"{API}/purchase-orders/{o['id']}", headers=_h(other_org["owner"]))).status_code == 404
    assert (await client.get(f"{API}/purchase-orders", headers=_h(other_org["owner"]))).json()["total"] == 0


async def test_step_date_anchors_on_the_start_day():
    assert pp.step_date(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)
    assert pp.step_date(date(2026, 1, 31), "monthly", 2) == date(2026, 3, 31)
    assert pp.step_date(date(2026, 11, 1), "weekly", 2) == date(2026, 11, 15)
    assert pp.step_date(date(2024, 2, 29), "yearly", 1) == date(2025, 2, 28)


async def test_recurring_bills_generate_draft_or_posted_and_catch_up(client, engine, org):
    from sqlalchemy.ext.asyncio import AsyncSession
    accs = await _setup(client, org)
    h = _h(org["owner"])
    v = await _vendor(client, h, payment_terms_days=15)
    body = {"title": "Office rent", "vendor_id": v["id"], "frequency": "monthly", "start_date": "2026-09-01", "lines": _lines(accs, "700", "Grocery")}
    assert (await client.post(f"{API}/recurring-bills", headers=h, json={**body, "end_date": "2026-08-01"})).status_code == 422
    r = await client.post(f"{API}/recurring-bills", headers=h, json=body)
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["status"] == "active" and rec["next_run_date"] == "2026-09-01" and Decimal(rec["total"]) == 700

    async with AsyncSession(engine) as s:                                       # sweep on 2026-11-05: Sep, Oct, Nov are due
        out = await pp.run_due(s, tenant_id=org["org"], today=date(2026, 11, 5))
        await s.commit()
    assert out == {"created": 3, "failed": []}
    bills = (await client.get(f"{API}/bills", headers=h)).json()["items"]
    assert sorted(b["issue_date"] for b in bills) == ["2026-09-01", "2026-10-01", "2026-11-01"]
    assert all(b["status"] == "draft" and b["due_date"] == f"{b['issue_date'][:8]}16" for b in bills)
    got = (await client.get(f"{API}/recurring-bills/{rec['id']}", headers=h)).json()
    assert got["run_count"] == 3 and got["next_run_date"] == "2026-12-01"
    assert (await client.get(f"{API}/bills/{bills[0]['id']}", headers=h)).json()["recurring_id"] == rec["id"]

    async with AsyncSession(engine) as s:                                       # same day again: nothing new
        assert (await pp.run_due(s, tenant_id=org["org"], today=date(2026, 11, 5)))["created"] == 0
        await s.commit()

    # pause / resume without back-filling
    assert (await client.post(f"{API}/recurring-bills/{rec['id']}/pause", headers=h)).json()["status"] == "paused"
    assert (await client.post(f"{API}/recurring-bills/{rec['id']}/pause", headers=h)).status_code == 409
    assert (await client.patch(f"{API}/recurring-bills/{rec['id']}", headers=h, json={"frequency": "weekly"})).status_code == 409
    assert (await client.post(f"{API}/recurring-bills/{rec['id']}/resume", headers=h)).json()["status"] == "active"
    assert (await client.delete(f"{API}/recurring-bills/{rec['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/recurring-bills", headers=h)).json()["items"] == []


async def test_recurring_auto_post_respects_the_approval_limit_and_isolates_failures(client, engine, org):
    from sqlalchemy.ext.asyncio import AsyncSession
    accs = await _setup(client, org)
    h = _h(org["owner"])
    v = await _vendor(client, h)
    await client.put(f"{API}/purchase-settings", headers=h, json={"approval_threshold": "5000"})
    small = (await client.post(f"{API}/recurring-bills", headers=h, json={
        "title": "Small", "vendor_id": v["id"], "frequency": "monthly", "start_date": "2026-11-01", "auto_post": True, "lines": _lines(accs, "100")})).json()
    big = (await client.post(f"{API}/recurring-bills", headers=h, json={
        "title": "Big", "vendor_id": v["id"], "frequency": "monthly", "start_date": "2026-11-01", "auto_post": True, "lines": _lines(accs, "9000", "Grocery")})).json()
    bad = (await client.post(f"{API}/recurring-bills", headers=h, json={
        "title": "Foreign", "vendor_id": v["id"], "frequency": "monthly", "start_date": "2026-11-01", "currency": "EUR", "lines": _lines(accs, "10")})).json()
    async with AsyncSession(engine) as s:
        out = await pp.run_due(s, tenant_id=org["org"], today=date(2026, 11, 5))
        await s.commit()
    assert out["created"] == 2 and [f["title"] for f in out["failed"]] == ["Foreign"]           # no EUR rate: only that one fails
    by_ref = {b["notes"]: b for b in (await client.get(f"{API}/bills", headers=h)).json()["items"]}
    assert by_ref["Small"]["status"] == "open" and by_ref["Big"]["status"] == "draft"          # above the limit waits for a person
    recs = {r["title"]: r for r in (await client.get(f"{API}/recurring-bills", headers=h)).json()["items"]}
    assert recs["Foreign"]["last_error"] and recs["Foreign"]["run_count"] == 0 and recs["Small"]["run_count"] == 1


async def test_recurring_bills_are_tenant_scoped_and_permissioned(client, engine, org, other_org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    viewer = _h(await _role_user(engine, org, ["finance.view"], "Viewer"))
    v = await _vendor(client, h)
    body = {"title": "Rent", "vendor_id": v["id"], "frequency": "monthly", "start_date": "2026-11-01", "lines": _lines(accs)}
    assert (await client.post(f"{API}/recurring-bills", headers=viewer, json=body)).status_code == 403
    rec = (await client.post(f"{API}/recurring-bills", headers=h, json=body)).json()
    assert (await client.get(f"{API}/recurring-bills/{rec['id']}", headers=_h(other_org["owner"]))).status_code == 404
    assert (await client.post(f"{API}/recurring-bills/run", headers=viewer)).status_code == 403
