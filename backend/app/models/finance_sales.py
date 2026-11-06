"""
Finance Phase 2a (Sales): customers, invoices, payments received.

Amounts on invoices and payments are in the document's own currency; the journal entry
that each posts carries the base-currency figures (see app/services/finance_sales.py).
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


def _enum(e, name):
    return SAEnum(e, name=name, values_callable=lambda x: [m.value for m in x])


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"            # posted to the ledger, nothing paid yet
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"


class PaymentStatus(str, enum.Enum):
    POSTED = "posted"
    VOID = "void"


class FinCustomer(TenantModel):
    __tablename__ = "fin_customers"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    company: Mapped[str | None] = mapped_column(String(150), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    auto_remind: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class FinInvoice(TenantModel):
    __tablename__ = "fin_invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_fin_invoices_tenant_number"),
        Index("ix_fin_invoices_tenant_customer", "tenant_id", "customer_id"),
        CheckConstraint("amount_paid >= 0 AND amount_paid <= total", name="ck_fin_invoices_paid_range"),
    )

    number: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_customers.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(_enum(InvoiceStatus, "fin_invoice_status_enum"), nullable=False, default=InvoiceStatus.DRAFT, server_default="draft")
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("1"), server_default="1")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_journal_entries.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    recurring_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_recurring_invoices.id", ondelete="SET NULL"), nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FinInvoiceLine(TenantModel):
    __tablename__ = "fin_invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_tax_rates.id", ondelete="SET NULL"), nullable=True)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    income_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")


class FinPayment(TenantModel):
    __tablename__ = "fin_payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_fin_payments_tenant_number"),
        CheckConstraint("amount > 0", name="ck_fin_payments_positive"),
    )

    number: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[PaymentStatus] = mapped_column(_enum(PaymentStatus, "fin_payment_status_enum"), nullable=False, default=PaymentStatus.POSTED, server_default="posted")
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("1"), server_default="1")
    deposit_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False)
    method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_journal_entries.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FinPaymentAllocation(TenantModel):
    __tablename__ = "fin_payment_allocations"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_fin_alloc_positive"),)

    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_invoices.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # in the invoice's currency


class QuoteStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    INVOICED = "invoiced"    # converted to an invoice


class FinQuote(TenantModel):
    """A priced offer. Never touches the ledger; converting it creates a draft invoice."""
    __tablename__ = "fin_quotes"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_fin_quotes_tenant_number"),
                      Index("ix_fin_quotes_tenant_customer", "tenant_id", "customer_id"))

    number: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_customers.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[QuoteStatus] = mapped_column(_enum(QuoteStatus, "fin_quote_status_enum"), nullable=False, default=QuoteStatus.DRAFT, server_default="draft")
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_invoices.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FinQuoteLine(TenantModel):
    __tablename__ = "fin_quote_lines"

    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_tax_rates.id", ondelete="SET NULL"), nullable=True)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    income_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")


class RecurringStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


class RecurringFrequency(str, enum.Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class FinRecurringInvoice(TenantModel):
    """Template that generates a draft (or sent) invoice on a schedule. Dates are start_date + n steps, so they never drift."""
    __tablename__ = "fin_recurring_invoices"

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[RecurringStatus] = mapped_column(_enum(RecurringStatus, "fin_recurring_status_enum"), nullable=False, default=RecurringStatus.ACTIVE, server_default="active")
    frequency: Mapped[RecurringFrequency] = mapped_column(_enum(RecurringFrequency, "fin_recurring_freq_enum"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    auto_send: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FinRecurringLine(TenantModel):
    __tablename__ = "fin_recurring_lines"

    recurring_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_recurring_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_tax_rates.id", ondelete="SET NULL"), nullable=True)
    income_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False)
