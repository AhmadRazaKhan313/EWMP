"""Onboarding, offers, templates and tasks (N-01) — authenticated endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_any_permission, require_permission
from app.schemas.onboarding import (
    CaseCreate, CaseUpdate, ConfirmIn, DocumentRequestIn, DocumentReviewIn, OfferConvert, OfferCreate,
    OfferDecision, OfferSend, OfferUpdate, TaskUpdate, TemplateCreate, TemplateUpdate, WelcomeIn,
)
from app.services.onboarding import OnboardingService
from app.services.onboarding_offers import OfferService

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

_OFFER_NULLABLE = {"candidate_phone", "department_id", "designation_id", "branch_id", "manager_id",
                   "template_id", "probation_months", "salary", "pay_items", "body"}
_CASE_NULLABLE = {"manager_id", "buddy_id", "welcome_message"}
_TASK_NULLABLE = {"assignee_user_id", "notes", "due_date"}
_TEMPLATE_NULLABLE = {"description", "department_id", "designation_id", "branch_id"}


def _clean(data: dict, nullable: set[str]) -> dict:
    """Drop explicit nulls on fields that cannot be null."""
    return {k: v for k, v in data.items() if v is not None or k in nullable}


# ── dashboard ───────────────────────────────────────────────────────────────
@router.get("/dashboard", summary="Upcoming joiners, progress and bottlenecks")
async def dashboard(
    current_user: User = Depends(require_permission("onboarding.view")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).dashboard()


# ── offers ──────────────────────────────────────────────────────────────────
@router.get("/offers", summary="List offers")
async def list_offers(
    status_: str | None = Query(None, alias="status"), search: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(require_any_permission("offers.manage", "offers.approve")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OfferService(db, tenant_id).list(status=status_, search=search, page=page, page_size=page_size)


@router.post("/offers", status_code=status.HTTP_201_CREATED, summary="Create an offer (draft)")
async def create_offer(
    data: OfferCreate, current_user: User = Depends(require_permission("offers.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OfferService(db, tenant_id).create(data.model_dump(), current_user.id)


@router.get("/offers/{offer_id}", summary="Offer detail")
async def get_offer(
    offer_id: UUID, current_user: User = Depends(require_any_permission("offers.manage", "offers.approve")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OfferService(db, tenant_id).get(offer_id)


@router.patch("/offers/{offer_id}", summary="Edit a draft offer")
async def update_offer(
    offer_id: UUID, data: OfferUpdate, current_user: User = Depends(require_permission("offers.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OfferService(db, tenant_id).update(offer_id, _clean(data.model_dump(exclude_unset=True), _OFFER_NULLABLE))


@router.delete("/offers/{offer_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft offer")
async def delete_offer(
    offer_id: UUID, current_user: User = Depends(require_permission("offers.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> None:
    await OfferService(db, tenant_id).delete(offer_id)


@router.post("/offers/{offer_id}/submit", summary="Submit for approval (or approve straight away if no approvers)")
async def submit_offer(
    offer_id: UUID, current_user: User = Depends(require_permission("offers.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OfferService(db, tenant_id).submit(offer_id)


@router.post("/offers/{offer_id}/decision", summary="Approve or reject (next approver only)")
async def decide_offer(
    offer_id: UUID, data: OfferDecision, current_user: User = Depends(require_permission("offers.approve")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OfferService(db, tenant_id).decide(offer_id, current_user.id, data.decision, data.note)


@router.post("/offers/{offer_id}/send", summary="Send (or resend) the offer with a secure link")
async def send_offer(
    offer_id: UUID, data: OfferSend | None = None,
    current_user: User = Depends(require_permission("offers.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OfferService(db, tenant_id).send(offer_id, valid_days=data.valid_days if data else None)


@router.post("/offers/{offer_id}/revoke", summary="Withdraw an offer")
async def revoke_offer(
    offer_id: UUID, current_user: User = Depends(require_permission("offers.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OfferService(db, tenant_id).revoke(offer_id)


@router.post("/offers/{offer_id}/revise", summary="Negotiate: close this version and open a new draft")
async def revise_offer(
    offer_id: UUID, data: OfferUpdate, current_user: User = Depends(require_permission("offers.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OfferService(db, tenant_id).revise(
        offer_id, current_user.id, _clean(data.model_dump(exclude_unset=True), _OFFER_NULLABLE))


@router.post("/offers/{offer_id}/convert", summary="Accepted offer -> employee + onboarding case")
async def convert_offer(
    offer_id: UUID, data: OfferConvert,
    current_user: User = Depends(require_permission("offers.manage")),
    _can_create: User = Depends(require_permission("employees.create")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).convert_offer(
        offer_id, current_user, role_id=data.role_id, first_name=data.first_name, last_name=data.last_name,
        template_id=data.template_id, manager_id=data.manager_id, buddy_id=data.buddy_id)


# ── templates ───────────────────────────────────────────────────────────────
@router.get("/templates", summary="List templates")
async def list_templates(
    kind: str | None = Query(None, pattern="^(onboarding|offboarding)$"),
    current_user: User = Depends(require_permission("onboarding.view")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).list_templates(kind)


@router.post("/templates/defaults", summary="Add the ready-made onboarding + offboarding templates")
async def seed_templates(
    current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).seed_default_templates()


@router.post("/templates", status_code=status.HTTP_201_CREATED, summary="Create a template")
async def create_template(
    data: TemplateCreate, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).create_template(data.model_dump())


@router.get("/templates/{template_id}", summary="Template with its tasks")
async def get_template(
    template_id: UUID, current_user: User = Depends(require_permission("onboarding.view")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).get_template(template_id)


@router.patch("/templates/{template_id}", summary="Edit a template (tasks are replaced when sent)")
async def update_template(
    template_id: UUID, data: TemplateUpdate, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    payload = _clean(data.model_dump(exclude_unset=True), _TEMPLATE_NULLABLE)
    if data.tasks is not None:  # full task dicts, so every default is filled in
        payload["tasks"] = [t.model_dump() for t in data.tasks]
    return await OnboardingService(db, tenant_id).update_template(template_id, payload)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a template")
async def delete_template(
    template_id: UUID, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> None:
    await OnboardingService(db, tenant_id).delete_template(template_id)


# ── cases ───────────────────────────────────────────────────────────────────
@router.get("/cases", summary="List onboarding / offboarding cases")
async def list_cases(
    kind: str | None = Query(None, pattern="^(onboarding|offboarding)$"),
    status_: str | None = Query(None, alias="status"), search: str | None = Query(None, max_length=100),
    employee_id: UUID | None = None, overdue: bool = False,
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(require_permission("onboarding.view")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).list_cases(
        kind=kind, status=status_, search=search, employee_id=employee_id, overdue=overdue,
        page=page, page_size=page_size)


@router.post("/cases", status_code=status.HTTP_201_CREATED, summary="Start onboarding / offboarding for an employee")
async def create_case(
    data: CaseCreate, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).create_case(actor_id=current_user.id, **data.model_dump())


@router.get("/cases/{case_id}", summary="Case detail with tasks and documents")
async def get_case(
    case_id: UUID, current_user: User = Depends(require_permission("onboarding.view")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).get_case(case_id)


@router.patch("/cases/{case_id}", summary="Change manager, buddy, date or welcome text")
async def update_case(
    case_id: UUID, data: CaseUpdate, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).update_case(
        case_id, _clean(data.model_dump(exclude_unset=True), _CASE_NULLABLE))


@router.post("/cases/{case_id}/cancel", summary="Cancel a case")
async def cancel_case(
    case_id: UUID, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).cancel_case(case_id)


@router.post("/cases/{case_id}/welcome", summary="Send the welcome message")
async def send_welcome(
    case_id: UUID, data: WelcomeIn, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).send_welcome(case_id, data.message, current_user.id)


@router.post("/cases/{case_id}/confirm", summary="Confirm the employee after probation")
async def confirm_case(
    case_id: UUID, data: ConfirmIn, current_user: User = Depends(require_permission("onboarding.manage")),
    _can_update: User = Depends(require_permission("employees.update")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).confirm(case_id, current_user.id, data.confirmed_on, data.note)


@router.post("/cases/{case_id}/preboarding-link", summary="Issue a fresh pre-boarding link")
async def preboarding_link(
    case_id: UUID, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).issue_preboarding_link(case_id)


@router.post("/cases/{case_id}/documents", status_code=status.HTTP_201_CREATED, summary="Request another document")
async def request_document(
    case_id: UUID, data: DocumentRequestIn, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).add_document_request(
        case_id, data.document_type, data.title, data.is_required)


@router.post("/documents/{doc_id}/review", summary="Verify or reject an uploaded document")
async def review_document(
    doc_id: UUID, data: DocumentReviewIn, current_user: User = Depends(require_permission("onboarding.manage")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).review_document(doc_id, current_user.id, data.approve, data.reason)


# ── tasks ───────────────────────────────────────────────────────────────────
@router.get("/tasks/mine", summary="Tasks assigned to me")
async def my_tasks(
    include_done: bool = False,
    current_user: User = Depends(require_any_permission("onboarding.manage", "onboarding.view_own")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).my_tasks(current_user, include_done=include_done)


@router.patch("/tasks/{task_id}", summary="Update a task (assignee or HR)")
async def update_task(
    task_id: UUID, data: TaskUpdate,
    current_user: User = Depends(require_any_permission("onboarding.manage", "onboarding.view_own")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await OnboardingService(db, tenant_id).update_task(
        task_id, current_user, _clean(data.model_dump(exclude_unset=True), _TASK_NULLABLE))
