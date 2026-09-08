"""
User model.

Every User belongs to exactly one Organization — no exceptions, including
the platform super admin, who belongs to the platform-operator's own
organization (created once at DB-seed time) rather than floating outside
any tenant. This used to be nullable specifically to let the platform
admin exist without an org; that's been removed so there is exactly one
kind of user in this system, not two.

Permissions are fully DB-driven through the Role → Permission
many-to-many relationship. There is exactly one "system" role in the
whole platform — Platform Super Admin, seeded once via `manage.py seed
--superadmin` — and it lives inside that same bootstrap organization.
Every other role, for every other organization, is a custom role: either
the single default "Admin" role auto-created for a newly signed-up org
(so its first user isn't locked out), or roles org admins create
themselves via the Roles API. `is_platform_admin` remains a fast-path
boolean for convenience, but it is only ever true for a user who also
has real Role/Permission rows via the system role — it is not a
standalone bypass identity anymore.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    Table,
    Column,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDMixin, TimestampMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.rbac import Role


# ── Association table: User ↔ Role ────────────────────────────────────────────
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class User(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    # ── Organization link ─────────────────────────────────────────
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Every user, including the platform super admin, belongs to an organization",
    )

    # ── Identity ──────────────────────────────────────────────────
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )
    email_normalized: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Lowercase, used for case-insensitive lookups",
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="NULL when using OAuth or magic link only",
    )
    username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
    )

    # ── Profile ───────────────────────────────────────────────────
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── Locale ────────────────────────────────────────────────────
    timezone: Mapped[str] = mapped_column(
        String(100), default="UTC", server_default="UTC"
    )
    locale: Mapped[str] = mapped_column(
        String(10), default="en-US", server_default="en-US"
    )
    date_format: Mapped[str] = mapped_column(
        String(20), default="YYYY-MM-DD", server_default="YYYY-MM-DD"
    )

    # ── Status ────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        index=True,
        comment="True only for the seeded platform super admin",
    )

    # ── Email verification ────────────────────────────────────────
    email_verification_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    email_verification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Password reset ────────────────────────────────────────────
    password_reset_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── 2FA ───────────────────────────────────────────────────────
    is_2fa_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    totp_secret: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Encrypted TOTP secret for authenticator apps",
    )
    backup_codes: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Hashed one-time backup codes",
    )

    # ── Session tracking ──────────────────────────────────────────
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    login_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Preferences ───────────────────────────────────────────────
    preferences: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        comment="UI preferences: theme, sidebar state, notifications, etc.",
    )

    # ── Relationships ─────────────────────────────────────────────
    organization: Mapped["Organization | None"] = relationship(
        "Organization",
        back_populates="users",
        foreign_keys=[organization_id],
        lazy="joined",
    )
    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary=user_roles,
        back_populates="users",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_locked(self) -> bool:
        if self.locked_until is None:
            return False
        from datetime import UTC
        from datetime import datetime as dt
        return dt.now(UTC) < self.locked_until

    @property
    def has_full_access(self) -> bool:
        """
        True if this user bypasses per-permission checks entirely:
          - `is_platform_admin` — platform-wide bypass.
          - Organization owner — the user who owns this org (matched via
            `organization.owner_id`) always has full access to their own
            org. This is deliberate: there is no seeded/"systematic" role
            anywhere in this system. A brand-new org has ZERO roles until
            its owner creates some via the Roles API — the owner bypass is
            what makes that org usable from the first login, without
            silently granting them a role they never asked for.
          - `Role.is_super` (settable on any custom role, e.g. a "Full
            Access" role an owner creates for a co-founder) — an ordinary
            property any custom role can have, not a special kind of role.

        Shared by `has_permission()` below and by the API layer (`/auth/me`,
        login) so that anything exposing "what can this user do" — including
        the frontend sidebar's permission-gated nav — agrees with the actual
        authorization check instead of only reflecting explicitly-assigned
        permission rows.
        """
        if self.is_platform_admin:
            return True
        if self.organization_id and self.organization and self.organization.owner_id == self.id:
            return True
        if any(role.is_super for role in self.roles):
            return True
        return False

    def has_permission(self, permission_codename: str) -> bool:
        """
        Check if this user has a specific permission.

        Bypass paths (no role lookup needed) are covered by
        `has_full_access`. Everything else is a plain DB-driven
        Role → Permission check.
        """
        if self.has_full_access:
            return True
        return any(
            any(p.codename == permission_codename for p in role.permissions)
            for role in self.roles
        )
