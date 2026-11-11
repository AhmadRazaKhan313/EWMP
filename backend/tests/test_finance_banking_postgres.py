"""Finance Phase 5: statement import, matching and reconciliation. Live Postgres, real HTTP."""
import io
from decimal import Decimal

import pytest

from tests.test_finance_ledger_postgres import API, _h, _role_user, _setup, client, engine, org, other_org  # noqa: F401

pytestmark = pytest.mark.asyncio
D = Decimal

# Opening balance 10 000. Rows are dd/mm/yyyy (20/11 proves it).
STATEMENT = (
    "Date,Description,Reference,Debit,Credit,Balance\n"
    "03/11/2026,Client retainer,TID-1,,5000,15000\n"
    "05/11/2026,Grocery run,,1200,,13800\n"
    "08/11/2026,Bank charges,,150,,13650\n"
    "20/11/2026,Transfer from cash,,,2000,15650\n"
)


async def _txn(client, h, accs, type, date, amount, acc, cat=None, to=None, **extra):
    body = {"type": type, "date": date, "amount": amount, "account_id": accs[acc], "description": "x", **extra}
    if cat:
        body["category_id"] = accs[cat]
    if to:
        body["to_account_id"] = accs[to]
    r = await client.post(f"{API}/transactions", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _import(client, h, accs, text=STATEMENT, account="Bank", dry_run=False, name="stmt.csv", **form):
    data = {"account_id": accs[account], "dry_run": str(dry_run).lower(), **form}
    return await client.post(f"{API}/banking/statements/import", headers=h, data=data, files={"file": (name, text.encode(), "text/csv")})


async def _lines(client, h, accs, account="Bank", **params):
    r = await client.get(f"{API}/banking/lines", headers=h, params={"account_id": accs[account], **params})
    assert r.status_code == 200, r.text
    return r.json()


def _by(items, desc):
    return next(i for i in items if i["description"] == desc)


async def test_import_dry_run_then_real_and_duplicates(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    r = await _import(client, h, accs, dry_run=True)
    assert r.status_code == 200, r.text
    dry = r.json()
    assert dry["dry_run"] is True and dry["to_import"] == 4 and dry["imported"] == 0 and dry["statement_id"] is None
    assert dry["date_order"] == "dmy" and dry["date_order_guessed"] is False and dry["preview"][0]["amount"] == "5000.00"
    assert (await _lines(client, h, accs))["total"] == 0                                      # dry run saved nothing

    real = (await _import(client, h, accs)).json()
    assert real["imported"] == 4 and real["duplicates"] == 0 and real["statement_id"]
    lines = await _lines(client, h, accs)
    assert lines["total"] == 4 and lines["counts"] == {"unmatched": 4, "matched": 0, "ignored": 0}
    assert _by(lines["items"], "Bank charges")["amount"] == "-150.00" and _by(lines["items"], "Client retainer")["date"] == "2026-11-03"

    st = (await client.get(f"{API}/banking/statements", headers=h, params={"account_id": accs["Bank"]})).json()["items"]
    assert len(st) == 1 and st[0]["opening_balance"] == "10000.00" and st[0]["closing_balance"] == "15650.00"
    assert st[0]["date_from"] == "2026-11-03" and st[0]["date_to"] == "2026-11-20" and st[0]["counts"]["unmatched"] == 4

    again = (await _import(client, h, accs)).json()                                           # same file twice
    assert again["imported"] == 0 and again["duplicates"] == 4 and again["statement_id"] is None
    more = (await _import(client, h, accs, STATEMENT + "21/11/2026,Late fee,,50,,15600\n")).json()
    assert more["imported"] == 1 and more["duplicates"] == 4
    assert (await _lines(client, h, accs))["total"] == 5


async def test_import_formats_signed_amount_descending_bad_rows_and_xlsx(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    signed = "Transaction Date,Narration,Amount\n2026-11-02,Salary in,\"10,000.50\"\n2026-11-03,ATM,-500\n,no date,5\n2026-11-04,zero,0\n2026-11-05,text,abc\n\n"
    r = (await _import(client, h, accs, signed, account="Cash")).json()
    assert r["imported"] == 2 and len(r["skipped"]) == 3 and {s["row"] for s in r["skipped"]} == {4, 5, 6}
    items = (await _lines(client, h, accs, "Cash"))["items"]
    assert _by(items, "Salary in")["amount"] == "10000.50" and _by(items, "ATM")["amount"] == "-500.00"

    desc = "Date,Details,Debit,Credit,Balance\n12/11/2026,Second,100,,900\n10/11/2026,First,,1000,1000\n"        # newest first
    await _import(client, h, accs, desc, account="Mobile Wallet")
    st = (await client.get(f"{API}/banking/statements", headers=h, params={"account_id": accs["Mobile Wallet"]})).json()["items"][0]
    assert st["opening_balance"] == "0.00" and st["closing_balance"] == "900.00"
    given = (await _import(client, h, accs, "Date,Details,Amount\n01/01/2027,x,5\n", account="Mobile Wallet", opening_balance="40", closing_balance="45")).json()
    assert given["imported"] == 1

    amb = (await _import(client, h, accs, "Date,Details,Amount\n03/04/2026,x,5\n", account="Cash", dry_run=True)).json()
    assert amb["date_order_guessed"] is True and amb["preview"][0]["date"] == "2026-04-03"
    forced = (await _import(client, h, accs, "Date,Details,Amount\n03/04/2026,x,5\n", account="Cash", dry_run=True, date_order="mdy")).json()
    assert forced["preview"][0]["date"] == "2026-03-04"

    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["Date", "Description", "Withdrawal", "Deposit"]); ws.append(["2026-11-09", "Xlsx row", None, 77])
    buf = io.BytesIO(); wb.save(buf)
    r = await client.post(f"{API}/banking/statements/import", headers=h, data={"account_id": accs["Bank"], "dry_run": "false"},
                          files={"file": ("s.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.json()["imported"] == 1
    assert (await _import(client, h, accs, "a,b\n1,2\n")).status_code == 422                  # no header row
    assert (await _import(client, h, accs, "x", name="x.pdf")).status_code == 422
    assert (await _import(client, h, accs, STATEMENT, account="Grocery")).status_code == 422   # not a money account


async def test_auto_match_is_careful(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "income", "2026-11-03", "5000", "Bank", "Client Payments")           # exact
    await _txn(client, h, accs, "expense", "2026-11-06", "1200", "Bank", "Grocery")                  # 1 day late: inside the window
    await _txn(client, h, accs, "expense", "2026-11-07", "150", "Bank", "Other Expenses")            # two candidates, none on the day -> not guessed
    await _txn(client, h, accs, "expense", "2026-11-09", "150", "Bank", "Gifts")
    gone = await _txn(client, h, accs, "income", "2026-11-20", "2000", "Bank", "Other Income")       # voided: never offered
    assert (await client.post(f"{API}/journal/{gone['id']}/void", headers=h, json={"reason": "oops", "on": "2026-11-20"})).status_code == 200
    r = (await _import(client, h, accs)).json()
    assert r["imported"] == 4 and r["matched"] == 2
    items = (await _lines(client, h, accs))["items"]
    assert _by(items, "Client retainer")["status"] == "matched" and _by(items, "Client retainer")["match"]["number"].startswith("JE-")
    assert _by(items, "Grocery run")["status"] == "matched"
    assert _by(items, "Bank charges")["status"] == "unmatched" and _by(items, "Transfer from cash")["status"] == "unmatched"

    sug = (await client.get(f"{API}/banking/lines/{_by(items, 'Bank charges')['id']}/suggestions", headers=h)).json()["items"]
    assert len(sug) == 2 and {s["amount"] for s in sug} == {"150.00"}
    assert (await client.post(f"{API}/banking/accounts/{accs['Bank']}/auto-match", headers=h)).json() == {"matched": 0}


async def test_reference_breaks_a_tie(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "expense", "2026-11-08", "150", "Bank", "Other Expenses")
    await _txn(client, h, accs, "expense", "2026-11-08", "150", "Bank", "Gifts", payment_provider="HBL (Habib Bank)", payment_tid="REF-77")
    await _import(client, h, accs, "Date,Description,Reference,Amount\n08/11/2026,Fee,ref-77,-150\n")
    line = (await _lines(client, h, accs))["items"][0]
    assert line["status"] == "matched"
    entries = (await client.get(f"{API}/transactions", headers=h, params={"type": "expense"})).json()["items"]
    tid = next(e for e in entries if e.get("payment_tid") == "REF-77")
    assert line["match"]["entry_id"] == tid["id"]


async def test_manual_match_unmatch_and_guards(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "expense", "2026-11-07", "150", "Bank", "Other Expenses")
    await _txn(client, h, accs, "expense", "2026-11-09", "150", "Bank", "Gifts")
    await _txn(client, h, accs, "expense", "2026-11-09", "999", "Cash", "Gifts")
    await _import(client, h, accs, "Date,Description,Amount\n08/11/2026,Fee A,-150\n08/11/2026,Fee B,-150\n20/11/2026,Big,-5000\n")
    items = (await _lines(client, h, accs))["items"]
    a, b, big = _by(items, "Fee A"), _by(items, "Fee B"), _by(items, "Big")
    assert a["status"] == "unmatched" and b["status"] == "unmatched"                         # ambiguous, left alone
    sug = (await client.get(f"{API}/banking/lines/{a['id']}/suggestions", headers=h)).json()["items"]
    pick = next(s for s in sug if s["date"] == "2026-11-07")["entry_line_id"]
    other = next(s for s in sug if s["date"] == "2026-11-09")["entry_line_id"]

    post = lambda line, el: client.post(f"{API}/banking/lines/{line['id']}/match", headers=h, json={"entry_line_id": el})  # noqa: E731
    assert (await post(big, pick)).status_code == 422                                        # amount differs
    ledger_cash = (await client.get(f"{API}/journal", headers=h)).json()["items"]
    cash = [e for e in ledger_cash if e["memo"] == "x"]
    assert cash
    ok = await post(a, pick)
    assert ok.status_code == 200 and ok.json()["status"] == "matched"
    assert (await post(b, pick)).status_code == 409                                          # already used by Fee A
    assert (await post(a, other)).status_code == 409                                         # Fee A already matched
    inflow = (await client.post(f"{API}/banking/lines/{b['id']}/match", headers=h, json={"entry_line_id": "00000000-0000-0000-0000-000000000000"}))
    assert inflow.status_code == 422                                                         # unknown ledger line
    un = await client.post(f"{API}/banking/lines/{a['id']}/unmatch", headers=h)
    assert un.json()["status"] == "unmatched" and un.json()["match"] is None
    assert (await client.post(f"{API}/banking/lines/{a['id']}/unmatch", headers=h)).status_code == 409
    assert (await post(a, pick)).status_code == 200                                          # free again


async def test_book_a_line_from_the_statement(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _import(client, h, accs)
    items = (await _lines(client, h, accs))["items"]
    fee, cash_in, retainer = _by(items, "Bank charges"), _by(items, "Transfer from cash"), _by(items, "Client retainer")
    mk = lambda line, **b: client.post(f"{API}/banking/lines/{line['id']}/create-entry", headers=h, json=b)  # noqa: E731

    assert (await mk(fee, type="income", category_id=accs["Client Payments"])).status_code == 422          # money out is not income
    assert (await mk(retainer, type="expense", category_id=accs["Grocery"])).status_code == 422            # money in is not an expense
    assert (await mk(fee, type="expense")).status_code == 422                                              # category missing
    assert (await mk(cash_in, type="transfer")).status_code == 422                                         # other account missing
    r = await mk(fee, type="expense", category_id=accs["Other Expenses"], description="Monthly bank charges")
    assert r.status_code == 201, r.text
    assert r.json()["line"]["status"] == "matched" and r.json()["number"].startswith("JE-")
    t = await mk(cash_in, type="transfer", other_account_id=accs["Cash"])
    assert t.status_code == 201 and t.json()["line"]["status"] == "matched"
    assert (await mk(fee, type="expense", category_id=accs["Other Expenses"])).status_code == 409          # already booked

    exp = (await client.get(f"{API}/transactions", headers=h, params={"type": "expense"})).json()["items"]
    assert any(e["description"] == "Monthly bank charges" and e["date"] == "2026-11-08" and D(str(e["amount"])) == 150 for e in exp)
    tr = (await client.get(f"{API}/transactions", headers=h, params={"type": "transfer"})).json()["items"]
    assert len(tr) == 1 and D(str(tr[0]["amount"])) == 2000
    s = (await client.get(f"{API}/summary", headers=h)).json()
    bank = next(a for a in s["accounts"] if a["id"] == accs["Bank"]) if "accounts" in s else None
    if bank:
        assert D(str(bank["balance"])) == D("1850")                                                        # +2000 transfer in, -150 fee


async def test_ignore_and_restore(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "expense", "2026-11-08", "150", "Bank", "Gifts")
    await _import(client, h, accs, "Date,Description,Amount\n08/11/2026,Fee,-150\n09/11/2026,Dup,-80\n")
    items = (await _lines(client, h, accs))["items"]
    fee, dup = _by(items, "Fee"), _by(items, "Dup")
    assert fee["status"] == "matched"
    assert (await client.post(f"{API}/banking/lines/{fee['id']}/ignore", headers=h)).status_code == 409   # unmatch first
    ig = await client.post(f"{API}/banking/lines/{dup['id']}/ignore", headers=h)
    assert ig.json()["status"] == "ignored"
    counts = (await _lines(client, h, accs))["counts"]
    assert counts == {"unmatched": 0, "matched": 1, "ignored": 1}
    assert (await client.post(f"{API}/banking/lines/{dup['id']}/match", headers=h, json={"entry_line_id": "00000000-0000-0000-0000-000000000000"})).status_code == 409
    assert (await _lines(client, h, accs, status="ignored"))["total"] == 1
    assert (await client.post(f"{API}/banking/lines/{dup['id']}/restore", headers=h)).json()["status"] == "unmatched"
    assert (await client.post(f"{API}/banking/lines/{dup['id']}/restore", headers=h)).status_code == 409
    assert len((await _lines(client, h, accs, q="dup"))["items"]) == 1 and len((await _lines(client, h, accs, q="nothing"))["items"]) == 0
    assert (await _lines(client, h, accs, date_from="2026-11-09"))["total"] == 1


async def _books_for_statement(client, h, accs):
    await _txn(client, h, accs, "income", "2026-11-03", "5000", "Bank", "Client Payments")
    await _txn(client, h, accs, "expense", "2026-11-05", "1200", "Bank", "Grocery")
    await _txn(client, h, accs, "expense", "2026-11-08", "150", "Bank", "Other Expenses")
    await _txn(client, h, accs, "income", "2026-11-20", "2000", "Bank", "Other Income")


async def test_reconciliation_flow(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _books_for_statement(client, h, accs)
    assert (await _import(client, h, accs)).json()["matched"] == 4
    prev = lambda **b: client.post(f"{API}/banking/reconciliations/preview", headers=h, json={"account_id": accs["Bank"], **b})  # noqa: E731

    p = (await prev(statement_date="2026-11-30", statement_balance="15650")).json()
    assert p["beginning_balance"] == "10000.00" and p["cleared_total"] == "5650.00" and p["difference"] == "0.00"
    assert p["can_finish"] is True and p["cleared_count"] == 4 and p["ledger_balance"] == "5650.00"        # books do not hold the 10 000 opening
    wrong = (await prev(statement_date="2026-11-30", statement_balance="15000")).json()
    assert wrong["difference"] == "-650.00" and wrong["can_finish"] is False and "difference" in wrong["reason"]
    part = (await prev(statement_date="2026-11-10", statement_balance="13650")).json()
    assert part["cleared_count"] == 3 and part["difference"] == "0.00" and part["can_finish"] is True       # only lines up to the date count
    typed = (await prev(statement_date="2026-11-30", statement_balance="15650", beginning_balance="9000")).json()
    assert typed["beginning_balance"] == "9000.00" and typed["difference"] == "1000.00"                       # a typed beginning balance beats the statement's opening

    bad = await client.post(f"{API}/banking/reconciliations", headers=h, json={"account_id": accs["Bank"], "statement_date": "2026-11-30", "statement_balance": "15000"})
    assert bad.status_code == 422 and "difference" in bad.text
    done = await client.post(f"{API}/banking/reconciliations", headers=h, json={"account_id": accs["Bank"], "statement_date": "2026-11-10", "statement_balance": "13650"})
    assert done.status_code == 201, done.text
    rec = done.json()
    assert rec["line_count"] == 3 and rec["beginning_balance"] == "10000.00" and rec["cleared_total"] == "3650.00"

    items = (await _lines(client, h, accs))["items"]
    locked = _by(items, "Client retainer")
    assert locked["reconciled"] is True and _by(items, "Transfer from cash")["reconciled"] is False
    assert (await client.post(f"{API}/banking/lines/{locked['id']}/unmatch", headers=h)).status_code == 409
    assert (await client.post(f"{API}/banking/lines/{locked['id']}/ignore", headers=h)).status_code == 409

    early = await prev(statement_date="2026-11-09", statement_balance="1")
    assert early.status_code == 422 and "last reconciliation" in early.text
    nxt = (await prev(statement_date="2026-11-30", statement_balance="15650")).json()
    assert nxt["beginning_balance"] == "13650.00" and nxt["beginning_from_last"] is True and nxt["cleared_count"] == 1 and nxt["can_finish"] is True
    nothing = (await prev(statement_date="2026-11-10", statement_balance="13650")).json()
    assert nothing["cleared_count"] == 0 and nothing["can_finish"] is False and "no matched" in nothing["reason"]

    second = await client.post(f"{API}/banking/reconciliations", headers=h, json={"account_id": accs["Bank"], "statement_date": "2026-11-30", "statement_balance": "15650"})
    assert second.status_code == 201
    hist = (await client.get(f"{API}/banking/reconciliations", headers=h, params={"account_id": accs["Bank"]})).json()["items"]
    assert [r["statement_date"] for r in hist] == ["2026-11-30", "2026-11-10"]
    assert (await client.delete(f"{API}/banking/reconciliations/{rec['id']}", headers=h)).status_code == 409     # not the latest
    assert (await client.delete(f"{API}/banking/reconciliations/{second.json()['id']}", headers=h)).status_code == 204
    assert (await client.delete(f"{API}/banking/reconciliations/{rec['id']}", headers=h)).status_code == 204
    assert (await client.post(f"{API}/banking/lines/{locked['id']}/unmatch", headers=h)).status_code == 200      # unlocked again
    assert (await client.get(f"{API}/banking/reconciliations", headers=h, params={"account_id": accs["Bank"]})).json()["items"] == []


async def test_unmatched_or_voided_lines_block_reconciliation(client, org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    e = await _txn(client, h, accs, "income", "2026-11-03", "5000", "Bank", "Client Payments")
    await _import(client, h, accs, "Date,Description,Amount,Balance\n03/11/2026,Retainer,5000,5000\n05/11/2026,Mystery,-300,4700\n")
    body = {"account_id": accs["Bank"], "statement_date": "2026-11-30", "statement_balance": "4700", "beginning_balance": "0"}
    p = (await client.post(f"{API}/banking/reconciliations/preview", headers=h, json=body)).json()
    assert p["unmatched_count"] == 1 and p["can_finish"] is False and "not matched" in p["reason"]
    assert (await client.post(f"{API}/banking/reconciliations", headers=h, json=body)).status_code == 422
    mystery = _by((await _lines(client, h, accs))["items"], "Mystery")
    await client.post(f"{API}/banking/lines/{mystery['id']}/ignore", headers=h)                                  # leaving it out changes the maths
    p = (await client.post(f"{API}/banking/reconciliations/preview", headers=h, json=body)).json()
    assert p["unmatched_count"] == 0 and p["difference"] == "-300.00" and p["can_finish"] is False
    ok = {**body, "statement_balance": "5000"}
    assert (await client.post(f"{API}/banking/reconciliations/preview", headers=h, json=ok)).json()["can_finish"] is True

    assert (await client.post(f"{API}/journal/{e['id']}/void", headers=h, json={"reason": "oops", "on": "2026-11-03"})).status_code == 200
    line = _by((await _lines(client, h, accs))["items"], "Retainer")
    assert line["status"] == "matched" and line["match"]["voided"] is True                                       # the page can show it
    p = (await client.post(f"{API}/banking/reconciliations/preview", headers=h, json=ok)).json()
    assert p["unmatched_count"] == 1 and p["can_finish"] is False


async def test_permissions_validation_and_isolation(client, engine, org, other_org):
    accs = await _setup(client, org)
    h = _h(org["owner"])
    await _txn(client, h, accs, "expense", "2026-11-08", "150", "Bank", "Gifts")
    await _import(client, h, accs, "Date,Description,Amount\n08/11/2026,Fee,-150\n09/11/2026,Other,-10\n")
    line = _by((await _lines(client, h, accs))["items"], "Other")

    viewer = _h(await _role_user(engine, org, ["finance.view"], name="Viewer"))
    assert (await client.get(f"{API}/banking/lines", headers=viewer, params={"account_id": accs["Bank"]})).status_code == 200
    assert (await client.get(f"{API}/banking/statements", headers=viewer, params={"account_id": accs["Bank"]})).status_code == 200
    assert (await _import(client, viewer, accs)).status_code == 403
    assert (await client.post(f"{API}/banking/lines/{line['id']}/ignore", headers=viewer)).status_code == 403
    assert (await client.post(f"{API}/banking/accounts/{accs['Bank']}/auto-match", headers=viewer)).status_code == 403
    body = {"account_id": accs["Bank"], "statement_date": "2026-11-30", "statement_balance": "0"}
    assert (await client.post(f"{API}/banking/reconciliations/preview", headers=viewer, json=body)).status_code == 200
    poster = _h(await _role_user(engine, org, ["finance.view", "finance.post"], name="Poster"))
    assert (await client.post(f"{API}/banking/lines/{line['id']}/ignore", headers=poster)).status_code == 200
    assert (await client.post(f"{API}/banking/reconciliations", headers=poster, json=body)).status_code == 403   # finishing needs finance.manage
    nobody = _h(await _role_user(engine, org, [], name="Nobody"))
    assert (await client.get(f"{API}/banking/lines", headers=nobody, params={"account_id": accs["Bank"]})).status_code == 403

    assert (await client.get(f"{API}/banking/lines", headers=h, params={"account_id": accs["Grocery"]})).status_code == 422   # not a money account
    assert (await client.get(f"{API}/banking/lines", headers=h, params={"account_id": accs["Bank"], "status": "weird"})).status_code == 422
    assert (await client.get(f"{API}/banking/lines", headers=h, params={"account_id": accs["Bank"], "limit": 9999})).status_code == 422
    assert (await client.post(f"{API}/banking/reconciliations/preview", headers=h, json={**body, "statement_balance": "1e30"})).status_code == 422
    assert (await _import(client, h, accs, opening_balance="1e30")).status_code == 422
    assert (await client.post(f"{API}/banking/lines/00000000-0000-0000-0000-000000000000/ignore", headers=h)).status_code == 404

    other_accs = await _setup(client, other_org)
    oh = _h(other_org["owner"])
    assert (await client.post(f"{API}/banking/lines/{line['id']}/restore", headers=oh)).status_code == 404         # another tenant
    assert (await client.get(f"{API}/banking/lines", headers=oh, params={"account_id": accs["Bank"]})).status_code in (404, 422)
    assert (await _lines(client, oh, other_accs))["total"] == 0
