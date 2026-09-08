"""Asset Management API endpoints."""
import uuid
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.devices import Asset, AssetAssignment, AssetStatus
from app.models.user import User
from app.permissions.dependencies import get_current_user, get_tenant_id, require_permission
from datetime import datetime, UTC

router = APIRouter(prefix="/assets", tags=["Assets"])


class AssetCreate(BaseModel):
    name: str
    asset_tag: str
    category: str
    brand: str = ""
    model: str = ""
    serial_number: str = ""
    purchase_cost: float | None = None
    purchase_date: str | None = None
    warranty_expiry: str | None = None
    location: str = ""
    vendor: str = ""


class AssetUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    location: str | None = None
    brand: str | None = None
    model: str | None = None
    warranty_expiry: str | None = None


class AssignAssetRequest(BaseModel):
    employee_id: uuid.UUID
    notes: str = ""


class ReturnAssetRequest(BaseModel):
    condition: str = "good"
    notes: str = ""


@router.get("")
async def list_assets(
    asset_status: str | None = Query(None, alias="status"),
    category: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("assets.view")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = [Asset.tenant_id == tenant_id, Asset.is_deleted == False]
    if asset_status:
        filters.append(Asset.status == asset_status)
    if category:
        filters.append(Asset.category == category)
    offset = (page - 1) * page_size
    stmt = select(Asset).where(*filters).order_by(Asset.created_at.desc()).offset(offset).limit(page_size)
    count_stmt = select(func.count()).select_from(Asset).where(*filters)
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "items": [{"id": str(a.id), "name": a.name, "asset_tag": a.asset_tag,
                   "category": a.category, "sub_category": a.sub_category,
                   "brand": a.brand, "model": a.model, "serial_number": a.serial_number,
                   "status": a.status.value, "location": a.location,
                   "purchase_cost": str(a.purchase_cost) if a.purchase_cost else None,
                   "purchase_date": str(a.purchase_date) if a.purchase_date else None,
                   "warranty_expiry": str(a.warranty_expiry) if a.warranty_expiry else None,
                   "vendor": a.vendor,
                   "assigned_employee_id": str(a.assigned_employee_id) if a.assigned_employee_id else None,
                   "created_at": a.created_at.isoformat()} for a in items],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
    }

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_asset(
    body: AssetCreate,
    current_user: User = Depends(require_permission("assets.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import date as ddate
    asset = Asset(
        tenant_id=tenant_id, name=body.name, asset_tag=body.asset_tag.upper(),
        category=body.category, brand=body.brand or None, model=body.model or None,
        serial_number=body.serial_number or None,
        purchase_cost=body.purchase_cost, vendor=body.vendor or None,
        purchase_date=ddate.fromisoformat(body.purchase_date) if body.purchase_date else None,
        warranty_expiry=ddate.fromisoformat(body.warranty_expiry) if body.warranty_expiry else None,
        location=body.location or None, status=AssetStatus.AVAILABLE,
    )
    db.add(asset)
    await db.flush()
    return {"id": str(asset.id), "asset_tag": asset.asset_tag, "created": True}

@router.patch("/{asset_id}")
async def update_asset(
    asset_id: uuid.UUID,
    body: AssetUpdate,
    current_user: User = Depends(require_permission("assets.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Asset).where(Asset.id == asset_id, Asset.tenant_id == tenant_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError("Asset not found")
    data = body.model_dump(exclude_unset=True)
    warranty_expiry = data.pop("warranty_expiry", None)
    for field, val in data.items():
        setattr(asset, field, val)
    if warranty_expiry:
        from datetime import date as ddate
        asset.warranty_expiry = ddate.fromisoformat(warranty_expiry)
    await db.flush()
    return {"id": str(asset.id), "updated": True}

@router.post("/{asset_id}/assign")
async def assign_asset(
    asset_id: uuid.UUID,
    body: AssignAssetRequest,
    current_user: User = Depends(require_permission("assets.assign")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Asset).where(Asset.id == asset_id, Asset.tenant_id == tenant_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError("Asset not found")

    # H8: the target employee must belong to this tenant too — otherwise an
    # org owner could assign their asset to another org's employee_id
    # (assign_device already validates this; assign_asset didn't).
    from app.models.employee import Employee
    employee = (
        await db.execute(
            select(Employee).where(Employee.id == body.employee_id, Employee.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not employee:
        raise NotFoundError("Employee not found")

    # H9: close any still-open assignment before opening a new one. Without
    # this, reassigning an already-assigned asset directly (skipping
    # /return) leaves two AssetAssignment rows with returned_at IS NULL,
    # making assignment history ambiguous.
    open_assignment = (
        await db.execute(
            select(AssetAssignment)
            .where(AssetAssignment.asset_id == asset_id, AssetAssignment.returned_at == None)  # noqa: E711
            .order_by(AssetAssignment.assigned_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_assignment is not None:
        open_assignment.returned_at = datetime.now(UTC)
        open_assignment.return_condition = "reassigned"

    asset.status = AssetStatus.ASSIGNED
    asset.assigned_employee_id = employee.id
    asset.assigned_at = datetime.now(UTC)
    assignment = AssetAssignment(
        tenant_id=tenant_id, asset_id=asset_id,
        employee_id=employee.id, assigned_at=datetime.now(UTC),
        assigned_by_id=current_user.id, notes=body.notes or None,
    )
    db.add(assignment)
    await db.flush()
    return {"message": "Asset assigned", "asset_id": str(asset_id)}

@router.post("/{asset_id}/return")
async def return_asset(
    asset_id: uuid.UUID,
    body: ReturnAssetRequest,
    current_user: User = Depends(require_permission("assets.assign")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Asset).where(Asset.id == asset_id, Asset.tenant_id == tenant_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError("Asset not found")
    asset.status = AssetStatus.AVAILABLE
    asset.assigned_employee_id = None
    asset.assigned_at = None
    # Update latest assignment
    assign_result = await db.execute(
        select(AssetAssignment)
        .where(AssetAssignment.asset_id == asset_id, AssetAssignment.returned_at == None)
        .order_by(AssetAssignment.assigned_at.desc())
        .limit(1)
    )
    assignment = assign_result.scalar_one_or_none()
    if assignment:
        assignment.returned_at = datetime.now(UTC)
        assignment.return_condition = body.condition
        assignment.notes = body.notes or assignment.notes
    await db.flush()
    return {"message": "Asset returned"}

@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: uuid.UUID,
    current_user: User = Depends(require_permission("assets.manage")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Asset).where(Asset.id == asset_id, Asset.tenant_id == tenant_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError("Asset not found")
    asset.soft_delete()
    await db.flush()