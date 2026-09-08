"""
Regression tests for two payroll Medium bugs:

1. "Payslip regeneration cascade failure" — `generate_payroll_run` cleared
   a run's previous payslips with `await db.delete(p)` looped over loaded
   `Payslip` ORM objects. `Payslip.lines` has no
   `cascade="all, delete-orphan"`, so on flush SQLAlchemy's unit-of-work
   tries to NULL OUT `PayslipLine.payslip_id` before deleting the parent —
   but that FK is NOT NULL, so regenerating any run that already had
   payslips crashed with an IntegrityError. The fix is a bulk `DELETE`,
   which bypasses ORM relationship-cascade evaluation and lets the
   database's own `ondelete="CASCADE"` FK constraint (already correctly
   declared) remove the child rows.

   A mocked/fake DB session can't exercise this — the bug is in
   SQLAlchemy's real unit-of-work cascade mechanics, not in application
   logic a fake would simulate. `TestCascadeDeleteMechanism` proves the
   mechanism in isolation with a minimal schema mirroring the exact same
   relationship shape (NOT NULL child FK, relationship with no delete
   cascade) against a real in-memory async SQLite DB.
   `TestGeneratePayrollRunUsesBulkDelete` then confirms the actual
   production code was changed to the safe pattern.

2. "Payroll self-view only half-wired" — `download_payslip_pdf` already had
   proper self-service ownership checking (`_can_view_payslip`), but
   `list_payslips` hard-required `payroll.view`, so an employee without
   that permission got a flat 403 and could never discover their own
   payslip_id to use the (already-working) self-view download. Fixed by
   making `list_payslips` self-scoped, same pattern as attendance/leave.

Run:  cd backend && pytest tests/test_payroll_cascade_and_selfview.py -v
"""
import asyncio
import inspect
import uuid
from types import SimpleNamespace

import pytest

TENANT = uuid.uuid4()
EMP_ID = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


# ── Part 1: cascade-delete mechanism, proven against a real async DB ───────
class TestCascadeDeleteMechanism:
    """Mirrors Payslip.lines' exact relationship shape (no delete cascade,
    NOT NULL child FK) against a real in-memory SQLite DB — this is not
    testable with a mocked session because the failure is in SQLAlchemy's
    own unit-of-work, not application code."""

    def test_looping_orm_delete_crashes_on_a_not_null_child_fk(self):
        """Proves the OLD pattern (`await db.delete(parent)` looped, with no
        delete-orphan cascade) genuinely crashes — this is the bug."""
        import sqlalchemy as sa
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import declarative_base, relationship

        Base = declarative_base()

        class Parent(Base):
            __tablename__ = "parents_old"
            id = sa.Column(sa.Integer, primary_key=True)
            # Same shape as Payslip.lines: relationship, no cascade= at all.
            children = relationship("Child", back_populates="parent")

        class Child(Base):
            __tablename__ = "children_old"
            id = sa.Column(sa.Integer, primary_key=True)
            parent_id = sa.Column(sa.Integer, sa.ForeignKey("parents_old.id", ondelete="CASCADE"), nullable=False)
            parent = relationship("Parent", back_populates="children")

        async def _scenario():
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with AsyncSession(engine) as session:
                session.add(Parent(id=1))
                await session.flush()
                session.add(Child(id=1, parent_id=1))
                await session.commit()
            async with AsyncSession(engine) as session:
                existing = (await session.execute(sa.select(Parent))).scalars().all()
                for p in existing:
                    await session.delete(p)
                await session.flush()  # <- this is what raises

        with pytest.raises(IntegrityError):
            _run(_scenario())

    def test_bulk_delete_avoids_the_crash_and_still_removes_children(self):
        """Proves the FIX (bulk DELETE) avoids ORM cascade evaluation
        entirely and the DB's own ondelete=CASCADE removes the children."""
        import sqlalchemy as sa
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import declarative_base, relationship

        Base = declarative_base()

        class Parent(Base):
            __tablename__ = "parents_new"
            id = sa.Column(sa.Integer, primary_key=True)
            children = relationship("Child", back_populates="parent")

        class Child(Base):
            __tablename__ = "children_new"
            id = sa.Column(sa.Integer, primary_key=True)
            parent_id = sa.Column(sa.Integer, sa.ForeignKey("parents_new.id", ondelete="CASCADE"), nullable=False)
            parent = relationship("Parent", back_populates="children")

        async def _scenario():
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")

            @sa.event.listens_for(engine.sync_engine, "connect")
            def _fk_pragma(dbapi_conn, _):
                dbapi_conn.execute("PRAGMA foreign_keys=ON")

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with AsyncSession(engine) as session:
                session.add(Parent(id=1))
                await session.flush()
                session.add(Child(id=1, parent_id=1))
                await session.commit()

            async with AsyncSession(engine) as session:
                await session.execute(sa.delete(Parent))
                await session.flush()
                await session.commit()

            async with AsyncSession(engine) as session:
                remaining_parents = (await session.execute(sa.select(Parent))).scalars().all()
                remaining_children = (await session.execute(sa.select(Child))).scalars().all()
                return remaining_parents, remaining_children

        parents, children = _run(_scenario())
        assert parents == []
        assert children == []  # DB-level ondelete=CASCADE cleaned these up


