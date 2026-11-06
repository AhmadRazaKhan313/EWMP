"""Finance Phase 3b: bill approvals, bill attachments, purchase orders and recurring bills."""
import calendar
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, UnprocessableError
from app.core.storage import get_storage
from app.models.finance_purchases import (BillStatus, FinBill, FinBillAttachment, FinPurchaseOrder, FinPurchaseOrderLine,
                                          FinPurchaseSettings, FinRecurringBill, FinRecurringBillLine, FinVendor,
                                          PurchaseOrderStatus, RecurringBillFrequency, RecurringBillStatus)
from app.services import finance_ledger as led
from app.services import finance_purchases as pur
from app.services.finance_purchases import BillLineSpec, _bill, _build_lines, _next, _q, _vendor, ZERO

MAX_ATTACH_BYTES = 10 * 1024 * 1024
MAX_ATTACH_PER_BILL = 20
MAX_CATCHUP = 12
# extension -> (mime, magic-prefix check). The bytes must match the extension, whatever the client claims.
_SIGS = {
    "pdf": ("application/pdf", (b"%PDF",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "webp": ("image/webp", (b"RIFF",)),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (b"PK\x03\x04",)),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (b"PK\x03\x04",)),
}


# ───────────────────────── approvals ─────────────────────────
async def get_settings(db, tenant_id) -> dict:
    t = await pur.get_threshold(db, tenant_id)
    return {"approval_threshold": str(t) if t is not None else None}


async def set_threshold(db, tenant_id, threshold: Decimal | None) -> dict:
    if threshold is not None and threshold <= 0:
        raise UnprocessableError("The approval limit must be greater than zero (or empty to switch approvals off)")
    r = (await db.execute(select(FinPurchaseSettings).where(FinPurchaseSettings.tenant_id == tenant_id).with_for_update())).scalar_one_or_none()
    if r is None:
        r = FinPurchaseSettings(tenant_id=tenant_id)
        db.add(r)
    r.is_deleted, r.deleted_at = False, None
    r.approval_threshold = _q(threshold) if threshold is not None else None
    await db.flush()
    return await get_settings(db, tenant_id)


async def request_approval(db, tenant_id, bid, *, user_id) -> dict:
    b = await _bill(db, tenant_id, bid, lock=True)
    if b.status != BillStatus.DRAFT:
        raise ConflictError("Only draft bills need approval")
    if not await pur.needs_approval(db, tenant_id, b):
        raise ConflictError("This bill is under the approval limit; just post it")
    if b.approval_status == "pending":
        raise ConflictError("Approval is already requested")
    b.approval_status, b.approval_requested_by, b.rejection_reason = "pending", user_id, None
    await db.flush()
    return await pur.get_bill(db, tenant_id, b.id)


async def approve(db, tenant_id, bid, *, user_id) -> dict:
    b = await _bill(db, tenant_id, bid, lock=True)
    if b.status != BillStatus.DRAFT or b.approval_status != "pending":
        raise ConflictError("Only a bill waiting for approval can be approved")
    if b.approval_requested_by == user_id:
        raise ConflictError("You asked for this approval, so someone else must approve it")
    b.approval_status, b.approved_by, b.approved_at = "approved", user_id, datetime.now(timezone.utc)
    await db.flush()
    return await pur.post_bill(db, tenant_id, b.id, created_by=user_id)       # approving posts it


async def reject(db, tenant_id, bid, *, user_id, reason: str) -> dict:
    b = await _bill(db, tenant_id, bid, lock=True)
    if b.status != BillStatus.DRAFT or b.approval_status != "pending":
        raise ConflictError("Only a bill waiting for approval can be rejected")
    if not (reason or "").strip():
        raise UnprocessableError("Say why it is rejected")
    b.approval_status, b.rejection_reason = "rejected", reason.strip()[:500]
    await db.flush()
    return await pur.get_bill(db, tenant_id, b.id)


# ───────────────────────── attachments ─────────────────────────
def _ser_att(a: FinBillAttachment) -> dict:
    return {"id": str(a.id), "file_name": a.file_name, "mime_type": a.mime_type, "size_bytes": a.size_bytes,
            "uploaded_at": a.created_at.isoformat() if a.created_at else None}


