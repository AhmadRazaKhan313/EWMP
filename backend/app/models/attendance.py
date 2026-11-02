"""
Attendance and Leave models.

AttendanceRecord  — one row per employee per day; its check_in/check_out
                    are the first-in / last-out summary of that day
AttendancePunch   — one in/out pair; a day may have many
AttendanceRegularization — employee request to correct a missed punch,
                    pending manager approval
LeaveType         — org-defined leave categories (Annual, Sick, Maternity...)
LeaveBalance      — accrued / used balance per employee per leave type per year
LeaveRequest      — employee's leave application with approval workflow
Holiday           — org/branch-level public holiday calendar
Shift             — work shift definition (Morning, Night, Rotational)
ShiftAssignment   — which employee works which shift on which dates
"""

import uuid
import enum
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, Time, JSON,
    Enum as SAEnum, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel


class AttendanceSource(str, enum.Enum):
    MANUAL = "manual"
    BIOMETRIC = "biometric"
    QR_CODE = "qr_code"
    GEO = "geo"
    DESKTOP_AGENT = "desktop_agent"
    MOBILE = "mobile"


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    HALF_DAY = "half_day"
    ON_LEAVE = "on_leave"
    HOLIDAY = "holiday"
    WEEKEND = "weekend"
    WORK_FROM_HOME = "work_from_home"
    # A day the employee started but never closed, which the auto-cutoff
    # scheduler force-closed on their behalf. Deliberately its own status
    # rather than a boolean on PRESENT: payroll, reports and the
    # dashboard all need to treat it as "we do not know what was worked
    # here", and a status is the one field every one of them already
    # branches on.
    MISSED_PUNCH = "missed_punch"


class RegularizationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LeaveRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REVOKED = "revoked"


