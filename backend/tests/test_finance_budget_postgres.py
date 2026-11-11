"""Finance Budget: weekly / monthly / yearly plan against actuals. Live Postgres, real HTTP."""
import datetime
from decimal import Decimal

import pytest

from app.services.finance_budget import period_bounds
from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio
D = Decimal
d = datetime.date


def test_period_bounds_week_month_and_financial_year():
    assert period_bounds("week", d(2026, 11, 6)) == (d(2026, 11, 2), d(2026, 11, 8), "02 Nov - 08 Nov 2026")   # Fri -> Mon..Sun
    assert period_bounds("week", d(2026, 11, 2))[:2] == (d(2026, 11, 2), d(2026, 11, 8))
    assert period_bounds("week", d(2026, 11, 8))[:2] == (d(2026, 11, 2), d(2026, 11, 8))
    assert period_bounds("week", d(2026, 12, 31))[:2] == (d(2026, 12, 28), d(2027, 1, 3))                       # crosses the year
    assert period_bounds("month", d(2028, 2, 10)) == (d(2028, 2, 1), d(2028, 2, 29), "February 2028")          # leap year
    assert period_bounds("year", d(2026, 6, 30)) == (d(2025, 7, 1), d(2026, 6, 30), "2025-26")
    assert period_bounds("year", d(2026, 7, 1)) == (d(2026, 7, 1), d(2027, 6, 30), "2026-27")
    assert period_bounds("year", d(2026, 11, 6))[2] == "2026-27"


async def _txn(client, h, accs, type, date, amount, acc, cat):
    r = await client.post(f"{API}/transactions", headers=h, json={"type": type, "date": date, "amount": amount,
                          "account_id": accs[acc], "category_id": accs[cat], "description": "x"})
    assert r.status_code == 201, r.text
    return r.json()


async def _get(client, h, period, date):
    r = await client.get(f"{API}/budget", headers=h, params={"period": period, "date": date})
    assert r.status_code == 200, r.text
    return r.json()


def _row(section, name):
    return next(x for x in section["rows"] if x["category"] == name)


async def test_weekly_monthly_and_yearly_actuals_come_from_the_ledger(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "income", "2026-11-03", "5000", "Bank", "Client Payments")      # Tue of the week of 2 Nov
    await _txn(client, h, accs, "expense", "2026-11-04", "1200", "Cash", "Grocery")
    await _txn(client, h, accs, "expense", "2026-11-04", "300", "Cash", "Upwork Connects")      # alias -> Upwork
    await _txn(client, h, accs, "expense", "2026-11-04", "50", "Cash", "Other Expenses")        # no category -> All Expenses
    await _txn(client, h, accs, "expense", "2026-11-20", "700", "Cash", "Grocery")              # later in the month
    await _txn(client, h, accs, "income", "2026-09-10", "9000", "Bank", "Upwork Income")        # same financial year, other month

    wk = await _get(client, h, "week", "2026-11-06")
    assert wk["start"] == "2026-11-02" and wk["end"] == "2026-11-08"
    assert D(_row(wk["income"], "Client Payment")["actual"]) == 5000
    assert D(_row(wk["expenses"], "Grocery")["actual"]) == 1200 and D(_row(wk["expenses"], "Upwork")["actual"]) == 300
    assert D(_row(wk["expenses"], "All Expenses")["actual"]) == 50
    assert D(wk["expenses"]["actual"]) == 1550 and D(wk["income"]["actual"]) == 5000 and D(wk["saved"]) == 3450

    mo = await _get(client, h, "month", "2026-11-06")
    assert D(_row(mo["expenses"], "Grocery")["actual"]) == 1900 and D(mo["expenses"]["actual"]) == 2250 and D(mo["saved"]) == 2750

    yr = await _get(client, h, "year", "2026-11-06")
    assert yr["label"] == "2026-27" and yr["start"] == "2026-07-01" and yr["end"] == "2027-06-30"
    assert D(_row(yr["income"], "Upwork")["actual"]) == 9000 and D(yr["income"]["actual"]) == 14000 and D(yr["saved"]) == 11750
    assert len(wk["expenses"]["rows"]) == 14 and len(wk["income"]["rows"]) == 6
    assert (await _get(client, h, "week", "2026-11-13"))["saved"] == "0.00"


async def test_equity_loan_and_asset_categories_count_but_transfers_and_voids_do_not(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "income", "2026-11-02", "100000", "Bank", "Founders Capital")   # Founders Investment
    await _txn(client, h, accs, "income", "2026-11-02", "20000", "Bank", "Loans")               # Loan
    await _txn(client, h, accs, "expense", "2026-11-03", "40000", "Bank", "Fixed Assets")       # Assets
    spend = await _txn(client, h, accs, "expense", "2026-11-03", "999", "Cash", "Gadgets")
    r = await client.post(f"{API}/transactions", headers=h, json={"type": "transfer", "date": "2026-11-03", "amount": "5000",
                          "account_id": accs["Bank"], "to_account_id": accs["Cash"]})
    assert r.status_code == 201, r.text
    assert (await client.post(f"{API}/journal/{spend['id']}/void", headers=h, json={"reason": "oops", "on": "2026-11-03"})).status_code == 200

    m = await _get(client, h, "month", "2026-11-15")
    assert D(_row(m["income"], "Founders Investment")["actual"]) == 100000 and D(_row(m["income"], "Loan")["actual"]) == 20000
    assert D(_row(m["expenses"], "Assets")["actual"]) == 40000
    assert D(_row(m["expenses"], "Gadgets")["actual"]) == 0                                     # void netted out
    assert D(m["income"]["actual"]) == 120000 and D(m["expenses"]["actual"]) == 40000 and D(m["saved"]) == 80000


