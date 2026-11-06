"""Finance Phase 4: reports and exports. Live Postgres, real HTTP."""
import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio
D = Decimal


async def _txn(client, h, accs, type, date, amount, acc, cat, desc="x"):
    r = await client.post(f"{API}/transactions", headers=h, json={"type": type, "date": date, "amount": amount,
                          "account_id": accs[acc], "category_id": accs[cat], "description": desc})
    assert r.status_code == 201, r.text
    return r.json()


async def _books(client, org):
    """Sep: +4000 income to Bank. Oct: +10000 income to Bank, -3000 Grocery from Cash. Invoice of 1000 in 2020 (income too)."""
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "income", "2026-09-15", "4000", "Bank", "Client Payments")
    await _txn(client, h, accs, "income", "2026-10-10", "10000", "Bank", "Client Payments")
    spend = await _txn(client, h, accs, "expense", "2026-10-20", "3000", "Cash", "Grocery", "rice")
    return accs, h, spend


async def test_profit_loss_period_compare_and_void(client, org):
    accs, h, spend = await _books(client, org)
    r = await client.get(f"{API}/reports/profit-loss", headers=h, params={"date_from": "2026-10-01", "date_to": "2026-10-31", "compare": "true"})
    assert r.status_code == 200, r.text
    pl = r.json()
    assert D(pl["income"]["total"]) == 10000 and D(pl["expenses"]["total"]) == 3000 and D(pl["net_profit"]) == 7000
    assert [x["name"] for x in pl["income"]["rows"]] == ["Client Payments"] and pl["expenses"]["rows"][0]["name"] == "Grocery"
    assert pl["previous_from"] == "2026-08-31" and pl["previous_to"] == "2026-09-30"
    assert D(pl["income"]["previous_total"]) == 4000 and D(pl["previous_net_profit"]) == 4000
    assert pl["income"]["rows"][0]["previous"] == "4000.00"
    # accounts with no activity are not listed
    assert all(D(x["amount"]) != 0 or D(x.get("previous", "0")) != 0 for x in pl["income"]["rows"] + pl["expenses"]["rows"])

    # a voided entry is netted out by its reversal
    v = await client.post(f"{API}/journal/{spend['id']}/void", headers=h, json={"reason": "oops", "on": "2026-10-20"})
    assert v.status_code == 200, v.text
    pl = (await client.get(f"{API}/reports/profit-loss", headers=h, params={"date_from": "2026-10-01", "date_to": "2026-10-31"})).json()
    assert D(pl["expenses"]["total"]) == 0 and D(pl["net_profit"]) == 10000 and "previous_net_profit" not in pl

    assert (await client.get(f"{API}/reports/profit-loss", headers=h, params={"date_from": "2026-11-01", "date_to": "2026-10-01"})).status_code == 422


async def test_balance_sheet_balances_and_respects_the_date(client, org):
    accs, h, _ = await _books(client, org)
    c = (await client.post(f"{API}/customers", headers=h, json={"name": "Acme"})).json()
    await client.post(f"{API}/invoices", headers=h, json={"customer_id": c["id"], "issue_date": "2020-01-01", "send": True,
                                                         "lines": [{"description": "old", "quantity": "1", "unit_price": "1000"}]})
    bs = (await client.get(f"{API}/reports/balance-sheet", headers=h, params={"as_of": "2026-10-31"})).json()
    names = {r["name"]: D(r["amount"]) for r in bs["assets"]["rows"]}
    assert names["Bank"] == 14000 and names["Cash"] == -3000 and names["Accounts Receivable"] == 1000
    assert D(bs["assets"]["total"]) == 12000 and D(bs["liabilities"]["total"]) == 0
    assert D(bs["equity"]["profit_to_date"]) == 12000 and D(bs["liabilities_and_equity"]) == 12000 and bs["balanced"] is True
    early = (await client.get(f"{API}/reports/balance-sheet", headers=h, params={"as_of": "2026-09-30"})).json()
    assert {r["name"]: D(r["amount"]) for r in early["assets"]["rows"]}["Bank"] == 4000 and early["balanced"] is True
    none = (await client.get(f"{API}/reports/balance-sheet", headers=h, params={"as_of": "2019-01-01"})).json()
    assert none["assets"]["rows"] == [] and none["balanced"] is True


async def test_general_ledger_running_balance_both_signs(client, org):
    accs, h, _ = await _books(client, org)
    get = lambda acc, **p: client.get(f"{API}/reports/general-ledger", headers=h, params={"account_id": accs[acc], **p})  # noqa: E731
    gl = (await get("Bank", date_from="2026-10-01", date_to="2026-10-31")).json()
    assert D(gl["opening_balance"]) == 4000 and len(gl["lines"]) == 1 and D(gl["lines"][0]["debit"]) == 10000
    assert D(gl["lines"][0]["balance"]) == 14000 and D(gl["closing_balance"]) == 14000 and gl["truncated"] is False
    inc = (await get("Client Payments", date_from="2026-10-01")).json()              # credit-normal account
    assert D(inc["opening_balance"]) == 4000 and D(inc["closing_balance"]) == 14000 and inc["account"]["type"] == "income"
    allrows = (await get("Bank")).json()
    assert [D(x["balance"]) for x in allrows["lines"]] == [4000, 14000] and D(allrows["opening_balance"]) == 0
    assert (await client.get(f"{API}/reports/general-ledger", headers=h, params={"account_id": "00000000-0000-0000-0000-000000000000"})).status_code == 404
    assert (await client.get(f"{API}/reports/general-ledger", headers=h)).status_code == 422


