"""
Employee API schemas.

Separate schemas for:
  - Create (all required fields for onboarding)
  - Update (all optional — partial updates)
  - Response (safe fields to return, never expose bank details in list view)
  - ListItem (minimal fields for table rows — fast to serialize)
"""

import uuid as _uuid
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.employee import (
    EmploymentStatus,
    EmploymentType,
    Gender,
    JobNature,
    MaritalStatus,
)


# ── Repeating profile sections ───────────────────────────────────────────────
# These are stored as JSON lists on the employee row. Each entry is validated
# here and written back as plain JSON (amounts as strings), so nothing
# non-serialisable ever reaches the JSON column.
MAX_EMERGENCY_CONTACTS = 20
MAX_PAY_ITEMS = 50
MAX_HISTORY_ROWS = 30


class EmergencyContactIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    relationship: str | None = Field(None, max_length=50)
    phone: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=500)

    model_config = {"extra": "ignore"}


class EducationIn(BaseModel):
    degree: str = Field(..., min_length=1, max_length=150)
    institute: str | None = Field(None, max_length=200)
    year: str | None = Field(None, max_length=10)
    grade: str | None = Field(None, max_length=50)

    model_config = {"extra": "ignore"}


class WorkExperienceIn(BaseModel):
    company: str = Field(..., min_length=1, max_length=200)
    designation: str | None = Field(None, max_length=150)
    from_date: date | None = None
    to_date: date | None = None
    notes: str | None = Field(None, max_length=500)

    model_config = {"extra": "ignore"}


class DependentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    relationship: str | None = Field(None, max_length=50)
    date_of_birth: date | None = None

    model_config = {"extra": "ignore"}


class SkillIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    level: Literal["beginner", "intermediate", "expert"] | None = None

    model_config = {"extra": "ignore"}


class LanguageIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    fluency: Literal["basic", "conversational", "fluent", "native"] | None = None

    model_config = {"extra": "ignore"}


class CertificationIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    issued_by: str | None = Field(None, max_length=200)
    issued_date: date | None = None
    expiry_date: date | None = None

    model_config = {"extra": "ignore"}


class CompensationItemIn(BaseModel):
    """One recurring extra pay line (e.g. Medical, Fuel, Loan EMI, Tax adj.)."""

    id: str | None = Field(None, max_length=40)
    name: str = Field(..., min_length=1, max_length=100)
    kind: Literal["earning", "deduction"]
    calculation: Literal["fixed", "percent_of_basic"] = "fixed"
    amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    percentage: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=4)
    is_taxable: bool = True
    # recurring: applied in every payroll period that overlaps effective_from..effective_to
    # (either end may be open). one_time: applied only in the period containing effective_from.
    frequency: Literal["recurring", "one_time"] = "recurring"
    effective_from: date | None = None
    effective_to: date | None = None

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _check_dates(self):
        if self.frequency == "one_time":
            if self.effective_from is None:
                raise ValueError("A one-time pay item needs the date it applies on")
            self.effective_to = None
        elif self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be before effective_from")
        return self


def _normalise(model: type[BaseModel], rows: list | None, limit: int, label: str):
    if rows is None:
        return None
    if len(rows) > limit:
        raise ValueError(f"At most {limit} {label} are allowed")
    out = []
    for row in rows:
        item = model.model_validate(row)
        dumped = item.model_dump(mode="json")
        if isinstance(item, CompensationItemIn):
            # Keep the unused figure at zero so what is stored matches what
            # payroll will actually use.
            if item.calculation == "fixed":
                dumped["percentage"] = "0"
            else:
                dumped["amount"] = "0"
            dumped["id"] = item.id or _uuid.uuid4().hex[:12]
        out.append(dumped)
    return out


