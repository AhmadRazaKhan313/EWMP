"""
Break-time lock resolver (K-01).

effective_break()   which window applies to an employee on a date, and why.
break_state()       what the employee's desktop should do right now.

Resolution order (first hit wins):
  1. employee override on that date      (start_time NULL  => no break)
  2. department override on that date
  3. employee policy
  4. department policy
  5. shift policy (employee.default_shift_id)
  6. organization default
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezones import local_today, org_zone
from app.models.break_policy import (
    BreakOverride, BreakPolicy, BreakScope, BreakUnlockRequest, UnlockStatus,
)
from app.models.employee import Employee

WARN_MINUTES = 5


@dataclass
class Window:
    start_time: time
    duration_minutes: int
    source: str  # override_employee | override_department | employee | department | shift | organization
    source_id: uuid.UUID | None = None


def _applies(p: BreakPolicy, d: date) -> bool:
    if not p.is_active:
        return False
    if p.valid_from and d < p.valid_from:
        return False
    if p.valid_to and d > p.valid_to:
        return False
    return not p.days or d.weekday() in p.days


async def _policy(db, tenant_id, scope: BreakScope, scope_id, d: date) -> BreakPolicy | None:
    q = select(BreakPolicy).where(
        BreakPolicy.tenant_id == tenant_id, BreakPolicy.is_deleted == False,  # noqa: E712
        BreakPolicy.scope == scope, BreakPolicy.is_active == True,  # noqa: E712
    )
    q = q.where(BreakPolicy.scope_id == scope_id) if scope_id else q.where(BreakPolicy.scope_id.is_(None))
    rows = (await db.execute(q.order_by(BreakPolicy.created_at.desc()))).scalars().all()
    return next((p for p in rows if _applies(p, d)), None)


async def effective_break(db: AsyncSession, tenant_id: uuid.UUID, employee: Employee, d: date) -> Window | None:
    base = (BreakOverride.tenant_id == tenant_id, BreakOverride.is_deleted == False, BreakOverride.on_date == d)  # noqa: E712
    ov = (await db.execute(select(BreakOverride).where(*base, BreakOverride.employee_id == employee.id)
                           .order_by(BreakOverride.created_at.desc()))).scalars().first()
    if ov is None and employee.department_id:
        ov = (await db.execute(select(BreakOverride).where(*base, BreakOverride.department_id == employee.department_id,
                                                           BreakOverride.employee_id.is_(None))
                               .order_by(BreakOverride.created_at.desc()))).scalars().first()
        src = "override_department"
    else:
        src = "override_employee"
    if ov is not None:
        if ov.start_time is None:
            return None
        return Window(ov.start_time, ov.duration_minutes or 60, src, ov.id)

    for scope, sid in ((BreakScope.EMPLOYEE, employee.id), (BreakScope.DEPARTMENT, employee.department_id),
                       (BreakScope.SHIFT, employee.default_shift_id), (BreakScope.ORGANIZATION, None)):
        if scope != BreakScope.ORGANIZATION and sid is None:
            continue
        p = await _policy(db, tenant_id, scope, sid, d)
        if p:
            return Window(p.start_time, p.duration_minutes, scope.value, p.id)
    return None


def _instants(d: date, w: Window, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(d, w.start_time, tzinfo=zone)
    return start.astimezone(UTC), (start + timedelta(minutes=w.duration_minutes)).astimezone(UTC)


async def break_state(db: AsyncSession, tenant_id: uuid.UUID, employee: Employee,
                      now: datetime | None = None) -> dict:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    zone = await org_zone(db, tenant_id)
    today = local_today(zone, now)
    out: dict = {"server_time": now.isoformat(), "timezone": str(zone), "date": today.isoformat(),
                 "has_break": False, "phase": "none", "locked": False, "start": None, "end": None,
                 "duration_minutes": None, "source": None, "request": None, "seconds_to_start": None,
                 "seconds_to_end": None}
    w = await effective_break(db, tenant_id, employee, today)
    if w is None:
        return out
    start, end = _instants(today, w, zone)
    req = (await db.execute(
        select(BreakUnlockRequest).where(
            BreakUnlockRequest.tenant_id == tenant_id, BreakUnlockRequest.is_deleted == False,  # noqa: E712
            BreakUnlockRequest.employee_id == employee.id, BreakUnlockRequest.break_date == today,
        ).order_by(BreakUnlockRequest.created_at.desc())
    )).scalars().first()

    if now < start - timedelta(minutes=WARN_MINUTES):
        phase = "upcoming"
    elif now < start:
        phase = "warning"
    elif now < end:
        phase = "active"
    else:
        phase = "over"
    unlocked = bool(req and req.status == UnlockStatus.APPROVED and req.unlock_until and now < req.unlock_until)
    out.update(
        has_break=True, phase=phase, locked=(phase == "active" and not unlocked),
        unlocked_by_admin=unlocked,
        start=start.isoformat(), end=end.isoformat(), duration_minutes=w.duration_minutes, source=w.source,
        seconds_to_start=max(0, int((start - now).total_seconds())),
        seconds_to_end=max(0, int((end - now).total_seconds())),
        request=None if req is None else {"id": str(req.id), "status": req.status.value, "reason": req.reason},
    )
    return out
