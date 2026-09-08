"""
Regression tests for the employee_code uniqueness bug (Medium):

`get_next_employee_code()` used `count(*) + 1` scoped to non-deleted
employees. Once any employee was soft-deleted, the count no longer
included them but their code was still taken — the next new employee
would be assigned that SAME already-used code. There was also no database
constraint to catch this, so it failed silently (two employees sharing a
code) until something looked them up by code
(`get_by_code`, using `scalar_one_or_none()`), which then raised
`MultipleResultsFound`.

Fixed with:
  1. `get_next_employee_code()` now derives the next number from the MAX
     existing numeric suffix across ALL rows (including soft-deleted), so
     a retired code is never reused.
  2. A real unique constraint on (tenant_id, employee_code)
     (migration 3e338fd61f00), with a defensive dedup step for any
     pre-existing collisions.
  3. `EmployeeService.create_employee` retries (via a SAVEPOINT, not a
     full rollback — the linked User row was already flushed in the same
     outer transaction) if a genuine concurrent race still produces a
     collision.

None of this is meaningfully testable with a mocked session — the bug is
about actual soft-delete semantics, a real uniqueness constraint, and
genuine concurrent-transaction behavior. This spins up real rows against
the local PostgreSQL instance and cleans up after itself.

Run:  cd backend && pytest tests/test_employee_code_uniqueness.py -v
      (requires the local PostgreSQL instance + `alembic upgrade head`)
"""
import asyncio
import os
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.organization import Organization
from app.models.rbac import Permission, Role
from app.models.user import User
from app.repositories.employee import EmployeeRepository
from app.schemas.employee import EmployeeCreateSchema
from app.services.employee import EmployeeService

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def org(engine):
    org_id = uuid.uuid4()
    async with AsyncSession(engine) as session:
        session.add(Organization(
            id=org_id, name="Code Test Org", slug=f"code-test-{org_id.hex[:8]}",
            email=f"code-test-{org_id.hex[:8]}@example.com",
        ))
        await session.commit()
    yield org_id
    async with AsyncSession(engine) as session:
        await session.execute(delete(Employee).where(Employee.tenant_id == org_id))
        await session.execute(delete(User).where(User.organization_id == org_id))
        await session.execute(delete(Role).where(Role.organization_id == org_id))
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


async def _make_employee(engine, org_id, code: str, created_at=None):
    """Directly insert an Employee (bypassing the service) with a specific
    code, for setting up soft-delete/collision scenarios precisely."""
    async with AsyncSession(engine) as session:
        u = User(
            organization_id=org_id, email=f"{uuid.uuid4().hex[:10]}@example.com",
            email_normalized=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x",
            first_name="Test", last_name="Employee", is_active=True, is_email_verified=True,
        )
        session.add(u)
        await session.flush()
        emp = Employee(
            tenant_id=org_id, user_id=u.id, employee_code=code,
            employment_type=EmploymentType.FULL_TIME, employment_status=EmploymentStatus.ACTIVE,
            date_of_joining=date(2026, 1, 1),
        )
        if created_at is not None:
            emp.created_at = created_at
        session.add(emp)
        await session.flush()
        emp_id = emp.id  # capture before commit expires the ORM object's attributes
        await session.commit()
        return emp_id


class TestNextEmployeeCodeSurvivesSoftDeletes:
    async def test_soft_deleted_employees_code_is_not_reused(self, engine, org):
        """THE bug assertion: soft-deleting an employee must not make their
        code available for reuse."""
        emp_id = await _make_employee(engine, org, "EMP-0001")

        # Soft-delete it.
        async with AsyncSession(engine) as session:
            emp = (await session.execute(select(Employee).where(Employee.id == emp_id))).scalar_one()
            emp.is_deleted = True
            await session.commit()

        async with AsyncSession(engine) as session:
            repo = EmployeeRepository(session, org)
            next_code = await repo.get_next_employee_code()

        assert next_code != "EMP-0001", (
            f"get_next_employee_code() returned {next_code!r} — an already-used "
            "(now soft-deleted) code. This reproduces the bug exactly."
        )
        assert next_code == "EMP-0002"

    async def test_multiple_soft_deletes_still_produce_correct_next_code(self, engine, org):
        await _make_employee(engine, org, "EMP-0001")
        emp2_id = await _make_employee(engine, org, "EMP-0002")
        await _make_employee(engine, org, "EMP-0003")

        async with AsyncSession(engine) as session:
            emp2 = (await session.execute(select(Employee).where(Employee.id == emp2_id))).scalar_one()
            emp2.is_deleted = True
            await session.commit()

        async with AsyncSession(engine) as session:
            repo = EmployeeRepository(session, org)
            next_code = await repo.get_next_employee_code()

        assert next_code == "EMP-0004"

    async def test_empty_tenant_starts_at_0001(self, engine, org):
        async with AsyncSession(engine) as session:
            repo = EmployeeRepository(session, org)
            next_code = await repo.get_next_employee_code()
        assert next_code == "EMP-0001"


