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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    JSON,
    text,
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

    # Family (Frappe-HR style "family background"). Plain names — no
    # dependants/relationship tables, so they stay trivial to fill in.
    father_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    mother_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    spouse_name: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # ── Contact ───────────────────────────────────────────────────
    personal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    personal_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Current address. Structured: street, city, state, postal_code, country",
    )
    permanent_address: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Same shape as `address`",
    )

    # ── Identity documents ────────────────────────────────────────
    national_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="CNIC / SSN / NIN"
    )
    passport_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    passport_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    driving_license_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    driving_license_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    national_id_type: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="cnic | passport | ssn | nin | other"
    )
    tax_number: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="NTN / TIN")
    social_security_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="EOBI / social security"
    )
    provident_fund_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    visa_number: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="Visa / work permit")
    visa_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── More personal details ─────────────────────────────────────
    religion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    place_of_birth: Mapped[str | None] = mapped_column(String(100), nullable=True)
    home_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    previous_employee_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    referral_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hobbies: Mapped[str | None] = mapped_column(Text, nullable=True)
    tshirt_size: Mapped[str | None] = mapped_column(String(5), nullable=True)
    social_links: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="{linkedin, twitter, github, facebook, website}"
    )

    # ── Banking ───────────────────────────────────────────────────
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Stored encrypted"
    )
    bank_routing_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_iban: Mapped[str | None] = mapped_column(String(34), nullable=True)

    # ── Health insurance ──────────────────────────────────────────
    health_insurance_provider: Mapped[str | None] = mapped_column(String(150), nullable=True)
    health_insurance_number: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # ── Emergency contacts ────────────────────────────────────────
    # `emergency_contacts` is the list (any number of people). The single
    # `emergency_contact` dict is the legacy column: it is kept in step with
    # the FIRST list entry so older readers (and old rows) keep working.
    emergency_contact: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="LEGACY single contact — mirrors emergency_contacts[0]",
    )
    emergency_contacts: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment="[{name, relationship, phone, email, address}] — any number",
    )

    # ── Education & work history (Frappe HR "qualification" tables) ──
    education: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="[{degree, institute, year, grade}]"
    )
    work_experience: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="[{company, designation, from_date, to_date, notes}]"
    )
    skills: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="[{name, level: beginner|intermediate|expert}]"
    )
    languages: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="[{name, fluency: basic|conversational|fluent|native}]"
    )
    certifications: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="[{name, issued_by, issued_date, expiry_date}]"
    )

    # ── Dependents (OrangeHRM "Dependents") ───────────────────────
    dependents: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="[{name, relationship, date_of_birth}]"
    )

    # ── Compensation (snapshot — full history in salary_structures) ───
    current_salary: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(
        String(3), default="USD", server_default="USD"
    )
    compensation_items: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Recurring extra pay lines on top of the salary structure: "
        "[{id, name, kind: earning|deduction, calculation: fixed|percent_of_basic, "
        "amount, percentage, is_taxable}]. Picked up by every payroll run.",
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


# ── Status history (E-08) ───────────────────────────────────────────────────
class EmployeeStatusHistory(TenantModel):
    """One row each time an employee's employment status changes (hired,
    confirmed, put on notice, offboarded, rehired ...). The detail page shows
    these as a timeline."""

    __tablename__ = "employee_status_history"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="update", server_default="update",
        comment="created | update | offboard | import",
    )


# ── Contracts (E-07) ────────────────────────────────────────────────────────
CONTRACT_TYPES = ("permanent", "fixed_term", "probation", "internship", "consultant")
CONTRACT_STATUSES = ("active", "renewed", "terminated")


class EmployeeContract(TenantModel):
    """An employment contract: type, term, renewal alert and the signed file.

    `status` is what HR decided (active / renewed / terminated). Whether an
    active contract is *expiring* or *expired* is worked out from end_date,
    never stored, so it can't go stale."""

    __tablename__ = "employee_contracts"
    __table_args__ = (
        Index(
            "uq_employee_contracts_one_active", "employee_id",
            unique=True, postgresql_where=text("status = 'active' AND is_deleted = false"),
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_type: Mapped[str] = mapped_column(String(30), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, index=True, comment="NULL for a permanent contract"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active", index=True)
    renewal_alert_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee_documents.id", ondelete="SET NULL"), nullable=True,
        comment="The signed contract, uploaded under the employee's Documents",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_alerted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    renewed_from_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
