"""
Celery application instance.

Import this module to get the configured Celery app.
All tasks are auto-discovered from app.workers.tasks.*
"""

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "ewmp",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.email",
        "app.workers.tasks.payroll",
        "app.workers.tasks.reports",
        "app.workers.tasks.notifications",
        "app.workers.tasks.device_health",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,                    # Acknowledge after completion, not on receipt
    worker_prefetch_multiplier=1,           # Prevent task hoarding by workers
    task_soft_time_limit=300,               # 5 min soft limit
    task_time_limit=600,                    # 10 min hard limit
    result_expires=86400,                   # Results kept for 24 hours
)

# device_health.mark_stale_devices_offline is a no-op unless something
# actually schedules it to run — being importable/registered in `include`
# above is not the same as being scheduled. Runs at 3x the heartbeat
# interval: frequent enough that a device going quiet is noticed
# reasonably fast, without hammering the DB with an UPDATE sweep every
# few seconds.
celery_app.conf.beat_schedule = {
    "mark-stale-devices-offline": {
        "task": "device_health.mark_stale_devices_offline",
        "schedule": settings.DEVICE_HEARTBEAT_INTERVAL_SECONDS * 3,
    },
}