class TestUniqueConstraint:
    async def test_database_rejects_a_duplicate_code_for_the_same_tenant(self, engine, org):
        await _make_employee(engine, org, "EMP-0001")
        with pytest.raises(IntegrityError):
            await _make_employee(engine, org, "EMP-0001")

    async def test_same_code_allowed_across_different_tenants(self, engine, org):
        """The constraint is scoped to (tenant_id, employee_code) — two
        different orgs independently numbering from EMP-0001 is fine."""
        other_org_id = uuid.uuid4()
        async with AsyncSession(engine) as session:
            session.add(Organization(
                id=other_org_id, name="Other Org", slug=f"other-{other_org_id.hex[:8]}",
                email=f"other-{other_org_id.hex[:8]}@example.com",
            ))
            await session.commit()
        try:
            await _make_employee(engine, org, "EMP-0001")
            await _make_employee(engine, other_org_id, "EMP-0001")  # must NOT raise
        finally:
            async with AsyncSession(engine) as session:
                await session.execute(delete(Employee).where(Employee.tenant_id == other_org_id))
                await session.execute(delete(User).where(User.organization_id == other_org_id))
                await session.execute(delete(Organization).where(Organization.id == other_org_id))
                await session.commit()


async def _seed_role_with_permission(engine, org_id, permission_codename="employees.create"):
    async with AsyncSession(engine) as session:
        perm = (
            await session.execute(select(Permission).where(Permission.codename == permission_codename))
        ).scalar_one_or_none()
        role = Role(
            organization_id=org_id, name="Test Role", slug=f"test-role-{uuid.uuid4().hex[:8]}",
            is_system=False, permissions=[perm] if perm else [],
        )
        session.add(role)
        await session.flush()
        role_id = role.id  # capture before commit expires the ORM object's attributes
        await session.commit()
        return role_id


class TestConcurrentCreateEmployeeRetries:
    async def test_two_concurrent_creates_both_succeed_with_different_codes(self, engine, org):
        """THE end-to-end assertion: two employees created for the same
        tenant at (as close to) the same time must both succeed, with
        DIFFERENT employee_codes — no MultipleResultsFound, no lost create."""
        role_id = await _seed_role_with_permission(engine, org)

        async def _create(email_prefix: str):
            async with AsyncSession(engine) as session:
                service = EmployeeService(session, org)
                data = EmployeeCreateSchema(
                    first_name="Concurrent", last_name="Employee",
                    email=f"{email_prefix}-{uuid.uuid4().hex[:8]}@example.com",
                    date_of_joining=date(2026, 1, 1), role_id=role_id,
                )
                employee, _ = await service.create_employee(data, created_by_id=uuid.uuid4())
                code = employee.employee_code  # capture before commit expires attributes
                await session.commit()
                return code

        codes = await asyncio.gather(_create("a"), _create("b"))
        assert codes[0] != codes[1], f"Both concurrent creates got the same code: {codes}"

        # And a lookup by either code must find exactly one row (no
        # MultipleResultsFound) — the original bug's actual crash mode.
        async with AsyncSession(engine) as session:
            repo = EmployeeRepository(session, org)
            for code in codes:
                found = await repo.get_by_code(code)  # would raise MultipleResultsFound if duplicated
                assert found is not None
                assert found.employee_code == code

    async def test_lookup_by_code_never_raises_multiple_results_found(self, engine, org):
        await _make_employee(engine, org, "EMP-0050")
        async with AsyncSession(engine) as session:
            repo = EmployeeRepository(session, org)
            try:
                result = await repo.get_by_code("EMP-0050")
            except MultipleResultsFound:
                pytest.fail("get_by_code raised MultipleResultsFound — the bug is still present.")
            assert result is not None
