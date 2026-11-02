"""Daily contract-expiry reminders (E-07)."""
import asyncio
import logging

from app.core.database import worker_db_session
from app.services.employee_contracts import notify_expiring_contracts
from app.workers.celery_app import celery_app

logger = logging.getLogger("ewmp.contracts")


async def _run() -> dict:
    async with worker_db_session() as db:
        result = await notify_expiring_contracts(db)
        await db.commit()
    return result


@celery_app.task(name="contracts.notify_expiring_contracts")
def notify_expiring_contracts_task() -> dict:
    result = asyncio.run(_run())
    if result["contracts"]:
        logger.info("Contract reminders: %s", result)
    return result
