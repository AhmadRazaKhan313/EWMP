"""Finance Budget: weekly / monthly / yearly plan against what the ledger actually shows.

Periods
  week  = Monday..Sunday          month = calendar month          year = financial year, 1 July..30 June
Actual comes from posted ledger lines (base currency); a voided entry nets to zero through its reversal.
A category's actual is the accounts whose name matches it (case and a trailing "s" ignored, plus a few aliases).
Anything that matches no category falls into "Other" (income) or "All Expenses" (expense).
"""
import calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select

from app.core.exceptions import UnprocessableError
from app.models.finance import AccountType, FinAccount, FinJournalEntry, FinJournalLine
from app.models.finance_budget import FinBudgetOpening, FinBudgetPlan
from app.services import finance_reports as rep

PERIODS = ("week", "month", "year")
EXPENSE_CATEGORIES = ("Grocery", "Gifts", "Health/medical", "Upwork", "Founders Withdrawal", "All Expenses", "Assets",
                      "Utilities", "Travel", "Debt", "Subscriptions", "Gadgets", "Loan Paid", "Salary")
INCOME_CATEGORIES = ("Founders Investment", "Upwork", "Bonus", "Client Payment", "Other", "Loan")
EXPENSE_CATCH_ALL = "All Expenses"
INCOME_CATCH_ALL = "Other"
MAX_AMOUNT = Decimal("999999999999.99")
ZERO = Decimal("0")


