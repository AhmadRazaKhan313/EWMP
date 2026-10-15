"""
How much of the period an employee is paid for — audit findings C-7 / H-9.

Before, the attendance factor was (present + paid-leave days) / Mon–Fri
days, and "no attendance at all" meant factor 1. So an employee who never
checked in got full pay while one with a single record got ~1/22 of it;
public holidays and half days were docked; paid leave was counted in
calendar days; soft-deleted attendance counted; the organisation's work
week and every proration setting in PayrollSettings were ignored; and
joiners / leavers were paid (or not paid) for the whole period.

The rule now (one pure function, compute_payable_days):

  * The period is measured by PayrollSettings.proration_method:
      CALENDAR_DAYS  every day of the period          (the default)
      WORKING_DAYS   the organisation's work week, minus holidays
      FIXED_DIVISOR  a constant (fixed_monthly_divisor, e.g. 30)
      HOURLY         treated as WORKING_DAYS for day proration
  * Pay is reduced ONLY for what is recorded: an ABSENT day (1), a HALF_DAY
    (½), approved UNPAID leave — each counted on work days only, never on a
    weekend or holiday — and days before joining / after leaving.
  * A day with no attendance record is not docked: absence has to be
    recorded, so a missing check-in never silently costs a day's pay, and
    there is no longer a cliff between "no data" and "some data".
  * Holidays never reduce pay. MISSED_PUNCH is presence (hours are fixed
    through a regularization, not by docking the day).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import (
    AttendanceRecord,
    AttendanceStatus,
    Holiday,
    LeaveRequest,
    LeaveRequestStatus,
    LeaveType,
)
from app.models.payroll import WorkingDaysMethod

ONE = Decimal("1")
ZERO = Decimal("0")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_WORK_DAYS = ("mon", "tue", "wed", "thu", "fri")


@dataclass
class DayInputs:
    period_start: date
    period_end: date
    method: WorkingDaysMethod
    fixed_divisor: Decimal | None
    work_weekdays: set[int]                      # 0 = Monday
    holidays: set[date]
    joined: date
    left: date | None
    absent: dict[date, Decimal] = field(default_factory=dict)        # 1 = absent, 0.5 = half day
    unpaid_leave: dict[date, Decimal] = field(default_factory=dict)
    paid_leave: dict[date, Decimal] = field(default_factory=dict)


@dataclass
class PayableDays:
    factor: Decimal            # 0..1 — multiply earnings by this
    working_days: int          # work days in the period (for the payslip)
    paid_days: Decimal         # employed work days, minus unpaid ones
    absent_days: Decimal
    paid_leave_days: Decimal
    unpaid_leave_days: Decimal
    holiday_days: int
    not_employed_days: int     # calendar days before joining / after leaving


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def compute_payable_days(inp: DayInputs) -> PayableDays:
    calendar = list(_days(inp.period_start, inp.period_end))

    def employed(d: date) -> bool:
        return inp.joined <= d and (inp.left is None or d <= inp.left)

    def work_day(d: date) -> bool:
        return d.weekday() in inp.work_weekdays and d not in inp.holidays

    work_days = [d for d in calendar if work_day(d)]
    holiday_days = sum(1 for d in calendar if d in inp.holidays and d.weekday() in inp.work_weekdays)
    not_employed = sum(1 for d in calendar if not employed(d))

    absent = unpaid = paid = ZERO
    for d in work_days:
        if not employed(d):
            continue
        a = min(ONE, inp.absent.get(d, ZERO))
        u = min(ONE - a, inp.unpaid_leave.get(d, ZERO))
        absent += a
        unpaid += u
        paid += min(ONE - a - u, inp.paid_leave.get(d, ZERO))
    unpaid_days = absent + unpaid

    if inp.method == WorkingDaysMethod.CALENDAR_DAYS:
        base = Decimal(len(calendar))
        payable = base - not_employed - unpaid_days
    elif inp.method == WorkingDaysMethod.FIXED_DIVISOR and inp.fixed_divisor and inp.fixed_divisor > 0:
        base = inp.fixed_divisor
        employed_share = Decimal(len(calendar) - not_employed) / Decimal(len(calendar))
        payable = base * employed_share - unpaid_days
    else:  # WORKING_DAYS, HOURLY, or FIXED_DIVISOR without a divisor
        base = Decimal(len(work_days))
        payable = sum((ONE for d in work_days if employed(d)), ZERO) - unpaid_days

    if base <= 0:  # a period with no work days at all (e.g. entirely holidays)
        factor = Decimal(len(calendar) - not_employed) / Decimal(len(calendar))
    else:
        factor = max(ZERO, min(ONE, payable / base))

    employed_work_days = sum((ONE for d in work_days if employed(d)), ZERO)
    return PayableDays(
        factor=factor,
        working_days=len(work_days),
        paid_days=max(ZERO, employed_work_days - unpaid_days),
        absent_days=absent,
        paid_leave_days=paid,
        unpaid_leave_days=unpaid,
        holiday_days=holiday_days,
        not_employed_days=not_employed,
    )


def work_weekdays_from(org_settings: dict | None) -> set[int]:
    days = (org_settings or {}).get("work_days") or DEFAULT_WORK_DAYS
    return {WEEKDAYS.index(d) for d in days if d in WEEKDAYS} or {0, 1, 2, 3, 4}


async def load_day_inputs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee,
    period_start: date,
    period_end: date,
    method: WorkingDaysMethod,
    fixed_divisor: Decimal | None,
    org_settings: dict | None,
) -> DayInputs:
    """Everything compute_payable_days needs for one employee."""
    holidays = set(
        (
            await db.execute(
                select(Holiday.date).where(
                    Holiday.tenant_id == tenant_id,
                    Holiday.is_deleted == False,  # noqa: E712
                    Holiday.is_optional == False,  # noqa: E712
                    Holiday.date >= period_start,
                    Holiday.date <= period_end,
                    (Holiday.branch_id.is_(None)) | (Holiday.branch_id == employee.branch_id),
                )
            )
        ).scalars().all()
    )

    inputs = DayInputs(
        period_start=period_start, period_end=period_end, method=method, fixed_divisor=fixed_divisor,
        work_weekdays=work_weekdays_from(org_settings), holidays=holidays,
        joined=employee.date_of_joining, left=employee.date_of_leaving,
    )

    records = (
        await db.execute(
            select(AttendanceRecord.date, AttendanceRecord.status).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employee_id == employee.id,
                AttendanceRecord.is_deleted == False,  # noqa: E712
                AttendanceRecord.date >= period_start,
                AttendanceRecord.date <= period_end,
            )
        )
    ).all()
    for day, status in records:
        if status == AttendanceStatus.ABSENT:
            inputs.absent[day] = ONE
        elif status == AttendanceStatus.HALF_DAY:
            inputs.absent[day] = Decimal("0.5")

    leaves = (
        await db.execute(
            select(LeaveRequest, LeaveType.is_paid)
            .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
            .where(
                LeaveRequest.tenant_id == tenant_id,
                LeaveRequest.employee_id == employee.id,
                LeaveRequest.status == LeaveRequestStatus.APPROVED,
                LeaveRequest.is_deleted == False,  # noqa: E712
                LeaveRequest.start_date <= period_end,
                LeaveRequest.end_date >= period_start,
            )
        )
    ).all()
    for request, is_paid in leaves:
        span = (request.end_date - request.start_date).days + 1
        # A half day or hourly request is spread over its dates; a full-day
        # request weighs 1 per date.
        weight = min(ONE, Decimal(request.total_days) / Decimal(span)) if span > 0 else ONE
        target = inputs.paid_leave if is_paid else inputs.unpaid_leave
        for d in _days(max(request.start_date, period_start), min(request.end_date, period_end)):
            target[d] = min(ONE, target.get(d, ZERO) + weight)
    return inputs
