"""Finance Phase 2a: customers, invoices and payments received, all posting to the ledger."""
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.finance import AccountType, FinAccount, FinTaxRate
from app.models.finance_sales import (FinCustomer, FinInvoice, FinInvoiceLine, FinPayment, FinPaymentAllocation,
                                      InvoiceStatus, PaymentStatus)
from app.services import finance_ledger as led

AR_CODE, TAX_CODE, FX_CODE, INCOME_CODE = "1100", "2200", "5950", "4010"
ZERO = Decimal("0")


def _q(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class LineSpec:
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal = ZERO
    tax_rate_id: uuid.UUID | None = None
    income_account_id: uuid.UUID | None = None


# ───────────────────────── helpers ─────────────────────────
async def _acct_by_code(db, tenant_id, code) -> FinAccount:
    await led.ensure_chart(db, tenant_id)
    a = (await db.execute(select(FinAccount).where(FinAccount.tenant_id == tenant_id, FinAccount.code == code,
                                                   FinAccount.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if a is None:
        raise UnprocessableError(f"System account {code} is missing")
    return a


async def _next(db, tenant_id, model, prefix: str) -> str:
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"fin-{prefix}-{tenant_id}"})
    last = (await db.execute(select(func.max(model.number)).where(model.tenant_id == tenant_id))).scalar()
    return f"{prefix}-{(int(last.split('-')[1]) + 1) if last else 1:06d}"


async def _customer(db, tenant_id, cid) -> FinCustomer:
    c = (await db.execute(select(FinCustomer).where(FinCustomer.id == cid, FinCustomer.tenant_id == tenant_id,
                                                    FinCustomer.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if c is None:
        raise NotFoundError("Customer not found")
    return c


async def _invoice(db, tenant_id, iid, lock=False) -> FinInvoice:
    q = select(FinInvoice).where(FinInvoice.id == iid, FinInvoice.tenant_id == tenant_id, FinInvoice.is_deleted == False)  # noqa: E712
    if lock:
        q = q.with_for_update()
    inv = (await db.execute(q)).scalar_one_or_none()
    if inv is None:
        raise NotFoundError("Invoice not found")
    return inv


async def _lines(db, inv_id) -> list[FinInvoiceLine]:
    return list((await db.execute(select(FinInvoiceLine).where(FinInvoiceLine.invoice_id == inv_id)
                                  .order_by(FinInvoiceLine.line_no))).scalars().all())


async def _rate(db, tenant_id, currency, on, given) -> Decimal:
    base = await led.base_currency(db, tenant_id)
    if currency == base:
        return Decimal("1")
    if given is not None:
        if Decimal(given) <= 0:
            raise UnprocessableError("Rate must be greater than zero")
        return Decimal(given)
    return await led._rate_for(db, tenant_id, currency, on)


def _status_for(inv: FinInvoice) -> InvoiceStatus:
    if inv.amount_paid >= inv.total:
        return InvoiceStatus.PAID
    return InvoiceStatus.PARTIALLY_PAID if inv.amount_paid > 0 else InvoiceStatus.SENT


def _ser_inv(inv: FinInvoice, cust: FinCustomer | None = None, lines: list[FinInvoiceLine] | None = None) -> dict:
    balance = _q(inv.total - inv.amount_paid)
    overdue = inv.status in (InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID) and balance > 0 and inv.due_date < date.today()
    d = {"id": str(inv.id), "number": inv.number, "customer_id": str(inv.customer_id),
         "customer_name": cust.name if cust else None, "status": inv.status.value, "is_overdue": overdue,
         "issue_date": inv.issue_date.isoformat(), "due_date": inv.due_date.isoformat(), "currency": inv.currency,
         "exchange_rate": str(inv.exchange_rate), "subtotal": str(inv.subtotal), "tax_total": str(inv.tax_total),
         "total": str(inv.total), "amount_paid": str(inv.amount_paid), "balance": str(balance),
         "reference": inv.reference, "notes": inv.notes, "recurring_id": str(inv.recurring_id) if inv.recurring_id else None,
         "reminder_count": inv.reminder_count,
         "last_reminded_at": inv.last_reminded_at.isoformat() if inv.last_reminded_at else None,
         "journal_entry_id": str(inv.journal_entry_id) if inv.journal_entry_id else None}
    if lines is not None:
        d["lines"] = [{"id": str(l.id), "description": l.description, "quantity": str(l.quantity),
                       "unit_price": str(l.unit_price), "discount_percent": str(l.discount_percent),
                       "tax_rate_id": str(l.tax_rate_id) if l.tax_rate_id else None, "tax_percent": str(l.tax_percent),
                       "income_account_id": str(l.income_account_id), "net_amount": str(l.net_amount),
                       "tax_amount": str(l.tax_amount)} for l in lines]
    return d


# ───────────────────────── customers ─────────────────────────
def _ser_cust(c: FinCustomer, balance: Decimal | None = None) -> dict:
    d = {"id": str(c.id), "name": c.name, "company": c.company, "email": c.email, "phone": c.phone,
         "address": c.address, "currency": c.currency, "payment_terms_days": c.payment_terms_days,
         "notes": c.notes, "is_active": c.is_active, "auto_remind": c.auto_remind}
    if balance is not None:
        d["balance"] = str(balance)
    return d


async def create_customer(db, tenant_id, **f) -> dict:
    if not (f.get("name") or "").strip():
        raise UnprocessableError("Customer name is required")
    if f.get("currency"):
        f["currency"] = f["currency"].upper()
    c = FinCustomer(tenant_id=tenant_id, **f)
    db.add(c)
    await db.flush()
    return _ser_cust(c, ZERO)


async def update_customer(db, tenant_id, cid, **f) -> dict:
    c = await _customer(db, tenant_id, cid)
    for k, v in f.items():
        if k == "currency" and v:
            v = v.upper()
        setattr(c, k, v)
    await db.flush()
    return _ser_cust(c)


async def _balances(db, tenant_id) -> dict:
    rows = (await db.execute(
        select(FinInvoice.customer_id, func.sum(FinInvoice.total - FinInvoice.amount_paid))
        .where(FinInvoice.tenant_id == tenant_id, FinInvoice.is_deleted == False,  # noqa: E712
               FinInvoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID]))
        .group_by(FinInvoice.customer_id))).all()
    return {r[0]: Decimal(r[1] or 0) for r in rows}


async def list_customers(db, tenant_id, search: str | None = None, include_inactive=False) -> list[dict]:
    q = select(FinCustomer).where(FinCustomer.tenant_id == tenant_id, FinCustomer.is_deleted == False)  # noqa: E712
    if not include_inactive:
        q = q.where(FinCustomer.is_active == True)  # noqa: E712
    if search:
        q = q.where(FinCustomer.name.ilike(f"%{search}%") | FinCustomer.company.ilike(f"%{search}%"))
    rows = (await db.execute(q.order_by(FinCustomer.name))).scalars().all()
    bal = await _balances(db, tenant_id)
    return [_ser_cust(c, bal.get(c.id, ZERO)) for c in rows]


async def customer_statement(db, tenant_id, cid) -> dict:
    c = await _customer(db, tenant_id, cid)
    invs = (await db.execute(select(FinInvoice).where(
        FinInvoice.tenant_id == tenant_id, FinInvoice.customer_id == cid, FinInvoice.is_deleted == False,  # noqa: E712
        FinInvoice.status != InvoiceStatus.DRAFT, FinInvoice.status != InvoiceStatus.VOID)
        .order_by(FinInvoice.issue_date, FinInvoice.number))).scalars().all()
    pays = (await db.execute(select(FinPayment).where(
        FinPayment.tenant_id == tenant_id, FinPayment.customer_id == cid, FinPayment.is_deleted == False,  # noqa: E712
        FinPayment.status == PaymentStatus.POSTED).order_by(FinPayment.payment_date, FinPayment.number))).scalars().all()
    events = [(i.issue_date, 0, {"date": i.issue_date.isoformat(), "type": "invoice", "number": i.number,
                                 "currency": i.currency, "debit": str(i.total), "credit": "0.00"}) for i in invs]
    events += [(p.payment_date, 1, {"date": p.payment_date.isoformat(), "type": "payment", "number": p.number,
                                    "currency": p.currency, "debit": "0.00", "credit": str(p.amount)}) for p in pays]
    events.sort(key=lambda e: (e[0], e[1]))
    run: dict[str, Decimal] = {}
    out = []
    for _, _, e in events:
        run[e["currency"]] = run.get(e["currency"], ZERO) + Decimal(e["debit"]) - Decimal(e["credit"])
        out.append({**e, "balance": str(run[e["currency"]])})
    return {"customer": _ser_cust(c), "lines": out, "balances": {k: str(v) for k, v in run.items()}}


# ───────────────────────── invoices ─────────────────────────
async def _build_lines(db, tenant_id, specs: list[LineSpec]) -> tuple[list[dict], Decimal, Decimal]:
    if not specs:
        raise UnprocessableError("An invoice needs at least one line")
    default_income = None
    out, sub, tax = [], ZERO, ZERO
    for i, s in enumerate(specs, start=1):
        if Decimal(s.quantity) <= 0 or Decimal(s.unit_price) < 0:
            raise UnprocessableError(f"Line {i}: quantity must be > 0 and price >= 0")
        disc = Decimal(s.discount_percent or 0)
        if not (ZERO <= disc <= 100):
            raise UnprocessableError(f"Line {i}: discount must be between 0 and 100")
        acct_id = s.income_account_id
        if acct_id is None:
            default_income = default_income or await _acct_by_code(db, tenant_id, INCOME_CODE)
            acct_id = default_income.id
        else:
            a = (await db.execute(select(FinAccount).where(FinAccount.id == acct_id, FinAccount.tenant_id == tenant_id,
                                                           FinAccount.is_deleted == False))).scalar_one_or_none()  # noqa: E712
            if a is None or a.type != AccountType.INCOME:
                raise UnprocessableError(f"Line {i}: pick an income account")
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
                        income_account_id=acct_id, net_amount=net, tax_amount=tx))
        if not out[-1]["description"]:
            raise UnprocessableError(f"Line {i}: description is required")
    return out, sub, tax


async def create_invoice(db, tenant_id, *, customer_id, issue_date: date, due_date: date | None, lines: list[LineSpec],
                         currency: str | None = None, rate: Decimal | None = None, reference=None, notes=None,
                         post: bool = False, created_by=None, recurring_id=None) -> dict:
    cust = await _customer(db, tenant_id, customer_id)
    base = await led.base_currency(db, tenant_id)
    cur = (currency or cust.currency or base).upper()
    due = due_date or issue_date + timedelta(days=cust.payment_terms_days or 0)
    if due < issue_date:
        raise UnprocessableError("Due date cannot be before the issue date")
    rows, sub, tax = await _build_lines(db, tenant_id, lines)
    fx = await _rate(db, tenant_id, cur, issue_date, rate)
    inv = FinInvoice(tenant_id=tenant_id, number=await _next(db, tenant_id, FinInvoice, "INV"), customer_id=cust.id,
                     status=InvoiceStatus.DRAFT, issue_date=issue_date, due_date=due, currency=cur, exchange_rate=fx,
                     subtotal=sub, tax_total=tax, total=sub + tax, amount_paid=ZERO, reference=reference, notes=notes,
                     created_by=created_by, recurring_id=recurring_id)
    db.add(inv)
    await db.flush()
    for r in rows:
        db.add(FinInvoiceLine(tenant_id=tenant_id, invoice_id=inv.id, **r))
    await db.flush()
    if post:
        await send_invoice(db, tenant_id, inv.id, created_by=created_by)
    return await get_invoice(db, tenant_id, inv.id)


async def update_invoice(db, tenant_id, iid, *, customer_id=None, issue_date=None, due_date=None, lines=None,
                         currency=None, rate=None, reference=None, notes=None) -> dict:
    inv = await _invoice(db, tenant_id, iid, lock=True)
    if inv.status != InvoiceStatus.DRAFT:
        raise ConflictError("Only draft invoices can be edited. Void it and create a new one.")
    if customer_id:
        inv.customer_id = (await _customer(db, tenant_id, customer_id)).id
    inv.issue_date = issue_date or inv.issue_date
    inv.due_date = due_date or inv.due_date
    if inv.due_date < inv.issue_date:
        raise UnprocessableError("Due date cannot be before the issue date")
    if currency:
        inv.currency = currency.upper()
    inv.exchange_rate = await _rate(db, tenant_id, inv.currency, inv.issue_date, rate)
    if reference is not None:
        inv.reference = reference
    if notes is not None:
        inv.notes = notes
    if lines is not None:
        rows, sub, tax = await _build_lines(db, tenant_id, lines)
        for old in await _lines(db, inv.id):
            await db.delete(old)
        await db.flush()
        for r in rows:
            db.add(FinInvoiceLine(tenant_id=tenant_id, invoice_id=inv.id, **r))
        inv.subtotal, inv.tax_total, inv.total = sub, tax, sub + tax
    await db.flush()
    return await get_invoice(db, tenant_id, inv.id)


async def send_invoice(db, tenant_id, iid, *, created_by=None) -> dict:
    inv = await _invoice(db, tenant_id, iid, lock=True)
    if inv.status != InvoiceStatus.DRAFT:
        raise ConflictError("Invoice is already sent")
    if inv.total <= 0:
        raise UnprocessableError("Cannot post an invoice with a zero total")
    ar = await _acct_by_code(db, tenant_id, AR_CODE)
    tax_default = await _acct_by_code(db, tenant_id, TAX_CODE)
    fx = Decimal(inv.exchange_rate)
    lines = await _lines(db, inv.id)

    credits: dict[uuid.UUID, Decimal] = {}
    tax_ids = {l.tax_rate_id for l in lines if l.tax_rate_id}
    tax_acc = {}
    if tax_ids:
        for t in (await db.execute(select(FinTaxRate).where(FinTaxRate.id.in_(tax_ids)))).scalars():
            tax_acc[t.id] = t.account_id
    for l in lines:
        credits[l.income_account_id] = credits.get(l.income_account_id, ZERO) + _q(l.net_amount * fx)
        if l.tax_amount > 0:
            acc = tax_acc.get(l.tax_rate_id) or tax_default.id
            credits[acc] = credits.get(acc, ZERO) + _q(l.tax_amount * fx)
    base_total = _q(inv.total * fx)
    diff = base_total - sum(credits.values())          # rounding across lines goes to the biggest credit
    if diff:
        big = max(credits, key=lambda k: credits[k])
        credits[big] += diff
    specs = [led.LineIn(account_id=ar.id, side="debit", amount=inv.total, currency=inv.currency, rate=fx,
                        base_amount=base_total, description=inv.number)]
    for acc, base_amt in credits.items():
        if base_amt <= 0:
            continue
        orig = _q(base_amt / fx) if fx else base_amt
        specs.append(led.LineIn(account_id=acc, side="credit", amount=orig, currency=inv.currency, rate=fx,
                                base_amount=base_amt))
    cust = await _customer(db, tenant_id, inv.customer_id)
    e = await led.post_entry(db, tenant_id, entry_date=inv.issue_date, lines=specs, memo=f"Invoice {inv.number} - {cust.name}",
                             reference=inv.number, source_type="invoice", source_id=inv.id, created_by=created_by)
    inv.journal_entry_id = e.id
    inv.status = InvoiceStatus.SENT
    await db.flush()
    return await get_invoice(db, tenant_id, inv.id)


async def void_invoice(db, tenant_id, iid, *, reason=None, created_by=None) -> dict:
    inv = await _invoice(db, tenant_id, iid, lock=True)
    if inv.status == InvoiceStatus.VOID:
        raise ConflictError("Invoice is already void")
    if inv.status == InvoiceStatus.DRAFT:
        raise ConflictError("Draft invoices are deleted, not voided")
    if inv.amount_paid > 0:
        raise ConflictError("This invoice has payments. Void the payment(s) first.")
    await led.void_entry(db, tenant_id, inv.journal_entry_id, reason=reason or f"Void {inv.number}", created_by=created_by)
    inv.status = InvoiceStatus.VOID
    await db.flush()
    return await get_invoice(db, tenant_id, inv.id)


async def delete_draft(db, tenant_id, iid) -> None:
    inv = await _invoice(db, tenant_id, iid, lock=True)
    if inv.status != InvoiceStatus.DRAFT:
        raise ConflictError("Only draft invoices can be deleted")
    inv.is_deleted = True
    inv.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def get_invoice(db, tenant_id, iid) -> dict:
    inv = await _invoice(db, tenant_id, iid)
    cust = await _customer(db, tenant_id, inv.customer_id)
    d = _ser_inv(inv, cust, await _lines(db, inv.id))
    allocs = (await db.execute(
        select(FinPaymentAllocation, FinPayment).join(FinPayment, FinPayment.id == FinPaymentAllocation.payment_id)
        .where(FinPaymentAllocation.invoice_id == inv.id, FinPayment.status == PaymentStatus.POSTED,
               FinPaymentAllocation.is_deleted == False))).all()  # noqa: E712
    d["payments"] = [{"payment_id": str(p.id), "number": p.number, "date": p.payment_date.isoformat(),
                      "amount": str(a.amount)} for a, p in allocs]
    return d


async def list_invoices(db, tenant_id, *, status: str | None = None, customer_id=None, search: str | None = None,
                        page=1, page_size=50) -> tuple[list[dict], int]:
    q = select(FinInvoice, FinCustomer).join(FinCustomer, FinCustomer.id == FinInvoice.customer_id).where(
        FinInvoice.tenant_id == tenant_id, FinInvoice.is_deleted == False)  # noqa: E712
    if customer_id:
        q = q.where(FinInvoice.customer_id == customer_id)
    if status == "overdue":
        q = q.where(FinInvoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID]),
                    FinInvoice.due_date < date.today(), FinInvoice.total > FinInvoice.amount_paid)
    elif status:
        q = q.where(FinInvoice.status == InvoiceStatus(status))
    if search:
        q = q.where(FinInvoice.number.ilike(f"%{search}%") | FinCustomer.name.ilike(f"%{search}%")
                    | FinInvoice.reference.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(q.order_by(FinInvoice.issue_date.desc(), FinInvoice.number.desc())
                             .offset((page - 1) * page_size).limit(page_size))).all()
    return [_ser_inv(i, c) for i, c in rows], total


