"""
Employee model.

An Employee is the HR representation of a User within an organization.
Not every User is an Employee (e.g., external contractors, IT admins),
and the separation allows a user to hold platform access without
appearing in HR reports, payroll, or attendance.

The relationship is: User (auth identity) → Employee (HR profile)
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    JSON,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantModel

import enum


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERN = "intern"
    FREELANCE = "freelance"


class JobNature(str, enum.Enum):
    """
    Employment Status (Job Nature) — the employee's contractual standing,
    as distinct from EmploymentType (work-schedule/engagement kind, above)
    and EmploymentStatus (day-to-day lifecycle state: active/on-leave/
    terminated, below). Drives probation/confirmation and contract-related
    HR logic separately from those two.
    """
    PERMANENT = "permanent"          # Regular — confirmed, completed probation
    PROBATIONARY = "probationary"    # New hire on a trial period
    CONTRACTUAL = "contractual"      # Fixed-term / project-based contract
    INTERN = "intern"                # Intern / trainee
    PART_TIME = "part_time"          # Reduced-hours employee
    TEMPORARY = "temporary"          # Seasonal / casual, short-term


class EmploymentStatus(str, enum.Enum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    PROBATION = "probation"
    NOTICE_PERIOD = "notice_period"
    TERMINATED = "terminated"
    RESIGNED = "resigned"


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class MaritalStatus(str, enum.Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


class Employee(TenantModel):
    __tablename__ = "employees"

    # ── Link to auth user ─────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )

    # ── Employee identity ─────────────────────────────────────────
    employee_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Org-defined code e.g. EMP-0042",
    )

    # ── Organizational structure ──────────────────────────────────
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    designation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("designations.id", ondelete="SET NULL"),
        nullable=True,
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Direct reporting manager",
    )
    default_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shifts.id", ondelete="SET NULL"),
        nullable=True,
        comment="Shift used to calculate late/overtime minutes on check-in",
    )

    # ── Employment details ────────────────────────────────────────
    employment_type: Mapped[EmploymentType] = mapped_column(
        SAEnum(EmploymentType, name="employment_type_enum"),
        default=EmploymentType.FULL_TIME,
        nullable=False,
    )
    job_nature: Mapped[JobNature] = mapped_column(
        SAEnum(JobNature, name="job_nature_enum"),
        default=JobNature.PROBATIONARY,
        nullable=False,
        index=True,
        comment="Employment Status / Job Nature: permanent, probationary, "
        "contractual, intern, part_time, or temporary",
    )
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        SAEnum(EmploymentStatus, name="employment_status_enum"),
        default=EmploymentStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    date_of_joining: Mapped[date] = mapped_column(Date, nullable=False)
    date_of_confirmation: Mapped[date | None] = mapped_column(Date, nullable=True)
    probation_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_period_days: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30"
    )
    date_of_leaving: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Work location ─────────────────────────────────────────────
    work_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_remote: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # ── Personal details ──────────────────────────────────────────
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[Gender | None] = mapped_column(
        SAEnum(Gender, name="gender_enum"), nullable=True
    )
    marital_status: Mapped[MaritalStatus | None] = mapped_column(
        SAEnum(MaritalStatus, name="marital_status_enum"), nullable=True
    )
    nationality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(5), nullable=True)

    # ── Contact ───────────────────────────────────────────────────
    personal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    personal_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Structured: street, city, state, postal_code, country",
    )

    # ── Identity documents ────────────────────────────────────────
    national_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="CNIC / SSN / NIN"
    )
    passport_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    passport_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Banking ───────────────────────────────────────────────────
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Stored encrypted"
    )
    bank_routing_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account_title: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Emergency contact ─────────────────────────────────────────
    emergency_contact: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="name, relationship, phone, email",
    )

    # ── Compensation (snapshot — full history in salary_structures) ───
    current_salary: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(
        String(3), default="USD", server_default="USD"
    )

    # ── Custom fields ─────────────────────────────────────────────
    custom_fields: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        comment="Org-defined additional fields",
    )

    # ── Relationships ─────────────────────────────────────────────
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="joined",
    )
    manager: Mapped["Employee | None"] = relationship(
        "Employee",
        remote_side="Employee.id",
        foreign_keys=[manager_id],
    )
    direct_reports: Mapped[list["Employee"]] = relationship(
        "Employee",
        foreign_keys=[manager_id],
        back_populates="manager",
    )

    def __repr__(self) -> str:
        return f"<Employee id={self.id} code={self.employee_code!r}>"

    @property
    def is_active(self) -> bool:
        return self.employment_status == EmploymentStatus.ACTIVE

    @property
    def years_of_service(self) -> float:
        from datetime import date as d
        delta = d.today() - self.date_of_joining
        return round(delta.days / 365.25, 1)
