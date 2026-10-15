"""Housekeeping for tracked refresh tokens (audit H-6)."""
import asyncio
import logging

from app.core.database import worker_db_session
from app.services.auth_sessions import purge_expired
from app.workers.celery_app import celery_app

logger = logging.getLogger("ewmp.auth.sessions")


async def _purge() -> int:
    async with worker_db_session() as db:
        deleted = await purge_expired(db)
        await db.commit()
    return deleted


@celery_app.task(name="auth.purge_expired_refresh_tokens")
def purge_expired_refresh_tokens_task() -> int:
    """Daily (celery_app.py beat_schedule)."""
    deleted = asyncio.run(_purge())
    if deleted:
        logger.info("Purged %d expired refresh tokens", deleted)
    return deleted
