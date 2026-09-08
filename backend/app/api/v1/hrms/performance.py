"""Performance Management API."""
import uuid
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.performance import Goal, PerformanceReview, GoalStatus, ReviewStatus
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from datetime import datetime, UTC

router = APIRouter(prefix="/performance", tags=["Performance"])


class GoalCreate(BaseModel):
    employee_id: uuid.UUID
    title: str
    description: str = ""
    category: str = ""
    start_date: str | None = None
    due_date: str | None = None
    weight: int = 1


class GoalUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    progress_percent: int | None = None
    description: str | None = None


class ReviewCreate(BaseModel):
    employee_id: uuid.UUID
    reviewer_id: uuid.UUID
    review_period: str
    review_year: int
    strengths: str = ""
    improvements: str = ""
    overall_rating: float | None = None


# ── Goals ─────────────────────────────────────────────────────────────────────
@router.get("/goals")
async def list_goals(
    employee_id: uuid.UUID | None = Query(None),
    goal_status: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("performance.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [Goal.tenant_id == tenant_id, Goal.is_deleted == False]
    if employee_id:
        filters.append(Goal.employee_id == employee_id)
    if goal_status:
        filters.append(Goal.status == goal_status)
    offset = (page - 1) * page_size
    stmt = select(Goal).where(*filters).order_by(Goal.due_date.asc().nulls_last()).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(Goal).where(*filters)
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "items": [{"id": str(g.id), "employee_id": str(g.employee_id),
                   "title": g.title, "description": g.description,
                   "status": g.status.value, "progress_percent": g.progress_percent,
                   "start_date": str(g.start_date) if g.start_date else None,
                   "due_date": str(g.due_date) if g.due_date else None,
                   "category": g.category, "weight": g.weight,
                   "key_results": g.key_results,
                   "created_at": g.created_at.isoformat()} for g in items],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }

@router.post("/goals", status_code=status.HTTP_201_CREATED)
async def create_goal(
    body: GoalCreate,
    current_user: User = Depends(require_permission("performance.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import date as ddate
    goal = Goal(
        tenant_id=tenant_id, employee_id=body.employee_id, title=body.title,
        description=body.description or None, category=body.category or None,
        start_date=ddate.fromisoformat(body.start_date) if body.start_date else None,
        due_date=ddate.fromisoformat(body.due_date) if body.due_date else None,
        weight=body.weight, status=GoalStatus.NOT_STARTED, progress_percent=0,
        created_by_id=current_user.id,
    )
    db.add(goal)
    await db.flush()
    return {"id": str(goal.id), "title": goal.title, "created": True}

@router.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: uuid.UUID,
    body: GoalUpdate,
    current_user: User = Depends(require_permission("performance.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.tenant_id == tenant_id))
    goal = result.scalar_one_or_none()
    if not goal:
        raise NotFoundError("Goal not found")
    if body.title: goal.title = body.title
    if body.status: goal.status = body.status
    if body.progress_percent is not None: goal.progress_percent = min(100, max(0, body.progress_percent))
    if body.description: goal.description = body.description
    await db.flush()
    return {"id": str(goal.id), "updated": True}

@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: uuid.UUID,
    current_user: User = Depends(require_permission("performance.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.tenant_id == tenant_id))
    goal = result.scalar_one_or_none()
    if not goal:
        raise NotFoundError("Goal not found")
    goal.soft_delete()
    await db.flush()

# ── Reviews ───────────────────────────────────────────────────────────────────
@router.get("/reviews")
async def list_reviews(
    employee_id: uuid.UUID | None = Query(None),
    review_year: int | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("performance.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [PerformanceReview.tenant_id == tenant_id, PerformanceReview.is_deleted == False]
    if employee_id:
        filters.append(PerformanceReview.employee_id == employee_id)
    if review_year:
        filters.append(PerformanceReview.review_year == review_year)
    offset = (page - 1) * page_size
    stmt = select(PerformanceReview).where(*filters).order_by(PerformanceReview.created_at.desc()).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(PerformanceReview).where(*filters)
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "items": [{"id": str(r.id), "employee_id": str(r.employee_id),
                   "reviewer_id": str(r.reviewer_id),
                   "review_period": r.review_period, "review_year": r.review_year,
                   "status": r.status.value, "overall_rating": str(r.overall_rating) if r.overall_rating else None,
                   "strengths": r.strengths, "improvements": r.improvements,
                   "created_at": r.created_at.isoformat()} for r in items],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }

@router.post("/reviews", status_code=status.HTTP_201_CREATED)
async def create_review(
    body: ReviewCreate,
    current_user: User = Depends(require_permission("performance.review")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    review = PerformanceReview(
        tenant_id=tenant_id, employee_id=body.employee_id, reviewer_id=body.reviewer_id,
        review_period=body.review_period, review_year=body.review_year,
        strengths=body.strengths or None, improvements=body.improvements or None,
        overall_rating=body.overall_rating, status=ReviewStatus.DRAFT,
    )
    db.add(review)
    await db.flush()
    return {"id": str(review.id), "created": True}
