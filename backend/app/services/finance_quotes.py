"""Finance Phase 2b: quotes. They never touch the ledger; converting one creates a draft invoice."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.finance_sales import FinCustomer, FinInvoice, FinQuote, FinQuoteLine, QuoteStatus
from app.services import finance_ledger as led
from app.services import finance_sales as sales
from app.services.finance_sales import LineSpec, _build_lines, _customer, _next, ZERO

DEFAULT_VALID_DAYS = 30


async def _quote(db, tenant_id, qid, lock=False) -> FinQuote:
    q = select(FinQuote).where(FinQuote.id == qid, FinQuote.tenant_id == tenant_id, FinQuote.is_deleted == False)  # noqa: E712
    if lock:
        q = q.with_for_update()
    r = (await db.execute(q)).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Quote not found")
    return r


async def _lines(db, qid) -> list[FinQuoteLine]:
    return list((await db.execute(select(FinQuoteLine).where(FinQuoteLine.quote_id == qid).order_by(FinQuoteLine.line_no))).scalars().all())


def _ser(q: FinQuote, cust: FinCustomer | None = None, lines: list[FinQuoteLine] | None = None) -> dict:
    d = {"id": str(q.id), "number": q.number, "customer_id": str(q.customer_id), "customer_name": cust.name if cust else None,
         "status": q.status.value, "is_expired": q.status == QuoteStatus.SENT and q.valid_until < date.today(),
         "issue_date": q.issue_date.isoformat(), "valid_until": q.valid_until.isoformat(), "currency": q.currency,
         "subtotal": str(q.subtotal), "tax_total": str(q.tax_total), "total": str(q.total),
         "reference": q.reference, "notes": q.notes, "invoice_id": str(q.invoice_id) if q.invoice_id else None}
    if lines is not None:
        d["lines"] = [{"id": str(l.id), "description": l.description, "quantity": str(l.quantity), "unit_price": str(l.unit_price),
                       "discount_percent": str(l.discount_percent), "tax_rate_id": str(l.tax_rate_id) if l.tax_rate_id else None,
                       "tax_percent": str(l.tax_percent), "income_account_id": str(l.income_account_id),
                       "net_amount": str(l.net_amount), "tax_amount": str(l.tax_amount)} for l in lines]
    return d


async def get_quote(db, tenant_id, qid) -> dict:
    q = await _quote(db, tenant_id, qid)
    return _ser(q, await _customer(db, tenant_id, q.customer_id), await _lines(db, q.id))


async def create_quote(db, tenant_id, *, customer_id, issue_date: date, valid_until: date | None, lines: list[LineSpec],
                       currency: str | None = None, reference=None, notes=None, send: bool = False, created_by=None) -> dict:
    cust = await _customer(db, tenant_id, customer_id)
    base = await led.base_currency(db, tenant_id)
    valid = valid_until or issue_date + timedelta(days=DEFAULT_VALID_DAYS)
    if valid < issue_date:
        raise UnprocessableError("'Valid until' cannot be before the issue date")
    rows, sub, tax = await _build_lines(db, tenant_id, lines)
    q = FinQuote(tenant_id=tenant_id, number=await _next(db, tenant_id, FinQuote, "QUO"), customer_id=cust.id,
                 status=QuoteStatus.SENT if send else QuoteStatus.DRAFT, issue_date=issue_date, valid_until=valid,
                 currency=(currency or cust.currency or base).upper(), subtotal=sub, tax_total=tax, total=sub + tax,
                 reference=reference, notes=notes, created_by=created_by)
    db.add(q)
    await db.flush()
    for r in rows:
        db.add(FinQuoteLine(tenant_id=tenant_id, quote_id=q.id, **r))
    await db.flush()
    return await get_quote(db, tenant_id, q.id)


async def update_quote(db, tenant_id, qid, *, customer_id=None, issue_date=None, valid_until=None, lines=None,
                       currency=None, reference=None, notes=None) -> dict:
    q = await _quote(db, tenant_id, qid, lock=True)
    if q.status != QuoteStatus.DRAFT:
        raise ConflictError("Only draft quotes can be edited")
    if customer_id:
        q.customer_id = (await _customer(db, tenant_id, customer_id)).id
    q.issue_date = issue_date or q.issue_date
    q.valid_until = valid_until or q.valid_until
    if q.valid_until < q.issue_date:
        raise UnprocessableError("'Valid until' cannot be before the issue date")
    if currency:
        q.currency = currency.upper()
    if reference is not None:
        q.reference = reference
    if notes is not None:
        q.notes = notes
    if lines is not None:
        rows, sub, tax = await _build_lines(db, tenant_id, lines)
        for old in await _lines(db, q.id):
            await db.delete(old)
        await db.flush()
        for r in rows:
            db.add(FinQuoteLine(tenant_id=tenant_id, quote_id=q.id, **r))
        q.subtotal, q.tax_total, q.total = sub, tax, sub + tax
    await db.flush()
    return await get_quote(db, tenant_id, q.id)


async def set_status(db, tenant_id, qid, to: str) -> dict:
    q = await _quote(db, tenant_id, qid, lock=True)
    allowed = {"sent": (QuoteStatus.DRAFT,), "accepted": (QuoteStatus.SENT,), "declined": (QuoteStatus.SENT,)}
    if to not in allowed:
        raise UnprocessableError("Unknown status")
    if q.status not in allowed[to]:
        raise ConflictError(f"A {q.status.value} quote cannot be marked {to}")
    q.status = QuoteStatus(to)
    await db.flush()
    return await get_quote(db, tenant_id, q.id)


async def delete_draft(db, tenant_id, qid) -> None:
    q = await _quote(db, tenant_id, qid, lock=True)
    if q.status != QuoteStatus.DRAFT:
        raise ConflictError("Only draft quotes can be deleted")
    q.is_deleted = True
    q.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def convert_to_invoice(db, tenant_id, qid, *, issue_date: date | None = None, created_by=None) -> dict:
    q = await _quote(db, tenant_id, qid, lock=True)
    if q.status not in (QuoteStatus.SENT, QuoteStatus.ACCEPTED, QuoteStatus.INVOICED):
        raise ConflictError("Send the quote before converting it")
    if q.invoice_id:
        existing = (await db.execute(select(FinInvoice).where(FinInvoice.id == q.invoice_id))).scalar_one_or_none()
        if existing is not None and not existing.is_deleted:
            raise ConflictError(f"Already converted to {existing.number}")
    specs = [LineSpec(description=l.description, quantity=l.quantity, unit_price=l.unit_price,
                      discount_percent=l.discount_percent, tax_rate_id=l.tax_rate_id, income_account_id=l.income_account_id)
             for l in await _lines(db, q.id)]
    inv = await sales.create_invoice(db, tenant_id, customer_id=q.customer_id, issue_date=issue_date or date.today(),
                                     due_date=None, lines=specs, currency=q.currency, reference=q.number,
                                     notes=q.notes, post=False, created_by=created_by)
    q.invoice_id = uuid.UUID(inv["id"])
    q.status = QuoteStatus.INVOICED
    await db.flush()
    return {"quote": await get_quote(db, tenant_id, q.id), "invoice": inv}


async def list_quotes(db, tenant_id, *, status: str | None = None, customer_id=None, search: str | None = None,
                      page=1, page_size=50) -> tuple[list[dict], int]:
    qy = select(FinQuote, FinCustomer).join(FinCustomer, FinCustomer.id == FinQuote.customer_id).where(
        FinQuote.tenant_id == tenant_id, FinQuote.is_deleted == False)  # noqa: E712
    if customer_id:
        qy = qy.where(FinQuote.customer_id == customer_id)
    if status == "expired":
        qy = qy.where(FinQuote.status == QuoteStatus.SENT, FinQuote.valid_until < date.today())
    elif status:
        qy = qy.where(FinQuote.status == QuoteStatus(status))
    if search:
        qy = qy.where(FinQuote.number.ilike(f"%{search}%") | FinCustomer.name.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(qy.subquery()))).scalar() or 0
    rows = (await db.execute(qy.order_by(FinQuote.issue_date.desc(), FinQuote.number.desc())
                             .offset((page - 1) * page_size).limit(page_size))).all()
    return [_ser(q, c) for q, c in rows], total