class AttendanceRecord(TenantModel):
    __tablename__ = "attendance_records"
    # One live row per employee per day (audit H-2; migration 1ff3dd1a844a).
    __table_args__ = (
        Index(
            "uq_attendance_records_one_per_day", "tenant_id", "employee_id", "date",
            unique=True, postgresql_where=text("is_deleted = false"),
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_in_source: Mapped[AttendanceSource] = mapped_column(
        SAEnum(AttendanceSource, name="attendance_source_enum"),
        default=AttendanceSource.MANUAL,
    )
    check_out_source: Mapped[AttendanceSource | None] = mapped_column(
        SAEnum(AttendanceSource, name="attendance_source_enum2"),
        nullable=True,
    )

    # Geo data
    check_in_latitude: Mapped[float | None] = mapped_column(nullable=True)
    check_in_longitude: Mapped[float | None] = mapped_column(nullable=True)
    check_out_latitude: Mapped[float | None] = mapped_column(nullable=True)
    check_out_longitude: Mapped[float | None] = mapped_column(nullable=True)
    is_within_geofence: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    status: Mapped[AttendanceStatus] = mapped_column(
        SAEnum(AttendanceStatus, name="attendance_status_enum"),
        default=AttendanceStatus.PRESENT,
        nullable=False,
        index=True,
    )

    # Computed durations in minutes (set by background worker)
    total_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    late_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shifts.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_regularized: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    regularized_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # ── Multi-punch + auto-cutoff ────────────────────────────────────────
    # check_in/check_out above are kept as the FIRST-in / LAST-out summary
    # of the day, because payroll, the CSV export and every existing report
    # read them. They are now derived from `punches` rather than being the
    # only record of what happened — see recalculate_from_punches().
    punches: Mapped[list["AttendancePunch"]] = relationship(
        "AttendancePunch",
        back_populates="attendance_record",
        cascade="all, delete-orphan",
        order_by="AttendancePunch.punch_in",
    )

    # How many completed in/out pairs make up this day. Denormalized so a
    # list view can show "3 punches" without loading every child row.
    punch_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Set when the scheduler closed this day rather than the employee.
    # Kept separate from status so that a regularization which restores
    # the day to PRESENT still leaves an audit trail that it was
    # originally force-closed.
    is_forced_checkout: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    forced_checkout_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<AttendanceRecord employee={self.employee_id} date={self.date}>"


class AttendancePunch(TenantModel):
    """
    One in/out pair within a day.

    Before this existed, `attendance_records` held a single check_in and a
    single check_out, so an employee who stepped out for lunch and punched
    back in got "Already checked in for today" (400) — the second, third
    and fourth punches of a day were not merely unreported, they were
    impossible to record. Anything that read hours worked was therefore
    reading one interval and calling it the day.

    A punch is open while punch_out is NULL. At most one punch per
    employee may be open at a time; that invariant is enforced by a
    partial unique index (see the migration) rather than in application
    code, because two concurrent check-in requests from a flaky mobile
    connection would otherwise both pass a SELECT-then-INSERT check.
    """

    __tablename__ = "attendance_punches"

    attendance_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    punch_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    punch_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    punch_in_source: Mapped[AttendanceSource] = mapped_column(
        SAEnum(AttendanceSource, name="attendance_source_enum", create_type=False),
        default=AttendanceSource.MANUAL,
        nullable=False,
    )
    punch_out_source: Mapped[AttendanceSource | None] = mapped_column(
        SAEnum(AttendanceSource, name="attendance_source_enum", create_type=False),
        nullable=True,
    )

    punch_in_latitude: Mapped[float | None] = mapped_column(nullable=True)
    punch_in_longitude: Mapped[float | None] = mapped_column(nullable=True)
    punch_out_latitude: Mapped[float | None] = mapped_column(nullable=True)
    punch_out_longitude: Mapped[float | None] = mapped_column(nullable=True)

    # Minutes between punch_in and punch_out, less any break taken inside
    # the interval. NULL while the punch is open.
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # True when the scheduler closed this punch. The spec calls for
    # punch_out to stay NULL in that case so nobody mistakes a
    # system-invented time for something the employee actually did;
    # `auto_closed_at` records when the cutoff fired, purely for audit.
    is_forced_checkout: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    auto_closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shifts.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    attendance_record: Mapped["AttendanceRecord"] = relationship(
        "AttendanceRecord", back_populates="punches"
    )

    @property
    def is_open(self) -> bool:
        return self.punch_out is None and not self.is_forced_checkout

    def __repr__(self) -> str:
        state = "open" if self.is_open else "forced" if self.is_forced_checkout else "closed"
        return f"<AttendancePunch employee={self.employee_id} in={self.punch_in} {state}>"


class AttendanceRegularization(TenantModel):
    """
    An employee's request to correct a day the system could not record
    correctly — almost always a missed check-out that the auto-cutoff
    scheduler flagged.

    The requested times are held HERE, not written onto the attendance
    record, until a manager approves. That separation is the whole point:
    an unapproved claim must not be able to move payable hours, and
    keeping the claim in its own row means the original (wrong) state
    stays intact and auditable if the request is rejected.
    """

    __tablename__ = "attendance_regularizations"

    attendance_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The specific punch being corrected. NULL means the request is about
    # the day as a whole (e.g. the employee never punched in at all).
    punch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_punches.id", ondelete="CASCADE"),
        nullable=True,
    )

    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    requested_punch_in: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_punch_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[RegularizationStatus] = mapped_column(
        SAEnum(RegularizationStatus, name="regularization_status_enum"),
        default=RegularizationStatus.PENDING,
        nullable=False,
        index=True,
    )

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AttendanceRegularization employee={self.employee_id} date={self.date} {self.status}>"


class LeaveType(TenantModel):
    __tablename__ = "leave_types"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Accrual policy
    days_per_year: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    is_carry_forward: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    max_carry_forward_days: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    is_encashable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    min_days_per_request: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=1)
    max_days_per_request: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Rules
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    requires_document: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notice_days_required: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    applicable_gender: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="NULL=all, male, female"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class LeaveBalance(TenantModel):
    __tablename__ = "leave_balances"
    # One live balance per employee, leave type and year (audit H-2; migration 1ff3dd1a844a).
    __table_args__ = (
        Index(
            "uq_leave_balances_one_per_type_year", "employee_id", "leave_type_id", "year",
            unique=True, postgresql_where=text("is_deleted = false"),
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leave_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    entitled_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    carried_forward_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    used_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    pending_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)

    @property
    def remaining_days(self) -> Decimal:
        return self.entitled_days + self.carried_forward_days - self.used_days - self.pending_days


class LeaveRequest(TenantModel):
    __tablename__ = "leave_requests"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leave_types.id", ondelete="RESTRICT"),
        nullable=False,
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_days: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    # ── Duration model (bug H6) ─────────────────────────────────────
    # "full_day" | "half_day" | "hourly" — the single source of truth for
    # how total_days was computed. is_half_day/half_day_period are kept in
    # sync for backward compatibility with anything reading those directly.
    duration_type: Mapped[str] = mapped_column(String(10), default="full_day", server_default="full_day")
    hours: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2), nullable=True, comment="Only set when duration_type='hourly'"
    )
    is_half_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    half_day_period: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="morning or afternoon"
    )

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[LeaveRequestStatus] = mapped_column(
        SAEnum(LeaveRequestStatus, name="leave_request_status_enum"),
        default=LeaveRequestStatus.PENDING,
        nullable=False,
        index=True,
    )

    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<LeaveRequest employee={self.employee_id} {self.start_date}→{self.end_date}>"


class Holiday(TenantModel):
    __tablename__ = "holidays"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # NULL = applies to all branches
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<Holiday {self.name!r} {self.date}>"


class Shift(TenantModel):
    __tablename__ = "shifts"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_overnight: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Grace periods in minutes
    late_grace_minutes: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    early_leave_grace_minutes: Mapped[int] = mapped_column(Integer, default=10, server_default="10")

    # Work days: JSON array e.g. ["mon","tue","wed","thu","fri"]
    work_days: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")

    break_duration_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    weekly_hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=40)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<Shift {self.name!r} {self.start_time}–{self.end_time}>"