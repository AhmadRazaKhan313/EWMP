"""
Double-entry ledger service (finance Phase 0).

Rules enforced here, not in the routes:
  * an entry has at least two lines and total debits == total credits (base currency)
  * every account belongs to the tenant, is active, and is not soft-deleted
  * amounts are positive and quantized to 2 decimals
  * posted entries are never edited — a void creates a mirror-image reversal entry
"""
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.finance import (
    AccountType, EntryStatus, FinAccount, FinExchangeRate, FinJournalEntry, FinJournalLine,
)
from app.models.organization import Organization

CENT = Decimal("0.01")

# (code, name, type, parent_code)
DEFAULT_CHART: list[tuple[str, str, AccountType, str | None]] = [
    ("1000", "Assets", AccountType.ASSET, None),
    ("1010", "Cash", AccountType.ASSET, "1000"),
    ("1020", "Bank", AccountType.ASSET, "1000"),
    ("1030", "Mobile Wallet", AccountType.ASSET, "1000"),
    ("1100", "Accounts Receivable", AccountType.ASSET, "1000"),
    ("1500", "Fixed Assets", AccountType.ASSET, "1000"),
    ("2000", "Liabilities", AccountType.LIABILITY, None),
    ("2010", "Accounts Payable", AccountType.LIABILITY, "2000"),
    ("2100", "Loans", AccountType.LIABILITY, "2000"),
    ("3000", "Equity", AccountType.EQUITY, None),
    ("3010", "Founders Capital", AccountType.EQUITY, "3000"),
    ("3900", "Retained Earnings", AccountType.EQUITY, "3000"),
    ("4000", "Income", AccountType.INCOME, None),
    ("4010", "Client Payments", AccountType.INCOME, "4000"),
    ("4020", "Upwork Income", AccountType.INCOME, "4000"),
    ("4900", "Other Income", AccountType.INCOME, "4000"),
    ("5000", "Expenses", AccountType.EXPENSE, None),
    ("5010", "Salary", AccountType.EXPENSE, "5000"),
    ("5020", "Utilities", AccountType.EXPENSE, "5000"),
    ("5030", "Subscriptions", AccountType.EXPENSE, "5000"),
    ("5040", "Upwork Connects", AccountType.EXPENSE, "5000"),
    ("5050", "Grocery", AccountType.EXPENSE, "5000"),
    ("5060", "Gadgets", AccountType.EXPENSE, "5000"),
    ("5070", "Gifts", AccountType.EXPENSE, "5000"),
    ("5900", "Other Expenses", AccountType.EXPENSE, "5000"),
]


@dataclass
class LineIn:
    account_id: uuid.UUID
    side: str  # "debit" | "credit"
    amount: Decimal  # in `currency`
    currency: str | None = None  # default: org base currency
    rate: Decimal | None = None  # base units per 1 unit of currency; looked up if omitted
    description: str | None = None


