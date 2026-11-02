"""
Monthly attendance report: one row per employee for a calendar month.

Built on the same per-day rules as the Daily Attendance sheet
(app.services.attendance_daily.build_daily_sheet), so the report can never
disagree with what HR sees day by day: shifts, holidays, approved leave and
real punches are all already resolved there. This module only adds the days up.

Days that are not decided yet (today before the shift ends, or any future day)
are counted as `pending`, never as absent, and days after today are not
walked at all.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezones import local_today, org_zone
from app.services.attendance_daily import DayStatus, SheetRow, WORKED, build_daily_sheet


@dataclass
class EmployeeMonth:
    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    department_name: str | None
    present: int = 0          # present + work from home
    late: int = 0
    half_day: int = 0
    missed_punch: int = 0
    absent: int = 0
    on_leave: int = 0
    holiday: int = 0
    weekly_off: int = 0
    pending: int = 0          # not decided yet (today / future)
    worked_minutes: int = 0
    late_minutes: int = 0
    overtime_minutes: int = 0

    @property
    def days_worked(self) -> int:
        return self.present + self.late + self.half_day + self.missed_punch

    @property
    def working_days(self) -> int:
        """Days the employee was expected to work and that are already decided."""
        return self.days_worked + self.absent + self.on_leave

    @property
    def attendance_pct(self) -> float | None:
        if self.working_days == 0:
            return None
        return round(100.0 * self.days_worked / self.working_days, 1)

    def add(self, row: SheetRow) -> None:
        s = row.status
        if s in (DayStatus.PRESENT, DayStatus.WORK_FROM_HOME):
            self.present += 1
        elif s is DayStatus.LATE:
            self.late += 1
        elif s is DayStatus.HALF_DAY:
            self.half_day += 1
        elif s is DayStatus.MISSED_PUNCH:
            self.missed_punch += 1
        elif s is DayStatus.ABSENT:
            self.absent += 1
        elif s is DayStatus.ON_LEAVE:
            self.on_leave += 1
        elif s is DayStatus.HOLIDAY:
            self.holiday += 1
        elif s is DayStatus.WEEKLY_OFF:
            self.weekly_off += 1
        else:  # NOT_CHECKED_IN / SCHEDULED
            self.pending += 1
        if s in WORKED:
            self.worked_minutes += row.total_minutes or 0
            self.late_minutes += row.late_minutes or 0
            self.overtime_minutes += row.overtime_minutes or 0

    def as_dict(self) -> dict:
        return {
            "employee_id": str(self.employee_id),
            "employee_code": self.employee_code,
            "employee_name": self.employee_name,
            "department_name": self.department_name,
            "present": self.present,
            "late": self.late,
            "half_day": self.half_day,
            "missed_punch": self.missed_punch,
            "absent": self.absent,
            "on_leave": self.on_leave,
            "holiday": self.holiday,
            "weekly_off": self.weekly_off,
            "pending": self.pending,
            "days_worked": self.days_worked,
            "working_days": self.working_days,
            "attendance_pct": self.attendance_pct,
            "worked_hours": round(self.worked_minutes / 60, 1),
            "late_minutes": self.late_minutes,
            "overtime_hours": round(self.overtime_minutes / 60, 1),
        }


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


async def build_monthly_report(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    year: int,
    month: int,
    *,
    employee_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    search: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Returns {"period": {...}, "items": [per-employee dicts], "totals": {...}}."""
    now = now or datetime.now(UTC)
    first, last = month_bounds(year, month)
    today = local_today(await org_zone(db, tenant_id), now)
    end = min(last, today)

    people: dict[uuid.UUID, EmployeeMonth] = {}
    day = first
    while day <= end:
        _, rows = await build_daily_sheet(
            db, tenant_id, day,
            employee_id=employee_id, department_id=department_id,
            branch_id=branch_id, search=search, now=now,
        )
        for row in rows:
            person = people.get(row.employee_id)
            if person is None:
                person = people[row.employee_id] = EmployeeMonth(
                    employee_id=row.employee_id,
                    employee_code=row.employee_code,
                    employee_name=row.employee_name,
                    department_name=row.department_name,
                )
            person.add(row)
        day += timedelta(days=1)

    items = sorted(people.values(), key=lambda p: (p.employee_name or "").lower())
    totals = {
        key: sum(getattr(p, key) for p in items)
        for key in ("present", "late", "half_day", "missed_punch", "absent",
                    "on_leave", "holiday", "weekly_off", "pending")
    }
    worked = sum(p.days_worked for p in items)
    expected = sum(p.working_days for p in items)
    totals["employees"] = len(items)
    totals["attendance_pct"] = round(100.0 * worked / expected, 1) if expected else None

    return {
        "period": {
            "year": year,
            "month": month,
            "from": str(first),
            "to": str(last),
            "counted_through": str(end) if end >= first else None,
        },
        "items": [p.as_dict() for p in items],
        "totals": totals,
    }