async def list_attachments(db, tenant_id, bid) -> list[dict]:
    await _bill(db, tenant_id, bid)
    rows = (await db.execute(select(FinBillAttachment).where(
        FinBillAttachment.tenant_id == tenant_id, FinBillAttachment.bill_id == bid,
        FinBillAttachment.is_deleted == False).order_by(FinBillAttachment.created_at))).scalars().all()  # noqa: E712
    return [_ser_att(a) for a in rows]


async def add_attachment(db, tenant_id, bid, *, file_name: str, content: bytes, uploaded_by=None) -> dict:
    b = await _bill(db, tenant_id, bid)
    if b.status == BillStatus.VOID:
        raise ConflictError("A void bill cannot take new files")
    name = re.sub(r"[^\w.\- ]", "_", (file_name or "file").split("/")[-1].split("\\")[-1]).strip()[:200] or "file"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in _SIGS:
        raise BadRequestError("Allowed files: PDF, PNG, JPG, WEBP, DOCX, XLSX")
    if not content:
        raise BadRequestError("The file is empty")
    if len(content) > MAX_ATTACH_BYTES:
        raise BadRequestError("File exceeds the 10 MB limit")
    mime, sigs = _SIGS[ext]
    if not content.startswith(sigs) or (ext == "webp" and content[8:12] != b"WEBP"):
        raise BadRequestError("The file content does not match its type")
    count = (await db.execute(select(func.count()).select_from(FinBillAttachment).where(
        FinBillAttachment.bill_id == bid, FinBillAttachment.is_deleted == False))).scalar() or 0  # noqa: E712
    if count >= MAX_ATTACH_PER_BILL:
        raise ConflictError(f"A bill can have up to {MAX_ATTACH_PER_BILL} files")
    key = f"finance/{tenant_id}/bills/{bid}/{uuid.uuid4().hex}_{name}"
    await get_storage().save(key, content)
    a = FinBillAttachment(tenant_id=tenant_id, bill_id=bid, file_name=name, mime_type=mime, size_bytes=len(content),
                          storage_key=key, uploaded_by=uploaded_by)
    db.add(a)
    await db.flush()
    return _ser_att(a)


async def _att(db, tenant_id, bid, aid) -> FinBillAttachment:
    a = (await db.execute(select(FinBillAttachment).where(
        FinBillAttachment.id == aid, FinBillAttachment.bill_id == bid, FinBillAttachment.tenant_id == tenant_id,
        FinBillAttachment.is_deleted == False))).scalar_one_or_none()  # noqa: E712
    if a is None:
        raise NotFoundError("Attachment not found")
    return a


async def read_attachment(db, tenant_id, bid, aid) -> tuple[FinBillAttachment, bytes]:
    a = await _att(db, tenant_id, bid, aid)
    return a, await get_storage().read(a.storage_key)


async def delete_attachment(db, tenant_id, bid, aid) -> None:
    a = await _att(db, tenant_id, bid, aid)
    a.is_deleted, a.deleted_at = True, datetime.now(timezone.utc)
    await db.flush()
    try:
        await get_storage().delete(a.storage_key)
    except Exception:  # noqa: BLE001 - the row is already gone; a stray file must not fail the request
        pass


# ───────────────────────── purchase orders ─────────────────────────
async def _po(db, tenant_id, pid, lock=False) -> FinPurchaseOrder:
    q = select(FinPurchaseOrder).where(FinPurchaseOrder.id == pid, FinPurchaseOrder.tenant_id == tenant_id,
                                       FinPurchaseOrder.is_deleted == False)  # noqa: E712
    if lock:
        q = q.with_for_update()
    r = (await db.execute(q)).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Purchase order not found")
    return r


async def _po_lines(db, pid) -> list[FinPurchaseOrderLine]:
    return list((await db.execute(select(FinPurchaseOrderLine).where(FinPurchaseOrderLine.order_id == pid)
                                  .order_by(FinPurchaseOrderLine.line_no))).scalars().all())


