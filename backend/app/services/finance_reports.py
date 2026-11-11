"""Finance Phase 4: reports computed straight from the ledger (base currency, posted entries only).

Voided entries are reversed by a mirror entry, so they net to zero here without any special handling.
"""
import csv
import io
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.finance import AccountType, FinAccount, FinJournalEntry, FinJournalLine
from app.models.finance_purchases import BillStatus, FinBill, FinVendor
from app.models.finance_sales import FinCustomer, FinInvoice, InvoiceStatus
from app.services import finance_ledger as led

ZERO = Decimal("0")
GL_MAX_ROWS = 5000
BUCKETS = ("current", "d1_30", "d31_60", "d61_90", "d90_plus")
# Debit-normal accounts show debit - credit; the rest show credit - debit.
DEBIT_NORMAL = (AccountType.ASSET, AccountType.EXPENSE)


def _q(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"))


def _signed(t: AccountType, dr: Decimal, cr: Decimal) -> Decimal:
    return _q(dr - cr) if t in DEBIT_NORMAL else _q(cr - dr)


def _check_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise UnprocessableError("'From' date cannot be after the 'To' date")


async def _sums(db, tenant_id, *, date_from: date | None = None, date_to: date | None = None,
                types: tuple[AccountType, ...] | None = None, before: date | None = None) -> list[tuple]:
    """(account, debit, credit) per account. `before` = strictly earlier than that date (opening balances)."""
    q = (select(FinAccount, func.coalesce(func.sum(FinJournalLine.debit), 0), func.coalesce(func.sum(FinJournalLine.credit), 0))
         .join(FinJournalLine, FinJournalLine.account_id == FinAccount.id)
         .join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
         .where(FinAccount.tenant_id == tenant_id, FinAccount.is_deleted == False,  # noqa: E712
                FinJournalLine.tenant_id == tenant_id, FinJournalEntry.tenant_id == tenant_id,
                FinJournalEntry.is_deleted == False))  # noqa: E712
    if types:
        q = q.where(FinAccount.type.in_(types))
    if date_from:
        q = q.where(FinJournalEntry.entry_date >= date_from)
    if date_to:
        q = q.where(FinJournalEntry.entry_date <= date_to)
    if before:
        q = q.where(FinJournalEntry.entry_date < before)
    return list((await db.execute(q.group_by(FinAccount.id).order_by(FinAccount.code))).all())


def _rows(sums: list[tuple]) -> dict[uuid.UUID, dict]:
    return {a.id: {"account_id": str(a.id), "code": a.code, "name": a.name, "type": a.type.value,
                   "amount": _signed(a.type, Decimal(dr), Decimal(cr))} for a, dr, cr in sums}


# ───────────────────────── profit & loss ─────────────────────────
async def profit_loss(db, tenant_id, date_from: date, date_to: date, compare: bool = False) -> dict:
    _check_range(date_from, date_to)
    cur = _rows(await _sums(db, tenant_id, date_from=date_from, date_to=date_to, types=(AccountType.INCOME, AccountType.EXPENSE)))
    prev, prev_range = {}, None
    if compare:
        span = (date_to - date_from).days + 1
        p_to = date.fromordinal(date_from.toordinal() - 1)
        p_from = date.fromordinal(p_to.toordinal() - span + 1)
        prev_range = (p_from, p_to)
        prev = _rows(await _sums(db, tenant_id, date_from=p_from, date_to=p_to, types=(AccountType.INCOME, AccountType.EXPENSE)))
    ids = {**{k: v for k, v in prev.items()}, **cur}                 # accounts seen in either period

    def section(kind: str) -> dict:
        out, tot, ptot = [], ZERO, ZERO
        for k, base in sorted(ids.items(), key=lambda kv: kv[1]["code"]):
            if base["type"] != kind:
                continue
            amt = cur.get(k, {}).get("amount", ZERO)
            pamt = prev.get(k, {}).get("amount", ZERO)
            if amt == 0 and pamt == 0:
                continue
            row = {"account_id": base["account_id"], "code": base["code"], "name": base["name"], "amount": str(amt)}
            if compare:
                row["previous"] = str(pamt)
            out.append(row)
            tot += amt
            ptot += pamt
        d = {"rows": out, "total": str(_q(tot))}
        if compare:
            d["previous_total"] = str(_q(ptot))
        return d

    inc, exp = section("income"), section("expense")
    res = {"currency": await led.base_currency(db, tenant_id), "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
           "income": inc, "expenses": exp, "net_profit": str(_q(Decimal(inc["total"]) - Decimal(exp["total"])))}
    if compare and prev_range:
        res["previous_from"], res["previous_to"] = prev_range[0].isoformat(), prev_range[1].isoformat()
        res["previous_net_profit"] = str(_q(Decimal(inc["previous_total"]) - Decimal(exp["previous_total"])))
    return res


# ───────────────────────── balance sheet ─────────────────────────
async def balance_sheet(db, tenant_id, as_of: date) -> dict:
    rows = _rows(await _sums(db, tenant_id, date_to=as_of))
    sec = {"asset": [], "liability": [], "equity": []}
    totals = {"asset": ZERO, "liability": ZERO, "equity": ZERO}
    income = expense = ZERO
    for r in rows.values():
        t = r["type"]
        if t == "income":
            income += r["amount"]
        elif t == "expense":
            expense += r["amount"]
        elif r["amount"] != 0:
            sec[t].append({"account_id": r["account_id"], "code": r["code"], "name": r["name"], "amount": str(r["amount"])})
            totals[t] += r["amount"]
    for t in sec:
        sec[t].sort(key=lambda x: x["code"])
    profit = _q(income - expense)                                    # not closed into equity yet
    equity_total = _q(totals["equity"] + profit)
    le = _q(totals["liability"] + equity_total)
    return {"currency": await led.base_currency(db, tenant_id), "as_of": as_of.isoformat(),
            "assets": {"rows": sec["asset"], "total": str(_q(totals["asset"]))},
            "liabilities": {"rows": sec["liability"], "total": str(_q(totals["liability"]))},
            "equity": {"rows": sec["equity"], "profit_to_date": str(profit), "total": str(equity_total)},
            "liabilities_and_equity": str(le), "balanced": _q(totals["asset"]) == le}


# ───────────────────────── trial balance (period-aware wrapper) ─────────────────────────
async def trial_balance(db, tenant_id, as_of: date | None) -> dict:
    return await led.trial_balance(db, tenant_id, as_of)


# ───────────────────────── aging ─────────────────────────
def _bucket(days_over: int) -> str:
    if days_over <= 0:
        return "current"
    return "d1_30" if days_over <= 30 else "d31_60" if days_over <= 60 else "d61_90" if days_over <= 90 else "d90_plus"


def _age(docs: list[tuple], today: date) -> dict:
    """docs: (party_id, party_name, number, due_date, base_balance)."""
    parties: dict[uuid.UUID, dict] = {}
    totals = {b: ZERO for b in BUCKETS}
    for pid, name, number, due, bal in docs:
        if bal <= 0:
            continue
        days = (today - due).days
        b = _bucket(days)
        p = parties.setdefault(pid, {"party_id": str(pid), "name": name, **{k: ZERO for k in BUCKETS}, "total": ZERO, "items": []})
        p[b] += bal
        p["total"] += bal
        totals[b] += bal
        p["items"].append({"number": number, "due_date": due.isoformat(), "days_overdue": max(days, 0), "bucket": b, "balance": str(bal)})
    rows = []
    for p in sorted(parties.values(), key=lambda x: -x["total"]):
        rows.append({**p, **{k: str(_q(p[k])) for k in (*BUCKETS, "total")}})
    grand = _q(sum(totals.values(), ZERO))
    return {"as_of": today.isoformat(), "rows": rows, "totals": {**{k: str(_q(v)) for k, v in totals.items()}, "total": str(grand)}}


async def receivables_aging(db, tenant_id, today: date | None = None) -> dict:
    today = today or date.today()
    rows = (await db.execute(select(FinInvoice, FinCustomer).join(FinCustomer, FinCustomer.id == FinInvoice.customer_id).where(
        FinInvoice.tenant_id == tenant_id, FinInvoice.is_deleted == False,  # noqa: E712
        FinInvoice.status.in_((InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID))))).all()
    docs = [(c.id, c.name, i.number, i.due_date, _q((i.total - i.amount_paid) * i.exchange_rate)) for i, c in rows]
    return {"currency": await led.base_currency(db, tenant_id), **_age(docs, today)}


async def payables_aging(db, tenant_id, today: date | None = None) -> dict:
    today = today or date.today()
    rows = (await db.execute(select(FinBill, FinVendor).join(FinVendor, FinVendor.id == FinBill.vendor_id).where(
        FinBill.tenant_id == tenant_id, FinBill.is_deleted == False,  # noqa: E712
        FinBill.status.in_((BillStatus.OPEN, BillStatus.PARTIALLY_PAID))))).all()
    docs = [(v.id, v.name, b.number, b.due_date, _q((b.total - b.amount_paid) * b.exchange_rate)) for b, v in rows]
    return {"currency": await led.base_currency(db, tenant_id), **_age(docs, today)}


# ───────────────────────── general ledger ─────────────────────────
async def general_ledger(db, tenant_id, account_id: uuid.UUID, date_from: date | None, date_to: date | None) -> dict:
    _check_range(date_from, date_to)
    acc = (await db.execute(select(FinAccount).where(FinAccount.id == account_id, FinAccount.tenant_id == tenant_id,
                                                      FinAccount.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if acc is None:
        raise NotFoundError("Account not found")
    opening = ZERO
    if date_from:
        dr, cr = (await db.execute(
            select(func.coalesce(func.sum(FinJournalLine.debit), 0), func.coalesce(func.sum(FinJournalLine.credit), 0))
            .join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
            .where(FinJournalLine.tenant_id == tenant_id, FinJournalLine.account_id == account_id,
                   FinJournalEntry.is_deleted == False, FinJournalEntry.entry_date < date_from))).one()  # noqa: E712
        opening = _signed(acc.type, Decimal(dr), Decimal(cr))
    q = (select(FinJournalLine, FinJournalEntry).join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
         .where(FinJournalLine.tenant_id == tenant_id, FinJournalLine.account_id == account_id,
                FinJournalEntry.is_deleted == False))  # noqa: E712
    if date_from:
        q = q.where(FinJournalEntry.entry_date >= date_from)
    if date_to:
        q = q.where(FinJournalEntry.entry_date <= date_to)
    fetched = (await db.execute(q.order_by(FinJournalEntry.entry_date, FinJournalEntry.number, FinJournalLine.created_at)
                                .limit(GL_MAX_ROWS + 1))).all()
    truncated = len(fetched) > GL_MAX_ROWS
    run, tot_dr, tot_cr, lines = opening, ZERO, ZERO, []
    for ln, e in fetched[:GL_MAX_ROWS]:
        run += _signed(acc.type, ln.debit, ln.credit)
        tot_dr += ln.debit
        tot_cr += ln.credit
        lines.append({"date": e.entry_date.isoformat(), "number": e.number, "entry_id": str(e.id), "memo": e.memo,
                      "reference": e.reference, "description": ln.description, "debit": str(ln.debit), "credit": str(ln.credit),
                      "balance": str(_q(run))})
    return {"currency": await led.base_currency(db, tenant_id),
            "account": {"id": str(acc.id), "code": acc.code, "name": acc.name, "type": acc.type.value},
            "date_from": date_from.isoformat() if date_from else None, "date_to": date_to.isoformat() if date_to else None,
            "opening_balance": str(_q(opening)), "lines": lines, "total_debit": str(_q(tot_dr)), "total_credit": str(_q(tot_cr)),
            "closing_balance": str(_q(run)), "truncated": truncated}


# ───────────────────────── export ─────────────────────────
def _safe(v):
    """Stop spreadsheet formula injection: text that starts with = + - @ is stored as text, not as a formula."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _num(v):
    return Decimal(v) if isinstance(v, str) else v


def to_table(report: str, d: dict) -> tuple[str, list[list]]:
    """Flatten a report into (title, rows). Numbers are Decimal, text is str."""
    cur = d.get("currency", "")
    if report == "profit-loss":
        cmp = "previous_net_profit" in d
        head = ["Code", "Account", "Amount"] + (["Previous"] if cmp else [])
        rows: list[list] = [[f"Profit & Loss  {d['date_from']} to {d['date_to']}  ({cur})"], head]
        for title, sec in (("Income", d["income"]), ("Expenses", d["expenses"])):
            rows.append([title])
            for r in sec["rows"]:
                rows.append([r["code"], r["name"], _num(r["amount"])] + ([_num(r["previous"])] if cmp else []))
            rows.append(["", f"Total {title.lower()}", _num(sec["total"])] + ([_num(sec["previous_total"])] if cmp else []))
        rows.append(["", "Net profit", _num(d["net_profit"])] + ([_num(d["previous_net_profit"])] if cmp else []))
        return "Profit and Loss", rows
    if report == "balance-sheet":
        rows = [[f"Balance Sheet as of {d['as_of']}  ({cur})"], ["Code", "Account", "Amount"]]
        for title, sec in (("Assets", d["assets"]), ("Liabilities", d["liabilities"]), ("Equity", d["equity"])):
            rows.append([title])
            rows += [[r["code"], r["name"], _num(r["amount"])] for r in sec["rows"]]
            if title == "Equity":
                rows.append(["", "Profit to date (not yet closed)", _num(sec["profit_to_date"])])
            rows.append(["", f"Total {title.lower()}", _num(sec["total"])])
        rows.append(["", "Total liabilities and equity", _num(d["liabilities_and_equity"])])
        return "Balance Sheet", rows
    if report == "trial-balance":
        rows = [[f"Trial Balance" + (f" as of {d['as_of']}" if d.get("as_of") else "")], ["Code", "Account", "Type", "Debit", "Credit"]]
        rows += [[r["code"], r["name"], r["type"], _num(r["debit"]), _num(r["credit"])] for r in d["accounts"]]
        rows.append(["", "Total", "", _num(d["total_debit"]), _num(d["total_credit"])])
        return "Trial Balance", rows
    if report in ("receivables-aging", "payables-aging"):
        who = "Customer" if report == "receivables-aging" else "Vendor"
        rows = [[f"{'Receivables' if who == 'Customer' else 'Payables'} aging as of {d['as_of']}  ({cur})"],
                [who, "Current", "1-30", "31-60", "61-90", "90+", "Total"]]
        rows += [[r["name"], *[_num(r[k]) for k in BUCKETS], _num(r["total"])] for r in d["rows"]]
        t = d["totals"]
        rows.append(["Total", *[_num(t[k]) for k in BUCKETS], _num(t["total"])])
        return ("Receivables Aging" if who == "Customer" else "Payables Aging"), rows
    if report == "general-ledger":
        a = d["account"]
        rows = [[f"General ledger  {a['code']} {a['name']}  ({cur})"], ["Date", "Entry", "Memo", "Reference", "Debit", "Credit", "Balance"],
                ["", "", "Opening balance", "", "", "", _num(d["opening_balance"])]]
        rows += [[r["date"], r["number"], r["memo"] or r["description"] or "", r["reference"] or "", _num(r["debit"]), _num(r["credit"]), _num(r["balance"])] for r in d["lines"]]
        rows.append(["", "", "Closing balance", "", _num(d["total_debit"]), _num(d["total_credit"]), _num(d["closing_balance"])])
        return "General Ledger", rows
    if report == "taxes":
        rows = [[f"Tax report  {d['date_from']} to {d['date_to']}  ({cur})"], ["", "Rate", "Percent", "Taxable amount", "Tax", "Documents"]]
        for title, sec in (("Sales (output tax, invoices)", d["sales"]), ("Purchases (input tax, bills)", d["purchases"])):
            rows.append([title])
            rows += [["", r["name"], r["percent"], _num(r["taxable"]), _num(r["tax"]), r["documents"]] for r in sec["rows"]]
            rows.append(["", "Total", "", _num(sec["taxable"]), _num(sec["tax"]), ""])
        rows.append(["", "Net tax payable (output - input)", "", "", _num(d["net_tax_payable"]), ""])
        return "Tax Report", rows
    raise UnprocessableError("Unknown report")


def render(report: str, d: dict, fmt: str) -> tuple[bytes, str, str]:
    title, rows = to_table(report, d)
    stamp = f"{report}"
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        for r in rows:
            w.writerow([_safe(c) if isinstance(c, str) else (str(c) if c is not None else "") for c in r])
        return ("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"{stamp}.csv"
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    for i, r in enumerate(rows, start=1):
        for j, c in enumerate(r, start=1):
            cell = ws.cell(row=i, column=j, value=_safe(c) if isinstance(c, str) else (float(c) if isinstance(c, Decimal) else c))
            if isinstance(c, Decimal):
                cell.number_format = "#,##0.00;[Red]-#,##0.00"
            if i <= 2 or (len(r) == 1) or (isinstance(r[1] if len(r) > 1 else None, str) and str(r[1]).startswith(("Total", "Net profit", "Closing"))):
                cell.font = Font(bold=True)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(max((len(str(c.value)) for c in col if c.value is not None), default=8) + 2, 50)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{stamp}.xlsx"
