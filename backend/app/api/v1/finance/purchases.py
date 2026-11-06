"""Finance Phase 3a API: vendors, bills, payments made."""
import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services import finance_purchases as p
from app.services import finance_purchasing as pp

router = APIRouter()


class VendorBody(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    company: str | None = Field(None, max_length=150)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    address: str | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    payment_terms_days: int = Field(0, ge=0, le=365)
    notes: str | None = None


class VendorPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    payment_terms_days: int | None = Field(None, ge=0, le=365)
    notes: str | None = None
    is_active: bool | None = None


class BillLineBody(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(Decimal("1"), gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_percent: Decimal = Field(Decimal("0"), ge=0, le=100)
    tax_rate_id: uuid.UUID | None = None
    expense_account_id: uuid.UUID | None = None

    def spec(self) -> p.BillLineSpec:
        return p.BillLineSpec(**self.model_dump())


class BillBody(BaseModel):
    vendor_id: uuid.UUID
    issue_date: datetime.date
    due_date: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    rate: Decimal | None = Field(None, gt=0)
    vendor_ref: str | None = Field(None, max_length=100)
    notes: str | None = None
    lines: list[BillLineBody] = Field(min_length=1)
    post: bool = False


class BillPatch(BaseModel):
    vendor_id: uuid.UUID | None = None
    issue_date: datetime.date | None = None
    due_date: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    rate: Decimal | None = Field(None, gt=0)
    vendor_ref: str | None = None
    notes: str | None = None
    lines: list[BillLineBody] | None = None


class Allocation(BaseModel):
    bill_id: uuid.UUID
    amount: Decimal = Field(gt=0)


class PaymentBody(BaseModel):
    vendor_id: uuid.UUID
    payment_date: datetime.date
    amount: Decimal = Field(gt=0)
    paid_from_account_id: uuid.UUID
    currency: str | None = Field(None, min_length=3, max_length=3)
    rate: Decimal | None = Field(None, gt=0)
    method: str | None = Field(None, max_length=50)
    reference: str | None = Field(None, max_length=100)
    notes: str | None = None
    allocations: list[Allocation] = []


class VoidBody(BaseModel):
    reason: str | None = Field(None, max_length=300)


_view, _post, _void = (require_permission(f"finance.{a}") for a in ("view", "post", "void"))


# ── vendors ──
@router.get("/vendors", summary="List vendors with what you owe each")
async def vendors(search: str | None = Query(None, max_length=100), include_inactive: bool = False,
                  user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                  db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await p.list_vendors(db, tenant_id, search, include_inactive)}


@router.post("/vendors", status_code=status.HTTP_201_CREATED, summary="Add a vendor")
async def add_vendor(body: VendorBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                     db: AsyncSession = Depends(get_db)) -> dict:
    return await p.create_vendor(db, tenant_id, **body.model_dump())


@router.patch("/vendors/{vendor_id}", summary="Edit a vendor")
async def edit_vendor(vendor_id: uuid.UUID, body: VendorPatch, user: User = Depends(_post),
                      tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await p.update_vendor(db, tenant_id, vendor_id, **body.model_dump(exclude_unset=True))


@router.get("/vendors/{vendor_id}/statement", summary="Vendor statement (bills and payments)")
async def vendor_statement(vendor_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                           db: AsyncSession = Depends(get_db)) -> dict:
    return await p.vendor_statement(db, tenant_id, vendor_id)


# ── bills ──
@router.get("/bills", summary="List bills")
async def bills(status_: Literal["draft", "open", "partially_paid", "paid", "void", "overdue"] | None = Query(None, alias="status"),
                vendor_id: uuid.UUID | None = None, search: str | None = Query(None, max_length=100),
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                db: AsyncSession = Depends(get_db)) -> dict:
    items, total = await p.list_bills(db, tenant_id, status=status_, vendor_id=vendor_id, search=search, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/bills", status_code=status.HTTP_201_CREATED, summary="Enter a bill (draft, or post straight away)")
async def add_bill(body: BillBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                   db: AsyncSession = Depends(get_db)) -> dict:
    return await p.create_bill(db, tenant_id, vendor_id=body.vendor_id, issue_date=body.issue_date, due_date=body.due_date,
                               lines=[l.spec() for l in body.lines], currency=body.currency, rate=body.rate,
                               vendor_ref=body.vendor_ref, notes=body.notes, post=body.post, created_by=user.id)


@router.get("/bills/{bill_id}", summary="Bill with lines and payments")
async def one_bill(bill_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                   db: AsyncSession = Depends(get_db)) -> dict:
    return await p.get_bill(db, tenant_id, bill_id)


@router.patch("/bills/{bill_id}", summary="Edit a draft bill")
async def edit_bill(bill_id: uuid.UUID, body: BillPatch, user: User = Depends(_post),
                    tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    d = body.model_dump(exclude_unset=True)
    lines = [l.spec() for l in body.lines] if body.lines is not None else None
    d.pop("lines", None)
    return await p.update_bill(db, tenant_id, bill_id, lines=lines, **d)


@router.post("/bills/{bill_id}/post", summary="Post a draft bill to the ledger")
async def post_bill(bill_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                    db: AsyncSession = Depends(get_db)) -> dict:
    return await p.post_bill(db, tenant_id, bill_id, created_by=user.id)


@router.post("/bills/{bill_id}/void", summary="Void a posted bill (no payments allowed)")
async def void_bill(bill_id: uuid.UUID, body: VoidBody | None = None, user: User = Depends(_void),
                    tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await p.void_bill(db, tenant_id, bill_id, reason=body.reason if body else None, created_by=user.id)


@router.delete("/bills/{bill_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft bill")
async def delete_bill(bill_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> None:
    await p.delete_draft(db, tenant_id, bill_id)


# ── payments made ──
@router.get("/bill-payments", summary="List payments made to vendors")
async def payments(vendor_id: uuid.UUID | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                   user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                   db: AsyncSession = Depends(get_db)) -> dict:
    items, total = await p.list_payments(db, tenant_id, vendor_id=vendor_id, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/bill-payments", status_code=status.HTTP_201_CREATED, summary="Pay a vendor and apply it to bills")
async def add_payment(body: PaymentBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await p.create_payment(db, tenant_id, vendor_id=body.vendor_id, payment_date=body.payment_date, amount=body.amount,
                                  paid_from_account_id=body.paid_from_account_id,
                                  allocations=[(a.bill_id, a.amount) for a in body.allocations], currency=body.currency,
                                  rate=body.rate, method=body.method, reference=body.reference, notes=body.notes,
                                  created_by=user.id)


@router.get("/bill-payments/{payment_id}", summary="One payment made")
async def one_payment(payment_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await p.get_payment(db, tenant_id, payment_id)


@router.post("/bill-payments/{payment_id}/void", summary="Void a payment and reopen its bills")
async def void_pay(payment_id: uuid.UUID, body: VoidBody | None = None, user: User = Depends(_void),
                   tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await p.void_payment(db, tenant_id, payment_id, reason=body.reason if body else None, created_by=user.id)


# ── Phase 3b: approvals, attachments, purchase orders, recurring bills ──
_manage = require_permission("finance.manage")
MAX_BODY = 10 * 1024 * 1024 + 1


class SettingsBody(BaseModel):
    approval_threshold: Decimal | None = Field(None, gt=0)


class RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.get("/purchase-settings", summary="Purchase settings (approval limit)")
async def get_settings(user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.get_settings(db, tenant_id)


@router.put("/purchase-settings", summary="Set the bill approval limit (empty = approvals off)")
async def put_settings(body: SettingsBody, user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.set_threshold(db, tenant_id, body.approval_threshold)


@router.post("/bills/{bill_id}/request-approval", summary="Ask for approval of a bill above the limit")
async def request_approval(bill_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                           db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.request_approval(db, tenant_id, bill_id, user_id=user.id)


@router.post("/bills/{bill_id}/approve", summary="Approve a bill (this posts it)")
async def approve_bill(bill_id: uuid.UUID, user: User = Depends(_manage), tenant_id: uuid.UUID = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.approve(db, tenant_id, bill_id, user_id=user.id)


@router.post("/bills/{bill_id}/reject", summary="Reject a bill waiting for approval")
async def reject_bill(bill_id: uuid.UUID, body: RejectBody, user: User = Depends(_manage),
                      tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.reject(db, tenant_id, bill_id, user_id=user.id, reason=body.reason)


@router.get("/bills/{bill_id}/attachments", summary="Files attached to a bill")
async def list_attachments(bill_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                           db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await pp.list_attachments(db, tenant_id, bill_id)}


@router.post("/bills/{bill_id}/attachments", status_code=status.HTTP_201_CREATED, summary="Attach a file to a bill")
async def add_attachment(bill_id: uuid.UUID, file: UploadFile = File(...), user: User = Depends(_post),
                         tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    content = await file.read(MAX_BODY)
    return await pp.add_attachment(db, tenant_id, bill_id, file_name=file.filename or "file", content=content, uploaded_by=user.id)


@router.get("/bills/{bill_id}/attachments/{attachment_id}", summary="Download an attached file")
async def download_attachment(bill_id: uuid.UUID, attachment_id: uuid.UUID, user: User = Depends(_view),
                              tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> Response:
    a, content = await pp.read_attachment(db, tenant_id, bill_id, attachment_id)
    return Response(content=content, media_type=a.mime_type, headers={
        "Content-Disposition": f'attachment; filename="{a.file_name}"', "X-Content-Type-Options": "nosniff"})


@router.delete("/bills/{bill_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an attached file")
async def delete_attachment(bill_id: uuid.UUID, attachment_id: uuid.UUID, user: User = Depends(_post),
                            tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> None:
    await pp.delete_attachment(db, tenant_id, bill_id, attachment_id)


class OrderBody(BaseModel):
    vendor_id: uuid.UUID
    issue_date: datetime.date
    expected_date: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    reference: str | None = Field(None, max_length=100)
    notes: str | None = None
    lines: list[BillLineBody] = Field(min_length=1)
    send: bool = False


class OrderPatch(BaseModel):
    vendor_id: uuid.UUID | None = None
    issue_date: datetime.date | None = None
    expected_date: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    reference: str | None = None
    notes: str | None = None
    lines: list[BillLineBody] | None = None


class ConvertBody(BaseModel):
    issue_date: datetime.date | None = None


@router.get("/purchase-orders", summary="List purchase orders")
async def list_orders(status_: Literal["draft", "sent", "received", "billed", "cancelled"] | None = Query(None, alias="status"),
                      vendor_id: uuid.UUID | None = None, search: str | None = Query(None, max_length=100),
                      page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), user: User = Depends(_view),
                      tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    items, total = await pp.list_orders(db, tenant_id, status=status_, vendor_id=vendor_id, search=search, page=page, page_size=page_size)
    return {"items": items, "total": total}


@router.post("/purchase-orders", status_code=status.HTTP_201_CREATED, summary="Create a purchase order")
async def add_order(body: OrderBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                    db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.create_order(db, tenant_id, vendor_id=body.vendor_id, issue_date=body.issue_date, expected_date=body.expected_date,
                                 lines=[l.spec() for l in body.lines], currency=body.currency, reference=body.reference,
                                 notes=body.notes, send=body.send, created_by=user.id)


@router.get("/purchase-orders/{order_id}", summary="One purchase order with lines")
async def one_order(order_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                    db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.get_order(db, tenant_id, order_id)


@router.patch("/purchase-orders/{order_id}", summary="Edit a draft purchase order")
async def edit_order(order_id: uuid.UUID, body: OrderPatch, user: User = Depends(_post),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    d = body.model_dump(exclude_unset=True)
    lines = [l.spec() for l in body.lines] if body.lines is not None else None
    d.pop("lines", None)
    return await pp.update_order(db, tenant_id, order_id, lines=lines, **d)


@router.post("/purchase-orders/{order_id}/convert", summary="Turn a purchase order into a draft bill")
async def convert_order(order_id: uuid.UUID, body: ConvertBody | None = None, user: User = Depends(_post),
                        tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.convert_order_to_bill(db, tenant_id, order_id, issue_date=body.issue_date if body else None, created_by=user.id)


@router.post("/purchase-orders/{order_id}/{action}", summary="Mark a purchase order sent, received or cancelled")
async def order_status(order_id: uuid.UUID, action: Literal["sent", "received", "cancelled"], user: User = Depends(_post),
                       tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.set_order_status(db, tenant_id, order_id, action)


@router.delete("/purchase-orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft purchase order")
async def delete_order(order_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)) -> None:
    await pp.delete_order(db, tenant_id, order_id)


class RecBillBody(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    vendor_id: uuid.UUID
    frequency: Literal["weekly", "monthly", "quarterly", "yearly"]
    start_date: datetime.date
    end_date: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    vendor_ref: str | None = Field(None, max_length=100)
    notes: str | None = None
    auto_post: bool = False
    lines: list[BillLineBody] = Field(min_length=1)


class RecBillPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    frequency: Literal["weekly", "monthly", "quarterly", "yearly"] | None = None
    end_date: datetime.date | None = None
    vendor_ref: str | None = None
    notes: str | None = None
    auto_post: bool | None = None
    lines: list[BillLineBody] | None = None


@router.get("/recurring-bills", summary="List recurring bill schedules")
async def list_recurring_bills(user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                               db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await pp.list_recurring(db, tenant_id)}


@router.post("/recurring-bills", status_code=status.HTTP_201_CREATED, summary="Create a recurring bill schedule")
async def add_recurring_bill(body: RecBillBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                             db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.create_recurring(db, tenant_id, title=body.title, vendor_id=body.vendor_id, frequency=body.frequency,
                                     start_date=body.start_date, end_date=body.end_date, lines=[l.spec() for l in body.lines],
                                     auto_post=body.auto_post, currency=body.currency, vendor_ref=body.vendor_ref,
                                     notes=body.notes, created_by=user.id)


@router.post("/recurring-bills/run", summary="Make any bills that are due now")
async def run_recurring_bills(user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                              db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.run_due(db, tenant_id=tenant_id)


@router.get("/recurring-bills/{recurring_id}", summary="One recurring bill schedule with its lines")
async def one_recurring_bill(recurring_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                             db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.get_recurring(db, tenant_id, recurring_id)


@router.patch("/recurring-bills/{recurring_id}", summary="Edit a recurring bill schedule")
async def edit_recurring_bill(recurring_id: uuid.UUID, body: RecBillPatch, user: User = Depends(_post),
                              tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    d = body.model_dump(exclude_unset=True)
    lines = [l.spec() for l in body.lines] if body.lines is not None else None
    d.pop("lines", None)
    return await pp.update_recurring(db, tenant_id, recurring_id, lines=lines, **d)


@router.post("/recurring-bills/{recurring_id}/{action}", summary="Pause or resume a schedule")
async def recurring_bill_state(recurring_id: uuid.UUID, action: Literal["pause", "resume"], user: User = Depends(_post),
                               tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await pp.set_recurring_state(db, tenant_id, recurring_id, action)


@router.delete("/recurring-bills/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a schedule (bills already made stay)")
async def delete_recurring_bill(recurring_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                                db: AsyncSession = Depends(get_db)) -> None:
    await pp.delete_recurring(db, tenant_id, recurring_id)
