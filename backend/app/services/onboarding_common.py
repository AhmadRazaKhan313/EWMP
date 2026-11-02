"""Shared helpers for the offer and onboarding services (N-01)."""
import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings

logger = logging.getLogger("ewmp.onboarding")

OFFER_VALID_DAYS = 7
PREBOARDING_GRACE_DAYS = 7


def now() -> datetime:
    return datetime.now(UTC)


def new_token() -> str:
    """URL-safe secret shown once; only its sha256 is stored."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def offer_url(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/offer/{token}"


def preboarding_url(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/preboarding/{token}"


def queue(task, *args) -> None:
    """Fire a Celery task without letting a down broker fail the request."""
    try:
        task.delay(*args)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not queue %s: %s", getattr(task, "name", task), exc)


async def recipient_ids(db: AsyncSession, tenant_id: uuid.UUID, *permissions: str) -> list[uuid.UUID]:
    """Org owner plus every active user holding any of `permissions`."""
    from app.models.organization import Organization
    from app.models.rbac import Role
    from app.models.user import User

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
    return [u.id for u in users if org.owner_id == u.id or any(u.has_permission(p) for p in permissions)]


def notify(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, *, title: str, body: str,
           type_: str, action_url: str | None = None, icon: str = "user-plus", meta: dict | None = None) -> None:
    from app.models.workflows import Notification

    db.add(Notification(
        tenant_id=tenant_id, user_id=user_id, title=title, body=body, type=type_,
        icon=icon, action_url=action_url, metadata_=meta or {},
    ))
