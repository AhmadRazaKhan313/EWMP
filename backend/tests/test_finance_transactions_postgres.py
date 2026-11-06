"""Finance Phase 1: income / expense / transfer entries, summary, import and export. Live Postgres, real HTTP."""
import io
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook

from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio


def _t(accs, type="expense", amount="300", cat="Grocery", acc="Cash", date="2026-11-02", desc="milk", **kw):
    b = {"type": type, "date": date, "amount": amount, "account_id": accs[acc], "description": desc, **kw}
    if cat:
        b["category_id"] = accs[cat]
    return b


async def _tb(client, h):
    return {a["name"]: Decimal(a["balance"]) for a in (await client.get(f"{API}/trial-balance", headers=h)).json()["accounts"]}


async def test_income_and_expense_move_the_right_accounts(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    r = await client.post(f"{API}/transactions", headers=h, json=_t(accs, "income", "1000", "Client Payments", desc="client"))
    assert r.status_code == 201, r.text
    assert r.json()["type"] == "income" and r.json()["category"] == "Client Payments" and r.json()["account"] == "Cash"
    assert (await client.post(f"{API}/transactions", headers=h, json=_t(accs))).status_code == 201
    tb = await _tb(client, h)
    assert tb["Cash"] == 700 and tb["Client Payments"] == -1000 and tb["Grocery"] == 300
    items = (await client.get(f"{API}/transactions", headers=h)).json()
    assert items["total"] == 2
    assert [i["type"] for i in items["items"]] == ["expense", "income"]  # newest first


async def test_category_rules(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    assert (await client.post(f"{API}/transactions", headers=h, json=_t(accs, "expense", cat="Client Payments"))).status_code == 422
    assert (await client.post(f"{API}/transactions", headers=h, json=_t(accs, "income", cat="Grocery"))).status_code == 422
    assert (await client.post(f"{API}/transactions", headers=h, json=_t(accs, acc="Loans"))).status_code == 422  # not a money account
    assert (await client.post(f"{API}/transactions", headers=h, json=_t(accs, cat=None))).status_code == 422
    assert (await client.get(f"{API}/transactions", headers=h)).json()["total"] == 0


async def test_founder_money_and_loans_count_as_income_but_not_profit(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, "income", "500000", "Founders Capital", acc="Bank"))
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, "income", "150000", "Loans", acc="Bank"))
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, "income", "100000", "Upwork Income", acc="Bank"))
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, "expense", "40000", "Salary", acc="Bank"))
    s = (await client.get(f"{API}/summary", headers=h)).json()
    assert Decimal(s["income_total"]) == 750000 and Decimal(s["expense_total"]) == 40000
    assert Decimal(s["balance"]) == 710000  # the sheet's "income minus expenses"
    assert Decimal(s["income_operating"]) == 100000 and Decimal(s["income_financing"]) == 650000
    assert Decimal(s["profit"]) == 60000
    bank = next(a for a in s["money_accounts"] if a["name"] == "Bank")
    assert Decimal(bank["balance"]) == 710000
    assert {c["category"] for c in s["income_by_category"]} == {"Founders Capital", "Loans", "Upwork Income"}
    tb = await _tb(client, h)  # ledger classification is right too
    assert tb["Founders Capital"] == -500000 and tb["Loans"] == -150000


async def test_transfer_is_neither_income_nor_expense(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, "income", "1000", "Other Income"))
    r = await client.post(f"{API}/transactions", headers=h, json={"type": "transfer", "date": "2026-11-03", "amount": "400", "account_id": accs["Cash"], "to_account_id": accs["Bank"]})
    assert r.status_code == 201, r.text
    s = (await client.get(f"{API}/summary", headers=h)).json()
    assert Decimal(s["income_total"]) == 1000 and Decimal(s["expense_total"]) == 0
    bal = {a["name"]: Decimal(a["balance"]) for a in s["money_accounts"]}
    assert bal["Cash"] == 600 and bal["Bank"] == 400
    same = {"type": "transfer", "date": "2026-11-03", "amount": "1", "account_id": accs["Cash"], "to_account_id": accs["Cash"]}
    assert (await client.post(f"{API}/transactions", headers=h, json=same)).status_code == 422


