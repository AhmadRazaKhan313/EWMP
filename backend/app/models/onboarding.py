"""Onboarding / offer management models (N-01).

Flow: Offer -> (accepted) -> employee + onboarding case -> pre-boarding ->
day-1 / first-week tasks -> probation check-ins -> confirmation. An
*offboarding* case mirrors it with an exit checklist.

Status columns are plain strings validated in the services (not Postgres
enums), so adding a status later never needs an enum migration.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel

OFFER_STATUSES = (
    "draft", "pending_approval", "approved", "sent", "viewed",
    "accepted", "declined", "expired", "revoked", "revised",
)
CASE_STATUSES = ("pre_boarding", "active", "completed", "cancelled")
TASK_STATUSES = ("pending", "in_progress", "done", "skipped")
OWNER_ROLES = ("hr", "it", "manager", "employee")
TASK_PHASES = ("pre_boarding", "day_1", "first_week", "probation", "exit")
TASK_KINDS = ("manual", "document", "form", "acknowledge", "provision")


class OnboardingTemplate(TenantModel):
    __tablename__ = "onboarding_templates"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(15), default="onboarding", server_default="onboarding", index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    designation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("designations.id", ondelete="SET NULL"), nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class OnboardingTemplateTask(TenantModel):
    __tablename__ = "onboarding_template_tasks"

    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("onboarding_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_role: Mapped[str] = mapped_column(String(15), default="hr")
    phase: Mapped[str] = mapped_column(String(20), default="day_1")
    # Days relative to the anchor date (joining date / last working day).
    # Negative = before. e.g. -3 = three days before joining.
    due_offset_days: Mapped[int] = mapped_column(Integer, default=0)
    # `order` of another task in the same template that must be done first.
    depends_on_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    kind: Mapped[str] = mapped_column(String(15), default="manual", server_default="manual")
    # For kind="provision": which system area this task is about
    # (account | asset | device | shift | leave_policy | salary | access | ...).
    provision_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Offer(TenantModel):
    __tablename__ = "offers"

    applicant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("applicants.id", ondelete="SET NULL"), nullable=True, index=True)
    candidate_name: Mapped[str] = mapped_column(String(200), nullable=False)
    candidate_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    candidate_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    job_title: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    designation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("designations.id", ondelete="SET NULL"), nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("onboarding_templates.id", ondelete="SET NULL"), nullable=True)

    employment_type: Mapped[str] = mapped_column(String(30), default="full_time", server_default="full_time")
    job_nature: Mapped[str] = mapped_column(String(30), default="probationary", server_default="probationary")
    salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="PKR", server_default="PKR")
    pay_items: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    probation_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    parent_offer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("offers.id", ondelete="SET NULL"), nullable=True)

    # Ordered approver user ids, and the decisions recorded so far:
    # [{"user_id", "decision": "approved"|"rejected", "at", "note"}]
    approver_ids: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    approvals: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")

    # sha256 of the secure link token; the raw token is shown once at send time.
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    accepted_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted_user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)

    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class OnboardingCase(TenantModel):
    __tablename__ = "onboarding_cases"

    kind: Mapped[str] = mapped_column(String(15), default="onboarding", server_default="onboarding", index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    offer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("offers.id", ondelete="SET NULL"), nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("onboarding_templates.id", ondelete="SET NULL"), nullable=True)
    # Joining date for onboarding, last working day for offboarding.
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    buddy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="pre_boarding", server_default="pre_boarding", index=True)

    preboarding_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    preboarding_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preboarding_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preboarding_data: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    policy_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_onboarding_one_open_case",
            "employee_id", "kind",
            unique=True,
            postgresql_where=text("status IN ('pre_boarding','active') AND is_deleted = false"),
        ),
    )


class OnboardingCaseTask(TenantModel):
    __tablename__ = "onboarding_case_tasks"

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("onboarding_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    template_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("onboarding_template_tasks.id", ondelete="SET NULL"), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_role: Mapped[str] = mapped_column(String(15), default="hr")
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    phase: Mapped[str] = mapped_column(String(20), default="day_1")
    due_offset_days: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(15), default="pending", server_default="pending", index=True)
    depends_on_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("onboarding_case_tasks.id", ondelete="SET NULL"), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    kind: Mapped[str] = mapped_column(String(15), default="manual", server_default="manual")
    provision_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reminded_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    escalated_at: Mapped[date | None] = mapped_column(Date, nullable=True)


class OnboardingCaseDocument(TenantModel):
    __tablename__ = "onboarding_case_documents"

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("onboarding_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[str] = mapped_column(String(15), default="requested", server_default="requested")
    employee_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_documents.id", ondelete="SET NULL"), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
