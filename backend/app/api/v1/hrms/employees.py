"""Employee HRMS API endpoints."""

from uuid import UUID
from datetime import date

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
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
from app.api.v1.hrms.employee_bulk import router as _bulk_router
from app.api.v1.hrms.employee_contracts import router as _contracts_router
from app.services.employee_avatar import MAX_AVATAR_BYTES, remove_avatar, store_avatar

router = APIRouter(prefix="/employees", tags=["Employees"])
# Static paths (/export, /import, /contracts) must be registered before the
# /{employee_id} routes below so they are not read as an employee id.
router.include_router(_bulk_router)
router.include_router(_contracts_router)


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
        data, created_by_id=current_user.id, actor=current_user
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
    # Pay and ID numbers are not part of plain `employees.view`. Allowed:
    # the person themselves, anyone who can edit employees (the edit form needs
    # the current value), and — for pay only — `employees.view_salary`.
    can_edit = current_user.has_permission("employees.update")
    can_see_pay = is_own_record or can_edit or current_user.has_permission("employees.view_salary")
    can_see_ids = is_own_record or can_edit
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
        "current_salary": str(employee.current_salary) if (can_see_pay and employee.current_salary) else None,
        "currency": employee.currency,
        "date_of_birth": str(employee.date_of_birth) if employee.date_of_birth else None,
        "gender": str(employee.gender.value) if employee.gender else None,
        "nationality": employee.nationality,
        "blood_group": employee.blood_group,
        "personal_email": employee.personal_email,
        "personal_phone": employee.personal_phone,
        "work_phone": employee.work_phone,
        "national_id": employee.national_id if can_see_ids else None,
        "emergency_contact": employee.emergency_contact,
        "years_of_service": employee.years_of_service,
        "notice_period_days": employee.notice_period_days,
        "custom_fields": employee.custom_fields,
        "marital_status": employee.marital_status.value if employee.marital_status else None,
        "father_name": employee.father_name,
        "mother_name": employee.mother_name,
        "spouse_name": employee.spouse_name,
        "address": employee.address,
        "permanent_address": employee.permanent_address,
        "passport_number": employee.passport_number if can_see_ids else None,
        "passport_expiry": str(employee.passport_expiry) if employee.passport_expiry else None,
        "health_insurance_provider": employee.health_insurance_provider,
        "health_insurance_number": employee.health_insurance_number,
        # Several people, newest format first; older rows only have the single
        # legacy contact, so fall back to it rather than showing nothing.
        "emergency_contacts": employee.emergency_contacts
        or ([employee.emergency_contact] if employee.emergency_contact else []),
        "education": employee.education or [],
        "work_experience": employee.work_experience or [],
        "avatar_url": employee.user.avatar_url if employee.user else None,
        "manager_name": (
            employee.manager.user.full_name if employee.manager is not None and employee.manager.user else None
        ),
        "driving_license_number": employee.driving_license_number,
        "driving_license_expiry": str(employee.driving_license_expiry) if employee.driving_license_expiry else None,
        "date_of_confirmation": str(employee.date_of_confirmation) if employee.date_of_confirmation else None,
        "probation_end_date": str(employee.probation_end_date) if employee.probation_end_date else None,
        "dependents": employee.dependents or [],
        # More personal details. Tax / EOBI / PF / visa numbers are ID-class
        # data, so they follow national_id: the person, or someone who can edit.
        "religion": employee.religion,
        "place_of_birth": employee.place_of_birth,
        "home_phone": employee.home_phone,
        "previous_employee_id": employee.previous_employee_id,
        "referral_source": employee.referral_source,
        "hobbies": employee.hobbies,
        "tshirt_size": employee.tshirt_size,
        "social_links": employee.social_links or {},
        "national_id_type": employee.national_id_type,
        "visa_expiry": str(employee.visa_expiry) if employee.visa_expiry else None,
        "tax_number": employee.tax_number if can_see_ids else None,
        "social_security_number": employee.social_security_number if can_see_ids else None,
        "provident_fund_number": employee.provident_fund_number if can_see_ids else None,
        "visa_number": employee.visa_number if can_see_ids else None,
        "skills": employee.skills or [],
        "languages": employee.languages or [],
        "certifications": employee.certifications or [],
        # Pay and bank details: only the person themselves or someone allowed
        # to edit employees. A viewer with just `employees.view` does not get
        # them.
        **(
            {
                "bank_name": employee.bank_name,
                "bank_account_title": employee.bank_account_title,
                "bank_account_number": employee.bank_account_number,
                "bank_iban": employee.bank_iban,
                "compensation_items": employee.compensation_items or [],
            }
            if is_own_record or can_edit
            else {}
        ),
    }


async def _employee_for_photo(
    employee_id: UUID, current_user: User, tenant_id: UUID, db: AsyncSession
):
    """The employee whose photo is being changed — HR (employees.update) or the person themselves."""
    service = EmployeeService(db, tenant_id)
    employee = await service.get_employee(employee_id)
    if employee.user_id != current_user.id and not current_user.has_permission("employees.update"):
        raise PermissionDeniedError("You don't have permission to change this employee's photo")
    return employee


@router.post("/{employee_id}/avatar", summary="Upload or replace an employee's profile photo")
async def upload_employee_avatar(
    employee_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.repositories.user import UserRepository

    employee = await _employee_for_photo(employee_id, current_user, tenant_id, db)
    # Read one byte past the limit so an oversized upload is refused without
    # pulling an unbounded body into memory.
    content = await file.read(MAX_AVATAR_BYTES + 1)
    avatar_url = await store_avatar(employee.user_id, content)
    await UserRepository(db).update(employee.user_id, {"avatar_url": avatar_url})
    return {"avatar_url": avatar_url}


@router.delete(
    "/{employee_id}/avatar", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an employee's profile photo"
)
async def delete_employee_avatar(
    employee_id: UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    from app.repositories.user import UserRepository

    employee = await _employee_for_photo(employee_id, current_user, tenant_id, db)
    await remove_avatar(employee.user_id)
    await UserRepository(db).update(employee.user_id, {"avatar_url": None})


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

    # Same idea for employment_status: moving someone to/from Terminated or
    # Resigned enables/disables their login, so it needs the offboard permission.
    service = EmployeeService(db, tenant_id)
    employee = await service.update_employee(
        employee_id,
        data,
        current_user.id,
        can_manage_exit=current_user.has_permission("employees.delete"),
        actor=current_user,
    )
    return {"id": str(employee.id), "updated": True}


@router.post("/{employee_id}/offboard", summary="Offboard employee")
async def offboard_employee(
    employee_id: UUID,
    date_of_leaving: date,
    exit_reason: str,
    reason_type: str = Query("termination"),
    current_user: User = Depends(require_permission("employees.delete")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = EmployeeService(db, tenant_id)
    await service.offboard_employee(
        employee_id, date_of_leaving, exit_reason, current_user.id, reason_type=reason_type
    )
    return {"message": "Employee offboarding initiated"}


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete employee")
async def delete_employee(
    employee_id: UUID,
    current_user: User = Depends(require_permission("employees.delete")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Goes through the service so the employee's login is disabled too
    # (and the owner / yourself can't be deleted by accident).
    service = EmployeeService(db, tenant_id)
    await service.delete_employee(employee_id, current_user.id)