def _q(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"))


def _norm(name: str) -> str:
    n = " ".join(name.casefold().split())
    return n[:-1] if n.endswith("s") else n


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def period_bounds(period: str, anchor: date) -> tuple[date, date, str]:
    """(start, end, label) of the week / month / financial year that contains `anchor`."""
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
        return start, end, f"{start:%d %b} - {end:%d %b %Y}"
    if period == "month":
        start = date(anchor.year, anchor.month, 1)
        return start, _month_end(start), f"{start:%B %Y}"
    if period == "year":
        y = anchor.year if anchor.month >= 7 else anchor.year - 1
        return date(y, 7, 1), date(y + 1, 6, 30), f"{y}-{str(y + 1)[2:]}"
    raise UnprocessableError("period must be week, month or year")


# Chart names that belong to a category even though the words differ.
ALIASES = {
    "income": {"upwork income": "Upwork", "other income": "Other", "founders capital": "Founders Investment", "loans": "Loan"},
    "expense": {"upwork connects": "Upwork", "founders capital": "Founders Withdrawal", "loans": "Loan Paid", "fixed assets": "Assets"},
}


def _category(kind: str, account_name: str) -> str:
    cats = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES
    by_name = {_norm(c): c for c in cats}
    n = _norm(account_name)
    alias = {_norm(k): v for k, v in ALIASES[kind].items()}
    return by_name.get(n) or alias.get(n) or (INCOME_CATCH_ALL if kind == "income" else EXPENSE_CATCH_ALL)


async def _actuals(db, tenant_id, start: date, end: date) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """(income by category, expense by category) for the dates, in base currency.

    Income / expense accounts count whatever posted to them (invoices and bills included). Money-in / money-out
    transactions that use an equity, liability or asset category (founders' capital, a loan, a purchased asset)
    count too, so the budget reads like a cash plan. Transfers never count.
    """
    out = {"income": {c: ZERO for c in INCOME_CATEGORIES}, "expense": {c: ZERO for c in EXPENSE_CATEGORIES}}
    for acc, dr, cr in await rep._sums(db, tenant_id, date_from=start, date_to=end, types=(AccountType.INCOME, AccountType.EXPENSE)):
        kind = "income" if acc.type == AccountType.INCOME else "expense"
        out[kind][_category(kind, acc.name)] += rep._signed(acc.type, Decimal(dr), Decimal(cr))
    q = (select(FinAccount, FinJournalEntry.source_type, func.coalesce(func.sum(FinJournalLine.debit), 0), func.coalesce(func.sum(FinJournalLine.credit), 0))
         .join(FinJournalLine, FinJournalLine.account_id == FinAccount.id)
         .join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
         .where(FinAccount.tenant_id == tenant_id, FinAccount.is_deleted == False,  # noqa: E712
                FinAccount.type.in_((AccountType.EQUITY, AccountType.LIABILITY, AccountType.ASSET)),
                FinAccount.money_kind.is_(None),
                FinJournalLine.tenant_id == tenant_id, FinJournalEntry.tenant_id == tenant_id, FinJournalEntry.is_deleted == False,  # noqa: E712
                FinJournalEntry.entry_date >= start, FinJournalEntry.entry_date <= end,
                FinJournalEntry.source_type.in_(("txn:income", "txn:expense")))
         .group_by(FinAccount.id, FinJournalEntry.source_type))
    for acc, source, dr, cr in (await db.execute(q)).all():
        if source == "txn:income":
            out["income"][_category("income", acc.name)] += _q(Decimal(cr) - Decimal(dr))
        else:
            out["expense"][_category("expense", acc.name)] += _q(Decimal(dr) - Decimal(cr))
    return out["income"], out["expense"]


async def _ledger_money(db, tenant_id, before: date) -> Decimal:
    """Cash + bank + wallet balance from the ledger on the morning of `before`."""
    q = (select(func.coalesce(func.sum(FinJournalLine.debit - FinJournalLine.credit), 0))
         .join(FinAccount, FinAccount.id == FinJournalLine.account_id)
         .join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
         .where(FinAccount.tenant_id == tenant_id, FinAccount.is_deleted == False,  # noqa: E712
                FinAccount.type == AccountType.ASSET, FinAccount.money_kind.is_not(None),
                FinJournalLine.tenant_id == tenant_id, FinJournalEntry.tenant_id == tenant_id,
                FinJournalEntry.is_deleted == False, FinJournalEntry.entry_date < before))  # noqa: E712
    return _q((await db.execute(q)).scalar_one())


async def _plans(db, tenant_id, period: str, start: date) -> dict[tuple[str, str], Decimal]:
    q = select(FinBudgetPlan).where(FinBudgetPlan.tenant_id == tenant_id, FinBudgetPlan.is_deleted == False,  # noqa: E712
                                    FinBudgetPlan.period_type == period, FinBudgetPlan.period_start == start)
    return {(p.kind, p.category): _q(p.planned) for p in (await db.execute(q)).scalars().all()}


async def _opening_row(db, tenant_id, period: str, start: date) -> FinBudgetOpening | None:
    q = select(FinBudgetOpening).where(FinBudgetOpening.tenant_id == tenant_id, FinBudgetOpening.is_deleted == False,  # noqa: E712
                                       FinBudgetOpening.period_type == period, FinBudgetOpening.period_start == start)
    return (await db.execute(q)).scalars().first()


def _section(kind: str, names: tuple[str, ...], planned: dict, actual: dict[str, Decimal]) -> dict:
    rows, tp, ta = [], ZERO, ZERO
    for name in names:
        p, a = _q(planned.get((kind, name), ZERO)), _q(actual.get(name, ZERO))
        rows.append({"category": name, "planned": str(p), "actual": str(a),
                     "diff": str(_q(p - a) if kind == "expense" else _q(a - p))})   # expense: left to spend; income: ahead of plan
        tp, ta = tp + p, ta + a
    return {"planned": str(_q(tp)), "actual": str(_q(ta)), "diff": str(_q(tp - ta) if kind == "expense" else _q(ta - tp)), "rows": rows}


async def get_budget(db, tenant_id: uuid.UUID, period: str, anchor: date) -> dict:
    start, end, label = period_bounds(period, anchor)
    income, expense = await _actuals(db, tenant_id, start, end)
    plans = await _plans(db, tenant_id, period, start)
    opening = await _opening_row(db, tenant_id, period, start)
    manual = opening is not None
    starting = _q(opening.starting_balance) if manual else await _ledger_money(db, tenant_id, start)
    saved = _q(sum(income.values(), ZERO) - sum(expense.values(), ZERO))
    return {"period": period, "start": start.isoformat(), "end": end.isoformat(), "label": label,
            "starting_balance": str(starting), "starting_balance_manual": manual,
            "end_balance": str(_q(starting + saved)), "saved": str(saved),
            "expenses": _section("expense", EXPENSE_CATEGORIES, plans, expense),
            "income": _section("income", INCOME_CATEGORIES, plans, income)}


def _amount(value, *, allow_negative: bool) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise UnprocessableError("Enter a valid amount")
    if not d.is_finite():
        raise UnprocessableError("Enter a valid amount")
    if (d < 0 and not allow_negative) or abs(d) > MAX_AMOUNT:
        raise UnprocessableError("Amount is out of range")
    return _q(d)


async def set_plan(db, tenant_id: uuid.UUID, period: str, anchor: date, kind: str, category: str, planned) -> dict:
    start, _, _ = period_bounds(period, anchor)
    names = EXPENSE_CATEGORIES if kind == "expense" else INCOME_CATEGORIES if kind == "income" else None
    if names is None:
        raise UnprocessableError("kind must be income or expense")
    if category not in names:
        raise UnprocessableError(f"Unknown {kind} category")
    value = _amount(planned, allow_negative=False)
    q = select(FinBudgetPlan).where(FinBudgetPlan.tenant_id == tenant_id, FinBudgetPlan.period_type == period,
                                    FinBudgetPlan.period_start == start, FinBudgetPlan.kind == kind, FinBudgetPlan.category == category)
    row = (await db.execute(q)).scalars().first()
    if row is None:
        db.add(FinBudgetPlan(tenant_id=tenant_id, period_type=period, period_start=start, kind=kind, category=category, planned=value))
    else:
        row.planned, row.is_deleted, row.deleted_at = value, False, None
    await db.flush()
    return await get_budget(db, tenant_id, period, anchor)


async def set_opening(db, tenant_id: uuid.UUID, period: str, anchor: date, starting_balance) -> dict:
    """A number sets the starting balance by hand; None goes back to the ledger figure."""
    start, _, _ = period_bounds(period, anchor)
    q = select(FinBudgetOpening).where(FinBudgetOpening.tenant_id == tenant_id, FinBudgetOpening.period_type == period,
                                       FinBudgetOpening.period_start == start)
    row = (await db.execute(q)).scalars().first()
    if starting_balance is None:
        if row is not None and not row.is_deleted:
            row.is_deleted = True
            row.deleted_at = datetime.now(timezone.utc)
    else:
        value = _amount(starting_balance, allow_negative=True)
        if row is None:
            db.add(FinBudgetOpening(tenant_id=tenant_id, period_type=period, period_start=start, starting_balance=value))
        else:
            row.starting_balance, row.is_deleted, row.deleted_at = value, False, None
    await db.flush()
    return await get_budget(db, tenant_id, period, anchor)
