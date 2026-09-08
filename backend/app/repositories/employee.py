"""
Employee repository.

Extends BaseRepository[Employee] with HR-specific queries:
  - Full-text search across name, code, email
  - Filter by department, status, employment type
  - Org chart (manager → direct reports tree)
  - Bulk status updates (for offboarding workflows)
"""

import uuid
from typing import Any

from sqlalchemy import or_, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from app.models.employee import Employee, EmploymentStatus
from app.repositories.base import BaseRepository


class EmployeeRepository(BaseRepository[Employee]):
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(db, Employee, tenant_id)

    async def get_with_relations(self, employee_id: uuid.UUID) -> Employee | None:
        """Fetch employee with department, designation, branch, team, manager."""
        stmt = (
            select(Employee)
            .where(
                Employee.id == employee_id,
                Employee.tenant_id == self.tenant_id,
                Employee.is_deleted == False,  # noqa: E712
            )
            .options(
                joinedload(Employee.manager),
            )
        )
        result = await self.db.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def get_by_code(self, employee_code: str) -> Employee | None:
        """Lookup by org-assigned employee code (e.g. EMP-0042)."""
        return await self._get_one_by(
            Employee.employee_code == employee_code,
            Employee.tenant_id == self.tenant_id,
        )

    async def get_by_user_id(self, user_id: uuid.UUID) -> Employee | None:
        """Find the employee profile linked to a specific user."""
        return await self._get_one_by(
            Employee.user_id == user_id,
            Employee.tenant_id == self.tenant_id,
        )

    async def search(
        self,
        *,
        query: str | None = None,
        department_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        team_id: uuid.UUID | None = None,
        designation_id: uuid.UUID | None = None,
        manager_id: uuid.UUID | None = None,
        status: EmploymentStatus | None = None,
        employment_type: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[Employee], int]:
        """
        Full-featured employee search with all HR filters.
        Used by the employee list page with TanStack Table.
        """
        filters: list[Any] = [
            Employee.tenant_id == self.tenant_id,
            Employee.is_deleted == False,  # noqa: E712
        ]

        if query:
            q = f"%{query.lower()}%"
            filters.append(
                or_(
                    func.lower(Employee.employee_code).like(q),
                    Employee.work_phone.like(q),
                )
            )

        if department_id:
            filters.append(Employee.department_id == department_id)
        if branch_id:
            filters.append(Employee.branch_id == branch_id)
        if team_id:
            filters.append(Employee.team_id == team_id)
        if designation_id:
            filters.append(Employee.designation_id == designation_id)
        if manager_id:
            filters.append(Employee.manager_id == manager_id)
        if status:
            filters.append(Employee.employment_status == status)
        if employment_type:
            filters.append(Employee.employment_type == employment_type)

        offset = (page - 1) * page_size

        stmt = (
            select(Employee)
            .where(*filters)
            .order_by(Employee.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        count_stmt = (
            select(func.count())
            .select_from(Employee)
            .where(*filters)
        )

        items_result = await self.db.execute(stmt)
        count_result = await self.db.execute(count_stmt)

        return list(items_result.scalars().all()), count_result.scalar_one()

    async def get_direct_reports(self, manager_id: uuid.UUID) -> list[Employee]:
        """Return all employees reporting directly to a manager."""
        stmt = select(Employee).where(
            Employee.tenant_id == self.tenant_id,
            Employee.manager_id == manager_id,
            Employee.is_deleted == False,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_next_employee_code(self) -> str:
        """
        Generate the next sequential employee code for this tenant.
        Format: EMP-XXXX (zero-padded to 4 digits, then extends).

        Bug fix: this used to be `count(*) + 1` scoped to non-deleted
        employees only. That reused an already-assigned code once any
        employee was soft-deleted, since the count no longer includes them
        but their code is still taken — two employees ending up with the
        same code, undetected because there was no uniqueness constraint
        either (see migration 3e338fd61f00). Now derives the next number
        from the MAX existing numeric suffix across ALL rows, including
        soft-deleted ones, so a retired code is never reused. The DB
        constraint + retry in EmployeeService.create_employee together
        close the remaining concurrent-request race window.
        """
        stmt = select(Employee.employee_code).where(
            Employee.tenant_id == self.tenant_id,
            Employee.employee_code.like("EMP-%"),
        )
        result = await self.db.execute(stmt)
        codes = result.scalars().all()

        max_n = 0
        for code in codes:
            suffix = code[len("EMP-"):]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))

        return f"EMP-{str(max_n + 1).zfill(4)}"

    async def bulk_update_status(
        self, employee_ids: list[uuid.UUID], status: EmploymentStatus
    ) -> int:
        """Bulk update employment status. Returns number of rows affected."""
        stmt = (
            update(Employee)
            .where(
                Employee.id.in_(employee_ids),
                Employee.tenant_id == self.tenant_id,
            )
            .values(employment_status=status)
        )
        result = await self.db.execute(stmt)
        return result.rowcount

    async def count_by_status(self) -> dict[str, int]:
        """Return counts grouped by employment_status. Used on HR Dashboard."""
        stmt = (
            select(Employee.employment_status, func.count().label("count"))
            .where(
                Employee.tenant_id == self.tenant_id,
                Employee.is_deleted == False,  # noqa: E712
            )
            .group_by(Employee.employment_status)
        )
        result = await self.db.execute(stmt)
        return {row.employment_status.value: row.count for row in result}

    async def count_by_department(self) -> list[dict]:
        """Return (department_id, count) pairs. Used on org chart / analytics."""
        stmt = (
            select(Employee.department_id, func.count().label("count"))
            .where(
                Employee.tenant_id == self.tenant_id,
                Employee.is_deleted == False,  # noqa: E712
                Employee.employment_status == EmploymentStatus.ACTIVE,
            )
            .group_by(Employee.department_id)
        )
        result = await self.db.execute(stmt)
        return [{"department_id": str(row.department_id), "count": row.count} for row in result]