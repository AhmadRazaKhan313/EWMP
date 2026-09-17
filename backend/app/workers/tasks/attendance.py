"""
Midnight auto-checkout / stale-break closeout.

An employee who starts a break and forgets to end it (or forgets to
check out at all) would otherwise leave their WorkSession open
indefinitely — the desktop timer keeps climbing forever, and the next
day's hours get silently folded into the same never-ended session.

This periodic task (see celery_app.py's beat_schedule) closes that gap:
any WorkSession still ACTIVE/ON_BREAK whose start date, in the
EMPLOYEE'S ORGANIZATION'S LOCAL TIMEZONE, is no longer "today" gets
force-ended at that day's local midnight — not at whatever moment this
sweep happens to run. So an employee who started work at 9am and forgot
to check out gets exactly that day's worked hours counted, not
9am-until-whenever-the-sweep-caught-it.

Runs every 15 minutes, not exactly at midnight — a 15-minute lag before
a stale session is caught is an acceptable trade-off against needing a
separate per-timezone cron entry for every org's midnight (orgs can be in
any IANA timezone).
"""

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.workers.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.organization import Organization
from app.models.work_session import WorkSession, WorkSessionStatus
from app.models.employee import Employee

logger = logging.getLogger("ewmp.attendance")


def _org_timezone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        # An invalid/unrecognized tz string on the org row must never
        # crash the whole sweep for every other tenant — fall back to
        # UTC for just this one org's sessions rather than skip them
        # (leaving them open forever) or aborting the task entirely.
        logger.warning("Unknown organization timezone %r — defaulting to UTC for this sweep", tz_name)
        return ZoneInfo("UTC")


async def _close_stale_work_sessions() -> int:
    now_utc = datetime.now(UTC)
    closed = 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(WorkSession, Organization.timezone)
                .join(Organization, Organization.id == WorkSession.tenant_id)
                .where(WorkSession.status.in_([WorkSessionStatus.ACTIVE, WorkSessionStatus.ON_BREAK]))
                # Eager-load breaks — async SQLAlchemy has no implicit
                # lazy-load, and session.breaks gets read below after
                # this query's result set is done, when a lazy fetch
                # would raise MissingGreenlet.
                .options(selectinload(WorkSession.breaks))
            )
        ).all()

        for session, tz_name in rows:
            tz = _org_timezone(tz_name)
            local_now = now_utc.astimezone(tz)
            local_start = session.started_at.astimezone(tz)

            if local_start.date() >= local_now.date():
                continue  # still today (locally) — leave it running

            # The boundary is local midnight AT THE END of the day the
            # session started, converted back to UTC for storage — NOT
            # "now" (which could be hours or days after that midnight,
            # e.g. a laptop left off over a weekend).
            day_end_local = datetime.combine(local_start.date(), time(23, 59, 59), tzinfo=tz)
            cutoff = day_end_local.astimezone(UTC)

            open_break = next((b for b in session.breaks if b.ended_at is None), None)
            if open_break is not None:
                open_break.ended_at = cutoff

            completed_break_seconds = sum(
                int((b.ended_at - b.started_at).total_seconds()) for b in session.breaks if b.ended_at is not None
            )
            worked_seconds = (cutoff - session.started_at).total_seconds() - completed_break_seconds

            session.status = WorkSessionStatus.ENDED
            session.ended_at = cutoff
            session.total_minutes = max(0, int(worked_seconds // 60))
            closed += 1

            await _notify_auto_checkout(db, session)

        await db.commit()

    return closed


async def _notify_auto_checkout(db: AsyncSession, session: WorkSession) -> None:
    """Best-effort — see leave.py's identical _notify_leave_outcome
    pattern: a notification failure must never break the closeout
    itself."""
    try:
        from app.api.v1.hrms.notifications import notify_user

        employee = (
            await db.execute(select(Employee).where(Employee.id == session.employee_id))
        ).scalar_one_or_none()
        if employee is None or employee.user_id is None:
            return
        hours = (session.total_minutes or 0) // 60
        minutes = (session.total_minutes or 0) % 60
        await notify_user(
            db,
            tenant_id=session.tenant_id,
            user_id=employee.user_id,
            title="Automatically checked out",
            body=(
                f"You were still checked in past midnight, so we closed out your session for that day. "
                f"Working time counted: {hours}h {minutes}m."
            ),
            type="auto_checkout",
            metadata={"work_session_id": str(session.id)},
        )
    except Exception:  # noqa: BLE001
        pass


@celery_app.task(name="attendance.close_stale_work_sessions")
def close_stale_work_sessions() -> int:
    count = asyncio.run(_close_stale_work_sessions())
    if count:
        logger.info("Auto-closed %d stale work session(s) at their local midnight", count)
    return count
