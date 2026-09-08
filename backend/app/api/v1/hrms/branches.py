"""Branches API endpoints."""
import uuid
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ConflictError
from app.models.organization_structure import Branch
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission

router = APIRouter(prefix="/branches", tags=["Branches"])


class BranchCreate(BaseModel):
    name: str
    code: str = ""
    city: str = ""
    country: str = ""
    is_headquarters: bool = False
    timezone: str = "UTC"
    address_line1: str = ""
    phone: str = ""
    email: str = ""
    # Needed for geo-fenced attendance check-in — previously there was no
    # way to set these at all, so geofence check-in could never work.
    latitude: float | None = None
    longitude: float | None = None
    geo_fence_radius_meters: int | None = None


class BranchUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    city: str | None = None
    country: str | None = None
    is_headquarters: bool | None = None
    is_active: bool | None = None
    timezone: str | None = None
    phone: str | None = None
    email: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geo_fence_radius_meters: int | None = None


@router.get("", summary="List all branches")
async def list_branches(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [Branch.tenant_id == tenant_id, Branch.is_deleted == False]
    stmt = select(Branch).where(*filters).order_by(Branch.is_headquarters.desc(), Branch.name)
    items = (await db.execute(stmt)).scalars().all()
    total = len(items)
    return {
        "items": [{"id": str(b.id), "name": b.name, "code": b.code, "is_headquarters": b.is_headquarters,
                   "city": b.city, "country": b.country, "phone": b.phone, "email": b.email,
                   "timezone": b.timezone, "is_active": b.is_active,
                   "address_line1": b.address_line1, "address_line2": b.address_line2,
                   "state": b.state, "postal_code": b.postal_code,
                   "latitude": b.latitude, "longitude": b.longitude,
                   "geo_fence_radius_meters": b.geo_fence_radius_meters} for b in items],
        "total": total,
    }

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_branch(
    body: BranchCreate,
    current_user: User = Depends(require_permission("branches.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    branch = Branch(tenant_id=tenant_id, name=body.name, code=body.code or None,
                    city=body.city or None, country=body.country or None,
                    is_headquarters=body.is_headquarters, timezone=body.timezone,
                    address_line1=body.address_line1 or None,
                    phone=body.phone or None, email=body.email or None, is_active=True,
                    latitude=body.latitude, longitude=body.longitude,
                    geo_fence_radius_meters=body.geo_fence_radius_meters or 150)
    db.add(branch)
    await db.flush()
    return {"id": str(branch.id), "name": branch.name, "created": True}

@router.patch("/{branch_id}")
async def update_branch(
    branch_id: uuid.UUID,
    body: BranchUpdate,
    current_user: User = Depends(require_permission("branches.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Branch).where(Branch.id == branch_id, Branch.tenant_id == tenant_id))
    branch = result.scalar_one_or_none()
    if not branch:
        raise NotFoundError("Branch not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(branch, field, val)
    await db.flush()
    return {"id": str(branch.id), "updated": True}

@router.delete("/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_branch(
    branch_id: uuid.UUID,
    current_user: User = Depends(require_permission("branches.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Branch).where(Branch.id == branch_id, Branch.tenant_id == tenant_id))
    branch = result.scalar_one_or_none()
    if not branch:
        raise NotFoundError("Branch not found")

    from app.models.employee import Employee
    active_count = (
        await db.execute(
            select(func.count()).select_from(Employee).where(
                Employee.branch_id == branch_id,
                Employee.tenant_id == tenant_id,
                Employee.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one()
    if active_count > 0:
        raise ConflictError(
            f"Cannot delete this branch — {active_count} employee(s) are still "
            "assigned to it. Reassign them first."
        )

    branch.soft_delete()
    await db.flush()