def _q(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


async def base_currency(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    cur = (await db.execute(select(Organization.currency).where(Organization.id == tenant_id))).scalar_one_or_none()
    if cur is None:
        raise NotFoundError("Organization not found")
    return cur.upper()


async def ensure_chart(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Seed the default chart of accounts. Idempotent: only missing codes are added."""
    existing = {
        a.code: a for a in (await db.execute(
            select(FinAccount).where(FinAccount.tenant_id == tenant_id)
        )).scalars().all()
    }
    created = 0
    for code, name, typ, parent_code in DEFAULT_CHART:
        if code in existing:
            continue
        parent = existing.get(parent_code) if parent_code else None
        acc = FinAccount(tenant_id=tenant_id, code=code, name=name, type=typ,
                         parent_id=parent.id if parent else None, is_system=True)
        db.add(acc)
        await db.flush()
        existing[code] = acc
        created += 1
    return created


async def _next_number(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    # Serialize numbering per tenant for the rest of this transaction.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"fin-entry-{tenant_id}"})
    last = (await db.execute(
        select(func.max(FinJournalEntry.number)).where(FinJournalEntry.tenant_id == tenant_id)
    )).scalar()
    n = int(last.split("-")[1]) + 1 if last else 1
    return f"JE-{n:06d}"


async def _rate_for(db: AsyncSession, tenant_id: uuid.UUID, currency: str, on: date) -> Decimal:
    row = (await db.execute(
        select(FinExchangeRate.rate)
        .where(FinExchangeRate.tenant_id == tenant_id, FinExchangeRate.currency == currency,
               FinExchangeRate.on_date <= on, FinExchangeRate.is_deleted == False)  # noqa: E712
        .order_by(FinExchangeRate.on_date.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise UnprocessableError(f"No exchange rate for {currency} on or before {on}. Add one or pass a rate.")
    return Decimal(row)


async def post_entry(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    entry_date: date,
    lines: list[LineIn],
    memo: str | None = None,
    reference: str | None = None,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> FinJournalEntry:
    if len(lines) < 2:
        raise UnprocessableError("A journal entry needs at least two lines")

    base = await base_currency(db, tenant_id)
    ids = {ln.account_id for ln in lines}
    accounts = {
        a.id: a for a in (await db.execute(
            select(FinAccount).where(FinAccount.tenant_id == tenant_id, FinAccount.id.in_(ids),
                                     FinAccount.is_deleted == False)  # noqa: E712
        )).scalars().all()
    }
    prepared: list[dict] = []
    total_dr = total_cr = Decimal("0")
    for i, ln in enumerate(lines, start=1):
        acc = accounts.get(ln.account_id)
        if acc is None:
            raise UnprocessableError(f"Line {i}: account not found")
        if not acc.is_active:
            raise UnprocessableError(f"Line {i}: account {acc.code} is inactive")
        if ln.side not in ("debit", "credit"):
            raise UnprocessableError(f"Line {i}: side must be 'debit' or 'credit'")
        amount = _q(ln.amount)
        if amount <= 0:
            raise UnprocessableError(f"Line {i}: amount must be greater than zero")
        cur = (ln.currency or base).upper()
        if cur == base:
            rate = Decimal("1")
        elif ln.rate is not None:
            rate = Decimal(ln.rate)
            if rate <= 0:
                raise UnprocessableError(f"Line {i}: rate must be greater than zero")
        else:
            rate = await _rate_for(db, tenant_id, cur, entry_date)
        base_amt = _q(amount * rate)
        if base_amt <= 0:
            raise UnprocessableError(f"Line {i}: amount is too small after conversion")
        dr, cr = (base_amt, Decimal("0")) if ln.side == "debit" else (Decimal("0"), base_amt)
        total_dr += dr
        total_cr += cr
        prepared.append(dict(account_id=acc.id, debit=dr, credit=cr, currency=cur, amount_original=amount,
                             exchange_rate=rate, description=ln.description, line_no=i))

    if total_dr != total_cr:
        raise UnprocessableError(f"Entry is not balanced: debits {total_dr} != credits {total_cr}")

    entry = FinJournalEntry(
        tenant_id=tenant_id, number=await _next_number(db, tenant_id), entry_date=entry_date, memo=memo,
        reference=reference, source_type=source_type, source_id=source_id, base_currency=base,
        status=EntryStatus.POSTED, created_by=created_by,
    )
    db.add(entry)
    await db.flush()
    for p in prepared:
        db.add(FinJournalLine(tenant_id=tenant_id, entry_id=entry.id, **p))
    await db.flush()
    return entry


async def get_entry(db: AsyncSession, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> tuple[FinJournalEntry, list[FinJournalLine]]:
    entry = (await db.execute(
        select(FinJournalEntry).where(FinJournalEntry.id == entry_id, FinJournalEntry.tenant_id == tenant_id,
                                      FinJournalEntry.is_deleted == False)  # noqa: E712
    )).scalar_one_or_none()
    if entry is None:
        raise NotFoundError("Journal entry not found")
    lines = (await db.execute(
        select(FinJournalLine).where(FinJournalLine.entry_id == entry.id, FinJournalLine.tenant_id == tenant_id)
        .order_by(FinJournalLine.line_no)
    )).scalars().all()
    return entry, list(lines)


async def void_entry(
    db: AsyncSession, tenant_id: uuid.UUID, entry_id: uuid.UUID, *,
    reason: str | None = None, on: date | None = None, created_by: uuid.UUID | None = None,
) -> FinJournalEntry:
    entry, lines = await get_entry(db, tenant_id, entry_id)
    if entry.status != EntryStatus.POSTED or entry.reverses_id is not None:
        raise UnprocessableError("Only a posted, original entry can be voided")

    rev = FinJournalEntry(
        tenant_id=tenant_id, number=await _next_number(db, tenant_id), entry_date=on or entry.entry_date,
        memo=f"Reversal of {entry.number}" + (f": {reason}" if reason else ""), reference=entry.number,
        source_type=entry.source_type, source_id=entry.source_id, base_currency=entry.base_currency,
        status=EntryStatus.POSTED, reverses_id=entry.id, created_by=created_by,
    )
    db.add(rev)
    await db.flush()
    for ln in lines:
        db.add(FinJournalLine(
            tenant_id=tenant_id, entry_id=rev.id, account_id=ln.account_id, debit=ln.credit, credit=ln.debit,
            currency=ln.currency, amount_original=ln.amount_original, exchange_rate=ln.exchange_rate,
            description=ln.description, line_no=ln.line_no,
        ))
    entry.status = EntryStatus.REVERSED
    entry.reversed_by_id = rev.id
    await db.flush()
    return rev


async def trial_balance(db: AsyncSession, tenant_id: uuid.UUID, as_of: date | None = None) -> dict:
    sums = (
        select(FinJournalLine.account_id.label("account_id"),
               func.sum(FinJournalLine.debit).label("dr"), func.sum(FinJournalLine.credit).label("cr"))
        .join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
        .where(FinJournalLine.tenant_id == tenant_id, FinJournalEntry.tenant_id == tenant_id,
               FinJournalEntry.is_deleted == False)  # noqa: E712
    )
    if as_of is not None:
        sums = sums.where(FinJournalEntry.entry_date <= as_of)
    sums = sums.group_by(FinJournalLine.account_id).subquery()
    stmt = (
        select(FinAccount.id, FinAccount.code, FinAccount.name, FinAccount.type,
               func.coalesce(sums.c.dr, 0), func.coalesce(sums.c.cr, 0))
        .outerjoin(sums, sums.c.account_id == FinAccount.id)
        .where(FinAccount.tenant_id == tenant_id, FinAccount.is_deleted == False)  # noqa: E712
        .order_by(FinAccount.code)
    )
    rows = (await db.execute(stmt)).all()
    out, tot_dr, tot_cr = [], Decimal("0"), Decimal("0")
    for acc_id, code, name, typ, dr, cr in rows:
        dr, cr = Decimal(dr), Decimal(cr)
        tot_dr += dr
        tot_cr += cr
        out.append({"account_id": str(acc_id), "code": code, "name": name, "type": typ.value,
                    "debit": str(dr), "credit": str(cr), "balance": str(dr - cr)})
    return {"accounts": out, "total_debit": str(tot_dr), "total_credit": str(tot_cr),
            "balanced": tot_dr == tot_cr, "as_of": as_of.isoformat() if as_of else None}
