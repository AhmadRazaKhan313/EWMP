"""Notification response schemas — mirrors frontend/desktop's NotificationItem
(frontend/src/types/index.ts and desktop-app's types/hrms.ts NotificationItem)."""

from datetime import datetime

from pydantic import BaseModel


class NotificationItemSchema(BaseModel):
    id: str
    title: str
    body: str | None
    type: str
    icon: str | None
    action_url: str | None
    metadata: dict
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class NotificationsPageSchema(BaseModel):
    items: list[NotificationItemSchema]
    total: int
    unread_count: int


class UnreadCountSchema(BaseModel):
    unread_count: int


class MarkAllReadResultSchema(BaseModel):
    marked_read: int
