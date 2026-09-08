"""Employee document repository."""

import uuid
from datetime import date, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.documents import DocumentType, EmployeeDocument
from app.repositories.base import BaseRepository


class EmployeeDocumentRepository(BaseRepository[EmployeeDocument]):
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(db, EmployeeDocument, tenant_id)

    async def list_for_employee(
        self,
        employee_id: uuid.UUID,
        *,
        document_type: DocumentType | None = None,
        expiring_within_days: int | None = None,
    ) -> tuple[list[EmployeeDocument], int]:
        filters: list = [
            EmployeeDocument.tenant_id == self.tenant_id,
            EmployeeDocument.employee_id == employee_id,
            EmployeeDocument.is_deleted == False,  # noqa: E712
        ]
        if document_type is not None:
            filters.append(EmployeeDocument.document_type == document_type)
        if expiring_within_days is not None:
            cutoff = date.today() + timedelta(days=expiring_within_days)
            filters.append(EmployeeDocument.expiry_date.is_not(None))
            filters.append(EmployeeDocument.expiry_date <= cutoff)

        stmt = (
            select(EmployeeDocument)
            .where(*filters)
            .order_by(EmployeeDocument.created_at.desc())
        )
        count_stmt = select(func.count()).select_from(EmployeeDocument).where(*filters)

        items_result = await self.db.execute(stmt)
        count_result = await self.db.execute(count_stmt)
        return list(items_result.scalars().all()), count_result.scalar_one()

    async def list_expiring_org_wide(self, within_days: int = 30) -> list[EmployeeDocument]:
        """Used by a reminder job/dashboard — all employees' docs expiring soon."""
        cutoff = date.today() + timedelta(days=within_days)
        stmt = (
            select(EmployeeDocument)
            .where(
                EmployeeDocument.tenant_id == self.tenant_id,
                EmployeeDocument.is_deleted == False,  # noqa: E712
                EmployeeDocument.expiry_date.is_not(None),
                EmployeeDocument.expiry_date <= cutoff,
            )
            .order_by(EmployeeDocument.expiry_date.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