async def test_void_removes_it_from_lists_and_totals(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    t = (await client.post(f"{API}/transactions", headers=h, json=_t(accs, amount="999"))).json()
    assert (await client.post(f"{API}/journal/{t['id']}/void", headers=h, json={"reason": "oops"})).status_code == 200
    assert (await client.get(f"{API}/transactions", headers=h)).json()["total"] == 0
    s = (await client.get(f"{API}/summary", headers=h)).json()
    assert Decimal(s["expense_total"]) == 0
    assert (await _tb(client, h))["Cash"] == 0


async def test_filters(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, date="2026-11-01", desc="Milk by Rawal"))
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, cat="Utilities", date="2026-12-01", desc="Water bill"))
    g = lambda **p: client.get(f"{API}/transactions", headers=h, params=p)  # noqa: E731
    assert (await g(search="water")).json()["total"] == 1
    assert (await g(category_id=accs["Grocery"])).json()["total"] == 1
    assert (await g(date_from="2026-11-15")).json()["total"] == 1
    assert (await g(date_to="2026-11-15")).json()["total"] == 1
    s = (await client.get(f"{API}/summary", headers=h, params={"date_to": "2026-11-15"})).json()
    assert Decimal(s["expense_total"]) == 300


CSV_EXP = """Date,Amount,Description,Category
12/1/2025,650,Milk purchased by Rawal.,Grocery
12/3/2025,"27,700",Upwork connects purchase,Upwork
12/8/2025,30000,Paid by taimour for board,Assets
12/20/2025,11200,FIGMA,Subscriptions
12/21/2025,0,Rs 0 row,Utilities
12/22/2025,500,Mystery,Office Chai
"""


async def _import(client, h, accs, csv_text, type="expense", dry_run=True, **extra):
    data = {"type": type, "account_id": accs["Bank"], "dry_run": str(dry_run).lower(), **extra}
    return await client.post(f"{API}/transactions/import", headers=h, data=data,
                             files={"file": ("sheet.csv", csv_text.encode(), "text/csv")})