def _ser_po(o: FinPurchaseOrder, v: FinVendor | None = None, lines=None) -> dict:
    d = {"id": str(o.id), "number": o.number, "vendor_id": str(o.vendor_id), "vendor_name": v.name if v else None,
         "status": o.status.value, "issue_date": o.issue_date.isoformat(),
         "expected_date": o.expected_date.isoformat() if o.expected_date else None, "currency": o.currency,
         "subtotal": str(o.subtotal), "tax_total": str(o.tax_total), "total": str(o.total), "reference": o.reference,
         "notes": o.notes, "bill_id": str(o.bill_id) if o.bill_id else None}
    if lines is not None:
        d["lines"] = [{"id": str(l.id), "description": l.description, "quantity": str(l.quantity), "unit_price": str(l.unit_price),
                       "discount_percent": str(l.discount_percent), "tax_rate_id": str(l.tax_rate_id) if l.tax_rate_id else None,
                       "tax_percent": str(l.tax_percent), "expense_account_id": str(l.expense_account_id),
                       "net_amount": str(l.net_amount), "tax_amount": str(l.tax_amount)} for l in lines]
    return d


async def get_order(db, tenant_id, pid) -> dict:
    o = await _po(db, tenant_id, pid)
    return _ser_po(o, await _vendor(db, tenant_id, o.vendor_id), await _po_lines(db, o.id))


async def create_order(db, tenant_id, *, vendor_id, issue_date: date, expected_date: date | None, lines: list[BillLineSpec],
                       currency: str | None = None, reference=None, notes=None, send: bool = False, created_by=None) -> dict:
    v = await _vendor(db, tenant_id, vendor_id)
    base = await led.base_currency(db, tenant_id)
    if expected_date and expected_date < issue_date:
        raise UnprocessableError("The expected date cannot be before the order date")
    rows, sub, tax = await _build_lines(db, tenant_id, lines)
    o = FinPurchaseOrder(tenant_id=tenant_id, number=await _next(db, tenant_id, FinPurchaseOrder, "PO"), vendor_id=v.id,
                         status=PurchaseOrderStatus.SENT if send else PurchaseOrderStatus.DRAFT, issue_date=issue_date,
                         expected_date=expected_date, currency=(currency or v.currency or base).upper(), subtotal=sub,
                         tax_total=tax, total=sub + tax, reference=reference, notes=notes, created_by=created_by)
    db.add(o)
    await db.flush()
    for r in rows:
        db.add(FinPurchaseOrderLine(tenant_id=tenant_id, order_id=o.id, **r))
    await db.flush()
    return await get_order(db, tenant_id, o.id)


async def update_order(db, tenant_id, pid, *, vendor_id=None, issue_date=None, expected_date=..., lines=None, currency=None,
                       reference=None, notes=None) -> dict:
    o = await _po(db, tenant_id, pid, lock=True)
    if o.status != PurchaseOrderStatus.DRAFT:
        raise ConflictError("Only draft orders can be edited")
    if vendor_id:
        o.vendor_id = (await _vendor(db, tenant_id, vendor_id)).id
    o.issue_date = issue_date or o.issue_date
    if expected_date is not ...:
        o.expected_date = expected_date
    if o.expected_date and o.expected_date < o.issue_date:
        raise UnprocessableError("The expected date cannot be before the order date")
    if currency:
        o.currency = currency.upper()
    if reference is not None:
        o.reference = reference
    if notes is not None:
        o.notes = notes
    if lines is not None:
        rows, sub, tax = await _build_lines(db, tenant_id, lines)
        for old in await _po_lines(db, o.id):
            await db.delete(old)
        await db.flush()
        for r in rows:
            db.add(FinPurchaseOrderLine(tenant_id=tenant_id, order_id=o.id, **r))
        o.subtotal, o.tax_total, o.total = sub, tax, sub + tax
    await db.flush()
    return await get_order(db, tenant_id, o.id)


async def set_order_status(db, tenant_id, pid, to: str) -> dict:
    o = await _po(db, tenant_id, pid, lock=True)
    S = PurchaseOrderStatus
    allowed = {"sent": (S.DRAFT,), "received": (S.SENT,), "cancelled": (S.DRAFT, S.SENT)}
    if to not in allowed:
        raise UnprocessableError("Unknown status")
    if o.status not in allowed[to]:
        raise ConflictError(f"A {o.status.value} order cannot be marked {to}")
    o.status = S(to)
    await db.flush()
    return await get_order(db, tenant_id, o.id)


