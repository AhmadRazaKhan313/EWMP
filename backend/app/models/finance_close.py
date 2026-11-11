"""Finance Phase 6: period close. Books are locked through the latest active close; nothing can be posted on or before it."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


class FinPeriodClose(TenantModel):
    """One month or financial year that was closed. Reopening soft-deletes the latest row."""
    __tablename__ = "fin_period_closes"

    period_type: Mapped[str] = mapped_column(String(10), nullable=False)  # month | year
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    net_profit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
