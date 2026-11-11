"""Finance Phase 5: bank / wallet statements, matching to the ledger, and reconciliation.

A statement line is money in (+) or money out (-) on one cash / bank / wallet account. It is matched to ONE
journal line on that same account: money in matches a debit of the same amount, money out matches a credit.
Voided entries (the original and its reversal) are never offered and never auto-matched.

Reconciliation: beginning balance + matched, not-yet-reconciled lines up to the statement date must equal the
statement balance. Beginning balance = the previous reconciliation's statement balance (or what you type the first time).
"""
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.finance import AccountType, EntryStatus, FinAccount, FinJournalEntry, FinJournalLine
from app.models.finance_banking import FinBankLine, FinBankReconciliation, FinBankStatement
from app.services import finance_transactions as txn

MAX_ROWS = 5000
AUTO_WINDOW_DAYS = 3
SUGGEST_WINDOW_DAYS = 10
ZERO = Decimal("0")

HEADERS = {
    "date": {"date", "transaction date", "txn date", "value date", "posting date", "tran date", "booking date"},
    "description": {"description", "details", "narration", "particulars", "remarks", "transaction details", "narrative", "memo"},
    "reference": {"reference", "ref", "ref no", "reference no", "cheque no", "chq no", "cheque", "transaction id", "tid", "trx id",
                  "txn id", "transaction no", "instrument no"},
    "debit": {"debit", "withdrawal", "withdrawals", "dr", "paid out", "money out", "debit amount", "withdrawal amount"},
    "credit": {"credit", "deposit", "deposits", "cr", "paid in", "money in", "credit amount", "deposit amount"},
    "amount": {"amount", "transaction amount", "net amount"},
    "balance": {"balance", "running balance", "closing balance", "available balance"},
}


