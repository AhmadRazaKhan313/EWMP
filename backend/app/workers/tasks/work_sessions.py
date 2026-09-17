"""
Overnight auto-checkout for work sessions.

If an employee starts the desktop timer and never checks out (forgets,
the app crashes, the machine sleeps through the night, etc.), the naive
elapsed-time math in work_sessions.end_session() / attendance_sync's
ensure_work_session_ended() would keep growing forever — a session
started 9 AM Monday and first noticed Wednesday would credit ~52 hours
of "work" the moment someone finally closes it. This periodic task
closes that gap the same way device_health.mark_stale_devices_offline
closes an analogous "nothing ever says goodbye" gap for devices:
anything still open past its calendar day gets force-closed exactly at
that day's midnight boundary — not at "whenever this sweep happens to
run" — so the worked-minutes total is always the same regardless of how
late the sweep executes.

"Midnight" here means midnight in the EMPLOYEE'S ORGANIZATION's
timezone (Organization.timezone), not UTC — otherwise every non-UTC
tenant's sessions would get truncated at a random mid-shift hour instead
of an actual end-of-day boundary.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.organization import Organization
from app.models.work_session import BreakRecord, WorkSession, WorkSessionStatus
from app.services.attendance_sync import ensure_attendance_checked_out
from app.workers.celery_app import celery_app

logger = logging.getLogger("ewmp.work_sessions")


def _next_local_midnight_utc(started_at: datetime, tz_name: str) -> datetime | None:
    """The first local midnight strictly after `started_at`, as a UTC
    datetime — or None if that midnight hasn't arrived yet (the session
    hasn't crossed a day boundary yet, so there's nothing to close)."""
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    local_start = started_at.astimezone(tz)
    local_midnight = datetime(local_start.year, local_start.month, local_start.day, tzinfo=tz) + timedelta(days=1)
    midnight_utc = local_midnight.astimezone(UTC)
    if midnight_utc >= datetime.now(UTC):
        return None
    return midnight_utc


async def _auto_close_overnight_sessions() -> int:
    closed = 0
    async with AsyncSessionLocal() as db:
        sessions = (
            await db.execute(
                select(WorkSession).where(
                    WorkSession.status != WorkSessionStatus.ENDED,
                    WorkSession.is_deleted == False,  # noqa: E712
                )
            )
        ).scalars().all()

        # Cache each tenant's timezone rather than re-querying Organization
        # once per session — there just aren't enough concurrently-open
        # sessions across an install for the repeat lookups to matter, but
        # this avoids being silly about it when several employees in the
        # same org all forgot to check out.
        tz_cache: dict[UUID, str] = {}

        for session in sessions:
            if session.tenant_id not in tz_cache:
                org = (
                    await db.execute(select(Organization).where(Organization.id == session.tenant_id))
                ).scalar_one_or_none()
                tz_cache[session.tenant_id] = org.timezone if org else "UTC"
            tz_name = tz_cache[session.tenant_id]

            cutoff = _next_local_midnight_utc(session.started_at, tz_name)
            if cutoff is None:
                continue  # still within the same local calendar day — leave it running

            open_break = (
                await db.execute(
                    select(BreakRecord).where(
                        BreakRecord.work_session_id == session.id,
                        BreakRecord.ended_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if open_break is not None:
                # max() guards against clock skew; a break can't legitimately
                # start after the midnight it's being closed at.
                open_break.ended_at = max(open_break.started_at, cutoff)

            breaks = (
                await db.execute(select(BreakRecord).where(BreakRecord.work_session_id == session.id))
            ).scalars().all()
            break_minutes = sum(
                int(((b.ended_at or cutoff) - b.started_at).total_seconds() // 60) for b in breaks
            )
            total_minutes = int((cutoff - session.started_at).total_seconds() // 60) - break_minutes

            session.ended_at = cutoff
            session.status = WorkSessionStatus.ENDED
            session.total_minutes = max(0, total_minutes)

            # Same web/desktop sync every other end-of-session path uses —
            # an overnight auto-checkout should close today's Attendance
            # row too, not just the WorkSession.
            await ensure_attendance_checked_out(db, session.tenant_id, session.employee_id, checked_out_at=cutoff)
            closed += 1

        await db.commit()
    return closed


@celery_app.task(name="work_sessions.auto_close_overnight_sessions")
def auto_close_overnight_sessions() -> int:
    """Runs every few minutes (see celery_app.py's beat_schedule) — force-
    ends any work session still open past its own local midnight, so an
    employee who forgets to check out never accrues hours into the next
    calendar day. Safe to run frequently: sessions still within today are
    skipped every time until they actually cross midnight, and the total
    it computes only ever depends on `started_at`/break timestamps and
    the fixed midnight cutoff — never on when this task happens to run."""
    count = asyncio.run(_auto_close_overnight_sessions())
    if count:
        logger.info("Auto-closed %d overnight work session(s)", count)
    return count
