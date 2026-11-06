"""
Finance Phase 3a (Purchases): vendors, bills, payments made. Mirror of finance_sales.

Amounts are in the document's own currency; the journal entry each posts carries the base-currency figures.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


def _enum(e, name):
    return SAEnum(e, name=name, values_callable=lambda x: [m.value for m in x])


class BillStatus(str, enum.Enum):
    DRAFT = "draft"
    OPEN = "open"            # posted to the ledger, nothing paid yet
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"


class BillPaymentStatus(str, enum.Enum):
    POSTED = "posted"
    VOID = "void"


class FinVendor(TenantModel):
    __tablename__ = "fin_vendors"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    company: Mapped[str | None] = mapped_column(String(150), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class FinBill(TenantModel):
    __tablename__ = "fin_bills"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_fin_bills_tenant_number"),
        Index("ix_fin_bills_tenant_vendor", "tenant_id", "vendor_id"),
        CheckConstraint("amount_paid >= 0 AND amount_paid <= total", name="ck_fin_bills_paid_range"),
    )

    number: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_vendors.id", ondelete="RESTRICT"), nullable=False)
    vendor_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)   # the supplier's own invoice number
    status: Mapped[BillStatus] = mapped_column(_enum(BillStatus, "fin_bill_status_enum"), nullable=False, default=BillStatus.DRAFT, server_default="draft")
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("1"), server_default="1")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_journal_entries.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Phase 3b: approval workflow, recurring and purchase-order links
    approval_status: Mapped[str] = mapped_column(String(10), nullable=False, default="none", server_default="none")  # none|pending|approved|rejected
    approval_requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recurring_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_recurring_bills.id", ondelete="SET NULL"), nullable=True)


class FinBillLine(TenantModel):
    __tablename__ = "fin_bill_lines"

    bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_bills.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_tax_rates.id", ondelete="SET NULL"), nullable=True)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    expense_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")


class FinBillPayment(TenantModel):
    __tablename__ = "fin_bill_payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_fin_bill_payments_tenant_number"),
        CheckConstraint("amount > 0", name="ck_fin_bill_payments_positive"),
    )

    number: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_vendors.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[BillPaymentStatus] = mapped_column(_enum(BillPaymentStatus, "fin_bill_payment_status_enum"), nullable=False, default=BillPaymentStatus.POSTED, server_default="posted")
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("1"), server_default="1")
    paid_from_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False)
    method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_journal_entries.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FinBillPaymentAllocation(TenantModel):
    __tablename__ = "fin_bill_payment_allocations"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_fin_bill_alloc_positive"),)

    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_bill_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_bills.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # in the bill's currency


# ───────────────────────── Phase 3b ─────────────────────────
class PurchaseOrderStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    RECEIVED = "received"
    BILLED = "billed"
    CANCELLED = "cancelled"


class RecurringBillStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


class RecurringBillFrequency(str, enum.Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class FinPurchaseSettings(TenantModel):
    """One row per tenant. A bill whose base-currency total reaches approval_threshold must be approved before it posts."""
    __tablename__ = "fin_purchase_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_fin_purchase_settings_tenant"),)

    approval_threshold: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class FinBillAttachment(TenantModel):
    __tablename__ = "fin_bill_attachments"

    bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_bills.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FinPurchaseOrder(TenantModel):
    """A commitment to buy. Never touches the ledger; converting it creates a draft bill."""
    __tablename__ = "fin_purchase_orders"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_fin_po_tenant_number"),
                      Index("ix_fin_po_tenant_vendor", "tenant_id", "vendor_id"))

    number: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_vendors.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[PurchaseOrderStatus] = mapped_column(_enum(PurchaseOrderStatus, "fin_po_status_enum"), nullable=False, default=PurchaseOrderStatus.DRAFT, server_default="draft")
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    bill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_bills.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FinPurchaseOrderLine(TenantModel):
    __tablename__ = "fin_purchase_order_lines"

    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_tax_rates.id", ondelete="SET NULL"), nullable=True)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    expense_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")


class FinRecurringBill(TenantModel):
    """Template that makes a draft (or posted) bill on a schedule. Dates are start_date + n steps, so they never drift."""
    __tablename__ = "fin_recurring_bills"

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_vendors.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[RecurringBillStatus] = mapped_column(_enum(RecurringBillStatus, "fin_rbill_status_enum"), nullable=False, default=RecurringBillStatus.ACTIVE, server_default="active")
    frequency: Mapped[RecurringBillFrequency] = mapped_column(_enum(RecurringBillFrequency, "fin_rbill_freq_enum"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    auto_post: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vendor_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FinRecurringBillLine(TenantModel):
    __tablename__ = "fin_recurring_bill_lines"

    recurring_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_recurring_bills.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False, default=Decimal("0"), server_default="0")
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_tax_rates.id", ondelete="SET NULL"), nullable=True)
    expense_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False)
