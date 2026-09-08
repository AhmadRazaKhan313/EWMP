"""
Regression tests for Asset assignment bugs:

H8 — `assign_asset` set `assigned_employee_id` from the request body with no
check that the employee belongs to this tenant (unlike `assign_device`,
which already validates this). An org owner could assign their asset to
another org's employee_id.

H9 — reassigning an already-assigned asset (calling /assign again without
an intervening /return) never closed the prior open AssetAssignment row,
leaving two rows with `returned_at IS NULL` — assignment history becomes
ambiguous about who actually has the asset.

No database needed — same fake-DB-queue technique as test_device_enrollment_c3.py
and test_leave_completion.py: db.execute() returns pre-queued results in the
exact order the endpoint code issues queries.

Run:  cd backend && pytest tests/test_asset_assignment.py -v
"""
import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.v1.hrms.assets import AssignAssetRequest, assign_asset
from app.core.exceptions import NotFoundError
from app.models.devices import Asset, AssetAssignment, AssetStatus

TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()


class _FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    def __init__(self, results):
        self._queue = list(results)
        self.added = []

    async def execute(self, stmt):
        if not self._queue:
            raise AssertionError("FakeDB: ran out of queued results — unexpected extra db.execute() call.")
        return self._queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


def _asset(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Dell Laptop",
        asset_tag="AST-001",
        category="laptop",
        status=AssetStatus.AVAILABLE,
        assigned_employee_id=None,
        assigned_at=None,
    )
    defaults.update(overrides)
    return Asset(**defaults)


def _employee(**overrides):
    defaults = dict(id=uuid.uuid4(), tenant_id=TENANT)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _open_assignment(asset_id, employee_id, **overrides):
    defaults = dict(
        id=uuid.uuid4(), tenant_id=TENANT, asset_id=asset_id, employee_id=employee_id,
        assigned_at=datetime.now(UTC), assigned_by_id=uuid.uuid4(), returned_at=None,
    )
    defaults.update(overrides)
    return AssetAssignment(**defaults)


class TestAssignAssetCrossTenant:
    def test_rejects_employee_from_another_tenant(self):
        """THE H8 assertion: an employee belonging to a different tenant
        must never be assignable, even if the id is guessed/known."""
        asset = _asset()
        db = _FakeDB([
            _FakeResult(scalar=asset),   # asset lookup (this tenant)
            _FakeResult(scalar=None),    # employee lookup scoped by THIS tenant -> not found
        ])
        body = AssignAssetRequest(employee_id=uuid.uuid4())
        with pytest.raises(NotFoundError):
            _run(assign_asset(asset.id, body, SimpleNamespace(id=uuid.uuid4()), TENANT, db))

    def test_allows_employee_from_same_tenant(self):
        asset = _asset()
        employee = _employee()
        db = _FakeDB([
            _FakeResult(scalar=asset),
            _FakeResult(scalar=employee),
            _FakeResult(scalar=None),  # no open assignment yet
        ])
        body = AssignAssetRequest(employee_id=employee.id)
        result = _run(assign_asset(asset.id, body, SimpleNamespace(id=uuid.uuid4()), TENANT, db))

        assert result["message"] == "Asset assigned"
        assert asset.assigned_employee_id == employee.id
        assert asset.status == AssetStatus.ASSIGNED


class TestAssignAssetReassignmentHistory:
    def test_reassigning_closes_the_previous_open_assignment(self):
        """THE H9 assertion: reassigning without calling /return first must
        still close the prior assignment row rather than leaving two rows
        with returned_at IS NULL."""
        asset = _asset(status=AssetStatus.ASSIGNED)
        old_employee = _employee()
        new_employee = _employee()
        prior_assignment = _open_assignment(asset.id, old_employee.id)

        db = _FakeDB([
            _FakeResult(scalar=asset),
            _FakeResult(scalar=new_employee),
            _FakeResult(scalar=prior_assignment),  # the still-open assignment to old_employee
        ])
        body = AssignAssetRequest(employee_id=new_employee.id)
        _run(assign_asset(asset.id, body, SimpleNamespace(id=uuid.uuid4()), TENANT, db))

        # The old assignment must now be closed...
        assert prior_assignment.returned_at is not None
        # ...and exactly one NEW open assignment (to new_employee) was created.
        new_rows = [a for a in db.added if isinstance(a, AssetAssignment)]
        assert len(new_rows) == 1
        assert new_rows[0].employee_id == new_employee.id
        assert new_rows[0].returned_at is None

    def test_first_time_assignment_has_no_prior_assignment_to_close(self):
        asset = _asset()
        employee = _employee()
        db = _FakeDB([
            _FakeResult(scalar=asset),
            _FakeResult(scalar=employee),
            _FakeResult(scalar=None),  # nothing open yet — first assignment ever
        ])
        body = AssignAssetRequest(employee_id=employee.id)
        result = _run(assign_asset(asset.id, body, SimpleNamespace(id=uuid.uuid4()), TENANT, db))
        assert result["message"] == "Asset assigned"
        assert len(db.added) == 1

    def test_unknown_asset_404s(self):
        db = _FakeDB([_FakeResult(scalar=None)])
        body = AssignAssetRequest(employee_id=uuid.uuid4())
        with pytest.raises(NotFoundError):
            _run(assign_asset(uuid.uuid4(), body, SimpleNamespace(id=uuid.uuid4()), TENANT, db))
