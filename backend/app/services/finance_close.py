"""Finance Phase 6: month / year close (a period lock) and opening balances.

A close does not move any money. It records "books are closed through DATE"; finance_ledger.post_entry and void_entry
refuse any entry dated on or before the latest close, so every module (invoices, bills, payments, banking, recurring)
is covered. Reopening removes the latest close only, so closes always form one unbroken chain.
Year close is lock-only (no closing entry), so profit & loss for past years keeps reading straight from the ledger.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.finance import AccountType, EntryStatus, FinAccount, FinJournalEntry
from app.models.finance_banking import FinBankLine
from app.models.finance_close import FinPeriodClose
from app.models.finance_purchases import BillStatus, FinBill
from app.models.finance_sales import FinInvoice, InvoiceStatus
from app.services import finance_ledger as led
from app.services.finance_budget import period_bounds
from app.services.finance_reports import _sums, _signed

ZERO = Decimal("0")
OPENING = "opening_balance"
OPENING_CODE = "3020"
CREDIT_NORMAL = (AccountType.LIABILITY, AccountType.EQUITY, AccountType.INCOME)


def _q(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"))


def _row(c: FinPeriodClose) -> dict:
    return {"id": str(c.id), "period_type": c.period_type, "period_start": c.period_start.isoformat(),
            "period_end": c.period_end.isoformat(), "net_profit": str(c.net_profit), "note": c.note,
            "closed_at": c.created_at.isoformat() if c.created_at else None}


async def _active(db, tenant_id) -> list[FinPeriodClose]:
    return list((await db.execute(
        select(FinPeriodClose).where(FinPeriodClose.tenant_id == tenant_id, FinPeriodClose.is_deleted == False)  # noqa: E712
        .order_by(FinPeriodClose.period_end.desc()))).scalars().all())


async def status(db, tenant_id: uuid.UUID, today: date | None = None) -> dict:
    today = today or date.today()
    closes = await _active(db, tenant_id)
    locked = closes[0].period_end if closes else None
    # Suggest the next period that has already ended.
    nxt = (locked + timedelta(days=1)) if locked else None
    if nxt is None:
        first = (await db.execute(select(func.min(FinJournalEntry.entry_date)).where(
            FinJournalEntry.tenant_id == tenant_id, FinJournalEntry.is_deleted == False))).scalar_one_or_none()  # noqa: E712
        nxt = first
    suggested = None
    if nxt is not None:
        s, e, label = period_bounds("month", nxt)
        if e < today:
            suggested = {"period_type": "month", "period_start": s.isoformat(), "period_end": e.isoformat(), "label": label}
    return {"locked_through": locked.isoformat() if locked else None, "closes": [_row(c) for c in closes], "suggested": suggested}


async def preview(db, tenant_id: uuid.UUID, period_type: str, anchor: date, today: date | None = None) -> dict:
    if period_type not in ("month", "year"):
        raise UnprocessableError("period_type must be month or year")
    today = today or date.today()
    start, end, label = period_bounds(period_type, anchor)
    locked = await led.locked_through(db, tenant_id)
    blockers: list[str] = []
    warnings: list[str] = []
    if locked is not None and end <= locked:
        blockers.append(f"Books are already closed through {locked.isoformat()}.")
    elif locked is not None and start > locked + timedelta(days=1):
        blockers.append(f"Close the period starting {(locked + timedelta(days=1)).isoformat()} first.")
    if end >= today:
        blockers.append(f"{label} has not ended yet.")

    sums = await _sums(db, tenant_id, date_from=start, date_to=end, types=(AccountType.INCOME, AccountType.EXPENSE))
    income = sum((_signed(a.type, dr, cr) for a, dr, cr in sums if a.type == AccountType.INCOME), ZERO)
    expense = sum((_signed(a.type, dr, cr) for a, dr, cr in sums if a.type == AccountType.EXPENSE), ZERO)

    async def count(model, *conds) -> int:
        return int((await db.execute(select(func.count()).select_from(model).where(
            model.tenant_id == tenant_id, model.is_deleted == False, *conds))).scalar_one())  # noqa: E712

    drafts_inv = await count(FinInvoice, FinInvoice.status == InvoiceStatus.DRAFT, FinInvoice.issue_date <= end)
    drafts_bill = await count(FinBill, FinBill.status == BillStatus.DRAFT, FinBill.issue_date <= end)
    pending = await count(FinBill, FinBill.approval_status == "pending", FinBill.issue_date <= end)
    unmatched = await count(FinBankLine, FinBankLine.status == "unmatched", FinBankLine.tx_date <= end)
    if drafts_inv:
        warnings.append(f"{drafts_inv} draft invoice(s) dated up to {end.isoformat()} are not in the books yet.")
    if drafts_bill:
        warnings.append(f"{drafts_bill} draft bill(s) dated up to {end.isoformat()} are not in the books yet.")
    if pending:
        warnings.append(f"{pending} bill(s) are still waiting for approval.")
    if unmatched:
        warnings.append(f"{unmatched} bank statement line(s) are not matched yet.")
    return {"period_type": period_type, "period_start": start.isoformat(), "period_end": end.isoformat(), "label": label,
            "income": str(_q(income)), "expenses": str(_q(expense)), "net_profit": str(_q(income - expense)),
            "draft_invoices": drafts_inv, "draft_bills": drafts_bill, "pending_approval": pending, "unmatched_bank_lines": unmatched,
            "blockers": blockers, "warnings": warnings, "can_close": not blockers}


async def close_period(db, tenant_id: uuid.UUID, period_type: str, anchor: date, *, note: str | None = None,
                       created_by: uuid.UUID | None = None, today: date | None = None) -> dict:
    p = await preview(db, tenant_id, period_type, anchor, today)
    if not p["can_close"]:
        raise UnprocessableError(p["blockers"][0])
    row = FinPeriodClose(tenant_id=tenant_id, period_type=period_type, period_start=date.fromisoformat(p["period_start"]),
                         period_end=date.fromisoformat(p["period_end"]), net_profit=Decimal(p["net_profit"]),
                         note=(note or "").strip() or None, closed_by=created_by)
    db.add(row)
    await db.flush()
    return _row(row)


async def reopen_latest(db, tenant_id: uuid.UUID) -> dict:
    closes = await _active(db, tenant_id)
    if not closes:
        raise NotFoundError("Nothing is closed")
    c = closes[0]
    c.is_deleted = True
    c.deleted_at = func.now()
    await db.flush()
    return _row(c)


# ── Opening balances ─────────────────────────────────────────────────────────

async def _opening_entry(db, tenant_id):
    return (await db.execute(
        select(FinJournalEntry).where(
            FinJournalEntry.tenant_id == tenant_id, FinJournalEntry.is_deleted == False,  # noqa: E712
            FinJournalEntry.source_type == OPENING, FinJournalEntry.status == EntryStatus.POSTED,
            FinJournalEntry.reverses_id.is_(None)).order_by(FinJournalEntry.created_at.desc()).limit(1))).scalar_one_or_none()


async def _equity_account(db, tenant_id) -> FinAccount:
    acc = (await db.execute(select(FinAccount).where(
        FinAccount.tenant_id == tenant_id, FinAccount.code == OPENING_CODE, FinAccount.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if acc is None:
        parent = (await db.execute(select(FinAccount).where(
            FinAccount.tenant_id == tenant_id, FinAccount.code == "3000", FinAccount.is_deleted == False))).scalar_one_or_none()  # noqa: E712
        acc = FinAccount(tenant_id=tenant_id, code=OPENING_CODE, name="Opening Balance Equity", type=AccountType.EQUITY,
                         parent_id=parent.id if parent else None, is_system=True)
        db.add(acc)
        await db.flush()
    return acc


async def get_opening(db, tenant_id: uuid.UUID) -> dict:
    entry = await _opening_entry(db, tenant_id)
    if entry is None:
        return {"as_of": None, "entry_number": None, "items": [], "balancing": "0.00"}
    _, lines = await led.get_entry(db, tenant_id, entry.id)
    accs = {a.id: a for a in (await db.execute(select(FinAccount).where(
        FinAccount.tenant_id == tenant_id, FinAccount.id.in_([ln.account_id for ln in lines])))).scalars().all()}
    items, plug = [], ZERO
    for ln in lines:
        a = accs[ln.account_id]
        if a.code == OPENING_CODE:
            plug = _q(ln.credit - ln.debit)
            continue
        amt = _q(ln.credit - ln.debit) if a.type in CREDIT_NORMAL else _q(ln.debit - ln.credit)
        items.append({"account_id": str(a.id), "code": a.code, "name": a.name, "type": a.type.value, "amount": str(amt)})
    return {"as_of": entry.entry_date.isoformat(), "entry_number": entry.number, "items": items, "balancing": str(plug)}


async def set_opening(db, tenant_id: uuid.UUID, *, as_of: date, items: list[tuple[uuid.UUID, Decimal]],
                      created_by: uuid.UUID | None = None) -> dict:
    """Replace the opening-balance entry. `amount` is the balance on the account's normal side (a negative amount flips it)."""
    seen: set[uuid.UUID] = set()
    for aid, _ in items:
        if aid in seen:
            raise UnprocessableError("Each account can appear only once")
        seen.add(aid)
    eq = await _equity_account(db, tenant_id)
    accs = {a.id: a for a in (await db.execute(select(FinAccount).where(
        FinAccount.tenant_id == tenant_id, FinAccount.id.in_(seen), FinAccount.is_deleted == False))).scalars().all()}  # noqa: E712
    lines: list[led.LineIn] = []
    debit = credit = ZERO
    for aid, amount in items:
        a = accs.get(aid)
        if a is None:
            raise UnprocessableError("Account not found")
        if a.id == eq.id:
            raise UnprocessableError("Opening Balance Equity is calculated for you; leave it out")
        amt = _q(amount)
        if amt == 0:
            continue
        side = ("credit" if a.type in CREDIT_NORMAL else "debit")
        if amt < 0:
            side = "debit" if side == "credit" else "credit"
        lines.append(led.LineIn(account_id=a.id, side=side, amount=abs(amt)))
        if side == "debit":
            debit += abs(amt)
        else:
            credit += abs(amt)
    if not lines:
        raise UnprocessableError("Enter at least one account balance")
    diff = _q(debit - credit)
    if diff != 0:
        lines.append(led.LineIn(account_id=eq.id, side="credit" if diff > 0 else "debit", amount=abs(diff)))

    old = await _opening_entry(db, tenant_id)
    if old is not None:
        await led.void_entry(db, tenant_id, old.id, reason="Opening balances replaced", created_by=created_by)
    await led.post_entry(db, tenant_id, entry_date=as_of, lines=lines, memo="Opening balances", source_type=OPENING, created_by=created_by)
    return await get_opening(db, tenant_id)


async def clear_opening(db, tenant_id: uuid.UUID, created_by: uuid.UUID | None = None) -> dict:
    old = await _opening_entry(db, tenant_id)
    if old is None:
        raise NotFoundError("No opening balances entered")
    await led.void_entry(db, tenant_id, old.id, reason="Opening balances removed", created_by=created_by)
    return await get_opening(db, tenant_id)