async def test_aging_buckets_partial_payment_and_tenancy(client, org, other_org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    c = (await client.post(f"{API}/customers", headers=h, json={"name": "Acme"})).json()
    line = lambda p: [{"description": "w", "quantity": "1", "unit_price": p}]  # noqa: E731
    old = (await client.post(f"{API}/invoices", headers=h, json={"customer_id": c["id"], "issue_date": "2020-01-01", "send": True, "lines": line("1000")})).json()
    await client.post(f"{API}/invoices", headers=h, json={"customer_id": c["id"], "issue_date": "2099-01-01", "send": True, "lines": line("500")})
    await client.post(f"{API}/invoices", headers=h, json={"customer_id": c["id"], "issue_date": "2099-01-01", "lines": line("777")})   # draft: ignored
    ar = (await client.get(f"{API}/reports/receivables-aging", headers=h)).json()
    assert len(ar["rows"]) == 1 and ar["rows"][0]["name"] == "Acme"
    assert D(ar["rows"][0]["d90_plus"]) == 1000 and D(ar["rows"][0]["current"]) == 500 and D(ar["totals"]["total"]) == 1500
    assert {i["bucket"] for i in ar["rows"][0]["items"]} == {"d90_plus", "current"}

    p = await client.post(f"{API}/payments", headers=h, json={"customer_id": c["id"], "payment_date": "2026-11-01", "amount": "400",
                                                             "deposit_account_id": accs["Bank"], "allocations": [{"invoice_id": old["id"], "amount": "400"}]})
    assert p.status_code == 201, p.text
    ar = (await client.get(f"{API}/reports/receivables-aging", headers=h)).json()
    assert D(ar["totals"]["d90_plus"]) == 600 and D(ar["totals"]["total"]) == 1100

    v = (await client.post(f"{API}/vendors", headers=h, json={"name": "Zed"})).json()
    bl = lambda price, date: {"vendor_id": v["id"], "issue_date": date, "post": True, "due_date": date,   # noqa: E731
                              "lines": [{"description": "b", "quantity": "1", "unit_price": price, "expense_account_id": accs["Grocery"]}]}
    await client.post(f"{API}/bills", headers=h, json=bl("250", "2020-03-01"))
    await client.post(f"{API}/bills", headers=h, json=bl("100", "2099-03-01"))
    ap = (await client.get(f"{API}/reports/payables-aging", headers=h)).json()
    assert ap["rows"][0]["name"] == "Zed" and D(ap["totals"]["d90_plus"]) == 250 and D(ap["totals"]["current"]) == 100

    oh = _h(other_org["owner"])
    assert (await client.get(f"{API}/reports/receivables-aging", headers=oh)).json()["rows"] == []
    assert (await client.get(f"{API}/reports/payables-aging", headers=oh)).json()["rows"] == []
    assert D((await client.get(f"{API}/reports/profit-loss", headers=oh)).json()["net_profit"]) == 0
    assert (await client.get(f"{API}/reports/general-ledger", headers=oh, params={"account_id": accs["Bank"]})).status_code == 404


async def test_exports_xlsx_csv_permissions_and_formula_injection(client, engine, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "income", "2026-10-10", "10000", "Bank", "Client Payments", '=HYPERLINK("http://evil","x")')
    q = {"report": "general-ledger", "account_id": accs["Bank"]}

    x = await client.get(f"{API}/reports/export", headers=h, params={**q, "format": "xlsx"})
    assert x.status_code == 200 and "attachment" in x.headers["content-disposition"] and x.headers["x-content-type-options"] == "nosniff"
    ws = load_workbook(io.BytesIO(x.content)).active
    cells = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    assert 10000 in cells or 10000.0 in cells
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)               # stored as text, never a live formula
    assert any(isinstance(c, str) and c.startswith("'=HYPERLINK") for c in cells)

    c = await client.get(f"{API}/reports/export", headers=h, params={**q, "format": "csv"})
    assert c.status_code == 200 and c.headers["content-type"].startswith("text/csv")
    body = c.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body and "10000.00" in body

    for rep in ("profit-loss", "balance-sheet", "trial-balance", "receivables-aging", "payables-aging"):
        r = await client.get(f"{API}/reports/export", headers=h, params={"report": rep})
        assert r.status_code == 200, (rep, r.text)
        assert load_workbook(io.BytesIO(r.content)).active.max_row >= 2
    assert (await client.get(f"{API}/reports/export", headers=h, params={"report": "general-ledger"})).status_code == 422
    assert (await client.get(f"{API}/reports/export", headers=h, params={"report": "nope"})).status_code == 422

    viewer = _h(await _role_user(engine, org, ["finance.view"], "Viewer"))
    assert (await client.get(f"{API}/reports/profit-loss", headers=viewer)).status_code == 200
    assert (await client.get(f"{API}/reports/export", headers=viewer, params={"report": "profit-loss"})).status_code == 403
    exporter = _h(await _role_user(engine, org, ["finance.view", "finance.export"], "Exporter"))
    assert (await client.get(f"{API}/reports/export", headers=exporter, params={"report": "profit-loss", "format": "csv"})).status_code == 200
    nobody = _h(await _role_user(engine, org, ["payroll.view"], "Nobody"))
    assert (await client.get(f"{API}/reports/profit-loss", headers=nobody)).status_code == 403
