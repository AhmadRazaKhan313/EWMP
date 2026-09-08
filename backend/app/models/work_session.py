"""
WorkSession & Break models (Phase 3 — desktop app timer support).

`WorkSession` is the live, moment-to-moment source of truth the desktop
app's timer widget starts/stops and re-derives elapsed time from. This is
deliberately separate from `AttendanceRecord` (the once-per-day
check-in/check-out audit trail used by the web dashboard) — an employee
can start and stop the timer multiple times in a day (e.g. lunch break
handled by pausing rather than a new attendance record), and the
desktop app's "Start" action implicitly triggers the existing
`/attendance/check-in` the first time it happens each day (wiring done in
the API layer, not here).

`BreakType` — org-defined break categories (Lunch, Coffee, Personal).
`BreakRecord` — one break taken during a WorkSession; pauses the timer.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel


class WorkSessionStatus(str, enum.Enum):
    ACTIVE = "active"  # running, not on break
    ON_BREAK = "on_break"  # running, currently paused for a break
    ENDED = "ended"


class WorkSession(TenantModel):
    __tablename__ = "work_sessions"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[WorkSessionStatus] = mapped_column(
        SAEnum(WorkSessionStatus, name="work_session_status_enum"),
        default=WorkSessionStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    # Denormalized once ended, so history views don't need to recompute
    # (started_at, ended_at, minus every break's duration) every time.
    total_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    breaks: Mapped[list["BreakRecord"]] = relationship(
        "BreakRecord", back_populates="work_session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<WorkSession employee={self.employee_id} status={self.status}>"


class BreakType(TenantModel):
    __tablename__ = "break_types"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<BreakType {self.name!r}>"


class BreakRecord(TenantModel):
    __tablename__ = "break_records"

    work_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    break_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("break_types.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    work_session: Mapped["WorkSession"] = relationship("WorkSession", back_populates="breaks")

    def __repr__(self) -> str:
        return f"<BreakRecord session={self.work_session_id}>"
