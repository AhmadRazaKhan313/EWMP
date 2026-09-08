"""
Generic async base repository.

Every feature-specific repository extends BaseRepository[ModelT].
Tenant isolation is enforced at this layer — callers never need to
add `WHERE tenant_id = ?` themselves.

Design decisions:
  - Type-safe via generics: BaseRepository[Employee] gives full IDE completion.
  - Soft delete: `get`, `list`, `count` always exclude deleted records by default.
  - Pagination: list() returns (items, total) for consistent API pagination.
  - Audit trail: create/update/delete accept `actor_id` for audit log hooks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar, get_args
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.exceptions import NotFoundError, TenantScopeError
from app.models.base import TenantModel, Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """
    Generic async repository providing CRUD, pagination, and soft delete.

    Usage:
        class EmployeeRepository(BaseRepository[Employee]):
            def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
                super().__init__(db, Employee, tenant_id)

            async def find_by_code(self, code: str) -> Employee | None:
                return await self._get_one_by(Employee.employee_code == code)
    """

    def __init__(
        self,
        db: AsyncSession,
        model: type[ModelT],
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        self.db = db
        self.model = model
        self.tenant_id = tenant_id
        self._is_tenant_model = hasattr(model, "tenant_id")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _assert_tenant_scope(self) -> None:
        """Deny-by-default guard for tenant-scoped repositories.

        A tenant model must never be queried or written without a tenant_id:
        doing so would return or persist rows across *every* tenant. Callers
        always construct these repositories with a real tenant_id (resolved by
        get_tenant_id, which yields a UUID or raises), so a missing tenant_id
        here is a programming error. Fail closed and loud rather than silently
        leaking data.
        """
        if self._is_tenant_model and self.tenant_id is None:
            raise TenantScopeError(
                f"{self.model.__name__} is tenant-scoped but no tenant_id was "
                "provided; refusing to run an unscoped query."
            )

    def _base_query(self, include_deleted: bool = False):
        """Return a SELECT with tenant and soft-delete filters applied."""
        self._assert_tenant_scope()
        stmt = select(self.model)

        # Tenant isolation
        if self._is_tenant_model and self.tenant_id is not None:
            stmt = stmt.where(self.model.tenant_id == self.tenant_id)  # type: ignore[attr-defined]

        # Soft delete filter
        if not include_deleted and hasattr(self.model, "is_deleted"):
            stmt = stmt.where(self.model.is_deleted == False)  # noqa: E712

        return stmt

    async def _get_one_by(
        self, *conditions: Any, include_deleted: bool = False
    ) -> ModelT | None:
        stmt = self._base_query(include_deleted=include_deleted)
        for condition in conditions:
            stmt = stmt.where(condition)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ── Public CRUD ───────────────────────────────────────────────────────────

    async def get(self, id: uuid.UUID, include_deleted: bool = False) -> ModelT | None:
        """Fetch a single record by primary key, or None."""
        return await self._get_one_by(
            self.model.id == id,  # type: ignore[attr-defined]
            include_deleted=include_deleted,
        )

    async def get_or_raise(self, id: uuid.UUID) -> ModelT:
        """Fetch by primary key or raise NotFoundError."""
        instance = await self.get(id)
        if instance is None:
            raise NotFoundError(
                f"{self.model.__name__} with id '{id}' not found"
            )
        return instance

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        order_by: InstrumentedAttribute | None = None,
        descending: bool = False,
        include_deleted: bool = False,
        filters: list[Any] | None = None,
    ) -> tuple[Sequence[ModelT], int]:
        """
        Return (items, total_count) with pagination.

        Args:
            page: 1-based page number.
            page_size: Records per page (max 200 enforced here).
            order_by: Column to sort by.
            descending: Sort direction.
            include_deleted: Include soft-deleted records.
            filters: Additional SQLAlchemy WHERE conditions.

        Returns:
            Tuple of (records, total_count).
        """
        page_size = min(page_size, 200)
        offset = (page - 1) * page_size

        stmt = self._base_query(include_deleted=include_deleted)
        count_stmt = self._base_query(include_deleted=include_deleted)

        if filters:
            for f in filters:
                stmt = stmt.where(f)
                count_stmt = count_stmt.where(f)

        if order_by is not None:
            stmt = stmt.order_by(order_by.desc() if descending else order_by.asc())
        elif hasattr(self.model, "created_at"):
            stmt = stmt.order_by(self.model.created_at.desc())  # type: ignore[attr-defined]

        stmt = stmt.offset(offset).limit(page_size)

        count_stmt = select(func.count()).select_from(count_stmt.subquery())

        items_result = await self.db.execute(stmt)
        count_result = await self.db.execute(count_stmt)

        items = items_result.scalars().all()
        total = count_result.scalar_one()

        return items, total

    async def create(self, data: dict[str, Any]) -> ModelT:
        """
        Create and persist a new record.

        Automatically injects tenant_id if the model is tenant-scoped.
        """
        self._assert_tenant_scope()
        if self._is_tenant_model and self.tenant_id is not None:
            data.setdefault("tenant_id", self.tenant_id)

        instance = self.model(**data)  # type: ignore[call-arg]
        self.db.add(instance)
        await self.db.flush()  # Get generated id without committing
        await self.db.refresh(instance)
        return instance

    async def update(
        self, id: uuid.UUID, data: dict[str, Any]
    ) -> ModelT:
        """Update an existing record by id. Raises NotFoundError if absent."""
        instance = await self.get_or_raise(id)
        for key, value in data.items():
            setattr(instance, key, value)
        await self.db.flush()
        await self.db.refresh(instance)
        return instance

    async def delete(self, id: uuid.UUID, *, hard: bool = False) -> None:
        """
        Delete a record.

        Args:
            id: Primary key of the record to delete.
            hard: If True, physically removes the row. Default is soft delete.
        """
        instance = await self.get_or_raise(id)

        if hard:
            await self.db.delete(instance)
        else:
            if hasattr(instance, "soft_delete"):
                instance.soft_delete()  # type: ignore[attr-defined]
            else:
                # Fallback for models without SoftDeleteMixin
                await self.db.delete(instance)

        await self.db.flush()

    async def exists(self, id: uuid.UUID) -> bool:
        """Return True if a non-deleted record with this id exists."""
        instance = await self.get(id)
        return instance is not None

    async def count(self, filters: list[Any] | None = None) -> int:
        """Return the total count of non-deleted records matching filters."""
        stmt = select(func.count()).select_from(
            self._base_query().subquery()
        )
        if filters:
            stmt = stmt.where(*filters)
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def bulk_create(self, items: list[dict[str, Any]]) -> list[ModelT]:
        """Create multiple records in one flush."""
        self._assert_tenant_scope()
        instances = []
        for data in items:
            if self._is_tenant_model and self.tenant_id is not None:
                data.setdefault("tenant_id", self.tenant_id)
            instance = self.model(**data)  # type: ignore[call-arg]
            self.db.add(instance)
            instances.append(instance)
        await self.db.flush()
        for instance in instances:
            await self.db.refresh(instance)
        return instances