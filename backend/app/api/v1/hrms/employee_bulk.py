"""Export / import / status-history endpoints, mounted under /employees."""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.employee import EmploymentStatus
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.services import employee_bulk
from app.services.employee import EmployeeService
from app.services.employee_history import list_history

router = APIRouter(tags=["Employee bulk"])

_CSV_HEADERS = {"Cache-Control": "no-store"}


@router.get("/export", summary="Download employees as CSV (same filters as the list)")
async def export_employees(
    query: str | None = Query(None),
    department_id: UUID | None = Query(None),
    branch_id: UUID | None = Query(None),
    team_id: UUID | None = Query(None),
    designation_id: UUID | None = Query(None),
    manager_id: UUID | None = Query(None),
    status: EmploymentStatus | None = Query(None),
    employment_type: str | None = Query(None),
    current_user: User = Depends(require_permission("employees.export")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    body = await employee_bulk.export_csv(
        db, tenant_id, EmployeeService(db, tenant_id),
        query=query, department_id=department_id, branch_id=branch_id, team_id=team_id,
        designation_id=designation_id, manager_id=manager_id, status=status, employment_type=employment_type,
    )
    return Response(
        body, media_type="text/csv; charset=utf-8",
        headers={**_CSV_HEADERS, "Content-Disposition": 'attachment; filename="employees.csv"'},
    )


@router.get("/import/template", summary="CSV template for bulk import")
async def import_template(
    current_user: User = Depends(require_permission("employees.create")),
) -> Response:
    return Response(
        employee_bulk.import_template_csv(), media_type="text/csv; charset=utf-8",
        headers={**_CSV_HEADERS, "Content-Disposition": 'attachment; filename="employee-import-template.csv"'},
    )


@router.post("/import", summary="Bulk-create employees from CSV (dry_run=true only validates)")
async def import_employees(
    file: UploadFile = File(...),
    dry_run: bool = Query(True),
    current_user: User = Depends(require_permission("employees.create")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    raw = await file.read(employee_bulk.MAX_IMPORT_BYTES + 1)
    return await employee_bulk.import_csv(db, tenant_id, current_user, raw, dry_run=dry_run)


@router.get("/{employee_id}/history", summary="Employment-status timeline")
async def employee_history(
    employee_id: UUID,
    current_user: User = Depends(require_permission("employees.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await EmployeeService(db, tenant_id).get_employee(employee_id)  # 404 for another tenant's id
    return await list_history(db, tenant_id, employee_id)