class _ProfileSectionsMixin(BaseModel):
    """Validators shared by the create and update schemas."""

    @field_validator("emergency_contacts", check_fields=False)
    @classmethod
    def _v_contacts(cls, v):
        return _normalise(EmergencyContactIn, v, MAX_EMERGENCY_CONTACTS, "emergency contacts")

    @field_validator("education", check_fields=False)
    @classmethod
    def _v_education(cls, v):
        return _normalise(EducationIn, v, MAX_HISTORY_ROWS, "education rows")

    @field_validator("work_experience", check_fields=False)
    @classmethod
    def _v_experience(cls, v):
        return _normalise(WorkExperienceIn, v, MAX_HISTORY_ROWS, "work experience rows")

    @field_validator("dependents", check_fields=False)
    @classmethod
    def _v_dependents(cls, v):
        return _normalise(DependentIn, v, MAX_HISTORY_ROWS, "dependents")

    @field_validator("skills", check_fields=False)
    @classmethod
    def _v_skills(cls, v):
        return _normalise(SkillIn, v, 60, "skills")

    @field_validator("languages", check_fields=False)
    @classmethod
    def _v_languages(cls, v):
        return _normalise(LanguageIn, v, 30, "languages")

    @field_validator("certifications", check_fields=False)
    @classmethod
    def _v_certifications(cls, v):
        return _normalise(CertificationIn, v, MAX_HISTORY_ROWS, "certifications")

    @field_validator("compensation_items", check_fields=False)
    @classmethod
    def _v_items(cls, v):
        return _normalise(CompensationItemIn, v, MAX_PAY_ITEMS, "pay items")


# Fields accepted by BOTH create and update (so "Add" saves exactly what "Edit"
# does — create used to drop nationality, blood group and the emergency contact
# silently). Declared once and attached to each schema below.
class _ProfileFields(_ProfileSectionsMixin):
    marital_status: MaritalStatus | None = None
    nationality: str | None = Field(None, max_length=100)
    blood_group: str | None = Field(None, max_length=5)
    father_name: str | None = Field(None, max_length=150)
    mother_name: str | None = Field(None, max_length=150)
    spouse_name: str | None = Field(None, max_length=150)

    personal_email: EmailStr | None = None
    personal_phone: str | None = Field(None, max_length=50)
    address: dict | None = None
    permanent_address: dict | None = None

    national_id: str | None = Field(None, max_length=50)
    passport_number: str | None = Field(None, max_length=50)
    passport_expiry: date | None = None
    driving_license_number: str | None = Field(None, max_length=50)
    driving_license_expiry: date | None = None
    national_id_type: str | None = Field(None, max_length=30)
    tax_number: str | None = Field(None, max_length=50)
    social_security_number: str | None = Field(None, max_length=50)
    provident_fund_number: str | None = Field(None, max_length=50)
    visa_number: str | None = Field(None, max_length=50)
    visa_expiry: date | None = None

    religion: str | None = Field(None, max_length=50)
    place_of_birth: str | None = Field(None, max_length=100)
    home_phone: str | None = Field(None, max_length=50)
    previous_employee_id: str | None = Field(None, max_length=50)
    referral_source: str | None = Field(None, max_length=100)
    hobbies: str | None = Field(None, max_length=2000)
    tshirt_size: str | None = Field(None, max_length=5)
    social_links: dict[str, str] | None = None

    # Employment details the form now exposes (they existed on the model but
    # could not be set from the API on create).
    date_of_confirmation: date | None = None
    probation_end_date: date | None = None
    notice_period_days: int | None = Field(None, ge=0, le=365)

    bank_name: str | None = Field(None, max_length=100)
    bank_account_title: str | None = Field(None, max_length=100)
    bank_account_number: str | None = Field(None, max_length=50)
    bank_iban: str | None = Field(None, max_length=34)

    health_insurance_provider: str | None = Field(None, max_length=150)
    health_insurance_number: str | None = Field(None, max_length=80)

    emergency_contacts: list[dict] | None = None
    education: list[dict] | None = None
    work_experience: list[dict] | None = None
    dependents: list[dict] | None = None
    skills: list[dict] | None = None
    languages: list[dict] | None = None
    certifications: list[dict] | None = None
    compensation_items: list[dict] | None = None


# ── Create ────────────────────────────────────────────────────────────────────
class EmployeeCreateSchema(_ProfileFields):
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
class EmployeeUpdateSchema(_ProfileFields):
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
    work_phone: str | None = None
    emergency_contact: dict | None = None
    work_location: str | None = None
    is_remote: bool | None = None

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