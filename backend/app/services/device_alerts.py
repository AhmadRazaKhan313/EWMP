"""
Device alert notification fan-out.

When the agent uploads one or more flagged-activity alerts (see
DeviceAlert's docstring for the deliberate scope boundary — matches only,
never a full activity/browsing log), every admin in that organization who
holds `devices.view_alerts` gets:
  1. An in-app Notification row (dashboard bell / notification feed).
  2. A workflow event enqueued via the existing Celery worker
     (notifications.trigger_workflow_event), which is where email
     delivery for this event type should be wired up on the workflow
     side — this module only enqueues the event, it does not send email
     directly, to stay consistent with how the rest of the platform
     dispatches notifications.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.devices import Device
from app.models.user import User


async def _admin_user_ids_for_org(db: AsyncSession, tenant_id: UUID) -> list[UUID]:
    """
    Every active user in the org who can see device alerts: the
    organization owner (always, via the owner-bypass — see
    User.has_permission) plus anyone holding devices.view_alerts through
    a custom role. Loads roles+permissions explicitly since this runs
    outside a normal request's dependency-injected session.
    """
    from sqlalchemy.orm import selectinload
    from app.models.rbac import Role
    from app.models.organization import Organization

    org = (await db.execute(select(Organization).where(Organization.id == tenant_id))).scalar_one_or_none()
    if org is None:
        return []

    users = (
        await db.execute(
            select(User)
            .where(User.organization_id == tenant_id, User.is_deleted == False, User.is_active == True)  # noqa: E712
            .options(selectinload(User.roles).selectinload(Role.permissions))
        )
    ).scalars().all()

    recipient_ids = []
    for u in users:
        if u.is_platform_admin or (org.owner_id == u.id) or u.has_permission("devices.view_alerts"):
            recipient_ids.append(u.id)
    return recipient_ids


async def notify_admins_of_device_alert(db: AsyncSession, device: Device, alert_count: int) -> None:
    from app.models.workflows import Notification

    recipient_ids = await _admin_user_ids_for_org(db, device.tenant_id)
    if not recipient_ids:
        return

    device_label = device.device_name or device.hostname
    title = "Flagged device activity" if alert_count == 1 else f"{alert_count} flagged device activities"
    body = f"{device_label} triggered {alert_count} activity alert(s). Review in Device Management."

    for user_id in recipient_ids:
        db.add(
            Notification(
                tenant_id=device.tenant_id,
                user_id=user_id,
                title=title,
                body=body,
                type="device_alert",
                icon="alert-triangle",
                action_url=f"/devices?device_id={device.id}&tab=alerts",
                metadata_={"device_id": str(device.id), "alert_count": alert_count},
            )
        )
    await db.flush()

    # Enqueue the existing worker task so email dispatch (or any other
    # workflow-driven side effect) can hook into this event without this
    # module needing to know how email is actually sent.
    try:
        from app.workers.tasks.notifications import trigger_workflow_event
        trigger_workflow_event.delay(
            tenant_id=str(device.tenant_id),
            event_type="device.alert_raised",
            payload={
                "device_id": str(device.id),
                "device_label": device_label,
                "alert_count": alert_count,
                "recipient_ids": [str(uid) for uid in recipient_ids],
            },
        )
    except Exception:
        # Celery/broker may not be running in every environment (e.g. a
        # local dev setup without a worker) — the in-app notification
        # above already succeeded, so this stays non-fatal.
        pass
