"""
Role-Based Access Control models.

Architecture: fully DB-driven, zero hardcoded roles anywhere in the
application. There is no seeded/"systematic" role of any kind — not
even a default "Admin" role gets auto-created for a new organization.

Every organization starts with zero roles. Its owner (Organization.owner_id)
has full access to their own org regardless — see the owner-bypass in
User.has_permission — which is what makes a brand-new org usable before
anyone has created a single role. Org admins build their own role list
(HR Manager, Recruiter, whatever fits them) entirely through the Roles
API, assigning whichever permissions they choose to each one.

  Permission  — atomic action codename (e.g. "employees.create")
  Role        — named collection of permissions, scoped to a tenant
  User ↔ Role — many-to-many via user_roles
  Role ↔ Permission — many-to-many via role_permissions

Permission codename format: <resource>.<action>
  employees.view           employees.create       employees.update
  employees.delete         payroll.view           payroll.process
  devices.view             devices.remote_control leave.approve
  reports.export           settings.manage        ...
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Table, Text, Column, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


# ── Association: Role ↔ Permission ────────────────────────────────────────────
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(UUIDMixin, TimestampMixin, Base):
    """
    Atomic permission unit.

    Permissions are seeded from the registry in database/seeds/permissions.py
    and are never created by end users. They represent the full capability
    surface of the platform.
    """
    __tablename__ = "permissions"

    # e.g. "employees", "payroll", "devices", "reports"
    resource: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )

    # e.g. "view", "create", "update", "delete", "export", "approve"
    action: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    # e.g. "employees.create" — the string used in has_permission() checks
    codename: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        unique=True,
        index=True,
    )

    # Human-readable label shown in the Roles UI
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Groups permissions in the UI (e.g. "HR Management", "Device Control")
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Some permissions are dangerous — require explicit super admin grant
    is_sensitive: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary=role_permissions,
        back_populates="permissions",
    )

    def __repr__(self) -> str:
        return f"<Permission {self.codename!r}>"


class Role(UUIDMixin, TimestampMixin, Base):
    """
    A named collection of permissions, scoped to one tenant.

    Entirely custom — nothing is pre-seeded. `is_system` exists in the
    schema but nothing in this codebase ever sets it true; it's kept as
    an escape hatch in case a genuinely protected role is ever needed,
    not as a marker for "the roles every org gets by default" (there
    are none). `is_super` is an ordinary toggle any custom role can have
    ("give this role every permission, including future ones") — it's
    not reserved for a special role either.
    """
    __tablename__ = "roles"

    # NULL for platform-level roles (Platform Super Admin)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(
        String(7), nullable=True, comment="Hex color for UI badge"
    )

    # System roles cannot be deleted by org admins
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # Inherit all permissions automatically (used for Owner role)
    is_super: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # Ordering in UI
    display_order: Mapped[int] = mapped_column(default=0, server_default="0")

    # Extra metadata (e.g. default modules visible, dashboard layout)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        server_default="{}",
    )

    permissions: Mapped[list["Permission"]] = relationship(
        "Permission",
        secondary=role_permissions,
        back_populates="roles",
        lazy="selectin",
    )
    users: Mapped[list["User"]] = relationship(
        "User",
        secondary="user_roles",
        back_populates="roles",
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name!r}>"

    @property
    def permission_codenames(self) -> set[str]:
        return {p.codename for p in self.permissions}
