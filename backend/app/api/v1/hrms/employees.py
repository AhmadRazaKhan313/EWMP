"""Employee HRMS API endpoints."""

from uuid import UUID
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import PermissionDeniedError
from app.models.employee import EmploymentStatus
from app.models.user import User
from app.permissions.dependencies import (
    get_current_user,
    get_tenant_id,
    require_permission,
)
from app.schemas.employee import (
    EmployeeCreateSchema,
    EmployeeListResponse,
    EmployeeUpdateSchema,
)
from app.services.employee import EmployeeService

router = APIRouter(prefix="/employees", tags=["Employees"])


@router.get("", response_model=EmployeeListResponse, summary="List employees")
async def list_employees(
    query: str | None = Query(None),
    department_id: UUID | None = Query(None),
    branch_id: UUID | None = Query(None),
    team_id: UUID | None = Query(None),
    designation_id: UUID | None = Query(None),
    manager_id: UUID | None = Query(None),
    status: EmploymentStatus | None = Query(None),
    employment_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("employees.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EmployeeListResponse:
    service = EmployeeService(db, tenant_id)
    return await service.list_employees(
        query=query, department_id=department_id, branch_id=branch_id,
        team_id=team_id, designation_id=designation_id, manager_id=manager_id,
        status=status, employment_type=employment_type, page=page, page_size=page_size,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create employee")
async def create_employee(
    data: EmployeeCreateSchema,
    current_user: User = Depends(require_permission("employees.create")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Creates the User account (if not linking an existing one) and the
    Employee profile atomically — both succeed or both roll back together.
    """
    service = EmployeeService(db, tenant_id)
    employee, temporary_password = await service.create_employee(
        data, created_by_id=current_user.id
    )
    response = {"id": str(employee.id), "employee_code": employee.employee_code}
    if temporary_password:
        response["temporary_password"] = temporary_password
    return response


@router.get("/stats", summary="HR dashboard stats")
async def get_stats(
    current_user: User = Depends(require_permission("employees.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = EmployeeService(db, tenant_id)
    return await service.get_dashboard_stats()


@router.get("/{employee_id}", summary="Get employee detail")
async def get_employee(
    employee_id: UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = EmployeeService(db, tenant_id)
    employee = await service.get_employee(employee_id)

    # Allow self-view (an employee looking at their own profile) even
    # without employees.view — otherwise a user with zero roles (the
    # normal starting state for anyone who isn't the org owner) couldn't
    # even see their own record.
    is_own_record = employee.user_id == current_user.id
    if not is_own_record and not current_user.has_permission("employees.view"):
        from app.core.exceptions import PermissionDeniedError
        raise PermissionDeniedError("You don't have permission to view this employee")
    return {
        "id": str(employee.id),
        "employee_code": employee.employee_code,
        "first_name": employee.user.first_name if employee.user else None,
        "last_name": employee.user.last_name if employee.user else None,
        "email": employee.user.email if employee.user else None,
        "employment_status": str(employee.employment_status.value),
        "employment_type": str(employee.employment_type.value),
        "job_nature": str(employee.job_nature.value),
        "role_id": str(employee.user.roles[0].id) if employee.user and employee.user.roles else None,
        "date_of_joining": str(employee.date_of_joining),
        "department_id": str(employee.department_id) if employee.department_id else None,
        "designation_id": str(employee.designation_id) if employee.designation_id else None,
        "branch_id": str(employee.branch_id) if employee.branch_id else None,
        "team_id": str(employee.team_id) if employee.team_id else None,
        "manager_id": str(employee.manager_id) if employee.manager_id else None,
        "default_shift_id": str(employee.default_shift_id) if employee.default_shift_id else None,
        "work_location": employee.work_location,
        "is_remote": employee.is_remote,
        "current_salary": str(employee.current_salary) if employee.current_salary else None,
        "currency": employee.currency,
        "date_of_birth": str(employee.date_of_birth) if employee.date_of_birth else None,
        "gender": str(employee.gender.value) if employee.gender else None,
        "nationality": employee.nationality,
        "blood_group": employee.blood_group,
        "personal_email": employee.personal_email,
        "personal_phone": employee.personal_phone,
        "work_phone": employee.work_phone,
        "national_id": employee.national_id,
        "emergency_contact": employee.emergency_contact,
        "years_of_service": employee.years_of_service,
        "notice_period_days": employee.notice_period_days,
        "custom_fields": employee.custom_fields,
    }


@router.patch("/{employee_id}", summary="Update employee")
async def update_employee(
    employee_id: UUID,
    data: EmployeeUpdateSchema,
    current_user: User = Depends(require_permission("employees.update")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # role_id is a privileged field — reassigning an employee's role is
    # equivalent to what the dedicated /roles endpoints already gate behind
    # "roles.manage" (see app/api/v1/hrms/roles.py). Without this check,
    # anyone with plain "employees.update" (e.g. an HR data-entry role that
    # should only edit name/department) could grant themselves or anyone
    # else an Admin role just through the Edit Employee form.
    if data.role_id is not None and not current_user.has_permission("roles.manage"):
        raise PermissionDeniedError(
            "Changing an employee's role requires the 'roles.manage' permission."
        )

    service = EmployeeService(db, tenant_id)
    employee = await service.update_employee(employee_id, data, current_user.id)
    return {"id": str(employee.id), "updated": True}


@router.post("/{employee_id}/offboard", summary="Offboard employee")
async def offboard_employee(
    employee_id: UUID,
    date_of_leaving: date,
    exit_reason: str,
    current_user: User = Depends(require_permission("employees.delete")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = EmployeeService(db, tenant_id)
    await service.offboard_employee(employee_id, date_of_leaving, exit_reason, current_user.id)
    return {"message": "Employee offboarding initiated"}


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete employee")
async def delete_employee(
    employee_id: UUID,
    current_user: User = Depends(require_permission("employees.delete")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    from app.repositories.employee import EmployeeRepository
    repo = EmployeeRepository(db, tenant_id)
    await repo.delete(employee_id)