class TestGeneratePayrollRunUsesBulkDelete:
    """Confirms the actual production code was changed to the safe pattern
    proven above, not just the isolated mechanism."""

    def test_source_no_longer_loops_orm_delete_over_payslips(self):
        from app.api.v1.hrms import payroll as payroll_mod

        source = inspect.getsource(payroll_mod.generate_payroll_run)
        assert "for p in existing_payslips" not in source, (
            "generate_payroll_run still loops `await db.delete(p)` over "
            "loaded Payslip objects — this crashes on regeneration because "
            "Payslip.lines has no delete-orphan cascade (bug still present)."
        )

    def test_source_uses_a_bulk_delete_statement(self):
        from app.api.v1.hrms import payroll as payroll_mod

        source = inspect.getsource(payroll_mod.generate_payroll_run)
        assert "delete(Payslip)" in source or "sa_delete(Payslip)" in source


# ── Part 2: self-view list gap ───────────────────────────────────────────────
class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, scalar=None, scalars_list=None):
        self._scalar = scalar
        self._scalars_list = scalars_list

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return _FakeScalars(self._scalars_list or [])


class _FakeDB:
    def __init__(self, results):
        self._queue = list(results)

    async def execute(self, stmt):
        if not self._queue:
            raise AssertionError("FakeDB: ran out of queued results.")
        return self._queue.pop(0)


class _FakeEmployeeRepo:
    own_employee = None

    def __init__(self, db, tenant_id):
        pass

    async def get_by_user_id(self, user_id):
        return type(self).own_employee


def _payslip(**overrides):
    from app.models.payroll import Payslip, PayslipStatus
    from decimal import Decimal

    defaults = dict(
        id=uuid.uuid4(), tenant_id=TENANT, payroll_run_id=uuid.uuid4(), employee_id=EMP_ID,
        status=PayslipStatus.GENERATED, net_salary=Decimal("50000"),
    )
    defaults.update(overrides)
    return Payslip(**defaults)


class TestListPayslipsSelfView:
    @pytest.fixture(autouse=True)
    def _patch_repo(self, monkeypatch):
        from app.api.v1.hrms import payroll as payroll_mod

        _FakeEmployeeRepo.own_employee = SimpleNamespace(id=EMP_ID)
        monkeypatch.setattr(payroll_mod, "EmployeeRepository", _FakeEmployeeRepo)

    def test_user_without_payroll_view_sees_only_their_own_payslip(self):
        from app.api.v1.hrms.payroll import list_payslips

        run_id = uuid.uuid4()
        own_payslip = _payslip(payroll_run_id=run_id, employee_id=EMP_ID)
        db = _FakeDB([_FakeResult(scalars_list=[own_payslip])])
        user = SimpleNamespace(id=uuid.uuid4(), has_permission=lambda code: False)

        result = _run(list_payslips(run_id, user, TENANT, db))

        assert result["total"] == 1
        assert result["items"][0]["employee_id"] == str(EMP_ID)

    def test_user_without_payroll_view_and_no_employee_profile_gets_404_not_403(self):
        """A caller with no employee profile at all shouldn't blow up —
        should get a clean 404, not an unhandled error."""
        from app.api.v1.hrms.payroll import list_payslips
        from app.core.exceptions import NotFoundError

        _FakeEmployeeRepo.own_employee = None
        run_id = uuid.uuid4()
        db = _FakeDB([])
        user = SimpleNamespace(id=uuid.uuid4(), has_permission=lambda code: False)

        with pytest.raises(NotFoundError):
            _run(list_payslips(run_id, user, TENANT, db))

    def test_user_with_payroll_view_sees_everyone_in_the_run(self):
        from app.api.v1.hrms.payroll import list_payslips

        run_id = uuid.uuid4()
        p1 = _payslip(payroll_run_id=run_id, employee_id=uuid.uuid4())
        p2 = _payslip(payroll_run_id=run_id, employee_id=uuid.uuid4())
        db = _FakeDB([_FakeResult(scalars_list=[p1, p2])])
        user = SimpleNamespace(id=uuid.uuid4(), has_permission=lambda code: True)

        result = _run(list_payslips(run_id, user, TENANT, db))
        assert result["total"] == 2

    def test_query_is_scoped_to_own_employee_when_self_viewing(self):
        """Belt-and-suspenders: inspect the actual query filters built for
        a self-viewing (non payroll.view) caller."""
        from app.api.v1.hrms.payroll import list_payslips
        from app.models.payroll import Payslip

        run_id = uuid.uuid4()

        class _CapturingDB:
            def __init__(self, result):
                self._result = result
                self.last_stmt = None

            async def execute(self, stmt):
                self.last_stmt = stmt
                return self._result

        db = _CapturingDB(_FakeResult(scalars_list=[]))
        user = SimpleNamespace(id=uuid.uuid4(), has_permission=lambda code: False)
        _run(list_payslips(run_id, user, TENANT, db))

        compiled = str(db.last_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "payslips.employee_id" in compiled
        assert str(EMP_ID).replace("-", "") in compiled.replace("-", "") or str(EMP_ID) in compiled
