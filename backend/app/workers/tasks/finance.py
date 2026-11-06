"""Daily finance housekeeping: generate due recurring invoices, then send opted-in payment reminders."""
import asyncio
import logging

from app.core.database import worker_db_session
from app.services import finance_purchasing as purchasing
from app.services import finance_recurring as recurring
from app.workers.celery_app import celery_app

logger = logging.getLogger("ewmp.finance.daily")


async def _run() -> dict:
    async with worker_db_session() as db:
        gen = await recurring.run_due(db)
        await db.commit()
    async with worker_db_session() as db:
        bills = await purchasing.run_due(db)
        await db.commit()
    async with worker_db_session() as db:
        rem = await recurring.sweep_reminders(db)
        await db.commit()
    return {"recurring": gen, "recurring_bills": bills, "reminders": rem}


@celery_app.task(name="finance.daily_sweep")
def finance_daily_sweep_task() -> dict:
    """Daily (celery_app.py beat_schedule)."""
    out = asyncio.run(_run())
    logger.info("Finance daily sweep: %s", out)
    return out
