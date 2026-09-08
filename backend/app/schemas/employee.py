"""
Employee API schemas.

Separate schemas for:
  - Create (all required fields for onboarding)
  - Update (all optional — partial updates)
  - Response (safe fields to return, never expose bank details in list view)
  - ListItem (minimal fields for table rows — fast to serialize)
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.employee import (
    EmploymentStatus,
    EmploymentType,
    Gender,
    JobNature,
    MaritalStatus,
)


# ── Create ────────────────────────────────────────────────────────────────────
class EmployeeCreateSchema(BaseModel):
    # Required — used to create the linked User account atomically.
    # If user_id is provided, that existing user is linked instead of creating
    # a new one (first_name/last_name/email are then ignored for User creation).
    user_id: UUID | None = None
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    date_of_joining: date
    employment_type: EmploymentType = EmploymentType.FULL_TIME

    # Required — Employment Status / Job Nature (permanent, probationary,
    # contractual, intern, part_time, temporary). Same "must be explicit,
    # not silently defaulted" reasoning as role_id below.
    job_nature: JobNature = JobNature.PROBATIONARY

    # Required — every employee must be assigned exactly one role at creation.
    # A role-less user has zero permissions and an unusable app (empty sidebar,
    # no attendance/leave), so role assignment is mandatory here rather than a
    # separate, forgettable step. The role must belong to the caller's
    # organization — validated in EmployeeService.create_employee.
    role_id: UUID

    model_config = {"extra": "ignore"}

    # Optional organizational
    department_id: UUID | None = None
    designation_id: UUID | None = None
    branch_id: UUID | None = None
    team_id: UUID | None = None
    manager_id: UUID | None = None
    default_shift_id: UUID | None = None

    # Optional personal
    date_of_birth: date | None = None
    gender: Gender | None = None
    phone: str | None = None
    work_location: str | None = None
    is_remote: bool = False

    # Compensation
    current_salary: Decimal | None = None
    currency: str = Field(default="USD", max_length=3)


# ── Update ────────────────────────────────────────────────────────────────────
class EmployeeUpdateSchema(BaseModel):
    # first_name/last_name live on the linked User, not on Employee.
    # The service layer splits these out and updates User separately —
    # they must NOT be passed straight into the Employee repo.update().
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    date_of_joining: date | None = None
    employment_type: EmploymentType | None = None
    employment_status: EmploymentStatus | None = None
    job_nature: JobNature | None = None

    # Role can now be changed from the Edit form too (previously assignable
    # only at creation). A single active role is assumed — same "exactly
    # one role" model used at creation — so an update replaces, rather than
    # adds to, the user's existing role set. See EmployeeService.update_employee.
    role_id: UUID | None = None

    department_id: UUID | None = None
    designation_id: UUID | None = None
    branch_id: UUID | None = None
    team_id: UUID | None = None
    manager_id: UUID | None = None
    default_shift_id: UUID | None = None

    date_of_birth: date | None = None
    gender: Gender | None = None
    marital_status: MaritalStatus | None = None
    nationality: str | None = None
    blood_group: str | None = None

    personal_email: EmailStr | None = None
    work_phone: str | None = None
    personal_phone: str | None = None
    address: dict | None = None

    national_id: str | None = None
    passport_number: str | None = None
    passport_expiry: date | None = None

    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_title: str | None = None

    emergency_contact: dict | None = None
    work_location: str | None = None
    is_remote: bool | None = None
    notice_period_days: int | None = None

    current_salary: Decimal | None = None
    currency: str | None = Field(None, max_length=3)
    custom_fields: dict | None = None

    model_config = {"extra": "ignore"}


# ── Response — list item (minimal, used in table rows) ───────────────────────
class EmployeeListItemSchema(BaseModel):
    id: UUID
    employee_code: str
    first_name: str
    last_name: str
    full_name: str
    avatar_url: str | None
    employment_status: EmploymentStatus
    employment_type: EmploymentType
    job_nature: JobNature
    date_of_joining: date
    department_id: UUID | None
    designation_id: UUID | None
    branch_id: UUID | None
    work_phone: str | None
    is_remote: bool
    years_of_service: float

    model_config = {"from_attributes": True}

    @classmethod
    def from_employee(cls, emp: "Employee") -> "EmployeeListItemSchema":  # type: ignore[name-defined]
        return cls(
            id=emp.id,
            employee_code=emp.employee_code,
            first_name=emp.user.first_name if emp.user else "",
            last_name=emp.user.last_name if emp.user else "",
            full_name=emp.user.full_name if emp.user else emp.employee_code,
            avatar_url=emp.user.avatar_url if emp.user else None,
            employment_status=emp.employment_status,
            employment_type=emp.employment_type,
            job_nature=emp.job_nature,
            date_of_joining=emp.date_of_joining,
            department_id=emp.department_id,
            designation_id=emp.designation_id,
            branch_id=emp.branch_id,
            work_phone=emp.work_phone,
            is_remote=emp.is_remote,
            years_of_service=emp.years_of_service,
        )


# ── Response — full detail ────────────────────────────────────────────────────
class EmployeeDetailSchema(BaseModel):
    id: UUID
    employee_code: str
    user_id: UUID

    first_name: str
    last_name: str
    full_name: str
    avatar_url: str | None
    email: str | None

    employment_status: EmploymentStatus
    employment_type: EmploymentType
    job_nature: JobNature
    date_of_joining: date
    date_of_confirmation: date | None
    probation_end_date: date | None
    notice_period_days: int
    date_of_leaving: date | None

    role_id: UUID | None
    department_id: UUID | None
    designation_id: UUID | None
    branch_id: UUID | None
    team_id: UUID | None
    manager_id: UUID | None

    date_of_birth: date | None
    gender: Gender | None
    marital_status: MaritalStatus | None
    nationality: str | None
    blood_group: str | None

    personal_email: str | None
    work_phone: str | None
    personal_phone: str | None
    address: dict | None

    national_id: str | None
    passport_number: str | None
    passport_expiry: date | None

    emergency_contact: dict | None
    work_location: str | None
    is_remote: bool

    current_salary: Decimal | None
    currency: str

    custom_fields: dict
    years_of_service: float

    model_config = {"from_attributes": True}


# ── Paginated list response ───────────────────────────────────────────────────
class EmployeeListResponse(BaseModel):
    items: list[EmployeeListItemSchema]
    total: int
    page: int
    page_size: int
    total_pages: int