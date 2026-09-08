"""
Organizational structure models.

Department  → logical HR grouping (Engineering, HR, Finance)
Designation → job title/position (Senior Engineer, HR Manager)
Branch      → physical office location
Team        → cross-department project or functional team
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel


class Department(TenantModel):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="For nested department hierarchy",
    )
    head_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    parent: Mapped["Department | None"] = relationship(
        "Department", remote_side="Department.id", foreign_keys=[parent_id]
    )
    children: Mapped[list["Department"]] = relationship(
        "Department", foreign_keys=[parent_id], back_populates="parent"
    )

    def __repr__(self) -> str:
        return f"<Department {self.name!r}>"


class Designation(TenantModel):
    __tablename__ = "designations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1",
        comment="Hierarchy level: 1=IC, 2=Lead, 3=Manager, 4=Director, 5=VP, 6=C-Suite",
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<Designation {self.name!r}>"


class Branch(TenantModel):
    __tablename__ = "branches"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_headquarters: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Address
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Geo for attendance
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    geo_fence_radius_meters: Mapped[int] = mapped_column(
        Integer, default=100, server_default="100"
    )

    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC", server_default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<Branch {self.name!r}>"


class Team(TenantModel):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    lead_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<Team {self.name!r}>"
