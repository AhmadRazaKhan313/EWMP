"""Finance Phase 3a: vendors, bills and payments made, all posting to the ledger. Mirror of finance_sales."""
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.finance import AccountType, FinAccount, FinTaxRate
from app.models.finance_purchases import (BillPaymentStatus, BillStatus, FinBill, FinBillLine, FinBillPayment,
                                          FinBillPaymentAllocation, FinPurchaseSettings, FinVendor)
from app.services import finance_ledger as led
from app.services.finance_sales import _acct_by_code, _next, _q, _rate

AP_CODE, INPUT_TAX_CODE, FX_CODE, DEFAULT_EXPENSE_CODE = "2010", "1200", "5950", "5900"
ZERO = Decimal("0")
OPEN_STATES = (BillStatus.OPEN, BillStatus.PARTIALLY_PAID)


@dataclass
class BillLineSpec:
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal = ZERO
    tax_rate_id: uuid.UUID | None = None
    expense_account_id: uuid.UUID | None = None


# ───────────────────────── helpers ─────────────────────────
async def _vendor(db, tenant_id, vid) -> FinVendor:
    v = (await db.execute(select(FinVendor).where(FinVendor.id == vid, FinVendor.tenant_id == tenant_id,
                                                  FinVendor.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if v is None:
        raise NotFoundError("Vendor not found")
    return v


async def _bill(db, tenant_id, bid, lock=False) -> FinBill:
    q = select(FinBill).where(FinBill.id == bid, FinBill.tenant_id == tenant_id, FinBill.is_deleted == False)  # noqa: E712
    if lock:
        q = q.with_for_update()
    b = (await db.execute(q)).scalar_one_or_none()
    if b is None:
        raise NotFoundError("Bill not found")
    return b


async def _lines(db, bid) -> list[FinBillLine]:
    return list((await db.execute(select(FinBillLine).where(FinBillLine.bill_id == bid).order_by(FinBillLine.line_no))).scalars().all())


def _status_for(b: FinBill) -> BillStatus:
    if b.amount_paid >= b.total:
        return BillStatus.PAID
    return BillStatus.PARTIALLY_PAID if b.amount_paid > 0 else BillStatus.OPEN


def _ser_bill(b: FinBill, v: FinVendor | None = None, lines: list[FinBillLine] | None = None) -> dict:
    balance = _q(b.total - b.amount_paid)
    overdue = b.status in OPEN_STATES and balance > 0 and b.due_date < date.today()
    d = {"id": str(b.id), "number": b.number, "vendor_id": str(b.vendor_id), "vendor_name": v.name if v else None,
         "vendor_ref": b.vendor_ref, "status": b.status.value, "is_overdue": overdue,
         "issue_date": b.issue_date.isoformat(), "due_date": b.due_date.isoformat(), "currency": b.currency,
         "exchange_rate": str(b.exchange_rate), "subtotal": str(b.subtotal), "tax_total": str(b.tax_total),
         "total": str(b.total), "amount_paid": str(b.amount_paid), "balance": str(balance), "notes": b.notes,
         "journal_entry_id": str(b.journal_entry_id) if b.journal_entry_id else None,
         "approval_status": b.approval_status, "rejection_reason": b.rejection_reason,
         "approved_at": b.approved_at.isoformat() if b.approved_at else None,
         "recurring_id": str(b.recurring_id) if b.recurring_id else None}
    if lines is not None:
        d["lines"] = [{"id": str(l.id), "description": l.description, "quantity": str(l.quantity),
                       "unit_price": str(l.unit_price), "discount_percent": str(l.discount_percent),
                       "tax_rate_id": str(l.tax_rate_id) if l.tax_rate_id else None, "tax_percent": str(l.tax_percent),
                       "expense_account_id": str(l.expense_account_id), "net_amount": str(l.net_amount),
                       "tax_amount": str(l.tax_amount)} for l in lines]
    return d


# ───────────────────────── vendors ─────────────────────────
def _ser_vendor(v: FinVendor, balance: Decimal | None = None) -> dict:
    d = {"id": str(v.id), "name": v.name, "company": v.company, "email": v.email, "phone": v.phone, "address": v.address,
         "currency": v.currency, "payment_terms_days": v.payment_terms_days, "notes": v.notes, "is_active": v.is_active}
    if balance is not None:
        d["balance"] = str(balance)
    return d


async def create_vendor(db, tenant_id, **f) -> dict:
    if not (f.get("name") or "").strip():
        raise UnprocessableError("Vendor name is required")
    if f.get("currency"):
        f["currency"] = f["currency"].upper()
    v = FinVendor(tenant_id=tenant_id, **f)
    db.add(v)
    await db.flush()
    return _ser_vendor(v, ZERO)


async def update_vendor(db, tenant_id, vid, **f) -> dict:
    v = await _vendor(db, tenant_id, vid)
    for k, val in f.items():
        setattr(v, k, val.upper() if k == "currency" and val else val)
    await db.flush()
    return _ser_vendor(v)


async def list_vendors(db, tenant_id, search: str | None = None, include_inactive=False) -> list[dict]:
    q = select(FinVendor).where(FinVendor.tenant_id == tenant_id, FinVendor.is_deleted == False)  # noqa: E712
    if not include_inactive:
        q = q.where(FinVendor.is_active == True)  # noqa: E712
    if search:
        q = q.where(FinVendor.name.ilike(f"%{search}%") | FinVendor.company.ilike(f"%{search}%"))
    rows = (await db.execute(q.order_by(FinVendor.name))).scalars().all()
    owed = {r[0]: Decimal(r[1] or 0) for r in (await db.execute(
        select(FinBill.vendor_id, func.sum(FinBill.total - FinBill.amount_paid)).where(
            FinBill.tenant_id == tenant_id, FinBill.is_deleted == False,  # noqa: E712
            FinBill.status.in_(OPEN_STATES)).group_by(FinBill.vendor_id))).all()}
    return [_ser_vendor(v, owed.get(v.id, ZERO)) for v in rows]


async def vendor_statement(db, tenant_id, vid) -> dict:
    v = await _vendor(db, tenant_id, vid)
    bills = (await db.execute(select(FinBill).where(
        FinBill.tenant_id == tenant_id, FinBill.vendor_id == vid, FinBill.is_deleted == False,  # noqa: E712
        FinBill.status.notin_([BillStatus.DRAFT, BillStatus.VOID])).order_by(FinBill.issue_date, FinBill.number))).scalars().all()
    pays = (await db.execute(select(FinBillPayment).where(
        FinBillPayment.tenant_id == tenant_id, FinBillPayment.vendor_id == vid, FinBillPayment.is_deleted == False,  # noqa: E712
        FinBillPayment.status == BillPaymentStatus.POSTED).order_by(FinBillPayment.payment_date, FinBillPayment.number))).scalars().all()
    ev = [(b.issue_date, 0, {"date": b.issue_date.isoformat(), "type": "bill", "number": b.number, "currency": b.currency,
                             "credit": str(b.total), "debit": "0.00"}) for b in bills]
    ev += [(p.payment_date, 1, {"date": p.payment_date.isoformat(), "type": "payment", "number": p.number,
                                "currency": p.currency, "credit": "0.00", "debit": str(p.amount)}) for p in pays]
    ev.sort(key=lambda e: (e[0], e[1]))
    run: dict[str, Decimal] = {}
    out = []
    for _, _, e in ev:                     # balance = what you owe the vendor (bills raise it, payments lower it)
        run[e["currency"]] = run.get(e["currency"], ZERO) + Decimal(e["credit"]) - Decimal(e["debit"])
        out.append({**e, "balance": str(run[e["currency"]])})
    return {"vendor": _ser_vendor(v), "lines": out, "balances": {k: str(x) for k, x in run.items()}}


# ───────────────────────── approvals (Phase 3b) ─────────────────────────
async def get_threshold(db, tenant_id) -> Decimal | None:
    r = (await db.execute(select(FinPurchaseSettings).where(FinPurchaseSettings.tenant_id == tenant_id,
                                                           FinPurchaseSettings.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    return r.approval_threshold if r else None


def _base_total(b: FinBill) -> Decimal:
    return _q(b.total * Decimal(b.exchange_rate))


async def needs_approval(db, tenant_id, b: FinBill) -> bool:
    """True when a threshold is set and this bill (in base currency) reaches it."""
    t = await get_threshold(db, tenant_id)
    return t is not None and _base_total(b) >= t


# ───────────────────────── bills ─────────────────────────
async def _build_lines(db, tenant_id, specs: list[BillLineSpec]):
    if not specs:
        raise UnprocessableError("A bill needs at least one line")
    default = None
    out, sub, tax = [], ZERO, ZERO
    for i, s in enumerate(specs, start=1):
        if Decimal(s.quantity) <= 0 or Decimal(s.unit_price) < 0:
            raise UnprocessableError(f"Line {i}: quantity must be > 0 and price >= 0")
        disc = Decimal(s.discount_percent or 0)
        if not (ZERO <= disc <= 100):
            raise UnprocessableError(f"Line {i}: discount must be between 0 and 100")
        if not (s.description or "").strip():
            raise UnprocessableError(f"Line {i}: description is required")
        acct_id = s.expense_account_id
        if acct_id is None:
            default = default or await _acct_by_code(db, tenant_id, DEFAULT_EXPENSE_CODE)
            acct_id = default.id
        else:
            a = (await db.execute(select(FinAccount).where(FinAccount.id == acct_id, FinAccount.tenant_id == tenant_id,
                                                           FinAccount.is_deleted == False))).scalar_one_or_none()  # noqa: E712
            # expenses, or things you buy and keep (fixed assets). Never a bank/cash/receivable account.
            if a is None or a.type not in (AccountType.EXPENSE, AccountType.ASSET) or led.account_kind(a) or a.code in ("1000", "1100", "1200"):
                raise UnprocessableError(f"Line {i}: pick an expense (or fixed-asset) account")
        pct, rate_id = ZERO, None
        if s.tax_rate_id:
            t = (await db.execute(select(FinTaxRate).where(FinTaxRate.id == s.tax_rate_id, FinTaxRate.tenant_id == tenant_id,
                                                           FinTaxRate.is_deleted == False))).scalar_one_or_none()  # noqa: E712
            if t is None or not t.is_active:
                raise UnprocessableError(f"Line {i}: tax rate not found")
            pct, rate_id = Decimal(t.percent), t.id
        net = _q(Decimal(s.quantity) * Decimal(s.unit_price) * (1 - disc / 100))
        tx = _q(net * pct / 100)
        sub += net
        tax += tx
        out.append(dict(line_no=i, description=s.description.strip()[:500], quantity=Decimal(s.quantity),
                        unit_price=_q(s.unit_price), discount_percent=disc, tax_rate_id=rate_id, tax_percent=pct,
                        expense_account_id=acct_id, net_amount=net, tax_amount=tx))
    return out, sub, tax


async def create_bill(db, tenant_id, *, vendor_id, issue_date: date, due_date: date | None, lines: list[BillLineSpec],
                      currency: str | None = None, rate: Decimal | None = None, vendor_ref=None, notes=None,
                      post: bool = False, created_by=None, recurring_id=None) -> dict:
    v = await _vendor(db, tenant_id, vendor_id)
    base = await led.base_currency(db, tenant_id)
    cur = (currency or v.currency or base).upper()
    due = due_date or issue_date + timedelta(days=v.payment_terms_days or 0)
    if due < issue_date:
        raise UnprocessableError("Due date cannot be before the issue date")
    rows, sub, tax = await _build_lines(db, tenant_id, lines)
    fx = await _rate(db, tenant_id, cur, issue_date, rate)
    b = FinBill(tenant_id=tenant_id, number=await _next(db, tenant_id, FinBill, "BILL"), vendor_id=v.id, vendor_ref=vendor_ref,
                status=BillStatus.DRAFT, issue_date=issue_date, due_date=due, currency=cur, exchange_rate=fx,
                subtotal=sub, tax_total=tax, total=sub + tax, amount_paid=ZERO, notes=notes, created_by=created_by, recurring_id=recurring_id)
    db.add(b)
    await db.flush()
    for r in rows:
        db.add(FinBillLine(tenant_id=tenant_id, bill_id=b.id, **r))
    await db.flush()
    if post:
        await post_bill(db, tenant_id, b.id, created_by=created_by)
    return await get_bill(db, tenant_id, b.id)


async def update_bill(db, tenant_id, bid, *, vendor_id=None, issue_date=None, due_date=None, lines=None, currency=None,
                      rate=None, vendor_ref=None, notes=None) -> dict:
    b = await _bill(db, tenant_id, bid, lock=True)
    if b.status != BillStatus.DRAFT:
        raise ConflictError("Only draft bills can be edited. Void it and enter a new one.")
    if vendor_id:
        b.vendor_id = (await _vendor(db, tenant_id, vendor_id)).id
    b.issue_date = issue_date or b.issue_date
    b.due_date = due_date or b.due_date
    if b.due_date < b.issue_date:
        raise UnprocessableError("Due date cannot be before the issue date")
    if currency:
        b.currency = currency.upper()
    b.exchange_rate = await _rate(db, tenant_id, b.currency, b.issue_date, rate)
    if vendor_ref is not None:
        b.vendor_ref = vendor_ref
    if notes is not None:
        b.notes = notes
    if lines is not None:
        rows, sub, tax = await _build_lines(db, tenant_id, lines)
        for old in await _lines(db, b.id):
            await db.delete(old)
        await db.flush()
        for r in rows:
            db.add(FinBillLine(tenant_id=tenant_id, bill_id=b.id, **r))
        b.subtotal, b.tax_total, b.total = sub, tax, sub + tax
    if b.approval_status in ("approved", "pending", "rejected"):
        b.approval_status, b.approved_by, b.approved_at, b.rejection_reason = "none", None, None, None   # edited: must be re-approved
    await db.flush()
    return await get_bill(db, tenant_id, b.id)


async def post_bill(db, tenant_id, bid, *, created_by=None) -> dict:
    b = await _bill(db, tenant_id, bid, lock=True)
    if b.status != BillStatus.DRAFT:
        raise ConflictError("Bill is already posted")
    if b.total <= 0:
        raise UnprocessableError("Cannot post a bill with a zero total")
    if b.approval_status != "approved" and await needs_approval(db, tenant_id, b):
        raise ConflictError("This bill is above the approval limit. Request approval first.")
    ap = await _acct_by_code(db, tenant_id, AP_CODE)
    tax_default = await _acct_by_code(db, tenant_id, INPUT_TAX_CODE)
    fx = Decimal(b.exchange_rate)
    lines = await _lines(db, b.id)
    tax_acc = {}
    ids = {l.tax_rate_id for l in lines if l.tax_rate_id}
    if ids:
        for t in (await db.execute(select(FinTaxRate).where(FinTaxRate.id.in_(ids)))).scalars():
            tax_acc[t.id] = t.account_id
    debits: dict[uuid.UUID, Decimal] = {}
    for l in lines:
        debits[l.expense_account_id] = debits.get(l.expense_account_id, ZERO) + _q(l.net_amount * fx)
        if l.tax_amount > 0:
            acc = tax_acc.get(l.tax_rate_id) or tax_default.id
            debits[acc] = debits.get(acc, ZERO) + _q(l.tax_amount * fx)
    base_total = _q(b.total * fx)
    diff = base_total - sum(debits.values())
    if diff:
        big = max(debits, key=lambda k: debits[k])
        debits[big] += diff
    specs = [led.LineIn(account_id=ap.id, side="credit", amount=b.total, currency=b.currency, rate=fx,
                        base_amount=base_total, description=b.number)]
    for acc, base_amt in debits.items():
        if base_amt <= 0:
            continue
        specs.append(led.LineIn(account_id=acc, side="debit", amount=_q(base_amt / fx) if fx else base_amt,
                                currency=b.currency, rate=fx, base_amount=base_amt))
    v = await _vendor(db, tenant_id, b.vendor_id)
    e = await led.post_entry(db, tenant_id, entry_date=b.issue_date, lines=specs, memo=f"Bill {b.number} - {v.name}",
                             reference=b.vendor_ref or b.number, source_type="bill", source_id=b.id, created_by=created_by)
    b.journal_entry_id = e.id
    b.status = BillStatus.OPEN
    await db.flush()
    return await get_bill(db, tenant_id, b.id)


async def void_bill(db, tenant_id, bid, *, reason=None, created_by=None) -> dict:
    b = await _bill(db, tenant_id, bid, lock=True)
    if b.status == BillStatus.VOID:
        raise ConflictError("Bill is already void")
    if b.status == BillStatus.DRAFT:
        raise ConflictError("Draft bills are deleted, not voided")
    if b.amount_paid > 0:
        raise ConflictError("This bill has payments. Void the payment(s) first.")
    await led.void_entry(db, tenant_id, b.journal_entry_id, reason=reason or f"Void {b.number}", created_by=created_by)
    b.status = BillStatus.VOID
    await db.flush()
    return await get_bill(db, tenant_id, b.id)


async def delete_draft(db, tenant_id, bid) -> None:
    b = await _bill(db, tenant_id, bid, lock=True)
    if b.status != BillStatus.DRAFT:
        raise ConflictError("Only draft bills can be deleted")
    b.is_deleted = True
    b.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def get_bill(db, tenant_id, bid) -> dict:
    b = await _bill(db, tenant_id, bid)
    d = _ser_bill(b, await _vendor(db, tenant_id, b.vendor_id), await _lines(db, b.id))
    rows = (await db.execute(
        select(FinBillPaymentAllocation, FinBillPayment).join(FinBillPayment, FinBillPayment.id == FinBillPaymentAllocation.payment_id)
        .where(FinBillPaymentAllocation.bill_id == b.id, FinBillPayment.status == BillPaymentStatus.POSTED))).all()
    d["payments"] = [{"payment_id": str(p.id), "number": p.number, "date": p.payment_date.isoformat(), "amount": str(a.amount)} for a, p in rows]
    return d


async def list_bills(db, tenant_id, *, status: str | None = None, vendor_id=None, search: str | None = None,
                     page=1, page_size=50) -> tuple[list[dict], int]:
    q = select(FinBill, FinVendor).join(FinVendor, FinVendor.id == FinBill.vendor_id).where(
        FinBill.tenant_id == tenant_id, FinBill.is_deleted == False)  # noqa: E712
    if vendor_id:
        q = q.where(FinBill.vendor_id == vendor_id)
    if status == "overdue":
        q = q.where(FinBill.status.in_(OPEN_STATES), FinBill.due_date < date.today(), FinBill.total > FinBill.amount_paid)
    elif status:
        q = q.where(FinBill.status == BillStatus(status))
    if search:
        q = q.where(FinBill.number.ilike(f"%{search}%") | FinVendor.name.ilike(f"%{search}%") | FinBill.vendor_ref.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(q.order_by(FinBill.issue_date.desc(), FinBill.number.desc())
                             .offset((page - 1) * page_size).limit(page_size))).all()
    return [_ser_bill(b, v) for b, v in rows], total


# ───────────────────────── payments made ─────────────────────────
async def create_payment(db, tenant_id, *, vendor_id, payment_date: date, amount: Decimal, paid_from_account_id,
                         allocations: list[tuple[uuid.UUID, Decimal]], currency: str | None = None,
                         rate: Decimal | None = None, method=None, reference=None, notes=None, created_by=None) -> dict:
    v = await _vendor(db, tenant_id, vendor_id)
    base = await led.base_currency(db, tenant_id)
    amount = _q(amount)
    if amount <= 0:
        raise UnprocessableError("Payment amount must be greater than zero")
    cur = (currency or v.currency or base).upper()
    src = (await db.execute(select(FinAccount).where(FinAccount.id == paid_from_account_id, FinAccount.tenant_id == tenant_id,
                                                     FinAccount.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if src is None or src.type != AccountType.ASSET or led.account_kind(src) is None and src.code in ("1000", "1100", "1200", "1500"):
        raise UnprocessableError("Pay from a bank, cash or wallet account")
    fx = await _rate(db, tenant_id, cur, payment_date, rate)

    seen, alloc_total, targets = set(), ZERO, []
    for bid, amt in allocations:
        amt = _q(amt)
        if bid in seen:
            raise UnprocessableError("A bill can appear only once in a payment")
        seen.add(bid)
        if amt <= 0:
            raise UnprocessableError("Allocation amounts must be greater than zero")
        b = await _bill(db, tenant_id, bid, lock=True)
        if b.vendor_id != v.id:
            raise UnprocessableError(f"{b.number} belongs to a different vendor")
        if b.status not in OPEN_STATES:
            raise UnprocessableError(f"{b.number} is {b.status.value} and cannot be paid")
        if b.currency != cur:
            raise UnprocessableError(f"{b.number} is in {b.currency}; the payment must be in the same currency")
        if amt > b.total - b.amount_paid:
            raise UnprocessableError(f"{b.number}: allocation exceeds the balance due")
        alloc_total += amt
        targets.append((b, amt))
    if alloc_total > amount:
        raise UnprocessableError("Allocations exceed the payment amount")

    ap = await _acct_by_code(db, tenant_id, AP_CODE)
    fxa = await _acct_by_code(db, tenant_id, FX_CODE)
    paid_base = _q(amount * fx)
    specs = [led.LineIn(account_id=src.id, side="credit", amount=amount, currency=cur, rate=fx, base_amount=paid_base)]
    ap_total = ZERO
    for b, amt in targets:
        bb = _q(amt * Decimal(b.exchange_rate))              # the payable is relieved at the bill's carrying value
        ap_total += bb
        specs.append(led.LineIn(account_id=ap.id, side="debit", amount=amt, currency=cur, rate=b.exchange_rate,
                                base_amount=bb, description=b.number))
    unalloc = amount - alloc_total
    if unalloc > 0:
        bb = _q(unalloc * fx)
        ap_total += bb
        specs.append(led.LineIn(account_id=ap.id, side="debit", amount=unalloc, currency=cur, rate=fx, base_amount=bb,
                                description="Unapplied (advance to vendor)"))
    diff = ap_total - paid_base          # carried more payable than the cash we paid: gain
    if diff > 0:
        specs.append(led.LineIn(account_id=fxa.id, side="credit", amount=diff, description="Realized FX gain"))
    elif diff < 0:
        specs.append(led.LineIn(account_id=fxa.id, side="debit", amount=-diff, description="Realized FX loss"))

    number = await _next(db, tenant_id, FinBillPayment, "BPAY")
    p = FinBillPayment(tenant_id=tenant_id, number=number, vendor_id=v.id, status=BillPaymentStatus.POSTED,
                       payment_date=payment_date, amount=amount, currency=cur, exchange_rate=fx, paid_from_account_id=src.id,
                       method=method, reference=reference, notes=notes, created_by=created_by)
    db.add(p)
    await db.flush()
    e = await led.post_entry(db, tenant_id, entry_date=payment_date, lines=specs, memo=f"Payment {number} - {v.name}",
                             reference=reference or number, source_type="bill_payment", source_id=p.id, created_by=created_by)
    p.journal_entry_id = e.id
    for b, amt in targets:
        db.add(FinBillPaymentAllocation(tenant_id=tenant_id, payment_id=p.id, bill_id=b.id, amount=amt))
        b.amount_paid = b.amount_paid + amt
        b.status = _status_for(b)
    await db.flush()
    return await get_payment(db, tenant_id, p.id)


async def _payment(db, tenant_id, pid, lock=False) -> FinBillPayment:
    q = select(FinBillPayment).where(FinBillPayment.id == pid, FinBillPayment.tenant_id == tenant_id,
                                     FinBillPayment.is_deleted == False)  # noqa: E712
    if lock:
        q = q.with_for_update()
    p = (await db.execute(q)).scalar_one_or_none()
    if p is None:
        raise NotFoundError("Payment not found")
    return p


async def _allocs(db, pid):
    return (await db.execute(select(FinBillPaymentAllocation, FinBill).join(FinBill, FinBill.id == FinBillPaymentAllocation.bill_id)
                             .where(FinBillPaymentAllocation.payment_id == pid))).all()


def _ser_pay(p: FinBillPayment, v: FinVendor | None, allocs) -> dict:
    applied = sum((a.amount for a, _ in allocs), ZERO)
    return {"id": str(p.id), "number": p.number, "vendor_id": str(p.vendor_id), "vendor_name": v.name if v else None,
            "status": p.status.value, "payment_date": p.payment_date.isoformat(), "amount": str(p.amount),
            "currency": p.currency, "exchange_rate": str(p.exchange_rate), "paid_from_account_id": str(p.paid_from_account_id),
            "method": p.method, "reference": p.reference, "notes": p.notes, "unapplied": str(_q(p.amount - applied)),
            "allocations": [{"bill_id": str(b.id), "bill_number": b.number, "amount": str(a.amount)} for a, b in allocs]}


async def get_payment(db, tenant_id, pid) -> dict:
    p = await _payment(db, tenant_id, pid)
    return _ser_pay(p, await _vendor(db, tenant_id, p.vendor_id), list(await _allocs(db, p.id)))


async def list_payments(db, tenant_id, *, vendor_id=None, page=1, page_size=50) -> tuple[list[dict], int]:
    q = select(FinBillPayment, FinVendor).join(FinVendor, FinVendor.id == FinBillPayment.vendor_id).where(
        FinBillPayment.tenant_id == tenant_id, FinBillPayment.is_deleted == False)  # noqa: E712
    if vendor_id:
        q = q.where(FinBillPayment.vendor_id == vendor_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(q.order_by(FinBillPayment.payment_date.desc(), FinBillPayment.number.desc())
                             .offset((page - 1) * page_size).limit(page_size))).all()
    return [_ser_pay(p, v, list(await _allocs(db, p.id))) for p, v in rows], total


async def void_payment(db, tenant_id, pid, *, reason=None, created_by=None) -> dict:
    p = await _payment(db, tenant_id, pid, lock=True)
    if p.status == BillPaymentStatus.VOID:
        raise ConflictError("Payment is already void")
    await led.void_entry(db, tenant_id, p.journal_entry_id, reason=reason or f"Void {p.number}", created_by=created_by)
    for a, b in await _allocs(db, p.id):
        b = await _bill(db, tenant_id, b.id, lock=True)
        b.amount_paid = b.amount_paid - a.amount
        if b.status != BillStatus.VOID:
            b.status = _status_for(b)
    p.status = BillPaymentStatus.VOID
    await db.flush()
    return await get_payment(db, tenant_id, p.id)