async def delete_order(db, tenant_id, pid) -> None:
    o = await _po(db, tenant_id, pid, lock=True)
    if o.status != PurchaseOrderStatus.DRAFT:
        raise ConflictError("Only draft orders can be deleted (cancel the others)")
    o.is_deleted, o.deleted_at = True, datetime.now(timezone.utc)
    await db.flush()


async def convert_order_to_bill(db, tenant_id, pid, *, issue_date: date | None = None, created_by=None) -> dict:
    o = await _po(db, tenant_id, pid, lock=True)
    if o.status not in (PurchaseOrderStatus.SENT, PurchaseOrderStatus.RECEIVED):
        raise ConflictError("Send the order before billing it")
    if o.bill_id:
        ex = (await db.execute(select(FinBill).where(FinBill.id == o.bill_id))).scalar_one_or_none()
        if ex is not None and not ex.is_deleted:
            raise ConflictError(f"Already billed as {ex.number}")
    specs = [BillLineSpec(description=l.description, quantity=l.quantity, unit_price=l.unit_price, discount_percent=l.discount_percent,
                          tax_rate_id=l.tax_rate_id, expense_account_id=l.expense_account_id) for l in await _po_lines(db, o.id)]
    bill = await pur.create_bill(db, tenant_id, vendor_id=o.vendor_id, issue_date=issue_date or date.today(), due_date=None,
                                 lines=specs, currency=o.currency, vendor_ref=None, notes=f"From {o.number}" + (f"\n{o.notes}" if o.notes else ""),
                                 post=False, created_by=created_by)
    o.bill_id = uuid.UUID(bill["id"])
    o.status = PurchaseOrderStatus.BILLED
    await db.flush()
    return {"order": await get_order(db, tenant_id, o.id), "bill": bill}


async def list_orders(db, tenant_id, *, status: str | None = None, vendor_id=None, search: str | None = None,
                      page=1, page_size=50) -> tuple[list[dict], int]:
    q = select(FinPurchaseOrder, FinVendor).join(FinVendor, FinVendor.id == FinPurchaseOrder.vendor_id).where(
        FinPurchaseOrder.tenant_id == tenant_id, FinPurchaseOrder.is_deleted == False)  # noqa: E712
    if vendor_id:
        q = q.where(FinPurchaseOrder.vendor_id == vendor_id)
    if status:
        q = q.where(FinPurchaseOrder.status == PurchaseOrderStatus(status))
    if search:
        q = q.where(FinPurchaseOrder.number.ilike(f"%{search}%") | FinVendor.name.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(q.order_by(FinPurchaseOrder.issue_date.desc(), FinPurchaseOrder.number.desc())
                             .offset((page - 1) * page_size).limit(page_size))).all()
    return [_ser_po(o, v) for o, v in rows], total


# ───────────────────────── recurring bills ─────────────────────────
def step_date(start: date, freq, n: int) -> date:
    """start + n periods, anchored on start so month-end dates never drift (31 Jan -> 28 Feb -> 31 Mar)."""
    f = RecurringBillFrequency(freq)
    if f == RecurringBillFrequency.WEEKLY:
        return start + timedelta(weeks=n)
    months = {RecurringBillFrequency.MONTHLY: 1, RecurringBillFrequency.QUARTERLY: 3, RecurringBillFrequency.YEARLY: 12}[f] * n
    y, m = divmod(start.month - 1 + months, 12)
    y, m = start.year + y, m + 1
    return date(y, m, min(start.day, calendar.monthrange(y, m)[1]))


async def _rec(db, tenant_id, rid, lock=False) -> FinRecurringBill:
    q = select(FinRecurringBill).where(FinRecurringBill.id == rid, FinRecurringBill.tenant_id == tenant_id,
                                       FinRecurringBill.is_deleted == False)  # noqa: E712
    if lock:
        q = q.with_for_update()
    r = (await db.execute(q)).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Recurring bill not found")
    return r


