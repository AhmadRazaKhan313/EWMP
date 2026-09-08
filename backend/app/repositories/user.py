"""
User repository.

Extends BaseRepository with user-specific queries.
All password and token fields are handled here, never in route handlers.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.rbac import Role
from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        # Users are NOT tenant-scoped at model level (they reference organization_id)
        # so we pass tenant_id=None to BaseRepository and handle org filtering manually.
        super().__init__(db, User, tenant_id=None)

    async def get_with_roles(self, user_id: uuid.UUID) -> User | None:
        """
        Fetch user with roles+permissions and organization eagerly loaded.

        Used by get_current_user(), which runs on every authenticated
        request — this is why organization is loaded here too, not just
        at login: a suspended org's users must be locked out immediately
        on their next API call, not only the next time they log in (their
        current access token could otherwise keep working until it expires).
        """
        stmt = (
            select(User)
            .where(User.id == user_id, User.is_deleted == False)  # noqa: E712
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.organization),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_organization(self, user_id: uuid.UUID) -> User | None:
        """Fetch user with `organization` eagerly loaded (used by token refresh)."""
        stmt = (
            select(User)
            .where(User.id == user_id, User.is_deleted == False)  # noqa: E712
            .options(selectinload(User.organization))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """
        Case-insensitive email lookup.

        Eager-loads `organization` — this is used by login(), which reads
        `user.organization.is_active` right after. Without eager loading,
        that access lazy-loads outside the request's async greenlet and
        crashes with MissingGreenlet (same class of bug as the roles
        eager-load issue documented in get_with_roles / permissions
        dependencies).
        """
        stmt = select(User).where(
            User.email_normalized == email.lower().strip(),
            User.is_deleted == False,  # noqa: E712
        ).options(selectinload(User.organization))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_verification_token(self, token: str) -> User | None:
        stmt = select(User).where(
            User.email_verification_token == token,
            User.is_deleted == False,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_reset_token(self, token: str) -> User | None:
        stmt = select(User).where(
            User.password_reset_token == token,
            User.password_reset_expires_at > datetime.now(UTC),
            User.is_deleted == False,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        user = await self.get_by_email(email)
        return user is not None

    async def record_successful_login(self, user_id: uuid.UUID, ip: str) -> None:
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                last_login_at=datetime.now(UTC),
                last_login_ip=ip,
                login_count=User.login_count + 1,
                failed_login_count=0,
                locked_until=None,
            )
        )

    async def record_failed_login(self, user_id: uuid.UUID) -> None:
        """Increment the failure counter and lock the account after 5 consecutive
        failures — in a DEDICATED, committed transaction.

        The login flow calls this and then immediately raises
        ``InvalidCredentialsError``. ``get_db`` rolls the request's session back
        on any exception, so incrementing on ``self.db`` would be silently
        discarded — the counter would never rise and the lockout would never
        trigger (bug H1: unlimited brute force). Writing through a separate
        session that commits on its own persists the attempt regardless of the
        request rollback.
        """
        from app.core.database import get_db_context

        async with get_db_context() as session:
            result = await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(failed_login_count=User.failed_login_count + 1)
                .returning(User.failed_login_count)
            )
            new_count = result.scalar_one()

            if new_count >= 5:
                lock_until = datetime.now(UTC) + timedelta(minutes=30)
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(locked_until=lock_until)
                )

    async def list_by_organization(
        self,
        organization_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[User], int]:
        from sqlalchemy import func
        offset = (page - 1) * page_size

        stmt = (
            select(User)
            .where(
                User.organization_id == organization_id,
                User.is_deleted == False,  # noqa: E712
            )
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        count_stmt = select(func.count()).where(
            User.organization_id == organization_id,
            User.is_deleted == False,  # noqa: E712
        ).select_from(User)

        items_result = await self.db.execute(stmt)
        count_result = await self.db.execute(count_stmt)

        return list(items_result.scalars().all()), count_result.scalar_one()