"""Contract endpoints, mounted under /employees (see employees.py)."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.permissions.dependencies import get_tenant_id, require_permission
from app.schemas.employee_contract import (
    ContractCreate,
    ContractRenew,
    ContractTerminate,
    ContractUpdate,
)
from app.services.employee_contracts import EmployeeContractService

router = APIRouter(tags=["Employee contracts"])


@router.get("/contracts", summary="List contracts across employees")
async def list_contracts(
    state: str | None = Query(None, description="active|expiring|expired|renewed|terminated"),
    expiring_within_days: int | None = Query(None, ge=0, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("employees.view")),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await EmployeeContractService(db, tenant_id).list(
        state=state, expiring_within_days=expiring_within_days, page=page, page_size=page_size
    )


@router.patch("/contracts/{contract_id}", summary="Edit an active contract")
async def update_contract(
    contract_id: UUID, data: ContractUpdate,
    current_user: User = Depends(require_permission("employees.update")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await EmployeeContractService(db, tenant_id).update(contract_id, data.model_dump(exclude_unset=True))


@router.post("/contracts/{contract_id}/renew", summary="Renew a contract")
async def renew_contract(
    contract_id: UUID, data: ContractRenew,
    current_user: User = Depends(require_permission("employees.update")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await EmployeeContractService(db, tenant_id).renew(contract_id, data.model_dump(exclude_unset=True))


@router.post("/contracts/{contract_id}/terminate", summary="Terminate a contract")
async def terminate_contract(
    contract_id: UUID, data: ContractTerminate,
    current_user: User = Depends(require_permission("employees.update")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await EmployeeContractService(db, tenant_id).terminate(contract_id, data.reason)


@router.delete("/contracts/{contract_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a contract")
async def delete_contract(
    contract_id: UUID,
    current_user: User = Depends(require_permission("employees.update")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> None:
    await EmployeeContractService(db, tenant_id).delete(contract_id)


@router.get("/{employee_id}/contracts", summary="An employee's contracts")
async def employee_contracts(
    employee_id: UUID,
    current_user: User = Depends(require_permission("employees.view")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    svc = EmployeeContractService(db, tenant_id)
    await svc._employee(employee_id)
    return await svc.list(employee_id=employee_id, page_size=200)


@router.post("/{employee_id}/contracts", status_code=status.HTTP_201_CREATED, summary="Add a contract")
async def create_contract(
    employee_id: UUID, data: ContractCreate,
    current_user: User = Depends(require_permission("employees.update")),
    tenant_id: UUID = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
) -> dict:
    return await EmployeeContractService(db, tenant_id).create(employee_id, data.model_dump())
