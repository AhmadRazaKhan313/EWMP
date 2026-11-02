"""Make sure an id a client sends belongs to the caller's own organization.

Foreign keys only prove a row EXISTS somewhere in the database, not that it is
this tenant's. Accepting an employee/device id from another organization would
let one tenant link its records to (and, via the joins on read, leak data
about) another tenant. These helpers answer 404 for "not yours" and for "does
not exist" alike, so ids cannot be probed across organizations.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError


async def require_employee(db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID, label: str = "Employee") -> None:
    from app.models.employee import Employee

    found = (
        await db.execute(
            select(Employee.id).where(
                Employee.id == employee_id, Employee.tenant_id == tenant_id, Employee.is_deleted == False  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if found is None:
        raise NotFoundError(f"{label} not found")


async def require_device(db: AsyncSession, tenant_id: uuid.UUID, device_id: uuid.UUID) -> None:
    from app.models.devices import Device

    found = (
        await db.execute(
            select(Device.id).where(
                Device.id == device_id, Device.tenant_id == tenant_id, Device.is_deleted == False  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if found is None:
        raise NotFoundError("Device not found")
