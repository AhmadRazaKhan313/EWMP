"""Notification and workflow event Celery tasks."""

from app.workers.celery_app import celery_app
import logging

logger = logging.getLogger("ewmp.notifications")


@celery_app.task(name="notifications.trigger_workflow_event", bind=True, max_retries=3)
def trigger_workflow_event(self, tenant_id: str, event_type: str, payload: dict) -> None:
    """Fire a workflow trigger event. The workflow engine picks it up."""
    logger.info("Workflow event: %s tenant=%s", event_type, tenant_id)
    # TODO: query active workflows with matching trigger_type and enqueue runs
