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
    """Idempotent: called when the employee starts their timer via the
    desktop app, so the web Attendance table/report shows the same
    check-in without the employee having to also click Check In on web."""
    now = checked_in_at or datetime.now(UTC)
    today = now.date()

    existing = (
        await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.employee_id == employee.id,
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.date == today,
                AttendanceRecord.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.check_in is not None:
        return existing

    late_minutes = 0
    shift_id = employee.default_shift_id
    if shift_id:
        shift = (await db.execute(select(Shift).where(Shift.id == shift_id))).scalar_one_or_none()
        if shift:
            late_minutes = _minutes_late(shift, now)
    attendance_status = AttendanceStatus.LATE if late_minutes > 0 else AttendanceStatus.PRESENT

    if existing is not None:
        existing.check_in = now
        existing.check_in_source = source
        existing.late_minutes = late_minutes
        existing.status = attendance_status
        existing.shift_id = shift_id
        return existing

    record = AttendanceRecord(
        tenant_id=tenant_id,
        employee_id=employee.id,
        date=today,
        check_in=now,
        check_in_source=source,
        late_minutes=late_minutes,
        status=attendance_status,
        shift_id=shift_id,
    )
    db.add(record)
    await db.flush()
    return record


async def ensure_attendance_checked_out(
    db: AsyncSession, tenant_id: UUID, employee_id: UUID, *, checked_out_at: datetime | None = None
) -> AttendanceRecord | None:
    """Idempotent no-op if there's no open check-in — a web check-out that
    fires with nothing open (e.g. already closed) has nothing to do."""
    record = (
        await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.check_in.isnot(None),
                AttendanceRecord.check_out.is_(None),
                AttendanceRecord.is_deleted == False,  # noqa: E712
            )
            .order_by(AttendanceRecord.check_in.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if record is None:
        return None

    now = checked_out_at or datetime.now(UTC)
    record.check_out = now
    total_minutes = int((now - record.check_in).total_seconds() // 60)
    record.total_minutes = total_minutes

    overtime_minutes = 0
    if record.shift_id:
        shift = (await db.execute(select(Shift).where(Shift.id == record.shift_id))).scalar_one_or_none()
        if shift:
            scheduled = _scheduled_minutes(shift)
            overtime_minutes = max(0, total_minutes - scheduled)
    record.overtime_minutes = overtime_minutes

    await db.flush()
    return record
