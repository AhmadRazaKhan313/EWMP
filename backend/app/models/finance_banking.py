"""Finance Banking: imported bank / wallet statement lines, matching to the ledger, and reconciliations."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


class FinBankStatement(TenantModel):
    """One imported file for one cash / bank / wallet account."""
    __tablename__ = "fin_bank_statements"

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FinBankReconciliation(TenantModel):
    """A finished reconciliation: beginning + cleared lines = statement balance on `statement_date`."""
    __tablename__ = "fin_bank_reconciliations"

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    beginning_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    statement_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cleared_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FinBankLine(TenantModel):
    """One row of a statement. amount > 0 is money in, amount < 0 is money out."""
    __tablename__ = "fin_bank_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "account_id", "fingerprint", name="uq_fin_bank_line_fingerprint"),
        UniqueConstraint("tenant_id", "matched_line_id", name="uq_fin_bank_line_matched"),
        CheckConstraint("status in ('unmatched','matched','ignored')", name="ck_fin_bank_line_status"),
        CheckConstraint("amount <> 0", name="ck_fin_bank_line_amount"),
    )

    statement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_bank_statements.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    tx_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="unmatched", server_default="unmatched")
    matched_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_journal_lines.id", ondelete="SET NULL"), nullable=True)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    matched_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reconciliation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("fin_bank_reconciliations.id", ondelete="SET NULL"), nullable=True, index=True)
