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
    # Every entry here is imported when the worker boots, and a missing
    # module aborts the boot entirely (ModuleNotFoundError) — which is what
    # "app.workers.tasks.payroll" and "app.workers.tasks.reports" used to do,
    # silently disabling every task below. Only list modules that exist;
    # tests/test_celery_worker_boot.py enforces this.
    include=[
        "app.workers.tasks.email",
        "app.workers.tasks.notifications",
        "app.workers.tasks.device_health",
        "app.workers.tasks.attendance",
        "app.workers.tasks.auth_sessions",
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
    # The single auto-close policy for forgotten check-outs (audit M-7) —
    # see app/services/attendance_sync.sweep_stale_attendance. It replaced
    # the midnight auto-close. The times it records are fixed cutoff
    # instants, so the interval only affects how soon a stale punch is seen.
    "purge-old-screenshots": {
        "task": "device_health.purge_old_screenshots",
        "schedule": 86400,
    },
    "sweep-stale-attendance": {
        "task": "attendance.sweep_stale_attendance",
        "schedule": 900,
    },
    # Drops expired refresh-token rows (audit H-6) so auth_refresh_tokens
    # doesn't grow without bound.
    "purge-expired-refresh-tokens": {
        "task": "auth.purge_expired_refresh_tokens",
        "schedule": 86400,
    },
}