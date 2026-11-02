"""
Notifications API (self-service only).

Backs the desktop app's tray/dock unread badge (`useNotificationBadge`,
polling GET /notifications/unread-count every 60s) and its in-app inbox
(NotificationsScreen), matching the exact contract desktop-app's
`services/notificationsService.ts` already expects:

    GET  /notifications?unread_only=&limit=       -> NotificationsPage
    GET  /notifications/unread-count               -> { unread_count }
    POST /notifications/{id}/read                   -> 204
    POST /notifications/read-all                     -> 204

There is no "view someone else's notifications" mode — every route here
only ever touches the current user's own rows.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.workflows import Notification
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id
from app.repositories.notification import NotificationRepository
from app.schemas.notifications import (
    MarkAllReadResultSchema,
    NotificationItemSchema,
    NotificationsPageSchema,
    UnreadCountSchema,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _serialize(n: Notification) -> NotificationItemSchema:
    return NotificationItemSchema(
        id=str(n.id),
        title=n.title,
        body=n.body,
        type=n.type,
        icon=n.icon,
        action_url=n.action_url,
        metadata=n.metadata_ or {},
        is_read=n.is_read,
        read_at=n.read_at,
        created_at=n.created_at,
    )


@router.get("", response_model=NotificationsPageSchema)
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
) -> NotificationsPageSchema:
    repo = NotificationRepository(db, tenant_id)
    items, total, unread_count = await repo.list_for_user(
        current_user.id, unread_only=unread_only, limit=limit
    )
    return NotificationsPageSchema(
        items=[_serialize(n) for n in items],
        total=total,
        unread_count=unread_count,
    )


@router.get("/unread-count", response_model=UnreadCountSchema)
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
) -> UnreadCountSchema:
    repo = NotificationRepository(db, tenant_id)
    count = await repo.get_unread_count(current_user.id)
    return UnreadCountSchema(unread_count=count)


@router.post("/read-all", response_model=MarkAllReadResultSchema)
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
) -> MarkAllReadResultSchema:
    # NOTE: registered before /{notification_id}/read so "read-all" is
    # never swallowed by the {notification_id} path parameter.
    repo = NotificationRepository(db, tenant_id)
    marked = await repo.mark_all_read(current_user.id)
    return MarkAllReadResultSchema(marked_read=marked)


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
) -> None:
    repo = NotificationRepository(db, tenant_id)
    found = await repo.mark_read(notification_id, current_user.id)
    if not found:
        raise NotFoundError("Notification not found")