# ───────────────────────── payments ─────────────────────────
async def create_payment(db, tenant_id, *, customer_id, payment_date: date, amount: Decimal, deposit_account_id,
                         allocations: list[tuple[uuid.UUID, Decimal]], currency: str | None = None,
                         rate: Decimal | None = None, method=None, reference=None, notes=None, created_by=None) -> dict:
    cust = await _customer(db, tenant_id, customer_id)
    base = await led.base_currency(db, tenant_id)
    amount = _q(amount)
    if amount <= 0:
        raise UnprocessableError("Payment amount must be greater than zero")
    cur = (currency or cust.currency or base).upper()
    dep = (await db.execute(select(FinAccount).where(FinAccount.id == deposit_account_id, FinAccount.tenant_id == tenant_id,
                                                     FinAccount.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if dep is None or dep.type != AccountType.ASSET:
        raise UnprocessableError("Deposit account must be a bank / cash (asset) account")
    fx = await _rate(db, tenant_id, cur, payment_date, rate)

    seen, alloc_total, targets = set(), ZERO, []
    for iid, amt in allocations:
        amt = _q(amt)
        if iid in seen:
            raise UnprocessableError("An invoice can appear only once in a payment")
        seen.add(iid)
        if amt <= 0:
            raise UnprocessableError("Allocation amounts must be greater than zero")
        inv = await _invoice(db, tenant_id, iid, lock=True)
        if inv.customer_id != cust.id:
            raise UnprocessableError(f"{inv.number} belongs to a different customer")
        if inv.status not in (InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID):
            raise UnprocessableError(f"{inv.number} is {inv.status.value} and cannot receive payment")
        if inv.currency != cur:
            raise UnprocessableError(f"{inv.number} is in {inv.currency}; the payment must be in the same currency")
        if amt > inv.total - inv.amount_paid:
            raise UnprocessableError(f"{inv.number}: allocation exceeds the balance due")
        alloc_total += amt
        targets.append((inv, amt))
    if alloc_total > amount:
        raise UnprocessableError("Allocations exceed the payment amount")

    ar = await _acct_by_code(db, tenant_id, AR_CODE)
    fxa = await _acct_by_code(db, tenant_id, FX_CODE)
    dep_base = _q(amount * fx)
    specs = [led.LineIn(account_id=dep.id, side="debit", amount=amount, currency=cur, rate=fx, base_amount=dep_base)]
    ar_total = ZERO
    for inv, amt in targets:
        b = _q(amt * Decimal(inv.exchange_rate))             # AR is relieved at the invoice's carrying value
        ar_total += b
        specs.append(led.LineIn(account_id=ar.id, side="credit", amount=amt, currency=cur, rate=inv.exchange_rate,
                                base_amount=b, description=inv.number))
    unalloc = amount - alloc_total
    if unalloc > 0:
        b = _q(unalloc * fx)
        ar_total += b
        specs.append(led.LineIn(account_id=ar.id, side="credit", amount=unalloc, currency=cur, rate=fx,
                                base_amount=b, description="Unapplied (customer credit)"))
    diff = dep_base - ar_total
    if diff > 0:       # received more PKR than the receivable carried: gain
        specs.append(led.LineIn(account_id=fxa.id, side="credit", amount=diff, description="Realized FX gain"))
    elif diff < 0:
        specs.append(led.LineIn(account_id=fxa.id, side="debit", amount=-diff, description="Realized FX loss"))

    number = await _next(db, tenant_id, FinPayment, "PAY")
    p = FinPayment(tenant_id=tenant_id, number=number, customer_id=cust.id, status=PaymentStatus.POSTED,
                   payment_date=payment_date, amount=amount, currency=cur, exchange_rate=fx, deposit_account_id=dep.id,
                   method=method, reference=reference, notes=notes, created_by=created_by)
    db.add(p)
    await db.flush()
    e = await led.post_entry(db, tenant_id, entry_date=payment_date, lines=specs, memo=f"Payment {number} - {cust.name}",
                             reference=reference or number, source_type="payment", source_id=p.id, created_by=created_by)
    p.journal_entry_id = e.id
    for inv, amt in targets:
        db.add(FinPaymentAllocation(tenant_id=tenant_id, payment_id=p.id, invoice_id=inv.id, amount=amt))
        inv.amount_paid = inv.amount_paid + amt
        inv.status = _status_for(inv)
    await db.flush()
    return await get_payment(db, tenant_id, p.id)


async def _payment(db, tenant_id, pid, lock=False) -> FinPayment:
    q = select(FinPayment).where(FinPayment.id == pid, FinPayment.tenant_id == tenant_id, FinPayment.is_deleted == False)  # noqa: E712
    if lock:
        q = q.with_for_update()
    p = (await db.execute(q)).scalar_one_or_none()
    if p is None:
        raise NotFoundError("Payment not found")
    return p


def _ser_pay(p: FinPayment, cust: FinCustomer | None, allocs: list[tuple[FinPaymentAllocation, FinInvoice]]) -> dict:
    applied = sum((a.amount for a, _ in allocs), ZERO)
    return {"id": str(p.id), "number": p.number, "customer_id": str(p.customer_id),
            "customer_name": cust.name if cust else None, "status": p.status.value,
            "payment_date": p.payment_date.isoformat(), "amount": str(p.amount), "currency": p.currency,
            "exchange_rate": str(p.exchange_rate), "deposit_account_id": str(p.deposit_account_id),
            "method": p.method, "reference": p.reference, "notes": p.notes,
            "unapplied": str(_q(p.amount - applied)),
            "allocations": [{"invoice_id": str(i.id), "invoice_number": i.number, "amount": str(a.amount)} for a, i in allocs]}


async def _allocs(db, pid):
    return (await db.execute(select(FinPaymentAllocation, FinInvoice).join(FinInvoice, FinInvoice.id == FinPaymentAllocation.invoice_id)
                             .where(FinPaymentAllocation.payment_id == pid))).all()


async def get_payment(db, tenant_id, pid) -> dict:
    p = await _payment(db, tenant_id, pid)
    return _ser_pay(p, await _customer(db, tenant_id, p.customer_id), [(a, i) for a, i in await _allocs(db, p.id)])


async def list_payments(db, tenant_id, *, customer_id=None, page=1, page_size=50) -> tuple[list[dict], int]:
    q = select(FinPayment, FinCustomer).join(FinCustomer, FinCustomer.id == FinPayment.customer_id).where(
        FinPayment.tenant_id == tenant_id, FinPayment.is_deleted == False)  # noqa: E712
    if customer_id:
        q = q.where(FinPayment.customer_id == customer_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(q.order_by(FinPayment.payment_date.desc(), FinPayment.number.desc())
                             .offset((page - 1) * page_size).limit(page_size))).all()
    out = []
    for p, c in rows:
        out.append(_ser_pay(p, c, [(a, i) for a, i in await _allocs(db, p.id)]))
    return out, total


async def void_payment(db, tenant_id, pid, *, reason=None, created_by=None) -> dict:
    p = await _payment(db, tenant_id, pid, lock=True)
    if p.status == PaymentStatus.VOID:
        raise ConflictError("Payment is already void")
    await led.void_entry(db, tenant_id, p.journal_entry_id, reason=reason or f"Void {p.number}", created_by=created_by)
    for a, inv in await _allocs(db, p.id):
        inv = await _invoice(db, tenant_id, inv.id, lock=True)
        inv.amount_paid = inv.amount_paid - a.amount
        if inv.status != InvoiceStatus.VOID:
            inv.status = _status_for(inv)
    p.status = PaymentStatus.VOID
    await db.flush()
    return await get_payment(db, tenant_id, p.id)
