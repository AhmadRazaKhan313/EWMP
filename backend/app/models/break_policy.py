"""
Break-time lock (K-01).

`BreakPolicy`        — a daily break window at one scope (organization / department / shift / employee).
`BreakOverride`      — a one-day exception for an employee or a department (new window, or no break).
`BreakUnlockRequest` — an employee asking to keep working during the window; admin approves/denies.

Times are wall-clock in the organisation's timezone (see app.core.timezones).
"""
import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


class BreakScope(str, enum.Enum):
    ORGANIZATION = "organization"
    DEPARTMENT = "department"
    SHIFT = "shift"
    EMPLOYEE = "employee"


class UnlockStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class BreakPolicy(TenantModel):
    __tablename__ = "break_policies"

    scope: Mapped[BreakScope] = mapped_column(SAEnum(BreakScope, name="break_scope_enum", values_callable=lambda e: [m.value for m in e]), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    # Weekdays the break applies on (0=Mon … 6=Sun); NULL = every day.
    days: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class BreakOverride(TenantModel):
    __tablename__ = "break_overrides"

    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=True, index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True)
    on_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # NULL start_time = "no break that day".
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class BreakUnlockRequest(TenantModel):
    __tablename__ = "break_unlock_requests"
    __table_args__ = (Index("ix_break_unlock_employee_date", "employee_id", "break_date"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    break_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[UnlockStatus] = mapped_column(SAEnum(UnlockStatus, name="break_unlock_status_enum", values_callable=lambda e: [m.value for m in e]), nullable=False, default=UnlockStatus.PENDING, server_default="pending", index=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unlock_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
