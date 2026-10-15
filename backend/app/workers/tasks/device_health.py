"""
Device online/offline detection.

POST /devices/self-enroll and POST /devices/heartbeat are the only two
places that ever set `Device.status = ONLINE` — nothing ever runs the
other direction. If the desktop app is closed, crashes, or the machine
loses power/network, its last heartbeat simply stops arriving; there is
no "goodbye" packet to flip the row back to OFFLINE. Without this task,
every device that ever logged in once would show ONLINE in the admin
dashboard forever, regardless of whether it's actually reachable.

This periodic task (see celery_app.py's beat_schedule) is what closes
that gap: anything that hasn't heartbeated in
`settings.DEVICE_OFFLINE_AFTER_SECONDS` gets flipped to OFFLINE.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update

from app.workers.celery_app import celery_app
from app.core.config import settings
from app.core.database import worker_db_session
from app.models.devices import Device, DeviceScreenshot, DeviceStatus

logger = logging.getLogger("ewmp.device_health")


async def _mark_stale_devices_offline() -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.DEVICE_OFFLINE_AFTER_SECONDS)

    async with worker_db_session() as db:
        result = await db.execute(
            update(Device)
            .where(
                Device.is_deleted == False,  # noqa: E712
                Device.status.notin_([DeviceStatus.OFFLINE, DeviceStatus.DECOMMISSIONED]),
                (Device.last_heartbeat_at.is_(None)) | (Device.last_heartbeat_at < cutoff),
            )
            .values(status=DeviceStatus.OFFLINE)
        )
        await db.commit()
        return result.rowcount or 0


@celery_app.task(name="device_health.mark_stale_devices_offline")
def mark_stale_devices_offline() -> int:
    """Runs on a schedule (see celery_app.py beat_schedule) — flips any
    device that's gone quiet for too long from ONLINE/IDLE/LOCKED/etc.
    to OFFLINE, across every tenant."""
    count = asyncio.run(_mark_stale_devices_offline())
    if count:
        logger.info("Marked %d stale device(s) offline", count)
    return count


async def _purge_old_screenshots(batch_size: int = 500) -> int:
    """Delete screenshots older than the retention window — files first, then
    rows. Works in batches so a large backlog never holds one huge transaction."""
    from app.core.storage import get_storage

    cutoff = datetime.now(UTC) - timedelta(days=settings.DEVICE_SCREENSHOT_RETENTION_DAYS)
    storage = get_storage()
    total = 0
    while True:
        async with worker_db_session() as db:
            rows = (
                await db.execute(
                    select(DeviceScreenshot.id, DeviceScreenshot.storage_key)
                    .where(DeviceScreenshot.captured_at < cutoff)
                    .limit(batch_size)
                )
            ).all()
            if not rows:
                return total
            for _id, key in rows:
                try:
                    await storage.delete(key)
                except Exception:  # file already gone / storage hiccup — the row still goes
                    logger.warning("Could not delete screenshot file %s", key)
            await db.execute(delete(DeviceScreenshot).where(DeviceScreenshot.id.in_([r[0] for r in rows])))
            await db.commit()
            total += len(rows)


@celery_app.task(name="device_health.purge_old_screenshots")
def purge_old_screenshots() -> int:
    """Daily: drop screenshots past DEVICE_SCREENSHOT_RETENTION_DAYS."""
    count = asyncio.run(_purge_old_screenshots())
    if count:
        logger.info("Purged %d old screenshot(s)", count)
    return count
