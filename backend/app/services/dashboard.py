"""
Aggregate counts for the Dashboard page's stat cards.

Before this existed, the Dashboard's six stat cards (Total Employees,
Present Today, On Leave, Open Tickets, Devices Online, Assets Assigned)
were a hardcoded `stats = {...}` object in the frontend with a comment
saying "In production, these come from TanStack Query hooks" — they never
did. This is the one query per number that comment was describing.

Kept as a single aggregate endpoint (one round trip) rather than having the
dashboard fire six separate list-endpoint requests just to read `.total`
off each — cheaper for both the client and the DB.
"""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezones import local_today, org_zone

from app.models.attendance import AttendanceRecord, AttendanceStatus, LeaveRequest, LeaveRequestStatus
from app.models.devices import Asset, AssetStatus, Device, DeviceStatus
from app.models.employee import Employee
from app.models.helpdesk import SupportTicket, TicketStatus


async def get_dashboard_stats(db: AsyncSession, tenant_id: UUID) -> dict:
    # The organisation's "today", not the server's (audit H-1).
    today = local_today(await org_zone(db, tenant_id))

    total_employees = (
        await db.execute(
            select(func.count()).where(
                Employee.tenant_id == tenant_id, Employee.is_deleted == False  # noqa: E712
            )
        )
    ).scalar_one()

    present_today = (
        await db.execute(
            select(func.count()).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.date == today,
                AttendanceRecord.is_deleted == False,  # noqa: E712
                # A day row exists with default status PRESENT even before a
                # check-in; only a real check-in (or HR's explicit entry) counts.
                or_(AttendanceRecord.check_in.isnot(None), AttendanceRecord.is_regularized == True),  # noqa: E712
                AttendanceRecord.status.in_([
                    AttendanceStatus.PRESENT,
                    AttendanceStatus.LATE,
                    AttendanceStatus.HALF_DAY,
                    AttendanceStatus.WORK_FROM_HOME,
                ]),
            )
        )
    ).scalar_one()

    on_leave_today = (
        await db.execute(
            select(func.count()).where(
                LeaveRequest.tenant_id == tenant_id,
                LeaveRequest.status == LeaveRequestStatus.APPROVED,
                LeaveRequest.start_date <= today,
                LeaveRequest.end_date >= today,
            )
        )
    ).scalar_one()

    open_tickets = (
        await db.execute(
            select(func.count()).where(
                SupportTicket.tenant_id == tenant_id,
                SupportTicket.status.in_([
                    TicketStatus.OPEN,
                    TicketStatus.IN_PROGRESS,
                    TicketStatus.PENDING,
                ]),
            )
        )
    ).scalar_one()

    devices_online = (
        await db.execute(
            select(func.count()).where(
                Device.tenant_id == tenant_id,
                Device.status == DeviceStatus.ONLINE,
            )
        )
    ).scalar_one()

    devices_total = (
        await db.execute(
            select(func.count()).where(
                Device.tenant_id == tenant_id,
                Device.status != DeviceStatus.DECOMMISSIONED,
            )
        )
    ).scalar_one()

    assets_assigned = (
        await db.execute(
            select(func.count()).where(
                Asset.tenant_id == tenant_id,
                Asset.status == AssetStatus.ASSIGNED,
            )
        )
    ).scalar_one()

    return {
        "total_employees": total_employees,
        "present_today": present_today,
        "on_leave_today": on_leave_today,
        "open_tickets": open_tickets,
        "devices_online": devices_online,
        "devices_total": devices_total,
        "assets_assigned": assets_assigned,
    }

# --------------------------------------------------------------------------
# D-01  Absent today
# --------------------------------------------------------------------------

async def get_absent_today(db: AsyncSession, tenant_id: UUID, now=None) -> dict:
    """Who is missing from work today.

    Built on the daily attendance sheet so the rules are the Attendance page's
    rules, not a second copy: holiday / approved leave / weekly-off never
    count, and anyone with a real check-in is present even on an off day.

      * absent          - the shift (or day) is over and nobody punched
      * not_checked_in  - a working day that has started, no punch yet
    """
    from app.services.attendance_daily import DayStatus, build_daily_sheet

    day, rows = await build_daily_sheet(db, tenant_id, now=now)
    wanted = {DayStatus.ABSENT, DayStatus.NOT_CHECKED_IN}
    people = [
        {
            "employee_id": str(r.employee_id),
            "employee_code": r.employee_code,
            "employee_name": r.employee_name,
            "department_name": r.department_name,
            "shift_name": r.shift_name,
            "status": r.status.value,
        }
        for r in rows
        if r.status in wanted
    ]
    # Truly absent first, then the "not in yet" ones.
    people.sort(key=lambda p: (p["status"] != "absent", p["employee_name"].lower()))
    absent = sum(1 for p in people if p["status"] == "absent")
    return {
        "date": day.isoformat(),
        "absent": absent,
        "not_checked_in": len(people) - absent,
        "total": len(people),
        "employees": people,
    }


# --------------------------------------------------------------------------
# D-02  Hours per day for one week
# --------------------------------------------------------------------------

