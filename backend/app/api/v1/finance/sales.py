"""Finance Phase 2a API: customers, invoices, payments received."""
import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services import finance_sales as s

router = APIRouter()


class CustomerBody(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    company: str | None = Field(None, max_length=150)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    address: str | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    payment_terms_days: int = Field(0, ge=0, le=365)
    notes: str | None = None
    auto_remind: bool = False


class CustomerPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    payment_terms_days: int | None = Field(None, ge=0, le=365)
    notes: str | None = None
    is_active: bool | None = None
    auto_remind: bool | None = None


class LineBody(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(Decimal("1"), gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_percent: Decimal = Field(Decimal("0"), ge=0, le=100)
    tax_rate_id: uuid.UUID | None = None
    income_account_id: uuid.UUID | None = None

    def spec(self) -> s.LineSpec:
        return s.LineSpec(**self.model_dump())


class InvoiceBody(BaseModel):
    customer_id: uuid.UUID
    issue_date: datetime.date
    due_date: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    rate: Decimal | None = Field(None, gt=0)
    reference: str | None = Field(None, max_length=100)
    notes: str | None = None
    lines: list[LineBody] = Field(min_length=1)
    send: bool = False


class InvoicePatch(BaseModel):
    customer_id: uuid.UUID | None = None
    issue_date: datetime.date | None = None
    due_date: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    rate: Decimal | None = Field(None, gt=0)
    reference: str | None = None
    notes: str | None = None
    lines: list[LineBody] | None = None


class Allocation(BaseModel):
    invoice_id: uuid.UUID
    amount: Decimal = Field(gt=0)


class PaymentBody(BaseModel):
    customer_id: uuid.UUID
    payment_date: datetime.date
    amount: Decimal = Field(gt=0)
    deposit_account_id: uuid.UUID
    currency: str | None = Field(None, min_length=3, max_length=3)
    rate: Decimal | None = Field(None, gt=0)
    method: str | None = Field(None, max_length=50)
    reference: str | None = Field(None, max_length=100)
    notes: str | None = None
    allocations: list[Allocation] = []


class VoidBody(BaseModel):
    reason: str | None = Field(None, max_length=300)


_view, _post, _void, _manage = (require_permission(f"finance.{a}") for a in ("view", "post", "void", "manage"))


# ── customers ──
@router.get("/customers", summary="List customers with their open balance")
async def customers(search: str | None = Query(None, max_length=100), include_inactive: bool = False,
                    user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                    db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await s.list_customers(db, tenant_id, search, include_inactive)}


@router.post("/customers", status_code=status.HTTP_201_CREATED, summary="Add a customer")
async def add_customer(body: CustomerBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)) -> dict:
    return await s.create_customer(db, tenant_id, **body.model_dump())


@router.patch("/customers/{customer_id}", summary="Edit a customer")
async def edit_customer(customer_id: uuid.UUID, body: CustomerPatch, user: User = Depends(_post),
                        tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await s.update_customer(db, tenant_id, customer_id, **body.model_dump(exclude_unset=True))


@router.get("/customers/{customer_id}/statement", summary="Customer statement (invoices and payments)")
async def statement(customer_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                    db: AsyncSession = Depends(get_db)) -> dict:
    return await s.customer_statement(db, tenant_id, customer_id)


# ── invoices ──
@router.get("/invoices", summary="List invoices")
async def invoices(status_: Literal["draft", "sent", "partially_paid", "paid", "void", "overdue"] | None = Query(None, alias="status"),
                   customer_id: uuid.UUID | None = None, search: str | None = Query(None, max_length=100),
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                   user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                   db: AsyncSession = Depends(get_db)) -> dict:
    items, total = await s.list_invoices(db, tenant_id, status=status_, customer_id=customer_id, search=search,
                                         page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/invoices", status_code=status.HTTP_201_CREATED, summary="Create an invoice (draft, or send straight away)")
async def add_invoice(body: InvoiceBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await s.create_invoice(db, tenant_id, customer_id=body.customer_id, issue_date=body.issue_date,
                                  due_date=body.due_date, lines=[l.spec() for l in body.lines], currency=body.currency,
                                  rate=body.rate, reference=body.reference, notes=body.notes, post=body.send,
                                  created_by=user.id)


@router.get("/invoices/{invoice_id}", summary="Invoice with lines and payments")
async def one_invoice(invoice_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await s.get_invoice(db, tenant_id, invoice_id)


@router.patch("/invoices/{invoice_id}", summary="Edit a draft invoice")
async def edit_invoice(invoice_id: uuid.UUID, body: InvoicePatch, user: User = Depends(_post),
                       tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    d = body.model_dump(exclude_unset=True)
    lines = [l.spec() for l in body.lines] if body.lines is not None else None
    d.pop("lines", None)
    return await s.update_invoice(db, tenant_id, invoice_id, lines=lines, **d)


@router.post("/invoices/{invoice_id}/send", summary="Post a draft invoice to the ledger")
async def send(invoice_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
               db: AsyncSession = Depends(get_db)) -> dict:
    return await s.send_invoice(db, tenant_id, invoice_id, created_by=user.id)


@router.post("/invoices/{invoice_id}/void", summary="Void a sent invoice (no payments allowed)")
async def void(invoice_id: uuid.UUID, body: VoidBody | None = None, user: User = Depends(_void),
               tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await s.void_invoice(db, tenant_id, invoice_id, reason=body.reason if body else None, created_by=user.id)


@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft invoice")
async def delete(invoice_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                 db: AsyncSession = Depends(get_db)) -> None:
    await s.delete_draft(db, tenant_id, invoice_id)


# ── payments ──
@router.get("/payments", summary="List payments received")
async def payments(customer_id: uuid.UUID | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                   user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                   db: AsyncSession = Depends(get_db)) -> dict:
    items, total = await s.list_payments(db, tenant_id, customer_id=customer_id, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/payments", status_code=status.HTTP_201_CREATED, summary="Record a payment and apply it to invoices")
async def add_payment(body: PaymentBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await s.create_payment(db, tenant_id, customer_id=body.customer_id, payment_date=body.payment_date,
                                  amount=body.amount, deposit_account_id=body.deposit_account_id,
                                  allocations=[(a.invoice_id, a.amount) for a in body.allocations],
                                  currency=body.currency, rate=body.rate, method=body.method,
                                  reference=body.reference, notes=body.notes, created_by=user.id)


@router.get("/payments/{payment_id}", summary="One payment")
async def one_payment(payment_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return await s.get_payment(db, tenant_id, payment_id)


@router.post("/payments/{payment_id}/void", summary="Void a payment and reopen its invoices")
async def void_pay(payment_id: uuid.UUID, body: VoidBody | None = None, user: User = Depends(_void),
                   tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await s.void_payment(db, tenant_id, payment_id, reason=body.reason if body else None, created_by=user.id)


# ── quotes (Phase 2b) ──
from app.services import finance_quotes as quotes  # noqa: E402


class QuoteBody(BaseModel):
    customer_id: uuid.UUID
    issue_date: datetime.date
    valid_until: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    reference: str | None = Field(None, max_length=100)
    notes: str | None = None
    lines: list[LineBody] = Field(min_length=1)
    send: bool = False


class QuotePatch(BaseModel):
    customer_id: uuid.UUID | None = None
    issue_date: datetime.date | None = None
    valid_until: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    reference: str | None = None
    notes: str | None = None
    lines: list[LineBody] | None = None


class ConvertBody(BaseModel):
    issue_date: datetime.date | None = None


@router.get("/quotes", summary="List quotes")
async def list_quotes(status_: Literal["draft", "sent", "accepted", "declined", "invoiced", "expired"] | None = Query(None, alias="status"),
                      customer_id: uuid.UUID | None = None, search: str | None = Query(None, max_length=100),
                      page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                      user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                      db: AsyncSession = Depends(get_db)) -> dict:
    items, total = await quotes.list_quotes(db, tenant_id, status=status_, customer_id=customer_id, search=search,
                                            page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/quotes", status_code=status.HTTP_201_CREATED, summary="Create a quote (draft, or mark sent)")
async def add_quote(body: QuoteBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                    db: AsyncSession = Depends(get_db)) -> dict:
    return await quotes.create_quote(db, tenant_id, customer_id=body.customer_id, issue_date=body.issue_date,
                                     valid_until=body.valid_until, lines=[l.spec() for l in body.lines],
                                     currency=body.currency, reference=body.reference, notes=body.notes,
                                     send=body.send, created_by=user.id)


@router.get("/quotes/{quote_id}", summary="Quote with lines")
async def one_quote(quote_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                    db: AsyncSession = Depends(get_db)) -> dict:
    return await quotes.get_quote(db, tenant_id, quote_id)


@router.patch("/quotes/{quote_id}", summary="Edit a draft quote")
async def edit_quote(quote_id: uuid.UUID, body: QuotePatch, user: User = Depends(_post),
                     tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    d = body.model_dump(exclude_unset=True)
    lines = [l.spec() for l in body.lines] if body.lines is not None else None
    d.pop("lines", None)
    return await quotes.update_quote(db, tenant_id, quote_id, lines=lines, **d)


@router.post("/quotes/{quote_id}/convert", summary="Turn a quote into a draft invoice")
async def convert_quote(quote_id: uuid.UUID, body: ConvertBody | None = None, user: User = Depends(_post),
                        tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await quotes.convert_to_invoice(db, tenant_id, quote_id, issue_date=body.issue_date if body else None,
                                           created_by=user.id)


@router.post("/quotes/{quote_id}/{action}", summary="Mark a quote sent / accepted / declined")
async def quote_status(quote_id: uuid.UUID, action: Literal["send", "accept", "decline"], user: User = Depends(_post),
                       tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await quotes.set_status(db, tenant_id, quote_id, {"send": "sent", "accept": "accepted", "decline": "declined"}[action])


@router.delete("/quotes/{quote_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft quote")
async def delete_quote(quote_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)) -> None:
    await quotes.delete_draft(db, tenant_id, quote_id)


# ── recurring invoices + reminders (Phase 2c) ──
from app.services import finance_recurring as recurring  # noqa: E402


class RecurringBody(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    customer_id: uuid.UUID
    frequency: Literal["weekly", "monthly", "quarterly", "yearly"]
    start_date: datetime.date
    end_date: datetime.date | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    reference: str | None = Field(None, max_length=100)
    notes: str | None = None
    auto_send: bool = False
    lines: list[LineBody] = Field(min_length=1)


class RecurringPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    frequency: Literal["weekly", "monthly", "quarterly", "yearly"] | None = None
    end_date: datetime.date | None = None
    reference: str | None = None
    notes: str | None = None
    auto_send: bool | None = None
    lines: list[LineBody] | None = None


@router.get("/recurring", summary="List recurring invoice schedules")
async def list_recurring(user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                         db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await recurring.list_recurring(db, tenant_id)}


@router.post("/recurring", status_code=status.HTTP_201_CREATED, summary="Create a recurring invoice schedule")
async def add_recurring(body: RecurringBody, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                        db: AsyncSession = Depends(get_db)) -> dict:
    return await recurring.create_recurring(
        db, tenant_id, title=body.title, customer_id=body.customer_id, frequency=body.frequency, start_date=body.start_date,
        end_date=body.end_date, lines=[l.spec() for l in body.lines], auto_send=body.auto_send, currency=body.currency,
        reference=body.reference, notes=body.notes, created_by=user.id)


@router.post("/recurring/run", summary="Generate any invoices that are due now")
async def run_recurring(user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                        db: AsyncSession = Depends(get_db)) -> dict:
    return await recurring.run_due(db, tenant_id=tenant_id)


@router.get("/recurring/{recurring_id}", summary="One recurring schedule with its lines")
async def one_recurring(recurring_id: uuid.UUID, user: User = Depends(_view), tenant_id: uuid.UUID = Depends(get_tenant_id),
                        db: AsyncSession = Depends(get_db)) -> dict:
    return await recurring.get_recurring(db, tenant_id, recurring_id)


@router.patch("/recurring/{recurring_id}", summary="Edit a recurring schedule")
async def edit_recurring(recurring_id: uuid.UUID, body: RecurringPatch, user: User = Depends(_post),
                         tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    d = body.model_dump(exclude_unset=True)
    lines = [l.spec() for l in body.lines] if body.lines is not None else None
    d.pop("lines", None)
    return await recurring.update_recurring(db, tenant_id, recurring_id, lines=lines, **d)


@router.post("/recurring/{recurring_id}/{action}", summary="Pause or resume a schedule")
async def recurring_state(recurring_id: uuid.UUID, action: Literal["pause", "resume"], user: User = Depends(_post),
                          tenant_id: uuid.UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)) -> dict:
    return await recurring.set_state(db, tenant_id, recurring_id, action)


@router.delete("/recurring/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a schedule (invoices already made stay)")
async def delete_recurring(recurring_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                           db: AsyncSession = Depends(get_db)) -> None:
    await recurring.delete_recurring(db, tenant_id, recurring_id)


@router.post("/invoices/{invoice_id}/remind", summary="Email the customer a payment reminder")
async def remind(invoice_id: uuid.UUID, user: User = Depends(_post), tenant_id: uuid.UUID = Depends(get_tenant_id),
                 db: AsyncSession = Depends(get_db)) -> dict:
    return await recurring.send_reminder(db, tenant_id, invoice_id)
