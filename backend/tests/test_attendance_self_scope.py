"""
Regression tests for the attendance self-scope fix (bug H7).

`check_in` / `check_out` are protected only by `get_current_user` (any valid
login, no permission), and `_resolve_employee` previously honored a
client-supplied `employee_id` with NO gate — so any authenticated user could
check in or out as *any* employee just by passing their id. The resolver now
forces self-service: you may only record your own attendance unless you hold
`attendance.regularize` (manager/HR override).

These tests exercise the resolver directly with a fake repository
(monkeypatched), so they need NO database.

Run:  cd backend && pytest tests/test_attendance_self_scope.py -v
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

import app.api.v1.hrms.attendance as attendance_mod
from app.core.exceptions import NotFoundError, PermissionDeniedError

OWN_EMP = uuid.uuid4()
OTHER_EMP = uuid.uuid4()
USER_ID = uuid.uuid4()
TENANT = uuid.uuid4()


class _FakeEmployeeRepo:
    """Stand-in for EmployeeRepository. Configured per-test via class attrs."""

    own_employee = None            # returned by get_by_user_id
    by_id: dict = {}               # employee_id -> employee, for get()

    def __init__(self, db, tenant_id):
        pass

    async def get_by_user_id(self, user_id):
        return type(self).own_employee

    async def get(self, employee_id):
        return type(self).by_id.get(employee_id)


def _emp(emp_id):
    return SimpleNamespace(id=emp_id)


def _user(*, can_regularize: bool):
    return SimpleNamespace(
        id=USER_ID,
        has_permission=lambda code: can_regularize and code == "attendance.regularize",
    )


@pytest.fixture(autouse=True)
def _patch_repo(monkeypatch):
    # Reset per test, then patch the name the resolver reads.
    _FakeEmployeeRepo.own_employee = _emp(OWN_EMP)
    _FakeEmployeeRepo.by_id = {OWN_EMP: _emp(OWN_EMP), OTHER_EMP: _emp(OTHER_EMP)}
    monkeypatch.setattr(attendance_mod, "EmployeeRepository", _FakeEmployeeRepo)


def _resolve(user, employee_id):
    return asyncio.run(
        attendance_mod._resolve_employee(None, TENANT, user, employee_id)
    )


# ── Self-service path ─────────────────────────────────────────────────────────

def test_no_employee_id_uses_own_record():
    assert _resolve(_user(can_regularize=False), None).id == OWN_EMP


def test_explicit_self_employee_id_allowed():
    assert _resolve(_user(can_regularize=False), OWN_EMP).id == OWN_EMP


def test_no_employee_profile_is_rejected():
    _FakeEmployeeRepo.own_employee = None
    with pytest.raises(NotFoundError):
        _resolve(_user(can_regularize=False), None)


# ── On-behalf path (the security assertion) ───────────────────────────────────

def test_regular_user_cannot_record_for_another_employee():
    """THE H7 assertion: without attendance.regularize, a spoofed employee_id is
    refused rather than checking in/out as someone else."""
    with pytest.raises(PermissionDeniedError):
        _resolve(_user(can_regularize=False), OTHER_EMP)


def test_manager_can_record_for_another_employee():
    assert _resolve(_user(can_regularize=True), OTHER_EMP).id == OTHER_EMP


def test_manager_recording_for_unknown_employee_gets_404():
    """Manager targeting a non-existent / cross-tenant employee (repo returns
    None because it is tenant-scoped) → NotFound, never a silent misfile."""
    with pytest.raises(NotFoundError):
        _resolve(_user(can_regularize=True), uuid.uuid4())