async def test_import_dry_run_then_real_then_duplicate_safe(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    r = await _import(client, h, accs, CSV_EXP)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["dry_run"] and d["date_order"] == "mdy" and d["total_rows"] == 6
    assert d["to_import"] == 5 and d["new_categories"] == ["Office Chai"]
    assert any("zero" in s["reason"] for s in d["skipped"])
    assert (await client.get(f"{API}/transactions", headers=h)).json()["total"] == 0  # nothing saved by a dry run

    r = await _import(client, h, accs, CSV_EXP, dry_run=False)
    assert r.json()["imported"] == 5
    items = (await client.get(f"{API}/transactions", headers=h, params={"page_size": 100})).json()["items"]
    cats = {i["description"]: i["category"] for i in items}
    assert cats["Upwork connects purchase"] == "Upwork Connects"      # alias, expense side
    assert cats["Paid by taimour for board"] == "Fixed Assets"
    assert cats["Mystery"] == "Office Chai"
    amounts = {i["description"]: Decimal(i["amount"]) for i in items}
    assert amounts["Upwork connects purchase"] == 27700               # "27,700" parsed
    assert next(i for i in items if i["description"] == "FIGMA")["date"] == "2025-12-20"
    assert all(i["account"] == "Bank" for i in items)

    again = (await _import(client, h, accs, CSV_EXP, dry_run=False)).json()
    assert again["imported"] == 0 and again["duplicates"] == 5
    assert (await client.get(f"{API}/transactions", headers=h)).json()["total"] == 5


async def test_import_income_aliases_and_no_auto_create(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    csv_inc = ("Date,Amount,Description,Category\n12/3/2025,500000,Payment by Rawal,Founders Investment\n"
               "1/10/2026,150000,Laptop loan,Loan\n1/14/2026,90000,Payment received,Upwork\n"
               "12/21/2025,219000,Client Payment Received,Client Payment\n2/2/2026,5,Odd,Mystery\n")
    d = (await _import(client, h, accs, csv_inc, type="income", dry_run=False, create_missing_categories="false")).json()
    assert d["imported"] == 4 and any("unknown category" in s["reason"] for s in d["skipped"])
    items = (await client.get(f"{API}/transactions", headers=h, params={"type": "income"})).json()["items"]
    assert {i["category"] for i in items} == {"Founders Capital", "Loans", "Upwork Income", "Client Payments"}


async def test_import_day_first_dates_and_xlsx(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    d = (await _import(client, h, accs, "Date,Amount,Description,Category\n20/12/2025,100,x,Grocery\n")).json()
    assert d["date_order"] == "dmy" and d["preview"][0]["date"] == "2025-12-20"
    wb = Workbook()
    ws = wb.active
    ws.append(["Date", "Amount", "Description", "Category"])
    import datetime as dt
    ws.append([dt.datetime(2026, 1, 5), 1234.5, "Excel row", "Grocery"])
    buf = io.BytesIO()
    wb.save(buf)
    r = await client.post(f"{API}/transactions/import", headers=h, data={"type": "expense", "account_id": accs["Cash"], "dry_run": "false"},
                          files={"file": ("sheet.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.json()["imported"] == 1
    bad = await client.post(f"{API}/transactions/import", headers=h, data={"type": "expense", "account_id": accs["Cash"]},
                            files={"file": ("x.pdf", b"x", "application/pdf")})
    assert bad.status_code == 422
    nohead = await _import(client, h, accs, "a,b\n1,2\n")
    assert nohead.status_code == 422 and "header" in nohead.text


async def test_export_workbook(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, amount="650", desc="Milk"))
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, "income", "1000", "Client Payments", desc="Client"))
    r = await client.get(f"{API}/transactions/export", headers=h)
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Expenses", "Income"]
    rows = list(wb["Expenses"].iter_rows(values_only=True))
    assert rows[0] == ("Date", "Amount", "Description", "Category") and rows[1][1:] == (650, "Milk", "Grocery")


async def test_permissions_and_isolation(client, engine, org, other_org):
    accs = await _setup(client, org)
    other = await _setup(client, other_org)
    h = _h(org["owner"])
    await client.post(f"{API}/transactions", headers=h, json=_t(accs))
    viewer = await _role_user(engine, org, ["finance.view"], "Viewer")
    poster = await _role_user(engine, org, ["finance.view", "finance.post"], "Poster")
    assert (await client.get(f"{API}/transactions", headers=_h(viewer))).status_code == 200
    assert (await client.get(f"{API}/summary", headers=_h(viewer))).status_code == 200
    assert (await client.post(f"{API}/transactions", headers=_h(viewer), json=_t(accs))).status_code == 403
    assert (await client.post(f"{API}/transactions", headers=_h(poster), json=_t(accs))).status_code == 201
    assert (await client.get(f"{API}/transactions/export", headers=_h(poster))).status_code == 403
    assert (await _import(client, _h(viewer), accs, CSV_EXP)).status_code == 403
    ho = _h(other_org["owner"])
    assert (await client.get(f"{API}/transactions", headers=ho)).json()["total"] == 0
    assert (await client.post(f"{API}/transactions", headers=ho, json=_t(accs))).status_code == 422  # other org's accounts
    assert (await client.get(f"{API}/summary", headers=ho)).json()["income_total"] == "0"


async def test_accounts_get_codes_automatically_and_money_accounts_show_in_summary(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    r = await client.post(f"{API}/accounts", headers=h, json={"name": "Faysal Bank", "type": "asset"})
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "1040" and r.json()["parent_id"] == accs["Assets"]
    r2 = await client.post(f"{API}/accounts", headers=h, json={"name": "Office Chai", "type": "expense"})
    assert r2.json()["code"] == "5080"
    r3 = await client.post(f"{API}/accounts", headers=h, json={"name": "Retainers", "type": "income"})
    assert r3.json()["code"] == "4030"
    accs["Faysal Bank"] = r.json()["id"]
    await client.post(f"{API}/transactions", headers=h, json=_t(accs, "income", "250", "Client Payments", acc="Faysal Bank"))
    s = (await client.get(f"{API}/summary", headers=h)).json()
    names = {a["name"]: Decimal(a["balance"]) for a in s["money_accounts"]}
    assert names["Faysal Bank"] == 250 and "Fixed Assets" not in names and "Accounts Receivable" not in names
    assert s["currency"] == "PKR"
