"""
Base SQLAlchemy model mixins.

Every production table needs:
  - UUID primary key (no sequential IDs exposed externally)
  - Audit timestamps (created_at, updated_at)
  - Soft delete (deleted_at — rows are never physically removed)
  - Tenant isolation (tenant_id on every tenant-scoped table)

These are implemented as mixins so they can be composed selectively.
The PlatformModel mixin skips tenant_id for platform-level tables
(super admin, platform settings, billing plans) that exist outside tenants.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UUIDMixin:
    """Adds a UUID primary key generated at the database level."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        index=True,
    )


class TimestampMixin:
    """Adds created_at and updated_at audit columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """
    Adds soft delete support.

    Deleted records keep deleted_at set to the deletion timestamp.
    All repository queries must filter WHERE deleted_at IS NULL unless
    explicitly requesting archived records.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        index=True,
    )

    def soft_delete(self) -> None:
        """Mark this record as deleted without removing it from the database."""
        self.deleted_at = datetime.now(UTC)
        self.is_deleted = True

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None
        self.is_deleted = False


class TenantMixin:
    """
    Adds tenant_id to scope every row to a specific organization.

    This is the primary guard for multi-tenancy. Every repository
    method must include tenant_id in its WHERE clause. The tenant
    middleware (middleware/tenant.py) sets the current tenant on
    every request, and the base repository enforces it automatically.
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


# ── Composed Base Models ──────────────────────────────────────────────────────

class TenantModel(UUIDMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    """
    Base for all tenant-scoped tables.

    Use this for: Employee, Department, LeaveRequest, Payroll,
    Device, Asset, Ticket, WorkflowDefinition, etc.
    """
    __abstract__ = True


class PlatformModel(UUIDMixin, TimestampMixin, Base):
    """
    Base for platform-level tables that exist outside any tenant.

    Use this for: Organization, PlatformAdmin, BillingPlan,
    MarketplacePlugin, PlatformAuditLog, etc.
    """
    __abstract__ = True


class PlatformSoftDeleteModel(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Platform model with soft delete support."""
    __abstract__ = True