def _q(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"))


def _s(v) -> str:
    return str(_q(v))


# ───────────────────────── import ─────────────────────────
def _map_header(rows: list[list]) -> tuple[int, dict[str, int]]:
    for i, row in enumerate(rows[:15]):
        found: dict[str, int] = {}
        for j, cell in enumerate(row):
            n = txn._norm(str(cell)) if cell is not None else ""
            for key, names in HEADERS.items():
                if n in names and key not in found:
                    found[key] = j
        if "date" in found and ({"amount"} <= found.keys() or "debit" in found or "credit" in found):
            return i, found
    raise UnprocessableError("Could not find the header row. Expected columns: Date, Description, Debit, Credit (or Amount), Balance")


def _cell(row: list, idx: int | None):
    return row[idx] if idx is not None and idx < len(row) else None


@dataclass
class ParsedLine:
    row_no: int
    tx_date: date
    description: str | None
    reference: str | None
    amount: Decimal
    balance: Decimal | None


def _parse(rows: list[list], date_order: str | None) -> tuple[list[ParsedLine], list[dict], str, bool]:
    head, cols = _map_header(rows)
    body = rows[head + 1:]
    if len(body) > MAX_ROWS:
        raise UnprocessableError(f"The file has more than {MAX_ROWS} rows. Split it and import in parts")
    detected = txn._detect_order([_cell(r, cols["date"]) for r in body])
    order = date_order or detected or "dmy"
    ambiguous = date_order is None and detected is None
    out: list[ParsedLine] = []
    skipped: list[dict] = []
    for k, row in enumerate(body):
        row_no = head + 2 + k
        if all(c is None or str(c).strip() == "" for c in row):
            continue
        try:
            raw_date = _cell(row, cols["date"])
            if raw_date is None or str(raw_date).strip() == "":
                raise ValueError("no date")
            d = txn._parse_date(raw_date, order)
            if "amount" in cols:
                amount = txn._parse_amount(_cell(row, cols["amount"]))
                if amount is None:
                    raise ValueError("no amount")
            else:
                dr = txn._parse_amount(_cell(row, cols.get("debit"))) or ZERO
                cr = txn._parse_amount(_cell(row, cols.get("credit"))) or ZERO
                amount = cr - dr
            amount = _q(amount)
            if amount == 0:
                raise ValueError("amount is zero")
            balance = txn._parse_amount(_cell(row, cols.get("balance"))) if "balance" in cols else None
            desc = _cell(row, cols.get("description"))
            ref = _cell(row, cols.get("reference"))
            out.append(ParsedLine(row_no, d, (str(desc).strip()[:500] or None) if desc is not None else None,
                                  (str(ref).strip()[:100] or None) if ref is not None else None, amount,
                                  _q(balance) if balance is not None else None))
        except (ValueError, ArithmeticError) as e:
            skipped.append({"row": row_no, "reason": str(e)})
    return out, skipped, order, ambiguous


def _fingerprints(account_id: uuid.UUID, lines: list[ParsedLine]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for ln in lines:
        key = f"{account_id}|{ln.tx_date}|{ln.amount}|{txn._norm(ln.description or '')}|{(ln.reference or '').lower()}"
        n = seen.get(key, 0)
        seen[key] = n + 1
        out.append(hashlib.sha256(f"{key}|{n}".encode()).hexdigest())
    return out


async def _money_account(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID) -> FinAccount:
    acc = await txn._account(db, tenant_id, account_id, "Account")
    if acc.type != AccountType.ASSET or acc.money_kind is None:
        raise UnprocessableError("Pick a cash, bank or wallet account")
    return acc


async def import_statement(db: AsyncSession, tenant_id: uuid.UUID, *, account_id: uuid.UUID, filename: str, content: bytes,
                           dry_run: bool, opening_balance: Decimal | None = None, closing_balance: Decimal | None = None,
                           date_order: str | None = None, created_by: uuid.UUID | None = None) -> dict:
    await _money_account(db, tenant_id, account_id)
    parsed, skipped, order, ambiguous = _parse(txn._read_rows(filename, content), date_order)
    prints = _fingerprints(account_id, parsed)
    have = set()
    if prints:
        have = set((await db.execute(select(FinBankLine.fingerprint).where(
            FinBankLine.tenant_id == tenant_id, FinBankLine.account_id == account_id, FinBankLine.fingerprint.in_(prints)))).scalars().all())
    fresh = [(p, f) for p, f in zip(parsed, prints) if f not in have]
    res = {"dry_run": dry_run, "total_rows": len(parsed) + len(skipped), "to_import": len(fresh), "duplicates": len(parsed) - len(fresh),
           "skipped": skipped, "date_order": order, "date_order_guessed": ambiguous, "imported": 0, "matched": 0, "statement_id": None,
           "preview": [{"date": p.tx_date.isoformat(), "description": p.description, "reference": p.reference, "amount": _s(p.amount),
                        "duplicate": f in have} for p, f in zip(parsed[:10], prints[:10])]}
    if dry_run or not fresh:
        return res

    chrono = parsed if parsed[0].tx_date <= parsed[-1].tx_date else parsed[::-1]
    opening = opening_balance
    if opening is None and chrono[0].balance is not None:
        opening = chrono[0].balance - chrono[0].amount
    closing = closing_balance if closing_balance is not None else chrono[-1].balance
    st = FinBankStatement(tenant_id=tenant_id, account_id=account_id, filename=(filename or "statement")[:255],
                          date_from=min(p.tx_date for p, _ in fresh), date_to=max(p.tx_date for p, _ in fresh),
                          opening_balance=_q(opening) if opening is not None else None,
                          closing_balance=_q(closing) if closing is not None else None, line_count=len(fresh), created_by=created_by)
    db.add(st)
    await db.flush()
    for p, f in fresh:
        db.add(FinBankLine(tenant_id=tenant_id, statement_id=st.id, account_id=account_id, tx_date=p.tx_date, description=p.description,
                           reference=p.reference, amount=p.amount, balance=p.balance, fingerprint=f))
    await db.flush()
    res["imported"], res["statement_id"] = len(fresh), str(st.id)
    res["matched"] = await auto_match(db, tenant_id, account_id, created_by)
    return res


# ───────────────────────── matching ─────────────────────────
def _live(tenant_id):
    return [FinJournalEntry.tenant_id == tenant_id, FinJournalEntry.is_deleted == False,  # noqa: E712
            FinJournalEntry.status == EntryStatus.POSTED, FinJournalEntry.reverses_id.is_(None)]


async def _candidates(db: AsyncSession, tenant_id: uuid.UUID, ln: FinBankLine, days: int) -> list[tuple[FinJournalLine, FinJournalEntry]]:
    amt = abs(ln.amount)
    side = FinJournalLine.debit if ln.amount > 0 else FinJournalLine.credit
    taken = select(FinBankLine.matched_line_id).where(FinBankLine.tenant_id == tenant_id, FinBankLine.matched_line_id.is_not(None))
    q = (select(FinJournalLine, FinJournalEntry)
         .join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
         .where(*_live(tenant_id), FinJournalLine.tenant_id == tenant_id, FinJournalLine.account_id == ln.account_id,
                side > 0, or_(side == amt, FinJournalLine.amount_original == amt), FinJournalLine.id.not_in(taken),
                FinJournalEntry.entry_date >= ln.tx_date - timedelta(days=days), FinJournalEntry.entry_date <= ln.tx_date + timedelta(days=days))
         .order_by(FinJournalEntry.entry_date, FinJournalEntry.number))
    return [(jl, e) for jl, e in (await db.execute(q)).all()]


def _link(ln: FinBankLine, journal_line_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    ln.status, ln.matched_line_id, ln.matched_by, ln.matched_at = "matched", journal_line_id, user_id, datetime.now(timezone.utc)


async def auto_match(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID, user_id: uuid.UUID | None = None) -> int:
    """Match every unmatched line that has exactly one obvious ledger counterpart. Returns how many were matched."""
    lines = (await db.execute(select(FinBankLine).where(
        FinBankLine.tenant_id == tenant_id, FinBankLine.account_id == account_id, FinBankLine.status == "unmatched",
        FinBankLine.is_deleted == False).order_by(FinBankLine.tx_date, FinBankLine.created_at))).scalars().all()  # noqa: E712
    n = 0
    for ln in lines:
        cands = await _candidates(db, tenant_id, ln, AUTO_WINDOW_DAYS)
        pick = None
        ref = (ln.reference or "").strip().lower()
        if ref:
            by_tid = [c for c in cands if (c[1].payment_tid or "").strip().lower() == ref]
            if len(by_tid) == 1:
                pick = by_tid[0]
        if pick is None and len(cands) == 1:
            pick = cands[0]
        if pick is None:
            same_day = [c for c in cands if c[1].entry_date == ln.tx_date]
            if len(same_day) == 1:
                pick = same_day[0]
        if pick is not None:
            _link(ln, pick[0].id, user_id)
            await db.flush()
            n += 1
    return n


async def _line(db: AsyncSession, tenant_id: uuid.UUID, line_id: uuid.UUID) -> FinBankLine:
    ln = (await db.execute(select(FinBankLine).where(FinBankLine.id == line_id, FinBankLine.tenant_id == tenant_id,
                                                     FinBankLine.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if ln is None:
        raise NotFoundError("Statement line not found")
    return ln


def _editable(ln: FinBankLine) -> None:
    if ln.reconciliation_id is not None:
        raise ConflictError("This line is part of a finished reconciliation. Undo that reconciliation first")


async def _ser(db: AsyncSession, tenant_id: uuid.UUID, lines: list[FinBankLine]) -> list[dict]:
    ids = [l.matched_line_id for l in lines if l.matched_line_id]
    info: dict[uuid.UUID, tuple[FinJournalLine, FinJournalEntry]] = {}
    if ids:
        for jl, e in (await db.execute(select(FinJournalLine, FinJournalEntry).join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
                                       .where(FinJournalLine.id.in_(ids), FinJournalLine.tenant_id == tenant_id))).all():
            info[jl.id] = (jl, e)
    out = []
    for l in lines:
        m = None
        if l.matched_line_id and l.matched_line_id in info:
            jl, e = info[l.matched_line_id]
            m = {"entry_line_id": str(jl.id), "entry_id": str(e.id), "number": e.number, "date": e.entry_date.isoformat(), "memo": e.memo,
                 "voided": e.status != EntryStatus.POSTED}
        out.append({"id": str(l.id), "statement_id": str(l.statement_id), "account_id": str(l.account_id), "date": l.tx_date.isoformat(),
                    "description": l.description, "reference": l.reference, "amount": _s(l.amount),
                    "balance": _s(l.balance) if l.balance is not None else None, "status": l.status, "match": m,
                    "reconciled": l.reconciliation_id is not None})
    return out


async def list_lines(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID, *, status: str | None, statement_id: uuid.UUID | None,
                     date_from: date | None, date_to: date | None, q: str | None, limit: int, offset: int) -> dict:
    await _money_account(db, tenant_id, account_id)
    base = [FinBankLine.tenant_id == tenant_id, FinBankLine.account_id == account_id, FinBankLine.is_deleted == False]  # noqa: E712
    if statement_id:
        base.append(FinBankLine.statement_id == statement_id)
    if date_from:
        base.append(FinBankLine.tx_date >= date_from)
    if date_to:
        base.append(FinBankLine.tx_date <= date_to)
    if q and q.strip():
        like = f"%{q.strip()}%"
        base.append(or_(FinBankLine.description.ilike(like), FinBankLine.reference.ilike(like)))
    counts = {s: 0 for s in ("unmatched", "matched", "ignored")}
    for s, n in (await db.execute(select(FinBankLine.status, func.count()).where(*base).group_by(FinBankLine.status))).all():
        counts[s] = n
    where = base + ([FinBankLine.status == status] if status else [])
    total = (await db.execute(select(func.count()).select_from(FinBankLine).where(*where))).scalar_one()
    rows = (await db.execute(select(FinBankLine).where(*where).order_by(FinBankLine.tx_date.desc(), FinBankLine.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"items": await _ser(db, tenant_id, list(rows)), "total": total, "counts": counts}


async def suggestions(db: AsyncSession, tenant_id: uuid.UUID, line_id: uuid.UUID) -> list[dict]:
    ln = await _line(db, tenant_id, line_id)
    return [{"entry_line_id": str(jl.id), "entry_id": str(e.id), "number": e.number, "date": e.entry_date.isoformat(), "memo": e.memo,
             "reference": e.reference, "payment_tid": e.payment_tid, "amount": _s(jl.debit if ln.amount > 0 else jl.credit)}
            for jl, e in await _candidates(db, tenant_id, ln, SUGGEST_WINDOW_DAYS)]


async def match_line(db: AsyncSession, tenant_id: uuid.UUID, line_id: uuid.UUID, entry_line_id: uuid.UUID, user_id: uuid.UUID | None) -> dict:
    ln = await _line(db, tenant_id, line_id)
    _editable(ln)
    if ln.status == "matched":
        raise ConflictError("Already matched. Unmatch it first")
    if ln.status == "ignored":
        raise ConflictError("This line is ignored. Restore it first")
    row = (await db.execute(select(FinJournalLine, FinJournalEntry).join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
                            .where(FinJournalLine.id == entry_line_id, *_live(tenant_id), FinJournalLine.tenant_id == tenant_id))).first()
    if row is None or row[0].account_id != ln.account_id:
        raise UnprocessableError("That ledger entry is not on this account")
    jl = row[0]
    amt = abs(ln.amount)
    side = jl.debit if ln.amount > 0 else jl.credit
    if side == 0 or amt not in (side, jl.amount_original):
        raise UnprocessableError("The amount or direction does not match this statement line")
    if (await db.execute(select(FinBankLine.id).where(FinBankLine.tenant_id == tenant_id, FinBankLine.matched_line_id == jl.id))).first():
        raise ConflictError("That ledger entry is already matched to another statement line")
    _link(ln, jl.id, user_id)
    await db.flush()
    return (await _ser(db, tenant_id, [ln]))[0]


async def unmatch_line(db: AsyncSession, tenant_id: uuid.UUID, line_id: uuid.UUID) -> dict:
    ln = await _line(db, tenant_id, line_id)
    _editable(ln)
    if ln.status != "matched":
        raise ConflictError("This line is not matched")
    ln.status, ln.matched_line_id, ln.matched_by, ln.matched_at = "unmatched", None, None, None
    await db.flush()
    return (await _ser(db, tenant_id, [ln]))[0]


async def set_ignored(db: AsyncSession, tenant_id: uuid.UUID, line_id: uuid.UUID, ignored: bool) -> dict:
    ln = await _line(db, tenant_id, line_id)
    _editable(ln)
    if ignored:
        if ln.status == "matched":
            raise ConflictError("Unmatch the line before ignoring it")
        ln.status = "ignored"
    else:
        if ln.status != "ignored":
            raise ConflictError("This line is not ignored")
        ln.status = "unmatched"
    await db.flush()
    return (await _ser(db, tenant_id, [ln]))[0]


async def create_entry_for_line(db: AsyncSession, tenant_id: uuid.UUID, line_id: uuid.UUID, *, type: str, category_id: uuid.UUID | None,
                                other_account_id: uuid.UUID | None, description: str | None, user_id: uuid.UUID | None) -> dict:
    """Book a statement line that has no ledger entry yet (a bank fee, interest, a transfer from another account) and match it."""
    ln = await _line(db, tenant_id, line_id)
    _editable(ln)
    if ln.status != "unmatched":
        raise ConflictError("Only an unmatched line can be booked")
    inflow = ln.amount > 0
    if type == "income" and not inflow:
        raise UnprocessableError("Money going out is an expense or a transfer, not income")
    if type == "expense" and inflow:
        raise UnprocessableError("Money coming in is income or a transfer, not an expense")
    text = (description or ln.description or "").strip() or None
    amount = abs(ln.amount)
    if type == "transfer":
        if other_account_id is None:
            raise UnprocessableError("Pick the other account of the transfer")
        src, dst = (other_account_id, ln.account_id) if inflow else (ln.account_id, other_account_id)
        entry = await txn.create_transaction(db, tenant_id, type="transfer", entry_date=ln.tx_date, amount=amount, account_id=src,
                                             to_account_id=dst, description=text, reference=ln.reference, created_by=user_id)
    else:
        entry = await txn.create_transaction(db, tenant_id, type=type, entry_date=ln.tx_date, amount=amount, account_id=ln.account_id,
                                             category_id=category_id, description=text, reference=ln.reference, created_by=user_id)
    side = FinJournalLine.debit if inflow else FinJournalLine.credit
    jl = (await db.execute(select(FinJournalLine).where(FinJournalLine.entry_id == entry.id, FinJournalLine.account_id == ln.account_id,
                                                        FinJournalLine.tenant_id == tenant_id, side > 0))).scalars().first()
    if jl is None:  # cannot happen for a two-line transaction; refuse rather than leave a half-booked line
        raise UnprocessableError("Could not match the new entry")
    _link(ln, jl.id, user_id)
    await db.flush()
    return {"line": (await _ser(db, tenant_id, [ln]))[0], "entry_id": str(entry.id), "number": entry.number}


async def list_statements(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID) -> list[dict]:
    await _money_account(db, tenant_id, account_id)
    sts = (await db.execute(select(FinBankStatement).where(FinBankStatement.tenant_id == tenant_id, FinBankStatement.account_id == account_id,
                                                           FinBankStatement.is_deleted == False)  # noqa: E712
                            .order_by(FinBankStatement.created_at.desc()))).scalars().all()
    counts: dict[uuid.UUID, dict[str, int]] = {}
    for sid, s, n in (await db.execute(select(FinBankLine.statement_id, FinBankLine.status, func.count()).where(
            FinBankLine.tenant_id == tenant_id, FinBankLine.account_id == account_id).group_by(FinBankLine.statement_id, FinBankLine.status))).all():
        counts.setdefault(sid, {})[s] = n
    return [{"id": str(s.id), "filename": s.filename, "date_from": s.date_from.isoformat() if s.date_from else None,
             "date_to": s.date_to.isoformat() if s.date_to else None,
             "opening_balance": _s(s.opening_balance) if s.opening_balance is not None else None,
             "closing_balance": _s(s.closing_balance) if s.closing_balance is not None else None, "line_count": s.line_count,
             "counts": {k: counts.get(s.id, {}).get(k, 0) for k in ("unmatched", "matched", "ignored")},
             "created_at": s.created_at.isoformat()} for s in sts]


# ───────────────────────── reconciliation ─────────────────────────
async def _last_rec(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID) -> FinBankReconciliation | None:
    return (await db.execute(select(FinBankReconciliation).where(
        FinBankReconciliation.tenant_id == tenant_id, FinBankReconciliation.account_id == account_id, FinBankReconciliation.is_deleted == False)  # noqa: E712
        .order_by(FinBankReconciliation.statement_date.desc(), FinBankReconciliation.created_at.desc()).limit(1))).scalars().first()


@dataclass
class _Scope:
    beginning: Decimal
    last: FinBankReconciliation | None
    cleared: list[FinBankLine] = field(default_factory=list)
    blocking: list[FinBankLine] = field(default_factory=list)


async def _scope(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID, statement_date: date, beginning_balance: Decimal | None) -> _Scope:
    last = await _last_rec(db, tenant_id, account_id)
    if last is not None and statement_date < last.statement_date:
        raise UnprocessableError(f"The statement date is before the last reconciliation ({last.statement_date.isoformat()})")
    if last is not None:
        beginning = last.statement_balance
    elif beginning_balance is not None:
        beginning = beginning_balance
    else:
        first = (await db.execute(select(FinBankStatement.opening_balance).where(
            FinBankStatement.tenant_id == tenant_id, FinBankStatement.account_id == account_id, FinBankStatement.is_deleted == False,  # noqa: E712
            FinBankStatement.opening_balance.is_not(None)).order_by(FinBankStatement.date_from).limit(1))).scalar_one_or_none()
        beginning = first if first is not None else ZERO
    sc = _Scope(_q(beginning), last)
    lines = (await db.execute(select(FinBankLine).where(
        FinBankLine.tenant_id == tenant_id, FinBankLine.account_id == account_id, FinBankLine.is_deleted == False,  # noqa: E712
        FinBankLine.reconciliation_id.is_(None), FinBankLine.tx_date <= statement_date, FinBankLine.status != "ignored")
        .order_by(FinBankLine.tx_date))).scalars().all()
    voided: set[uuid.UUID] = set()
    ids = [l.matched_line_id for l in lines if l.matched_line_id]
    if ids:
        voided = set((await db.execute(select(FinJournalLine.id).join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id).where(
            FinJournalLine.id.in_(ids), FinJournalEntry.status != EntryStatus.POSTED))).scalars().all())
    for l in lines:
        (sc.cleared if l.status == "matched" and l.matched_line_id not in voided else sc.blocking).append(l)
    return sc


async def _ledger_balance(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID, on: date) -> Decimal:
    q = (select(func.coalesce(func.sum(FinJournalLine.debit - FinJournalLine.credit), 0))
         .join(FinJournalEntry, FinJournalEntry.id == FinJournalLine.entry_id)
         .where(FinJournalLine.tenant_id == tenant_id, FinJournalLine.account_id == account_id, FinJournalEntry.tenant_id == tenant_id,
                FinJournalEntry.is_deleted == False, FinJournalEntry.entry_date <= on))  # noqa: E712
    return _q((await db.execute(q)).scalar_one())


async def reconcile_preview(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID, statement_date: date, statement_balance: Decimal,
                            beginning_balance: Decimal | None = None) -> dict:
    await _money_account(db, tenant_id, account_id)
    sc = await _scope(db, tenant_id, account_id, statement_date, beginning_balance)
    cleared = _q(sum((l.amount for l in sc.cleared), ZERO))
    diff = _q(_q(statement_balance) - sc.beginning - cleared)
    reason = None
    if sc.blocking:
        reason = f"{len(sc.blocking)} statement line(s) up to this date are not matched yet"
    elif not sc.cleared:
        reason = "There are no matched lines to reconcile"
    elif diff != 0:
        reason = f"The difference is {diff}. It must be 0"
    return {"account_id": str(account_id), "statement_date": statement_date.isoformat(), "beginning_balance": _s(sc.beginning),
            "beginning_from_last": sc.last is not None, "statement_balance": _s(statement_balance), "cleared_total": _s(cleared),
            "cleared_count": len(sc.cleared), "unmatched_count": len(sc.blocking), "difference": _s(diff),
            "ledger_balance": _s(await _ledger_balance(db, tenant_id, account_id, statement_date)),
            "can_finish": reason is None, "reason": reason}


def _ser_rec(r: FinBankReconciliation) -> dict:
    return {"id": str(r.id), "account_id": str(r.account_id), "statement_date": r.statement_date.isoformat(), "beginning_balance": _s(r.beginning_balance),
            "statement_balance": _s(r.statement_balance), "cleared_total": _s(r.cleared_total), "line_count": r.line_count,
            "created_at": r.created_at.isoformat()}


async def finish_reconciliation(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID, statement_date: date, statement_balance: Decimal,
                                beginning_balance: Decimal | None, user_id: uuid.UUID | None) -> dict:
    await _money_account(db, tenant_id, account_id)
    sc = await _scope(db, tenant_id, account_id, statement_date, beginning_balance)
    cleared = _q(sum((l.amount for l in sc.cleared), ZERO))
    diff = _q(_q(statement_balance) - sc.beginning - cleared)
    if sc.blocking:
        raise UnprocessableError(f"{len(sc.blocking)} statement line(s) up to this date are not matched yet")
    if not sc.cleared:
        raise UnprocessableError("There are no matched lines to reconcile")
    if diff != 0:
        raise UnprocessableError(f"The difference is {diff}. It must be 0")
    rec = FinBankReconciliation(tenant_id=tenant_id, account_id=account_id, statement_date=statement_date, beginning_balance=sc.beginning,
                                statement_balance=_q(statement_balance), cleared_total=cleared, line_count=len(sc.cleared), created_by=user_id)
    db.add(rec)
    await db.flush()
    for l in sc.cleared:
        l.reconciliation_id = rec.id
    await db.flush()
    return _ser_rec(rec)


async def list_reconciliations(db: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID) -> list[dict]:
    await _money_account(db, tenant_id, account_id)
    rows = (await db.execute(select(FinBankReconciliation).where(
        FinBankReconciliation.tenant_id == tenant_id, FinBankReconciliation.account_id == account_id, FinBankReconciliation.is_deleted == False)  # noqa: E712
        .order_by(FinBankReconciliation.statement_date.desc(), FinBankReconciliation.created_at.desc()))).scalars().all()
    return [_ser_rec(r) for r in rows]


async def undo_reconciliation(db: AsyncSession, tenant_id: uuid.UUID, reconciliation_id: uuid.UUID) -> None:
    rec = (await db.execute(select(FinBankReconciliation).where(FinBankReconciliation.id == reconciliation_id,
                                                                FinBankReconciliation.tenant_id == tenant_id,
                                                                FinBankReconciliation.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if rec is None:
        raise NotFoundError("Reconciliation not found")
    last = await _last_rec(db, tenant_id, rec.account_id)
    if last is None or last.id != rec.id:
        raise ConflictError("Only the latest reconciliation of an account can be undone")
    for l in (await db.execute(select(FinBankLine).where(FinBankLine.tenant_id == tenant_id, FinBankLine.reconciliation_id == rec.id))).scalars().all():
        l.reconciliation_id = None
    rec.is_deleted, rec.deleted_at = True, datetime.now(timezone.utc)
    await db.flush()
