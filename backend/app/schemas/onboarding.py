from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class OfferCreate(BaseModel):
    applicant_id: UUID | None = None
    candidate_name: str = Field(..., min_length=2, max_length=200)
    candidate_email: EmailStr
    candidate_phone: str | None = Field(None, max_length=50)
    job_title: str = Field(..., min_length=2, max_length=200)
    department_id: UUID | None = None
    designation_id: UUID | None = None
    branch_id: UUID | None = None
    manager_id: UUID | None = None
    template_id: UUID | None = None
    employment_type: str = Field("full_time", max_length=30)
    job_nature: str = Field("probationary", max_length=30)
    salary: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    currency: str = Field("PKR", min_length=3, max_length=3)
    pay_items: list[dict] = Field(default_factory=list, max_length=30)
    joining_date: date
    probation_months: int | None = Field(None, ge=0, le=24)
    approver_ids: list[UUID] = Field(default_factory=list, max_length=5)
    body: str | None = Field(None, max_length=10000)


class OfferUpdate(BaseModel):
    candidate_name: str | None = Field(None, min_length=2, max_length=200)
    candidate_email: EmailStr | None = None
    candidate_phone: str | None = Field(None, max_length=50)
    job_title: str | None = Field(None, min_length=2, max_length=200)
    department_id: UUID | None = None
    designation_id: UUID | None = None
    branch_id: UUID | None = None
    manager_id: UUID | None = None
    template_id: UUID | None = None
    employment_type: str | None = Field(None, max_length=30)
    job_nature: str | None = Field(None, max_length=30)
    salary: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(None, min_length=3, max_length=3)
    pay_items: list[dict] | None = Field(None, max_length=30)
    joining_date: date | None = None
    probation_months: int | None = Field(None, ge=0, le=24)
    approver_ids: list[UUID] | None = Field(None, max_length=5)
    body: str | None = Field(None, max_length=10000)


class OfferDecision(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    note: str | None = Field(None, max_length=500)


class OfferSend(BaseModel):
    valid_days: int | None = Field(None, ge=1, le=60)


class OfferConvert(BaseModel):
    role_id: UUID
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    template_id: UUID | None = None
    manager_id: UUID | None = None
    buddy_id: UUID | None = None


class PublicAccept(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=200)
    agree: bool


class PublicDecline(BaseModel):
    reason: str | None = Field(None, max_length=1000)


class TemplateTaskIn(BaseModel):
    order: int = Field(..., ge=0, le=999)
    title: str = Field(..., min_length=2, max_length=200)
    description: str | None = Field(None, max_length=2000)
    owner_role: str = "hr"
    phase: str = "day_1"
    due_offset_days: int = Field(0, ge=-120, le=730)
    depends_on_order: int | None = None
    is_required: bool = True
    kind: str = "manual"
    provision_key: str | None = Field(None, max_length=40)
    link_url: str | None = Field(None, max_length=300)


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    description: str | None = Field(None, max_length=1000)
    kind: str = "onboarding"
    department_id: UUID | None = None
    designation_id: UUID | None = None
    branch_id: UUID | None = None
    is_active: bool = True
    is_default: bool = False
    tasks: list[TemplateTaskIn] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=150)
    description: str | None = Field(None, max_length=1000)
    department_id: UUID | None = None
    designation_id: UUID | None = None
    branch_id: UUID | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    tasks: list[TemplateTaskIn] | None = None


class CaseCreate(BaseModel):
    employee_id: UUID
    kind: str = "onboarding"
    template_id: UUID | None = None
    anchor_date: date | None = None
    manager_id: UUID | None = None
    buddy_id: UUID | None = None
    welcome_message: str | None = Field(None, max_length=2000)


class CaseUpdate(BaseModel):
    manager_id: UUID | None = None
    buddy_id: UUID | None = None
    anchor_date: date | None = None
    welcome_message: str | None = Field(None, max_length=2000)


class TaskUpdate(BaseModel):
    status: str | None = None
    notes: str | None = Field(None, max_length=2000)
    assignee_user_id: UUID | None = None
    due_date: date | None = None


class WelcomeIn(BaseModel):
    message: str | None = Field(None, max_length=2000)


class ConfirmIn(BaseModel):
    confirmed_on: date | None = None
    note: str | None = Field(None, max_length=500)


class DocumentRequestIn(BaseModel):
    document_type: str = Field(..., max_length=40)
    title: str = Field(..., min_length=2, max_length=200)
    is_required: bool = True


class DocumentReviewIn(BaseModel):
    approve: bool
    reason: str | None = Field(None, max_length=300)


class EmergencyContactIn(BaseModel):
    name: str = Field(..., max_length=100)
    phone: str = Field(..., max_length=30)
    relationship: str | None = Field(None, max_length=50)


class PreboardingSave(BaseModel):
    form: dict = Field(default_factory=dict)
    submit: bool = False
    acknowledge_policy: bool = False