async def test_plan_diff_and_periods_are_independent(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "expense", "2026-11-04", "1200", "Cash", "Grocery")
    await _txn(client, h, accs, "income", "2026-11-04", "5000", "Bank", "Client Payments")
    put = lambda **b: client.put(f"{API}/budget/plan", headers=h, json=b)  # noqa: E731
    r = await put(period="month", date="2026-11-10", kind="expense", category="Grocery", planned="2000")
    assert r.status_code == 200, r.text
    r = await put(period="month", date="2026-11-30", kind="income", category="Client Payment", planned="4000")   # same month, other day
    g = r.json()
    assert _row(g["expenses"], "Grocery")["planned"] == "2000.00" and _row(g["expenses"], "Grocery")["diff"] == "800.00"        # left to spend
    assert _row(g["income"], "Client Payment")["diff"] == "1000.00"                                                             # ahead of plan
    assert g["expenses"]["planned"] == "2000.00" and g["expenses"]["diff"] == "800.00" and g["income"]["diff"] == "1000.00"

    r = await put(period="month", date="2026-11-10", kind="expense", category="Grocery", planned="1000")      # update, not duplicate
    assert _row(r.json()["expenses"], "Grocery")["diff"] == "-200.00"                                         # overspent
    assert _row((await _get(client, h, "week", "2026-11-04"))["expenses"], "Grocery")["planned"] == "0.00"   # other period type untouched
    assert _row((await _get(client, h, "month", "2026-12-01"))["expenses"], "Grocery")["planned"] == "0.00"
    await put(period="week", date="2026-11-04", kind="expense", category="Grocery", planned="300")
    assert _row((await _get(client, h, "week", "2026-11-08"))["expenses"], "Grocery")["planned"] == "300.00"


async def test_starting_balance_from_ledger_or_by_hand(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "income", "2026-10-15", "10000", "Bank", "Client Payments")
    await _txn(client, h, accs, "expense", "2026-10-20", "3000", "Cash", "Grocery")
    await _txn(client, h, accs, "income", "2026-11-05", "2000", "Bank", "Client Payments")
    m = await _get(client, h, "month", "2026-11-06")
    assert m["starting_balance"] == "7000.00" and m["starting_balance_manual"] is False       # 10000 - 3000 before 1 Nov
    assert m["end_balance"] == "9000.00" and m["saved"] == "2000.00"

    r = await client.put(f"{API}/budget/opening", headers=h, json={"period": "month", "date": "2026-11-20", "starting_balance": "500"})
    assert r.status_code == 200, r.text
    assert r.json()["starting_balance"] == "500.00" and r.json()["starting_balance_manual"] is True and r.json()["end_balance"] == "2500.00"
    assert (await _get(client, h, "week", "2026-11-05"))["starting_balance_manual"] is False   # per period type
    r = await client.put(f"{API}/budget/opening", headers=h, json={"period": "month", "date": "2026-11-01", "starting_balance": None})
    assert r.json()["starting_balance"] == "7000.00" and r.json()["starting_balance_manual"] is False
    r = await client.put(f"{API}/budget/opening", headers=h, json={"period": "month", "date": "2026-11-01", "starting_balance": "-250"})
    assert r.json()["starting_balance"] == "-250.00"                                          # overdrawn is allowed again after clearing


async def test_validation_permissions_and_isolation(client, engine, org, other_org):
    await _setup(client, org)
    h = _h(org["owner"])
    put = lambda body, hh=h: client.put(f"{API}/budget/plan", headers=hh, json=body)  # noqa: E731
    base = {"period": "month", "date": "2026-11-10", "kind": "expense", "category": "Grocery", "planned": "10"}
    assert (await put({**base, "category": "Nonsense"})).status_code == 422
    assert (await put({**base, "category": "Loan"})).status_code == 422                       # an income category, not an expense one
    assert (await put({**base, "planned": "-1"})).status_code == 422
    assert (await put({**base, "planned": "1e30"})).status_code == 422
    assert (await put({**base, "planned": "abc"})).status_code == 422
    assert (await put({**base, "period": "day"})).status_code == 422
    assert (await put({**base, "kind": "other"})).status_code == 422
    assert (await client.get(f"{API}/budget", headers=h, params={"period": "decade"})).status_code == 422
    assert (await client.get(f"{API}/budget", headers=h)).status_code == 200                  # defaults: this month

    viewer = _h(await _role_user(engine, org, ["finance.view"], name="Viewer"))
    assert (await client.get(f"{API}/budget", headers=viewer, params={"period": "year"})).status_code == 200
    assert (await put(base, viewer)).status_code == 403
    assert (await client.put(f"{API}/budget/opening", headers=viewer, json={"period": "week", "date": "2026-11-10", "starting_balance": "1"})).status_code == 403
    nobody = _h(await _role_user(engine, org, [], name="Nobody"))
    assert (await client.get(f"{API}/budget", headers=nobody)).status_code == 403

    assert (await put(base)).status_code == 200
    await _setup(client, other_org)
    other = await _get(client, _h(other_org["owner"]), "month", "2026-11-10")
    assert _row(other["expenses"], "Grocery")["planned"] == "0.00"                            # another tenant sees nothing
