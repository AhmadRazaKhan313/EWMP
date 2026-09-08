"""Designations API endpoints."""
import uuid
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ConflictError
from app.models.organization_structure import Designation
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission

router = APIRouter(prefix="/designations", tags=["Designations"])


class DesignationCreate(BaseModel):
    name: str
    code: str = ""
    level: int = 1
    description: str = ""
    department_id: uuid.UUID | None = None


class DesignationUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    level: int | None = None
    description: str | None = None
    is_active: bool | None = None


@router.get("")
async def list_designations(
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = (await db.execute(select(Designation).where(Designation.tenant_id == tenant_id, Designation.is_deleted == False).order_by(Designation.level, Designation.name))).scalars().all()
    return {"items": [{"id": str(d.id), "name": d.name, "code": d.code,
                       "description": d.description, "level": d.level,
                       "department_id": str(d.department_id) if d.department_id else None,
                       "is_active": d.is_active} for d in items], "total": len(items)}

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_designation(
    body: DesignationCreate,
    current_user: User = Depends(require_permission("designations.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    desig = Designation(tenant_id=tenant_id, name=body.name, code=body.code or None,
                        level=body.level, description=body.description or None,
                        department_id=body.department_id, is_active=True)
    db.add(desig)
    await db.flush()
    return {"id": str(desig.id), "name": desig.name, "created": True}

@router.patch("/{desig_id}")
async def update_designation(
    desig_id: uuid.UUID,
    body: DesignationUpdate,
    current_user: User = Depends(require_permission("designations.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Designation).where(Designation.id == desig_id, Designation.tenant_id == tenant_id))
    desig = result.scalar_one_or_none()
    if not desig:
        raise NotFoundError("Designation not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(desig, field, val)
    await db.flush()
    return {"id": str(desig.id), "updated": True}

@router.delete("/{desig_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_designation(
    desig_id: uuid.UUID,
    current_user: User = Depends(require_permission("designations.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Designation).where(Designation.id == desig_id, Designation.tenant_id == tenant_id))
    desig = result.scalar_one_or_none()
    if not desig:
        raise NotFoundError("Designation not found")

    from app.models.employee import Employee
    active_count = (
        await db.execute(
            select(func.count()).select_from(Employee).where(
                Employee.designation_id == desig_id,
                Employee.tenant_id == tenant_id,
                Employee.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one()
    if active_count > 0:
        raise ConflictError(
            f"Cannot delete this designation — {active_count} employee(s) are still "
            "assigned to it. Reassign them first."
        )

    desig.soft_delete()
    await db.flush()
