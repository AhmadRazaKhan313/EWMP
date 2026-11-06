"""Finance Phase 2c: recurring invoices (templates that generate invoices on a schedule) and payment reminders."""
import calendar
import html
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.finance_sales import (FinCustomer, FinInvoice, FinRecurringInvoice, FinRecurringLine, InvoiceStatus,
                                      RecurringFrequency, RecurringStatus)
from app.models.organization import Organization
from app.services import finance_ledger as led
from app.services import finance_mail
from app.services import finance_sales as sales
from app.services.finance_sales import LineSpec, _build_lines, _customer, _q

MAX_CATCHUP = 12            # invoices generated per template in one run, if the scheduler was down for a while
REMIND_EVERY_DAYS = 7
MAX_AUTO_REMINDERS = 3


def step_date(start: date, freq: RecurringFrequency | str, n: int) -> date:
    """start + n periods. Months/years are anchored on start (31 Jan -> 28/29 Feb -> 31 Mar), so dates never drift."""
    f = RecurringFrequency(freq)
    if f == RecurringFrequency.WEEKLY:
        return start + timedelta(weeks=n)
    months = {RecurringFrequency.MONTHLY: 1, RecurringFrequency.QUARTERLY: 3, RecurringFrequency.YEARLY: 12}[f] * n
    y, m = divmod(start.month - 1 + months, 12)
    y, m = start.year + y, m + 1
    return date(y, m, min(start.day, calendar.monthrange(y, m)[1]))


async def _profile(db, tenant_id, rid, lock=False) -> FinRecurringInvoice:
    q = select(FinRecurringInvoice).where(FinRecurringInvoice.id == rid, FinRecurringInvoice.tenant_id == tenant_id,
                                          FinRecurringInvoice.is_deleted == False)  # noqa: E712
    if lock:
        q = q.with_for_update()
    r = (await db.execute(q)).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Recurring invoice not found")
    return r


async def _plines(db, rid) -> list[FinRecurringLine]:
    return list((await db.execute(select(FinRecurringLine).where(FinRecurringLine.recurring_id == rid)
                                  .order_by(FinRecurringLine.line_no))).scalars().all())


