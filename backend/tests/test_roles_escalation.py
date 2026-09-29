"""
Regression tests for the roles privilege-escalation fix.

Before the fix, anyone holding the ordinary `roles.manage` permission could
create a role with `is_super=True` (or flip an existing role to it) and assign
it to themselves — full org access from a delegable permission.

These tests exercise the handlers directly with a tiny fake DB session; no
Postgres and no FastAPI app are needed.

Run:  cd backend && pytest tests/test_roles_escalation.py -v
"""

import uuid
from types import SimpleNamespace

import pytest

from app.api.v1.hrms import roles as roles_api
from app.core.exceptions import PermissionDeniedError

TENANT = uuid.uuid4()


# ── helpers ──────────────────────────────────────────────────────────────────
def _perm(codename: str):
    return SimpleNamespace(codename=codename)


def _role(*, is_super=False, codenames=(), name="R"):
    perms = [_perm(c) for c in codenames]
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        slug=name.lower(),
        is_super=is_super,
        permissions=perms,
        permission_codenames={p.codename for p in perms},
        description=None,
        color=None,
        display_order=0,
    )


def _user(*, full_access=False, held=("roles.manage",)):
    """A caller. Only the attributes the guards read are provided."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        has_full_access=full_access,
        roles=[_role(codenames=held, name="Caller")],
    )


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeDB:
    """Returns queued values for successive `execute()` calls; records writes."""

    def __init__(self, *values):
        self._queue = list(values)
        self.executed = 0
        self.flushed = 0

    async def execute(self, *_a, **_k):
        self.executed += 1
        return _Result(self._queue.pop(0) if self._queue else None)

    async def flush(self):
        self.flushed += 1


class ExplodingDB:
    """Any DB access at all is a test failure (guards must run first)."""

    async def execute(self, *_a, **_k):
        raise AssertionError("DB was touched before the escalation guard ran")

    async def flush(self):
        raise AssertionError("DB was touched before the escalation guard ran")


# ── helper-level unit tests ──────────────────────────────────────────────────
class TestGuardHelpers:
    def test_held_codenames_collects_across_roles(self):
        u = SimpleNamespace(roles=[_role(codenames=["a.x"]), _role(codenames=["b.y", "a.x"])])
        assert roles_api._held_codenames(u) == {"a.x", "b.y"}

    def test_full_access_may_grant_anything(self):
        roles_api._require_can_grant(_user(full_access=True, held=()), {"payroll.approve"})

    def test_non_full_access_may_grant_subset(self):
        roles_api._require_can_grant(_user(held=("roles.manage", "leave.view")), {"leave.view"})

    def test_non_full_access_cannot_grant_unheld(self):
        with pytest.raises(PermissionDeniedError) as exc:
            roles_api._require_can_grant(_user(held=("roles.manage",)), {"payroll.approve", "leave.view"})
        assert "leave.view" in str(exc.value) and "payroll.approve" in str(exc.value)

    def test_super_requires_full_access(self):
        with pytest.raises(PermissionDeniedError):
            roles_api._require_full_access_for_super(_user(), "create")
        roles_api._require_full_access_for_super(_user(full_access=True), "create")


# ── create_role ──────────────────────────────────────────────────────────────
class TestCreateRole:
    @pytest.mark.asyncio
    async def test_roles_manage_holder_cannot_create_super_role(self):
        body = roles_api.RoleCreateRequest(name="Root", is_super=True)
        with pytest.raises(PermissionDeniedError):
            await roles_api.create_role(body, _user(), TENANT, ExplodingDB())

    @pytest.mark.asyncio
    async def test_cannot_create_role_with_permissions_caller_lacks(self):
        body = roles_api.RoleCreateRequest(name="Payroll", permission_codenames=["payroll.approve"])
        with pytest.raises(PermissionDeniedError):
            await roles_api.create_role(body, _user(), TENANT, ExplodingDB())


# ── update_role ──────────────────────────────────────────────────────────────
class TestUpdateRole:
    @pytest.mark.asyncio
    async def test_cannot_flip_own_role_to_super(self):
        role = _role(is_super=False, codenames=["roles.manage"])
        body = roles_api.RoleUpdateRequest(is_super=True)
        with pytest.raises(PermissionDeniedError):
            await roles_api.update_role(role.id, body, _user(), TENANT, FakeDB(role))
        assert role.is_super is False  # untouched

    @pytest.mark.asyncio
    async def test_cannot_modify_existing_super_role(self):
        role = _role(is_super=True)
        body = roles_api.RoleUpdateRequest(color="#ff0000")
        with pytest.raises(PermissionDeniedError):
            await roles_api.update_role(role.id, body, _user(), TENANT, FakeDB(role))

    @pytest.mark.asyncio
    async def test_cannot_add_permission_caller_does_not_hold(self):
        role = _role(codenames=["roles.manage"])
        body = roles_api.RoleUpdateRequest(permission_codenames=["roles.manage", "payroll.approve"])
        with pytest.raises(PermissionDeniedError):
            await roles_api.update_role(role.id, body, _user(), TENANT, FakeDB(role))
        assert [p.codename for p in role.permissions] == ["roles.manage"]  # untouched


# ── delete / assign / unassign ───────────────────────────────────────────────
class TestDeleteAssignUnassign:
    @pytest.mark.asyncio
    async def test_cannot_delete_super_role(self):
        role = _role(is_super=True)
        with pytest.raises(PermissionDeniedError):
            await roles_api.delete_role(role.id, _user(), TENANT, FakeDB(role))

    @pytest.mark.asyncio
    async def test_cannot_assign_super_role_to_self(self):
        role = _role(is_super=True)
        caller = _user()
        with pytest.raises(PermissionDeniedError):
            await roles_api.assign_role(role.id, caller.id, caller, TENANT, FakeDB(role))

    @pytest.mark.asyncio
    async def test_cannot_assign_role_carrying_more_than_caller_holds(self):
        role = _role(codenames=["payroll.approve"])
        caller = _user()
        with pytest.raises(PermissionDeniedError):
            await roles_api.assign_role(role.id, caller.id, caller, TENANT, FakeDB(role))

    @pytest.mark.asyncio
    async def test_can_assign_role_within_own_permissions(self):
        role = _role(codenames=["leave.view"])
        target = SimpleNamespace(roles=[])
        caller = _user(held=("roles.manage", "leave.view"))
        await roles_api.assign_role(role.id, uuid.uuid4(), caller, TENANT, FakeDB(role, target))
        assert role in target.roles

    @pytest.mark.asyncio
    async def test_full_access_user_can_assign_super_role(self):
        role = _role(is_super=True)
        target = SimpleNamespace(roles=[])
        owner = _user(full_access=True, held=())
        await roles_api.assign_role(role.id, uuid.uuid4(), owner, TENANT, FakeDB(role, target))
        assert role in target.roles

    @pytest.mark.asyncio
    async def test_cannot_strip_super_role_from_someone(self):
        role = _role(is_super=True)
        with pytest.raises(PermissionDeniedError):
            await roles_api.unassign_role(role.id, uuid.uuid4(), _user(), TENANT, FakeDB(role))
