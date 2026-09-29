"""Notification repository."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflows import Notification
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(db, Notification, tenant_id)

    def _own_filters(self, user_id: uuid.UUID, *, unread_only: bool = False) -> list:
        filters = [
            Notification.tenant_id == self.tenant_id,
            Notification.user_id == user_id,
            Notification.is_deleted == False,  # noqa: E712
            # expires_at is currently never set by any producer (e.g.
            # device_alerts.py leaves it null), but honor it defensively
            # so a future time-limited notification doesn't linger
            # forever in "unread" once past its own expiry.
            or_(Notification.expires_at.is_(None), Notification.expires_at > datetime.now(UTC)),
        ]
        if unread_only:
            filters.append(Notification.is_read == False)  # noqa: E712
        return filters

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        limit: int = 50,
    ) -> tuple[list[Notification], int, int]:
        """Returns (items, total matching the filter, unread_count regardless
        of the unread_only filter — the badge/pill always needs the true
        unread count even when the caller asked for "all")."""
        filters = self._own_filters(user_id, unread_only=unread_only)

        stmt = (
            select(Notification)
            .where(*filters)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        count_stmt = select(func.count()).select_from(Notification).where(*filters)

        items_result = await self.db.execute(stmt)
        count_result = await self.db.execute(count_stmt)
        unread_count = await self.get_unread_count(user_id)

        return list(items_result.scalars().all()), count_result.scalar_one(), unread_count

    async def get_unread_count(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(*self._own_filters(user_id, unread_only=True))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Returns False if the notification doesn't exist or doesn't
        belong to this user (repository callers turn that into a 404 —
        never leaks whether some other user's notification exists)."""
        notification = await self.get(notification_id)
        if notification is None or notification.user_id != user_id or notification.tenant_id != self.tenant_id:
            return False
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(UTC)
            await self.db.flush()
        return True

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        stmt = (
            update(Notification)
            .where(*self._own_filters(user_id, unread_only=True))
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount or 0
