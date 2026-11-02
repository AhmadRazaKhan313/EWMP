"""
Live-Postgres integration test for issue #6.

Follows the same convention as tests/test_employee_code_uniqueness.py: reads
TEST_DATABASE_URL (defaults to the docker-compose dev database), assumes
`alembic upgrade head` has already been run against it, and exercises the ORM
against the real schema — no mocking, this is what actually failed in
production use before the fix.

Requires a live Postgres with migrations applied:
    cd backend && alembic upgrade head
    cd backend && pytest tests/test_attendance_punch_postgres.py -v

Run the whole suite without Postgres and this file errors on connection, same
as the other Postgres-only tests already in this directory — that is
existing, accepted behavior here (no DATABASE_URL-independent skip marker is
used elsewhere in this suite either).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.attendance import (
    AttendancePunch,
    AttendanceRecord,
    AttendanceRegularization,
    AttendanceSource,
    AttendanceStatus,
    RegularizationStatus,
)
from app.models.employee import Employee, EmploymentStatus, EmploymentType
from app.models.organization import Organization
from app.models.user import User

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
async def employee(engine):
    """A real org/user/employee row, cleaned up afterwards."""
    org_id, user_id, emp_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    suffix = org_id.hex[:8]
    async with AsyncSession(engine) as session:
        session.add(Organization(id=org_id, name="Punch Test Org", slug=f"punch-{suffix}", email=f"punch-{suffix}@example.com"))
        await session.flush()
        session.add(User(
            id=user_id, organization_id=org_id, email=f"punch-{suffix}@example.com",
            email_normalized=f"punch-{suffix}@example.com", first_name="P", last_name="T",
            password_hash="x",
        ))
        await session.flush()
        session.add(Employee(
            id=emp_id, user_id=user_id, tenant_id=org_id, employee_code="PUNCH-0001",
            employment_type=EmploymentType.FULL_TIME, employment_status=EmploymentStatus.ACTIVE,
            date_of_joining=datetime.now(UTC).date(),
        ))
        await session.commit()
    yield org_id, emp_id
    async with AsyncSession(engine) as session:
        await session.execute(delete(AttendanceRegularization).where(AttendanceRegularization.tenant_id == org_id))
        await session.execute(delete(AttendancePunch).where(AttendancePunch.tenant_id == org_id))
        await session.execute(delete(AttendanceRecord).where(AttendanceRecord.tenant_id == org_id))
        await session.execute(delete(Employee).where(Employee.tenant_id == org_id))
        await session.execute(delete(User).where(User.organization_id == org_id))
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


class TestAttendancePunchDeletedAt:
    async def test_select_attendance_punch_does_not_error(self, engine, employee):
        """Before the fix this raised UndefinedColumnError against real Postgres:
        the model maps `deleted_at` but the table never had the column."""
        tenant_id, emp_id = employee
        rec_id = uuid.uuid4()
        async with AsyncSession(engine) as session:
            session.add(AttendanceRecord(
                id=rec_id, tenant_id=tenant_id, employee_id=emp_id,
                date=datetime.now(UTC).date(), status=AttendanceStatus.PRESENT,
            ))
            await session.flush()
            session.add(AttendancePunch(
                tenant_id=tenant_id, attendance_record_id=rec_id, employee_id=emp_id,
                punch_in=datetime.now(UTC) - timedelta(hours=1),
                punch_in_source=AttendanceSource.MANUAL,
            ))
            await session.commit()

        async with AsyncSession(engine) as session:
            rows = (
                await session.execute(select(AttendancePunch).where(AttendancePunch.tenant_id == tenant_id))
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].deleted_at is None  # column exists and reads back correctly

    async def test_soft_delete_sets_and_is_filtered(self, engine, employee):
        tenant_id, emp_id = employee
        rec_id = uuid.uuid4()
        async with AsyncSession(engine) as session:
            session.add(AttendanceRecord(
                id=rec_id, tenant_id=tenant_id, employee_id=emp_id,
                date=datetime.now(UTC).date(), status=AttendanceStatus.PRESENT,
            ))
            await session.flush()
            punch = AttendancePunch(
                tenant_id=tenant_id, attendance_record_id=rec_id, employee_id=emp_id,
                punch_in=datetime.now(UTC) - timedelta(hours=1),
                punch_in_source=AttendanceSource.MANUAL,
            )
            session.add(punch)
            await session.commit()
            punch.soft_delete()
            await session.commit()

        async with AsyncSession(engine) as session:
            active = (
                await session.execute(
                    select(AttendancePunch).where(
                        AttendancePunch.tenant_id == tenant_id, AttendancePunch.is_deleted == False  # noqa: E712
                    )
                )
            ).scalars().all()
            assert active == []
            archived = (
                await session.execute(select(AttendancePunch).where(AttendancePunch.tenant_id == tenant_id))
            ).scalars().all()
            assert len(archived) == 1 and archived[0].deleted_at is not None

    async def test_select_attendance_regularization_does_not_error(self, engine, employee):
        tenant_id, emp_id = employee
        rec_id = uuid.uuid4()
        async with AsyncSession(engine) as session:
            session.add(AttendanceRecord(
                id=rec_id, tenant_id=tenant_id, employee_id=emp_id,
                date=datetime.now(UTC).date(), status=AttendanceStatus.MISSED_PUNCH,
            ))
            await session.flush()
            session.add(AttendanceRegularization(
                tenant_id=tenant_id, attendance_record_id=rec_id, employee_id=emp_id,
                date=datetime.now(UTC).date(), reason="forgot to check out",
                status=RegularizationStatus.PENDING,
            ))
            await session.commit()

        async with AsyncSession(engine) as session:
            rows = (
                await session.execute(
                    select(AttendanceRegularization).where(AttendanceRegularization.tenant_id == tenant_id)
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].deleted_at is None


class TestBackfillEnumCastFix:
    """A completed attendance day (both check_in_source AND check_out_source set)
    is exactly the case that used to fail the a1b2c3d4e5f6 backfill INSERT with
    a cross-enum-type DatatypeMismatchError — independent of #6, but this
    migration cannot be delivered without it (see that migration's docstring)."""

    async def test_completed_day_columns_round_trip_through_the_same_enum_type(self, engine, employee):
        """Not a re-run of the backfill (it only runs once, at migration time);
        confirms both punch source columns accept the full label set post-fix,
        i.e. that punch_in_source/punch_out_source genuinely share one enum type."""
        tenant_id, emp_id = employee
        rec_id = uuid.uuid4()
        async with AsyncSession(engine) as session:
            session.add(AttendanceRecord(
                id=rec_id, tenant_id=tenant_id, employee_id=emp_id,
                date=datetime.now(UTC).date(), status=AttendanceStatus.PRESENT,
            ))
            await session.flush()
            session.add(AttendancePunch(
                tenant_id=tenant_id, attendance_record_id=rec_id, employee_id=emp_id,
                punch_in=datetime.now(UTC) - timedelta(hours=8),
                punch_out=datetime.now(UTC),
                punch_in_source=AttendanceSource.MOBILE,
                punch_out_source=AttendanceSource.DESKTOP_AGENT,
            ))
            await session.commit()

        async with AsyncSession(engine) as session:
            row = (
                await session.execute(select(AttendancePunch).where(AttendancePunch.tenant_id == tenant_id))
            ).scalar_one()
            assert row.punch_in_source == AttendanceSource.MOBILE
            assert row.punch_out_source == AttendanceSource.DESKTOP_AGENT