DEFAULT_WEEKLY_TARGET_HOURS = 40.0


async def get_weekly_hours(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    employee_id: UUID | None = None,
    week_start=None,
    now=None,
) -> dict:
    """Hours worked on each of the 7 days (Mon..Sun) of one week.

    employee_id given -> that person's hours, target from their shift.
    employee_id None  -> the team: average hours per person who worked that
                         day (so the 24h axis still holds) and a headcount.

    A day total is `AttendanceRecord.total_minutes` (already clamped to 24h by
    the punch service), plus the running interval if today has an open punch.
    Off days are shown as 0 -- never absent -- but a check-in on one counts:
    it's flagged `extra_day` and goes into the weekly total.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.attendance import AttendancePunch, Holiday, Shift
    from app.models.organization import Organization
    from app.services.attendance_punches import HARD_CAP_HOURS
    from app.services.payroll_calendar import WEEKDAYS, work_weekdays_from

    now = now or datetime.now(UTC)
    zone = await org_zone(db, tenant_id)
    today = local_today(zone, now)
    if week_start is None:
        week_start = today - timedelta(days=today.weekday())
    else:  # snap any date to its Monday
        week_start = week_start - timedelta(days=week_start.weekday())
    days = [week_start + timedelta(days=i) for i in range(7)]

    org_settings = (
        await db.execute(select(Organization.settings).where(Organization.id == tenant_id))
    ).scalar_one_or_none()
    work_days = work_weekdays_from(org_settings)
    target = DEFAULT_WEEKLY_TARGET_HOURS
    if employee_id is not None:
        shift = (
            await db.execute(
                select(Shift)
                .join(Employee, Employee.default_shift_id == Shift.id)
                .where(Employee.id == employee_id, Employee.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if shift is not None:
            if shift.work_days:
                work_days = {WEEKDAYS.index(d) for d in shift.work_days if d in WEEKDAYS} or work_days
            if shift.weekly_hours:
                target = float(shift.weekly_hours)

    rec_filters = [
        AttendanceRecord.tenant_id == tenant_id,
        AttendanceRecord.is_deleted == False,  # noqa: E712
        AttendanceRecord.date >= days[0],
        AttendanceRecord.date <= days[-1],
        or_(AttendanceRecord.check_in.isnot(None), AttendanceRecord.is_regularized == True),  # noqa: E712
    ]
    if employee_id is not None:
        rec_filters.append(AttendanceRecord.employee_id == employee_id)
    records = (await db.execute(select(AttendanceRecord).where(*rec_filters))).scalars().all()

    minutes: dict = {d: [] for d in days}  # date -> [minutes per person]
    by_emp_day: dict = {}
    for r in records:
        by_emp_day[(r.employee_id, r.date)] = min(24 * 60, max(0, r.total_minutes or 0))

    # Live minutes of a punch that is still open today.
    if week_start <= today <= days[-1]:
        open_q = select(AttendancePunch).where(
            AttendancePunch.tenant_id == tenant_id,
            AttendancePunch.punch_out.is_(None),
            AttendancePunch.is_forced_checkout == False,  # noqa: E712
        )
        if employee_id is not None:
            open_q = open_q.where(AttendancePunch.employee_id == employee_id)
        for p in (await db.execute(open_q)).scalars().all():
            live = int((now - p.punch_in).total_seconds() // 60)
            if 0 < live <= HARD_CAP_HOURS * 60:
                key = (p.employee_id, today)
                by_emp_day[key] = min(24 * 60, by_emp_day.get(key, 0) + live)

    for (_, d), m in by_emp_day.items():
        if m > 0:
            minutes[d].append(m)

    holiday_dates = set(
        (
            await db.execute(
                select(Holiday.date).where(
                    Holiday.tenant_id == tenant_id,
                    Holiday.is_deleted == False,  # noqa: E712
                    Holiday.is_optional == False,  # noqa: E712
                    Holiday.date >= days[0],
                    Holiday.date <= days[-1],
                )
            )
        ).scalars().all()
    )

    out_days, total = [], 0.0
    for d in days:
        vals = minutes[d]
        if employee_id is not None:
            hours = round(sum(vals) / 60, 2)
        else:
            hours = round((sum(vals) / len(vals)) / 60, 2) if vals else 0.0
        is_work = d.weekday() in work_days
        out_days.append({
            "date": d.isoformat(),
            "weekday": WEEKDAYS[d.weekday()],
            "hours": hours,
            "people": len(vals),
            "is_working_day": is_work,
            "is_holiday": d in holiday_dates,
            "extra_day": (not is_work) and hours > 0,
            "is_today": d == today,
            "is_future": d > today,
        })
        total += hours

    working_count = len(work_days)
    return {
        "week_start": days[0].isoformat(),
        "week_end": days[-1].isoformat(),
        "scope": "employee" if employee_id is not None else "team",
        "days": out_days,
        "total_hours": round(total, 2),
        "target_hours": target,
        "working_days": working_count,
        "hours_per_working_day": round(target / working_count, 2) if working_count else 0,
        "max_axis_hours": 24,
    }
