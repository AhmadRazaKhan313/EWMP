"""
Scheduled stale-attendance sweep — the ONE auto-close policy (audit M-7).

Replaces work_sessions.auto_close_overnight_sessions, which closed timers
AND attendance at local midnight and credited the hours up to it (cutting
night shifts at 00:00, paying hours nobody worked). The policy itself lives
in app.services.attendance_sync.sweep_stale_attendance; this module only
schedules it. `python manage.py attendance-cutoff` runs the same function.
"""
import asyncio
import logging

from app.core.database import worker_db_session
from app.services.attendance_sync import sweep_stale_attendance
from app.workers.celery_app import celery_app

logger = logging.getLogger("ewmp.attendance")


async def _sweep() -> dict:
    async with worker_db_session() as db:
        result = await sweep_stale_attendance(db)
        await db.commit()
    return {
        "punches_closed": result.punches_closed,
        "timers_stopped": result.timers_stopped,
        "orphan_timers_stopped": result.orphan_timers_stopped,
    }


@celery_app.task(name="attendance.sweep_stale_attendance")
def sweep_stale_attendance_task() -> dict:
    """Runs every 15 minutes (celery_app.py beat_schedule). Frequency only
    affects how soon a stale punch is noticed — the times it records are
    the fixed cutoff instants, never "when the sweep ran"."""
    counts = asyncio.run(_sweep())
    if any(counts.values()):
        logger.info("Stale-attendance sweep: %s", counts)
    return counts
