"""
Finance foundations (Phase 0): a per-organization double-entry ledger.

`FinAccount`      — chart of accounts. Categories ARE accounts (Salary, Utilities …).
`FinJournalEntry` — one balanced transaction (header).
`FinJournalLine`  — one debit-or-credit line, stored in the org's base currency,
                    with the original amount / currency / rate kept alongside.
`FinExchangeRate` — optional per-day rate table (1 unit of currency = rate base units).
`FinTaxRate`      — configurable tax rates (no jurisdiction rules are hard-coded).

Every table is tenant-scoped (tenant_id = Organization id): each organization
has its own independent books.
"""
import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


def _enum(e, name):
    return SAEnum(e, name=name, values_callable=lambda x: [m.value for m in x])


class AccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


class EntryStatus(str, enum.Enum):
    POSTED = "posted"
    REVERSED = "reversed"


class FinAccount(TenantModel):
    __tablename__ = "fin_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_fin_accounts_tenant_code"),
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[AccountType] = mapped_column(_enum(AccountType, "fin_account_type_enum"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="SET NULL"), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    money_kind: Mapped[str | None] = mapped_column(String(10), nullable=True)  # cash | bank | wallet (asset accounts)


class FinJournalEntry(TenantModel):
    __tablename__ = "fin_journal_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_fin_entries_tenant_number"),
        Index("ix_fin_entries_tenant_date", "tenant_id", "entry_date"),
    )

    number: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[EntryStatus] = mapped_column(_enum(EntryStatus, "fin_entry_status_enum"), nullable=False, default=EntryStatus.POSTED, server_default="posted")
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_journal_entries.id", ondelete="SET NULL"), nullable=True)
    reversed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_journal_entries.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payment_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)   # bank / wallet name
    payment_account_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    payment_tid: Mapped[str | None] = mapped_column(String(100), nullable=True)        # transaction id


class FinJournalLine(TenantModel):
    __tablename__ = "fin_journal_lines"
    __table_args__ = (
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="ck_fin_lines_one_side",
        ),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_journal_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Base-currency amounts (what the books balance on).
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    # What the user actually entered.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_original: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("1"), server_default="1")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class FinExchangeRate(TenantModel):
    __tablename__ = "fin_exchange_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "currency", "on_date", name="uq_fin_rates_tenant_cur_date"),
        CheckConstraint("rate > 0", name="ck_fin_rates_positive"),
    )

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    on_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)


class FinTaxRate(TenantModel):
    __tablename__ = "fin_tax_rates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="sales", server_default="sales")
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class FinPaymentProvider(TenantModel):
    """Banks / mobile wallets this organization added beyond the built-in list."""
    __tablename__ = "fin_payment_providers"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "name", name="uq_fin_providers_tenant_kind_name"),)

    kind: Mapped[str] = mapped_column(String(10), nullable=False)   # bank | wallet
    name: Mapped[str] = mapped_column(String(100), nullable=False)