async def _rlines(db, rid) -> list[FinRecurringBillLine]:
    return list((await db.execute(select(FinRecurringBillLine).where(FinRecurringBillLine.recurring_id == rid)
                                  .order_by(FinRecurringBillLine.line_no))).scalars().all())


def _rspec(l: FinRecurringBillLine) -> BillLineSpec:
    return BillLineSpec(description=l.description, quantity=l.quantity, unit_price=l.unit_price,
                        discount_percent=l.discount_percent, tax_rate_id=l.tax_rate_id, expense_account_id=l.expense_account_id)


def _ser_rec(r: FinRecurringBill, v: FinVendor | None = None, lines=None, total: Decimal | None = None) -> dict:
    d = {"id": str(r.id), "title": r.title, "vendor_id": str(r.vendor_id), "vendor_name": v.name if v else None,
         "status": r.status.value, "frequency": r.frequency.value, "start_date": r.start_date.isoformat(),
         "end_date": r.end_date.isoformat() if r.end_date else None, "next_run_date": r.next_run_date.isoformat(),
         "run_count": r.run_count, "auto_post": r.auto_post, "currency": r.currency, "vendor_ref": r.vendor_ref,
         "notes": r.notes, "last_error": r.last_error}
    if total is not None:
        d["total"] = str(total)
    if lines is not None:
        d["lines"] = [{"description": l.description, "quantity": str(l.quantity), "unit_price": str(l.unit_price),
                       "discount_percent": str(l.discount_percent), "tax_rate_id": str(l.tax_rate_id) if l.tax_rate_id else None,
                       "expense_account_id": str(l.expense_account_id)} for l in lines]
    return d


async def get_recurring(db, tenant_id, rid) -> dict:
    r = await _rec(db, tenant_id, rid)
    lines = await _rlines(db, r.id)
    _, sub, tax = await _build_lines(db, tenant_id, [_rspec(l) for l in lines])
    return _ser_rec(r, await _vendor(db, tenant_id, r.vendor_id), lines, sub + tax)


async def _store_rlines(db, tenant_id, rid, specs) -> None:
    rows, _, _ = await _build_lines(db, tenant_id, specs)        # validates, resolves the default expense account
    for old in await _rlines(db, rid):
        await db.delete(old)
    await db.flush()
    for r in rows:
        db.add(FinRecurringBillLine(tenant_id=tenant_id, recurring_id=rid, line_no=r["line_no"], description=r["description"],
                                    quantity=r["quantity"], unit_price=r["unit_price"], discount_percent=r["discount_percent"],
                                    tax_rate_id=r["tax_rate_id"], expense_account_id=r["expense_account_id"]))
    await db.flush()


async def create_recurring(db, tenant_id, *, title, vendor_id, frequency: str, start_date: date, end_date: date | None,
                           lines, auto_post=False, currency=None, vendor_ref=None, notes=None, created_by=None) -> dict:
    v = await _vendor(db, tenant_id, vendor_id)
    if not (title or "").strip():
        raise UnprocessableError("Give the schedule a title")
    if end_date and end_date < start_date:
        raise UnprocessableError("End date cannot be before the start date")
    base = await led.base_currency(db, tenant_id)
    r = FinRecurringBill(tenant_id=tenant_id, title=title.strip(), vendor_id=v.id, frequency=RecurringBillFrequency(frequency),
                         start_date=start_date, end_date=end_date, next_run_date=start_date, auto_post=auto_post,
                         currency=(currency or v.currency or base).upper(), vendor_ref=vendor_ref, notes=notes, created_by=created_by)
    db.add(r)
    await db.flush()
    await _store_rlines(db, tenant_id, r.id, lines)
    return await get_recurring(db, tenant_id, r.id)


async def update_recurring(db, tenant_id, rid, *, title=None, frequency=None, end_date=..., lines=None, auto_post=None,
                           vendor_ref=None, notes=None) -> dict:
    r = await _rec(db, tenant_id, rid, lock=True)
    if title is not None:
        r.title = title.strip() or r.title
    if frequency is not None and frequency != r.frequency.value:
        if r.run_count:
            raise ConflictError("The schedule has already run; create a new one to change the frequency")
        r.frequency = RecurringBillFrequency(frequency)
    if end_date is not ...:
        if end_date and end_date < r.start_date:
            raise UnprocessableError("End date cannot be before the start date")
        r.end_date = end_date
    if auto_post is not None:
        r.auto_post = auto_post
    if vendor_ref is not None:
        r.vendor_ref = vendor_ref
    if notes is not None:
        r.notes = notes
    if lines is not None:
        await _store_rlines(db, tenant_id, r.id, lines)
    await db.flush()
    return await get_recurring(db, tenant_id, r.id)


