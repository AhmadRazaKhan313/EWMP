"""Recruitment API endpoints."""
import uuid
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.recruitment import JobPosting, Applicant, JobStatus, ApplicantStatus
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission

router = APIRouter(prefix="/recruitment", tags=["Recruitment"])


class JobCreate(BaseModel):
    title: str
    employment_type: str = "full_time"
    description: str = ""
    requirements: str = ""
    location: str = ""
    is_remote: bool = False
    openings: int = 1
    deadline: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str = "USD"
    department_id: uuid.UUID | None = None


class JobUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    description: str | None = None
    openings: int | None = None


class ApplicantCreate(BaseModel):
    job_posting_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: str = ""
    source: str = ""
    experience_years: float | None = None
    expected_salary: float | None = None
    cover_letter: str = ""


class ApplicantStageUpdate(BaseModel):
    status: str
    stage: str = ""
    notes: str = ""


# ── Job Postings ──────────────────────────────────────────────────────────────
@router.get("/jobs")
async def list_jobs(
    job_status: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("recruitment.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [JobPosting.tenant_id == tenant_id, JobPosting.is_deleted == False]
    if job_status:
        filters.append(JobPosting.status == job_status)
    offset = (page - 1) * page_size
    stmt = select(JobPosting).where(*filters).order_by(JobPosting.created_at.desc()).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(JobPosting).where(*filters)
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "items": [{"id": str(j.id), "title": j.title, "code": j.code,
                   "department_id": str(j.department_id) if j.department_id else None,
                   "employment_type": j.employment_type, "location": j.location,
                   "is_remote": j.is_remote, "status": j.status.value, "openings": j.openings,
                   "deadline": str(j.deadline) if j.deadline else None,
                   "salary_min": j.salary_min, "salary_max": j.salary_max,
                   "currency": j.currency, "skills_required": j.skills_required,
                   "created_at": j.created_at.isoformat()} for j in items],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }

@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreate,
    current_user: User = Depends(require_permission("recruitment.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import date as ddate
    job = JobPosting(
        tenant_id=tenant_id, title=body.title, employment_type=body.employment_type,
        description=body.description or None, requirements=body.requirements or None,
        location=body.location or None, is_remote=body.is_remote, openings=body.openings,
        deadline=ddate.fromisoformat(body.deadline) if body.deadline else None,
        salary_min=body.salary_min, salary_max=body.salary_max, currency=body.currency,
        department_id=body.department_id, status=JobStatus.OPEN,
        created_by_id=current_user.id,
    )
    db.add(job)
    await db.flush()
    return {"id": str(job.id), "title": job.title, "created": True}

@router.patch("/jobs/{job_id}")
async def update_job(
    job_id: uuid.UUID,
    body: JobUpdate,
    current_user: User = Depends(require_permission("recruitment.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(JobPosting).where(JobPosting.id == job_id, JobPosting.tenant_id == tenant_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Job posting not found")
    if body.title: job.title = body.title
    if body.status: job.status = body.status
    if body.description: job.description = body.description
    if body.openings: job.openings = body.openings
    await db.flush()
    return {"id": str(job.id), "updated": True}

@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: uuid.UUID,
    current_user: User = Depends(require_permission("recruitment.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(JobPosting).where(JobPosting.id == job_id, JobPosting.tenant_id == tenant_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Job not found")
    job.soft_delete()
    await db.flush()

# ── Applicants ────────────────────────────────────────────────────────────────
@router.get("/applicants")
async def list_applicants(
    job_id: uuid.UUID | None = Query(None),
    applicant_status: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("recruitment.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [Applicant.tenant_id == tenant_id, Applicant.is_deleted == False]
    if job_id:
        filters.append(Applicant.job_posting_id == job_id)
    if applicant_status:
        filters.append(Applicant.status == applicant_status)
    offset = (page - 1) * page_size
    stmt = select(Applicant).where(*filters).order_by(Applicant.created_at.desc()).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(Applicant).where(*filters)
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "items": [{"id": str(a.id), "job_posting_id": str(a.job_posting_id),
                   "first_name": a.first_name, "last_name": a.last_name,
                   "full_name": f"{a.first_name} {a.last_name}",
                   "email": a.email, "phone": a.phone,
                   "status": a.status.value, "current_stage": a.current_stage,
                   "source": a.source, "rating": a.rating,
                   "experience_years": a.experience_years,
                   "expected_salary": a.expected_salary,
                   "created_at": a.created_at.isoformat()} for a in items],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }

@router.post("/applicants", status_code=status.HTTP_201_CREATED)
async def add_applicant(
    body: ApplicantCreate,
    current_user: User = Depends(require_permission("recruitment.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    applicant = Applicant(
        tenant_id=tenant_id, job_posting_id=body.job_posting_id,
        first_name=body.first_name, last_name=body.last_name, email=body.email,
        phone=body.phone or None, source=body.source or None,
        experience_years=body.experience_years, expected_salary=body.expected_salary,
        cover_letter=body.cover_letter or None, status=ApplicantStatus.APPLIED,
        current_stage="Applied",
    )
    db.add(applicant)
    await db.flush()
    return {"id": str(applicant.id), "created": True}

@router.patch("/applicants/{applicant_id}/stage")
async def update_applicant_stage(
    applicant_id: uuid.UUID,
    body: ApplicantStageUpdate,
    current_user: User = Depends(require_permission("recruitment.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Applicant).where(Applicant.id == applicant_id, Applicant.tenant_id == tenant_id))
    applicant = result.scalar_one_or_none()
    if not applicant:
        raise NotFoundError("Applicant not found")
    applicant.status = body.status
    if body.stage:
        applicant.current_stage = body.stage
    if body.notes:
        applicant.notes = body.notes
    await db.flush()
    return {"id": str(applicant.id), "status": body.status, "updated": True}