def _ser(r: FinRecurringInvoice, cust: FinCustomer | None = None, lines=None, total: Decimal | None = None) -> dict:
    d = {"id": str(r.id), "title": r.title, "customer_id": str(r.customer_id), "customer_name": cust.name if cust else None,
         "status": r.status.value, "frequency": r.frequency.value, "start_date": r.start_date.isoformat(),
         "end_date": r.end_date.isoformat() if r.end_date else None, "next_run_date": r.next_run_date.isoformat(),
         "run_count": r.run_count, "auto_send": r.auto_send, "currency": r.currency, "reference": r.reference,
         "notes": r.notes, "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None, "last_error": r.last_error}
    if total is not None:
        d["amount"] = str(total)
    if lines is not None:
        d["lines"] = [{"description": l.description, "quantity": str(l.quantity), "unit_price": str(l.unit_price),
                       "discount_percent": str(l.discount_percent),
                       "tax_rate_id": str(l.tax_rate_id) if l.tax_rate_id else None,
                       "income_account_id": str(l.income_account_id)} for l in lines]
    return d


async def get_recurring(db, tenant_id, rid) -> dict:
    r = await _profile(db, tenant_id, rid)
    lines = await _plines(db, r.id)
    _, sub, tax = await _build_lines(db, tenant_id, [_spec(l) for l in lines])
    return _ser(r, await _customer(db, tenant_id, r.customer_id), lines, sub + tax)


def _spec(l: FinRecurringLine) -> LineSpec:
    return LineSpec(description=l.description, quantity=l.quantity, unit_price=l.unit_price,
                    discount_percent=l.discount_percent, tax_rate_id=l.tax_rate_id, income_account_id=l.income_account_id)


async def _store_lines(db, tenant_id, rid, specs: list[LineSpec]) -> None:
    rows, _, _ = await _build_lines(db, tenant_id, specs)       # validates and resolves the default income account
    for old in await _plines(db, rid):
        await db.delete(old)
    await db.flush()
    for r in rows:
        db.add(FinRecurringLine(tenant_id=tenant_id, recurring_id=rid, line_no=r["line_no"], description=r["description"],
                                quantity=r["quantity"], unit_price=r["unit_price"], discount_percent=r["discount_percent"],
                                tax_rate_id=r["tax_rate_id"], income_account_id=r["income_account_id"]))
    await db.flush()


async def create_recurring(db, tenant_id, *, title, customer_id, frequency: str, start_date: date, end_date: date | None,
                           lines: list[LineSpec], auto_send=False, currency=None, reference=None, notes=None,
                           created_by=None) -> dict:
    cust = await _customer(db, tenant_id, customer_id)
    if not title.strip():
        raise UnprocessableError("Give the schedule a title")
    if end_date and end_date < start_date:
        raise UnprocessableError("End date cannot be before the start date")
    base = await led.base_currency(db, tenant_id)
    r = FinRecurringInvoice(tenant_id=tenant_id, title=title.strip(), customer_id=cust.id, frequency=RecurringFrequency(frequency),
                            start_date=start_date, end_date=end_date, next_run_date=start_date, auto_send=auto_send,
                            currency=(currency or cust.currency or base).upper(), reference=reference, notes=notes,
                            created_by=created_by)
    db.add(r)
    await db.flush()
    await _store_lines(db, tenant_id, r.id, lines)
    return await get_recurring(db, tenant_id, r.id)


async def update_recurring(db, tenant_id, rid, *, title=None, frequency=None, end_date=..., lines=None, auto_send=None,
                           reference=None, notes=None) -> dict:
    r = await _profile(db, tenant_id, rid, lock=True)
    if title is not None:
        r.title = title.strip() or r.title
    if frequency is not None and frequency != r.frequency.value:
        if r.run_count:
            raise ConflictError("The schedule has already run; change the frequency by creating a new one")
        r.frequency = RecurringFrequency(frequency)
    if end_date is not ...:
        if end_date and end_date < r.start_date:
            raise UnprocessableError("End date cannot be before the start date")
        r.end_date = end_date
    if auto_send is not None:
        r.auto_send = auto_send
    if reference is not None:
        r.reference = reference
    if notes is not None:
        r.notes = notes
    if lines is not None:
        await _store_lines(db, tenant_id, r.id, lines)
    if r.status == RecurringStatus.ENDED and (r.end_date is None or r.next_run_date <= r.end_date):
        r.status = RecurringStatus.ACTIVE
    await db.flush()
    return await get_recurring(db, tenant_id, r.id)


async def set_state(db, tenant_id, rid, action: str) -> dict:
    r = await _profile(db, tenant_id, rid, lock=True)
    if action == "pause":
        if r.status != RecurringStatus.ACTIVE:
            raise ConflictError("Only an active schedule can be paused")
        r.status = RecurringStatus.PAUSED
    elif action == "resume":
        if r.status != RecurringStatus.PAUSED:
            raise ConflictError("Only a paused schedule can be resumed")
        # do not back-fill the weeks it was paused: skip forward to the first future date
        n = r.run_count
        nxt = step_date(r.start_date, r.frequency, n)
        while nxt < date.today():
            n += 1
            nxt = step_date(r.start_date, r.frequency, n)
        r.run_count, r.next_run_date = n, nxt
        r.status = RecurringStatus.ACTIVE
    else:
        raise UnprocessableError("Unknown action")
    await db.flush()
    return await get_recurring(db, tenant_id, r.id)


async def delete_recurring(db, tenant_id, rid) -> None:
    r = await _profile(db, tenant_id, rid, lock=True)
    r.is_deleted = True
    r.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def list_recurring(db, tenant_id) -> list[dict]:
    rows = (await db.execute(select(FinRecurringInvoice, FinCustomer).join(FinCustomer, FinCustomer.id == FinRecurringInvoice.customer_id)
                             .where(FinRecurringInvoice.tenant_id == tenant_id, FinRecurringInvoice.is_deleted == False)  # noqa: E712
                             .order_by(FinRecurringInvoice.next_run_date))).all()
    return [_ser(r, c) for r, c in rows]


# ───────────────────────── generation ─────────────────────────
async def _generate_one(db, r: FinRecurringInvoice, today: date) -> int:
    made = 0
    specs = [_spec(l) for l in await _plines(db, r.id)]
    while r.status == RecurringStatus.ACTIVE and r.next_run_date <= today and made < MAX_CATCHUP:
        if r.end_date and r.next_run_date > r.end_date:
            r.status = RecurringStatus.ENDED
            break
        inv = await sales.create_invoice(db, r.tenant_id, customer_id=r.customer_id, issue_date=r.next_run_date, due_date=None,
                                         lines=specs, currency=r.currency, reference=r.reference or r.title, notes=r.notes,
                                         post=r.auto_send, created_by=r.created_by, recurring_id=r.id)
        made += 1
        r.run_count += 1
        r.next_run_date = step_date(r.start_date, r.frequency, r.run_count)
        r.last_run_at = datetime.now(timezone.utc)
        r.last_error = None
        if r.end_date and r.next_run_date > r.end_date:
            r.status = RecurringStatus.ENDED
    return made


async def run_due(db, *, tenant_id: uuid.UUID | None = None, today: date | None = None) -> dict:
    """Generate every invoice that is due. One broken template is recorded and skipped; it never blocks the rest."""
    today = today or date.today()
    q = select(FinRecurringInvoice).where(FinRecurringInvoice.is_deleted == False,  # noqa: E712
                                          FinRecurringInvoice.status == RecurringStatus.ACTIVE,
                                          FinRecurringInvoice.next_run_date <= today)
    if tenant_id:
        q = q.where(FinRecurringInvoice.tenant_id == tenant_id)
    profiles = (await db.execute(q.order_by(FinRecurringInvoice.next_run_date).with_for_update(skip_locked=True))).scalars().all()
    created, failed = 0, []
    for r in profiles:
        rid, title = r.id, r.title
        try:
            async with db.begin_nested():
                created += await _generate_one(db, r, today)
        except Exception as e:  # noqa: BLE001 - recorded on the template, shown in the UI
            await db.refresh(r)
            r.last_error = (getattr(e, "message", None) or str(e))[:500]
            failed.append({"id": str(rid), "title": title, "error": r.last_error})
    await db.flush()
    return {"created": created, "failed": failed}


# ───────────────────────── reminders ─────────────────────────
def _reminder_html(org: str, cust: FinCustomer, inv: FinInvoice) -> tuple[str, str]:
    days = (date.today() - inv.due_date).days
    when = f"{days} day{'s' if days != 1 else ''} overdue" if days > 0 else "due today" if days == 0 else f"due on {inv.due_date}"
    bal = f"{inv.currency} {_q(inv.total - inv.amount_paid):,.2f}"
    subject = f"Payment reminder: invoice {inv.number} ({when})"
    body = (f"<p>Dear {html.escape(cust.name)},</p>"
            f"<p>This is a friendly reminder that invoice <b>{html.escape(inv.number)}</b> from {html.escape(org)} "
            f"for <b>{html.escape(bal)}</b> was due on {inv.due_date} ({when}).</p>"
            f"<p>If you have already paid, please ignore this message and accept our thanks.</p>"
            f"<p>Regards,<br>{html.escape(org)}</p>")
    return subject, body


async def send_reminder(db, tenant_id, invoice_id) -> dict:
    inv = await sales._invoice(db, tenant_id, invoice_id, lock=True)
    if inv.status not in (InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID) or inv.total - inv.amount_paid <= 0:
        raise ConflictError("Only an unpaid, sent invoice can be reminded")
    cust = await _customer(db, tenant_id, inv.customer_id)
    if not cust.email:
        raise UnprocessableError("This customer has no email address")
    org = (await db.execute(select(Organization).where(Organization.id == tenant_id))).scalar_one()
    subject, body = _reminder_html(org.display_name or org.name, cust, inv)
    try:
        await finance_mail.deliver(cust.email, subject, body)
    except Exception as e:  # noqa: BLE001
        raise UnprocessableError(f"The email could not be sent: {e}") from e
    inv.reminder_count += 1
    inv.last_reminded_at = datetime.now(timezone.utc)
    await db.flush()
    return await sales.get_invoice(db, tenant_id, inv.id)


async def sweep_reminders(db, *, tenant_id: uuid.UUID | None = None, today: date | None = None) -> dict:
    """Remind customers who opted in (auto_remind) about overdue invoices: at most every 7 days, at most 3 times."""
    today = today or date.today()
    cutoff = datetime.now(timezone.utc) - timedelta(days=REMIND_EVERY_DAYS)
    q = (select(FinInvoice.id, FinInvoice.tenant_id).join(FinCustomer, FinCustomer.id == FinInvoice.customer_id)
         .where(FinInvoice.is_deleted == False, FinCustomer.auto_remind == True, FinCustomer.email.is_not(None),  # noqa: E712
                FinInvoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID]),
                FinInvoice.due_date < today, FinInvoice.total > FinInvoice.amount_paid,
                FinInvoice.reminder_count < MAX_AUTO_REMINDERS,
                (FinInvoice.last_reminded_at.is_(None)) | (FinInvoice.last_reminded_at < cutoff)))
    if tenant_id:
        q = q.where(FinInvoice.tenant_id == tenant_id)
    sent, failed = 0, 0
    for iid, tid in (await db.execute(q)).all():
        try:
            async with db.begin_nested():
                await send_reminder(db, tid, iid)
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
    return {"sent": sent, "failed": failed}
