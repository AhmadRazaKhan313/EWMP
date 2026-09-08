"""
Organization (Tenant) model.

Each organization is a fully isolated tenant. It has its own:
  - Users and roles
  - HR data (employees, departments, payroll)
  - Device inventory
  - Billing subscription
  - Custom workflows
  - Integration settings

The organization slug is used as the subdomain: acme.ewmp.io
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import PlatformSoftDeleteModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.subscription import Subscription


class Organization(PlatformSoftDeleteModel):
    __tablename__ = "organizations"

    # ── Identity ──────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="Used as subdomain and URL identifier",
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Branding ──────────────────────────────────────────────────
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    favicon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[str | None] = mapped_column(
        String(7),
        nullable=True,
        comment="Hex color for white-label branding",
    )
    custom_domain: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        comment="e.g. hr.acme.com for enterprise customers",
    )

    # ── Contact ───────────────────────────────────────────────────
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Location ──────────────────────────────────────────────────
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(100),
        default="UTC",
        server_default="UTC",
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        default="USD",
        server_default="USD",
        nullable=False,
        comment="ISO 4217 currency code",
    )
    locale: Mapped[str] = mapped_column(
        String(10),
        default="en-US",
        server_default="en-US",
        nullable=False,
    )

    # ── Limits ────────────────────────────────────────────────────
    max_employees: Mapped[int] = mapped_column(
        Integer,
        default=50,
        server_default="50",
        nullable=False,
    )
    max_devices: Mapped[int] = mapped_column(
        Integer,
        default=100,
        server_default="100",
        nullable=False,
    )
    max_storage_gb: Mapped[int] = mapped_column(
        Integer,
        default=10,
        server_default="10",
        nullable=False,
    )

    # ── Status ────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    is_trial: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Feature Flags (per-org overrides) ─────────────────────────
    features: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
        comment="Per-org feature flag overrides",
    )

    # ── Settings ──────────────────────────────────────────────────
    settings: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
        comment="Org-level settings: work hours, leave policy defaults, etc.",
    )

    # ── Owner ─────────────────────────────────────────────────────
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Set after first user is created during onboarding",
    )

    # ── Relationships ─────────────────────────────────────────────
    users: Mapped[list["User"]] = relationship(
        "User",
        back_populates="organization",
        foreign_keys="User.organization_id",
    )

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug!r}>"

    @property
    def is_on_trial(self) -> bool:
        if not self.is_trial or self.trial_ends_at is None:
            return False
        from datetime import UTC
        from datetime import datetime as dt
        return dt.now(UTC) < self.trial_ends_at
