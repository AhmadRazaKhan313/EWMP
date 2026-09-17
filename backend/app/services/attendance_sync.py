"""
Attendance ↔ Work-Session sync.

Two systems track "is this employee currently working right now", built for
different purposes:
  - AttendanceRecord (app.models.attendance)   — once-per-day audit trail:
    check-in/out time, late/overtime vs shift, geo/QR verification. Used by
    the web dashboard's Attendance page and HR reports.
  - WorkSession (app.models.work_session)      — live timer state the
    desktop app's Check-In widget starts/stops/pauses. Can be started and
    paused multiple times a day (breaks), unlike AttendanceRecord.

Historically these were wired independently: the web Check-In button only
touched AttendanceRecord, the desktop app only touched WorkSession. That
meant checking in from one side was invisible to the other — the exact
bug this module fixes. Per the design already documented (but never
implemented) in app/models/work_session.py: a work-session start should
imply an attendance check-in, and vice versa.

Call ensure_work_session_started/ended from the /attendance endpoints, and
ensure_attendance_checked_in/out from the /work-sessions endpoints, so
BOTH sides always end up in a consistent state no matter which app the
employee used.
"""
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceRecord, AttendanceSource, AttendanceStatus, Shift
from app.models.employee import Employee
from app.models.work_session import BreakRecord, WorkSession, WorkSessionStatus


def _minutes_late(shift: Shift, check_in_at: datetime) -> int:
    local_time = check_in_at.time()
    scheduled_minutes = shift.start_time.hour * 60 + shift.start_time.minute
    actual_minutes = local_time.hour * 60 + local_time.minute
    late = actual_minutes - scheduled_minutes - shift.late_grace_minutes
    return max(0, late)


def _scheduled_minutes(shift: Shift) -> int:
    start = shift.start_time.hour * 60 + shift.start_time.minute
    end = shift.end_time.hour * 60 + shift.end_time.minute
    if shift.is_overnight or end <= start:
        end += 24 * 60
    return max(0, end - start - shift.break_duration_minutes)


async def ensure_work_session_started(
    db: AsyncSession, tenant_id: UUID, employee_id: UUID, *, started_at: datetime | None = None
) -> WorkSession:
    """Idempotent: called when the employee checks in via /attendance (web),
    so the desktop app's timer picks up the same session on its next poll."""
    existing = (
        await db.execute(
            select(WorkSession).where(
                WorkSession.tenant_id == tenant_id,
                WorkSession.employee_id == employee_id,
                WorkSession.status != WorkSessionStatus.ENDED,
                WorkSession.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    session = WorkSession(
        tenant_id=tenant_id,
        employee_id=employee_id,
        started_at=started_at or datetime.now(UTC),
        status=WorkSessionStatus.ACTIVE,
    )
    db.add(session)
    await db.flush()
    return session


async def ensure_work_session_ended(
    db: AsyncSession, tenant_id: UUID, employee_id: UUID, *, ended_at: datetime | None = None
) -> WorkSession | None:
    """Idempotent no-op if there's no open session — a desktop timer that
    was never started has nothing to close when the web check-out fires."""
    session = (
        await db.execute(
            select(WorkSession).where(
                WorkSession.tenant_id == tenant_id,
                WorkSession.employee_id == employee_id,
                WorkSession.status != WorkSessionStatus.ENDED,
                WorkSession.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if session is None:
        return None

    now = ended_at or datetime.now(UTC)
    open_break = (
        await db.execute(
            select(BreakRecord).where(
                BreakRecord.work_session_id == session.id,
                BreakRecord.ended_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if open_break is not None:
        open_break.ended_at = now

    breaks = (
        await db.execute(select(BreakRecord).where(BreakRecord.work_session_id == session.id))
    ).scalars().all()
    break_minutes = sum(
        int(((b.ended_at or now) - b.started_at).total_seconds() // 60) for b in breaks
    )
    total_minutes = int((now - session.started_at).total_seconds() // 60) - break_minutes

    session.ended_at = now
    session.status = WorkSessionStatus.ENDED
    session.total_minutes = max(0, total_minutes)
    await db.flush()
    return session


async def ensure_attendance_checked_in(
    db: AsyncSession,
    tenant_id: UUID,
    employee: Employee,
    *,
    source: AttendanceSource,
    checked_in_at: datetime | None = None,
) -> AttendanceRecord:
    """
    Called when the employee starts their timer via the desktop app, so
    the web Attendance table/report shows the same check-in without the
    employee having to also click Check In on the website.

    BUG THIS FIXES: this used to write straight onto
    `AttendanceRecord.check_in` and returned early whenever that column
    was already set for today — which is every time after the day's
    FIRST desktop check-in. A second work session started later the same
    day (after lunch, after stepping out) silently vanished: the function
    saw `existing.check_in is not None`, returned the untouched record,
    and nothing about the new session was ever recorded. The employee's
    desktop timer looked fine because WorkSession itself was tracking it
    correctly — only the attendance side, and everything downstream of
    it (the dashboard's daily summary, payroll's total_minutes), stayed
    frozen at the first punch of the day.

    Now delegates to the same open_punch() the web /attendance/check-in
    endpoint uses, so a desktop check-in and a web check-in are the same
    operation regardless of which app made it, and both correctly add a
    new punch rather than silently no-op-ing on every one after the
    first.
    """
    from app.services.attendance_punches import get_open_punch, open_punch

    now = checked_in_at or datetime.now(UTC)

    # Idempotent: if a punch is already open (started from the OTHER
    # app a moment ago), do nothing rather than raising — this is a sync
    # call, and two apps racing to report the same check-in is normal,
    # not an error.
    already_open = await get_open_punch(db, tenant_id, employee.id)
    if already_open is not None:
        return (
            await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.id == already_open.attendance_record_id
                )
            )
        ).scalar_one()

    _, record = await open_punch(
        db, tenant_id=tenant_id, employee_id=employee.id, at=now,
        source=source, shift_id=employee.default_shift_id,
    )
    return record


async def ensure_attendance_checked_out(
    db: AsyncSession,
    tenant_id: UUID,
    employee_id: UUID,
    *,
    checked_out_at: datetime | None = None,
    break_minutes: int = 0,
) -> AttendanceRecord | None:
    """
    Mirror of ensure_attendance_checked_in for the end of a desktop
    session — same bug, same fix: this used to look for "today's" record
    with check_out still null and close it directly, which is exactly
    the single-open-punch-per-day assumption that silently dropped every
    punch after the first. Delegates to close_punch() so a desktop
    check-out and a web check-out are the same operation.

    `break_minutes` lets the caller (work_sessions.py's end_session,
    which already computed break time for its own total_minutes) pass
    that through so the attendance punch's duration excludes it too —
    without this, the desktop's own total and the synced attendance
    total would disagree by however long the employee's breaks were.
    """
    from app.services.attendance_punches import close_punch, get_open_punch

    open_punch = await get_open_punch(db, tenant_id, employee_id)
    if open_punch is None:
        return None

    now = checked_out_at or datetime.now(UTC)
    _, record = await close_punch(
        db, open_punch, at=now, source=AttendanceSource.DESKTOP_AGENT, break_minutes=break_minutes
    )
    return record