async def set_recurring_state(db, tenant_id, rid, action: str) -> dict:
    r = await _rec(db, tenant_id, rid, lock=True)
    if action == "pause":
        if r.status != RecurringBillStatus.ACTIVE:
            raise ConflictError("Only an active schedule can be paused")
        r.status = RecurringBillStatus.PAUSED
    elif action == "resume":
        if r.status != RecurringBillStatus.PAUSED:
            raise ConflictError("Only a paused schedule can be resumed")
        n = r.run_count
        nxt = step_date(r.start_date, r.frequency, n)
        while nxt < date.today():                       # never back-fill the pause
            n += 1
            nxt = step_date(r.start_date, r.frequency, n)
        r.run_count, r.next_run_date = n, nxt
        r.status = RecurringBillStatus.ACTIVE
    else:
        raise UnprocessableError("Unknown action")
    await db.flush()
    return await get_recurring(db, tenant_id, r.id)


async def delete_recurring(db, tenant_id, rid) -> None:
    r = await _rec(db, tenant_id, rid, lock=True)
    r.is_deleted, r.deleted_at = True, datetime.now(timezone.utc)
    await db.flush()


async def list_recurring(db, tenant_id) -> list[dict]:
    rows = (await db.execute(select(FinRecurringBill, FinVendor).join(FinVendor, FinVendor.id == FinRecurringBill.vendor_id)
                             .where(FinRecurringBill.tenant_id == tenant_id, FinRecurringBill.is_deleted == False)  # noqa: E712
                             .order_by(FinRecurringBill.next_run_date))).all()
    return [_ser_rec(r, v) for r, v in rows]


async def _generate_one(db, r: FinRecurringBill, today: date) -> int:
    made = 0
    specs = [_rspec(l) for l in await _rlines(db, r.id)]
    while r.status == RecurringBillStatus.ACTIVE and r.next_run_date <= today and made < MAX_CATCHUP:
        if r.end_date and r.next_run_date > r.end_date:
            r.status = RecurringBillStatus.ENDED
            break
        bill = await pur.create_bill(db, r.tenant_id, vendor_id=r.vendor_id, issue_date=r.next_run_date, due_date=None, lines=specs,
                                     currency=r.currency, vendor_ref=r.vendor_ref, notes=r.notes or r.title, post=False,
                                     created_by=r.created_by, recurring_id=r.id)
        if r.auto_post:
            b = await _bill(db, r.tenant_id, uuid.UUID(bill["id"]))
            # a bill above the approval limit is left as a draft for a person to approve
            if not await pur.needs_approval(db, r.tenant_id, b):
                await pur.post_bill(db, r.tenant_id, b.id, created_by=r.created_by)
        made += 1
        r.run_count += 1
        r.next_run_date = step_date(r.start_date, r.frequency, r.run_count)
        r.last_run_at = datetime.now(timezone.utc)
        r.last_error = None
        if r.end_date and r.next_run_date > r.end_date:
            r.status = RecurringBillStatus.ENDED
    return made


async def run_due(db, *, tenant_id: uuid.UUID | None = None, today: date | None = None) -> dict:
    """Make every bill that is due. One broken template is recorded and skipped; it never blocks the rest."""
    today = today or date.today()
    q = select(FinRecurringBill).where(FinRecurringBill.is_deleted == False,  # noqa: E712
                                       FinRecurringBill.status == RecurringBillStatus.ACTIVE,
                                       FinRecurringBill.next_run_date <= today)
    if tenant_id:
        q = q.where(FinRecurringBill.tenant_id == tenant_id)
    profiles = (await db.execute(q.order_by(FinRecurringBill.next_run_date).with_for_update(skip_locked=True))).scalars().all()
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
