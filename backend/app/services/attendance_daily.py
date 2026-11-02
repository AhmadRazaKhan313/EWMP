"""
Daily attendance sheet: who is present, absent, late, on leave or off today.

Why this exists
---------------
The Attendance page used to list raw AttendanceRecord rows. A row only exists
when someone punches in, so

  * an employee who never showed up had no row -- nobody could ever be Absent;
  * the page asked for ?date=... but the endpoint ignored it, so it listed the
    newest records of ALL days and counted every one as Present.

Like OrangeHRM, presence comes from real punches and absence is *derived*: a
person is Absent only if the day was a scheduled working day for them, it is
over, and they did not punch. Nothing is stored for absent days, so a new
employee can never appear "present" just because they exist.

How a day is classified (first match wins)
------------------------------------------
  1. A record that shows work (present / late / half day / WFH / missed punch)
     AND has a real check-in (or HR set it explicitly) -> that status, even on
     an off day. A row with no check-in is ignored.
  2. HR's explicit call on the record (on leave / holiday / weekend / absent).
  3. A public holiday for the employee's branch -> HOLIDAY
  4. Not a working day on the employee's shift (or the org's work week when they
     have no shift)                          -> WEEKLY_OFF
  5. Approved leave covering the day         -> ON_LEAVE
  6. A working day with no punch:
       - the shift has not started yet / future day       -> SCHEDULED
       - the shift is running (or the day is today, no shift) -> NOT_CHECKED_IN
       - the shift/day is over                            -> ABSENT

Everything is evaluated in the organisation's timezone (app.core.timezones),
the same clock the punch system, lateness and payroll use.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezones import local_to_utc, local_today, org_zone
from app.models.attendance import (
    AttendanceRecord,
    AttendanceStatus,
    Holiday,
    LeaveRequest,
    LeaveRequestStatus,
    Shift,
)
from app.models.employee import Employee, EmploymentStatus
from app.models.organization import Organization
from app.models.organization_structure import Department
from app.models.user import User
from app.services.payroll_calendar import WEEKDAYS, work_weekdays_from


class DayStatus(str, enum.Enum):
    # worked
    PRESENT = "present"
    LATE = "late"
    HALF_DAY = "half_day"
    WORK_FROM_HOME = "work_from_home"
    MISSED_PUNCH = "missed_punch"
    # did not / will not work
    ABSENT = "absent"
    ON_LEAVE = "on_leave"
    HOLIDAY = "holiday"
    WEEKLY_OFF = "weekly_off"
    # a working day that is not decided yet
    NOT_CHECKED_IN = "not_checked_in"
    SCHEDULED = "scheduled"


WORKED = frozenset(
    {DayStatus.PRESENT, DayStatus.LATE, DayStatus.HALF_DAY,
     DayStatus.WORK_FROM_HOME, DayStatus.MISSED_PUNCH}
)

# What a stored record's status maps to on the sheet.
_FROM_RECORD = {
    AttendanceStatus.PRESENT: DayStatus.PRESENT,
    AttendanceStatus.LATE: DayStatus.LATE,
    AttendanceStatus.HALF_DAY: DayStatus.HALF_DAY,
    AttendanceStatus.WORK_FROM_HOME: DayStatus.WORK_FROM_HOME,
    AttendanceStatus.MISSED_PUNCH: DayStatus.MISSED_PUNCH,
    AttendanceStatus.ABSENT: DayStatus.ABSENT,
    AttendanceStatus.ON_LEAVE: DayStatus.ON_LEAVE,
    AttendanceStatus.HOLIDAY: DayStatus.HOLIDAY,
    AttendanceStatus.WEEKEND: DayStatus.WEEKLY_OFF,
}


def resolve_day_status(
    *,
    day: date,
    now: datetime,
    zone: ZoneInfo,
    record_status: AttendanceStatus | None,
    is_holiday: bool,
    is_work_day: bool,
    on_leave: bool,
    shift_start: time | None,
    shift_end: time | None,
    shift_overnight: bool = False,
    has_check_in: bool = True,
    is_regularized: bool = False,
) -> DayStatus:
    """Classify one employee-day. Pure -- no I/O, easy to test."""
    if record_status is not None:
        mapped = _FROM_RECORD.get(record_status)
        # A "worked" status only counts when the person really checked in (or
        # HR explicitly set it). The day row is created with the default status
        # PRESENT, so a row with no check-in must NOT make anyone Present.
        if mapped in WORKED and not has_check_in and not is_regularized:
            mapped = None
        if mapped is not None:
            return mapped

    if is_holiday:
        return DayStatus.HOLIDAY
    if not is_work_day:
        return DayStatus.WEEKLY_OFF
    if on_leave:
        return DayStatus.ON_LEAVE

    today = local_today(zone, now)
    if day > today:
        return DayStatus.SCHEDULED

    if shift_start is not None and shift_end is not None:
        start = local_to_utc(day, shift_start, zone)
        end_day = day.fromordinal(day.toordinal() + 1) if shift_overnight else day
        end = local_to_utc(end_day, shift_end, zone)
        if now < start:
            return DayStatus.SCHEDULED
        if now < end:
            return DayStatus.NOT_CHECKED_IN
        return DayStatus.ABSENT

    # No shift: the working day is "over" only once the calendar day is.
    return DayStatus.NOT_CHECKED_IN if day == today else DayStatus.ABSENT


@dataclass
class SheetRow:
    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    department_name: str | None
    shift_name: str | None
    shift_start: str | None
    shift_end: str | None
    status: DayStatus
    check_in: datetime | None
    check_out: datetime | None
    total_minutes: int | None
    late_minutes: int | None
    overtime_minutes: int | None
    record_id: uuid.UUID | None
    is_regularized: bool
    detail: str | None

    def as_dict(self) -> dict:
        return {
            "employee_id": str(self.employee_id),
            "employee_code": self.employee_code,
            "employee_name": self.employee_name,
            "department_name": self.department_name,
            "shift_name": self.shift_name,
            "shift_start": self.shift_start,
            "shift_end": self.shift_end,
            "status": self.status.value,
            "check_in": self.check_in.isoformat() if self.check_in else None,
            "check_out": self.check_out.isoformat() if self.check_out else None,
            "total_minutes": self.total_minutes,
            "late_minutes": self.late_minutes,
            "overtime_minutes": self.overtime_minutes,
            "record_id": str(self.record_id) if self.record_id else None,
            "is_regularized": self.is_regularized,
            "detail": self.detail,
        }


def summarize(rows: list[SheetRow]) -> dict[str, int]:
    counts = {s.value: 0 for s in DayStatus}
    for r in rows:
        counts[r.status.value] += 1
    present_total = sum(counts[s.value] for s in WORKED)
    return {
        **counts,
        "present_total": present_total,
        # People who were expected to work this day (not off, not on holiday).
        "expected": present_total + counts["absent"] + counts["on_leave"]
        + counts["not_checked_in"] + counts["scheduled"],
        "total": len(rows),
    }


async def build_daily_sheet(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    day: date | None = None,
    *,
    employee_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    search: str | None = None,
    now: datetime | None = None,
) -> tuple[date, list[SheetRow]]:
    """One row per employee who was employed on `day`, with a derived status.
    Returns (day, rows) -- `day` defaults to today in the org's timezone."""
    now = now or datetime.now(UTC)
    zone = await org_zone(db, tenant_id)
    day = day or local_today(zone, now)

    org_settings = (
        await db.execute(select(Organization.settings).where(Organization.id == tenant_id))
    ).scalar_one_or_none()
    org_weekdays = work_weekdays_from(org_settings)

    emp_filters = [
        Employee.tenant_id == tenant_id,
        Employee.is_deleted == False,  # noqa: E712
        Employee.date_of_joining <= day,
        or_(Employee.date_of_leaving.is_(None), Employee.date_of_leaving >= day),
        # Someone marked terminated/resigned with no leaving date can't be
        # placed in time -- leave them off rather than guess.
        or_(
            Employee.employment_status.notin_(
                [EmploymentStatus.TERMINATED, EmploymentStatus.RESIGNED]
            ),
            Employee.date_of_leaving.isnot(None),
        ),
    ]
    if employee_id:
        emp_filters.append(Employee.id == employee_id)
    if department_id:
        emp_filters.append(Employee.department_id == department_id)
    if branch_id:
        emp_filters.append(Employee.branch_id == branch_id)
    if search:
        like = f"%{search.strip()}%"
        emp_filters.append(
            or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.email.ilike(like),
                Employee.employee_code.ilike(like),
                func.concat(User.first_name, " ", User.last_name).ilike(like),
            )
        )

    employees = (
        await db.execute(
            select(Employee, User, Shift, Department.name)
            .join(User, Employee.user_id == User.id)
            .outerjoin(Shift, Employee.default_shift_id == Shift.id)
            .outerjoin(Department, Employee.department_id == Department.id)
            .where(*emp_filters)
            .order_by(User.first_name, User.last_name)
        )
    ).all()
    if not employees:
        return day, []

    ids = [e.id for e, _, _, _ in employees]

    records = {
        r.employee_id: r
        for r in (
            await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.tenant_id == tenant_id,
                    AttendanceRecord.is_deleted == False,  # noqa: E712
                    AttendanceRecord.date == day,
                    AttendanceRecord.employee_id.in_(ids),
                )
            )
        ).scalars().all()
    }

    holidays = (
        await db.execute(
            select(Holiday.branch_id, Holiday.name).where(
                Holiday.tenant_id == tenant_id,
                Holiday.is_deleted == False,  # noqa: E712
                Holiday.is_optional == False,  # noqa: E712
                Holiday.date == day,
            )
        )
    ).all()

    leave_rows = (
        await db.execute(
            select(LeaveRequest.employee_id).where(
                LeaveRequest.tenant_id == tenant_id,
                LeaveRequest.is_deleted == False,  # noqa: E712
                LeaveRequest.status == LeaveRequestStatus.APPROVED,
                LeaveRequest.start_date <= day,
                LeaveRequest.end_date >= day,
                LeaveRequest.employee_id.in_(ids),
            )
        )
    ).scalars().all()
    on_leave = set(leave_rows)

    rows: list[SheetRow] = []
    for emp, user, shift, dept_name in employees:
        holiday_name = next(
            (name for b_id, name in holidays if b_id is None or b_id == emp.branch_id), None
        )
        if shift is not None and shift.work_days:
            weekdays = {WEEKDAYS.index(d) for d in shift.work_days if d in WEEKDAYS}
        else:
            weekdays = org_weekdays
        record = records.get(emp.id)

        status = resolve_day_status(
            day=day,
            now=now,
            zone=zone,
            record_status=record.status if record else None,
            is_holiday=holiday_name is not None,
            is_work_day=day.weekday() in weekdays,
            on_leave=emp.id in on_leave,
            shift_start=shift.start_time if shift else None,
            shift_end=shift.end_time if shift else None,
            shift_overnight=bool(shift and shift.is_overnight),
            has_check_in=bool(record and record.check_in is not None),
            is_regularized=bool(record and record.is_regularized),
        )
        rows.append(
            SheetRow(
                employee_id=emp.id,
                employee_code=emp.employee_code,
                employee_name=(user.display_name or f"{user.first_name} {user.last_name}").strip(),
                department_name=dept_name,
                shift_name=shift.name if shift else None,
                shift_start=shift.start_time.strftime("%H:%M") if shift else None,
                shift_end=shift.end_time.strftime("%H:%M") if shift else None,
                status=status,
                check_in=record.check_in if record else None,
                check_out=record.check_out if record else None,
                total_minutes=record.total_minutes if record else None,
                late_minutes=record.late_minutes if record else None,
                overtime_minutes=record.overtime_minutes if record else None,
                record_id=record.id if record else None,
                is_regularized=bool(record and record.is_regularized),
                detail=holiday_name if status == DayStatus.HOLIDAY else None,
            )
        )
    return day, rows
