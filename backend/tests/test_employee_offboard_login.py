"""
Regression tests for issue #5: offboarding must disable the person's login.

Before: `offboard_employee` only changed a label on the Employee row. The linked
User stayed `is_active=True` (nothing in the codebase ever set it False), so a
terminated employee could still sign in, clock in and read payslips. Setting the
status through PATCH /employees/{id} had the same hole, and needed only the
ordinary `employees.update` permission.

What is pinned here
  * offboard / delete / PATCH-to-terminated/resigned  => User.is_active = False
  * PATCH back to an active status (rehire)           => User.is_active = True
  * the org owner and yourself can never be locked out this way
  * moving to/from an exited status needs `employees.delete` (fail-closed default)
  * a refused request changes NOTHING (guards run before any write)
  * the three places that actually enforce `is_active` keep doing so

Run:  cd backend && pytest tests/test_employee_offboard_login.py -v
"""

import uuid
from types import SimpleNamespace

import pytest

from app.api.v1.hrms import employees as employees_api
from app.core.exceptions import (
    AccountDisabledError,
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
)
from app.models.employee import EmploymentStatus as S
from app.schemas.employee import EmployeeUpdateSchema
from app.services.employee import EmployeeService

TENANT = uuid.uuid4()
HR_ID = uuid.uuid4()  # the person doing the offboarding


# ── fakes ────────────────────────────────────────────────────────────────────
class _Result:
    def __init__(self, value):
        self._v = value

    def scalar_one_or_none(self):
        return self._v


class FakeDB:
    """Answers by SQL text: the owner lookup vs the user lookup."""

    def __init__(self, user, owner_id=None):
        self.user = user
        self.owner_id = owner_id
        self.flushes = 0

    async def execute(self, stmt):
        sql = str(stmt).lower()
        if "from organizations" in sql:
            return _Result(self.owner_id)
        if "from users" in sql:
            return _Result(self.user)
        raise AssertionError(f"unexpected query: {sql[:80]}")

    async def flush(self):
        self.flushes += 1


class FakeRepo:
    def __init__(self, employee):
        self.employee = employee
        self.updates = []
        self.deleted = []

    async def get_or_raise(self, _id):
        return self.employee

    async def update(self, _id, data):
        self.updates.append(dict(data))
        for k, v in data.items():
            setattr(self.employee, k, v)
        return self.employee

    async def delete(self, _id):
        self.deleted.append(_id)


def _setup(status=S.ACTIVE, *, owner=False, self_target=False, user_active=True):
    user = SimpleNamespace(id=uuid.uuid4(), is_active=user_active)
    if self_target:
        user.id = HR_ID
    employee = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, employment_status=status)
    db = FakeDB(user, owner_id=user.id if owner else uuid.uuid4())
    svc = EmployeeService(db, TENANT)
    svc.repo = FakeRepo(employee)
    return svc, employee, user, db


@pytest.fixture(autouse=True)
def _no_celery(monkeypatch):
    """offboard_employee fires a Celery task; never hit a real broker in tests."""
    import app.workers.tasks.notifications as notif

    monkeypatch.setattr(notif, "trigger_workflow_event", SimpleNamespace(delay=lambda *a, **k: None))


def _patch(**fields):
    return EmployeeUpdateSchema(**fields)


# ── /offboard ────────────────────────────────────────────────────────────────
class TestOffboard:
    @pytest.mark.asyncio
    async def test_disables_the_login(self):
        svc, emp, user, _ = _setup()
        from datetime import date

        await svc.offboard_employee(emp.id, date(2026, 9, 30), "resigned", HR_ID)
        assert emp.employment_status == S.TERMINATED
        assert user.is_active is False  # <- the fix

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [S.TERMINATED, S.RESIGNED])
    async def test_already_offboarded_is_rejected_and_touches_nothing(self, status):
        svc, emp, user, _ = _setup(status)
        from datetime import date

        with pytest.raises(ConflictError):
            await svc.offboard_employee(emp.id, date(2026, 9, 30), "x", HR_ID)
        assert svc.repo.updates == []

    @pytest.mark.asyncio
    async def test_organization_owner_cannot_be_offboarded(self):
        svc, emp, user, _ = _setup(owner=True)
        from datetime import date

        with pytest.raises(ConflictError) as exc:
            await svc.offboard_employee(emp.id, date(2026, 9, 30), "x", HR_ID)
        assert "owner" in str(exc.value).lower()
        assert user.is_active is True
        assert svc.repo.updates == []  # nothing half-applied
        assert emp.employment_status == S.ACTIVE

    @pytest.mark.asyncio
    async def test_you_cannot_offboard_yourself(self):
        svc, emp, user, _ = _setup(self_target=True)
        from datetime import date

        with pytest.raises(ConflictError):
            await svc.offboard_employee(emp.id, date(2026, 9, 30), "x", HR_ID)
        assert user.is_active is True and svc.repo.updates == []

    @pytest.mark.asyncio
    async def test_already_disabled_login_is_left_alone(self):
        svc, emp, user, db = _setup(user_active=False)
        from datetime import date

        await svc.offboard_employee(emp.id, date(2026, 9, 30), "x", HR_ID)
        assert user.is_active is False and db.flushes == 0  # no needless write


# ── delete ───────────────────────────────────────────────────────────────────
class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_disables_login_and_soft_deletes(self):
        svc, emp, user, _ = _setup()
        await svc.delete_employee(emp.id, HR_ID)
        assert user.is_active is False
        assert svc.repo.deleted == [emp.id]

    @pytest.mark.asyncio
    async def test_cannot_delete_the_owner(self):
        svc, emp, user, _ = _setup(owner=True)
        with pytest.raises(ConflictError):
            await svc.delete_employee(emp.id, HR_ID)
        assert user.is_active is True and svc.repo.deleted == []

    @pytest.mark.asyncio
    async def test_cannot_delete_yourself(self):
        svc, emp, user, _ = _setup(self_target=True)
        with pytest.raises(ConflictError):
            await svc.delete_employee(emp.id, HR_ID)
        assert svc.repo.deleted == []


# ── PATCH employment_status ──────────────────────────────────────────────────
class TestUpdateStatus:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", [S.TERMINATED, S.RESIGNED])
    async def test_patching_to_exited_disables_login(self, target):
        svc, emp, user, _ = _setup()
        await svc.update_employee(emp.id, _patch(employment_status=target), HR_ID, can_manage_exit=True)
        assert user.is_active is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", [S.TERMINATED, S.RESIGNED])
    async def test_ordinary_update_permission_cannot_terminate(self, target):
        """The hole: `employees.update` alone used to be enough to flip status."""
        svc, emp, user, _ = _setup()
        with pytest.raises(PermissionDeniedError):
            await svc.update_employee(emp.id, _patch(employment_status=target), HR_ID)
        assert user.is_active is True and svc.repo.updates == []

    @pytest.mark.asyncio
    async def test_default_is_fail_closed(self):
        svc, emp, _, _ = _setup()
        with pytest.raises(PermissionDeniedError):
            await svc.update_employee(emp.id, _patch(employment_status=S.TERMINATED), HR_ID)

    @pytest.mark.asyncio
    async def test_rehire_reenables_login(self):
        svc, emp, user, _ = _setup(S.TERMINATED, user_active=False)
        await svc.update_employee(emp.id, _patch(employment_status=S.ACTIVE), HR_ID, can_manage_exit=True)
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_rehire_needs_the_permission_too(self):
        svc, emp, user, _ = _setup(S.RESIGNED, user_active=False)
        with pytest.raises(PermissionDeniedError):
            await svc.update_employee(emp.id, _patch(employment_status=S.ACTIVE), HR_ID)
        assert user.is_active is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", [S.PROBATION, S.ON_LEAVE, S.NOTICE_PERIOD, S.ACTIVE])
    async def test_ordinary_status_changes_need_no_special_permission_and_keep_login(self, target):
        svc, emp, user, db = _setup(S.ACTIVE)
        await svc.update_employee(emp.id, _patch(employment_status=target), HR_ID)
        assert user.is_active is True and db.flushes == 0

    @pytest.mark.asyncio
    async def test_moving_between_exited_statuses_changes_nothing_for_login(self):
        svc, emp, user, _ = _setup(S.TERMINATED, user_active=False)
        await svc.update_employee(emp.id, _patch(employment_status=S.RESIGNED), HR_ID)  # no perm needed
        assert user.is_active is False

    @pytest.mark.asyncio
    async def test_cannot_terminate_the_owner_via_patch(self):
        svc, emp, user, _ = _setup(owner=True)
        with pytest.raises(ConflictError):
            await svc.update_employee(emp.id, _patch(employment_status=S.TERMINATED), HR_ID, can_manage_exit=True)
        assert user.is_active is True and svc.repo.updates == []

    @pytest.mark.asyncio
    async def test_cannot_terminate_yourself_via_patch(self):
        svc, emp, user, _ = _setup(self_target=True)
        with pytest.raises(ConflictError):
            await svc.update_employee(emp.id, _patch(employment_status=S.TERMINATED), HR_ID, can_manage_exit=True)
        assert svc.repo.updates == []

    @pytest.mark.asyncio
    async def test_unrelated_edits_are_unaffected(self):
        svc, emp, user, db = _setup()
        await svc.update_employee(emp.id, _patch(phone="+1 555 0100"), HR_ID)
        assert user.is_active is True and db.flushes == 0


# ── the endpoints wire permissions/service correctly ─────────────────────────
class _CapturingService:
    calls = []

    def __init__(self, db, tenant_id):
        pass

    async def update_employee(self, employee_id, data, user_id, **kw):
        _CapturingService.calls.append(("update", kw))
        return SimpleNamespace(id=employee_id)

    async def delete_employee(self, employee_id, user_id):
        _CapturingService.calls.append(("delete", user_id))


def _caller(*perms):
    return SimpleNamespace(id=HR_ID, has_permission=lambda code: code in perms)


class TestEndpoints:
    @pytest.fixture(autouse=True)
    def _patch_service(self, monkeypatch):
        _CapturingService.calls = []
        monkeypatch.setattr(employees_api, "EmployeeService", _CapturingService)

    @pytest.mark.asyncio
    async def test_update_passes_offboard_permission_as_can_manage_exit(self):
        body = EmployeeUpdateSchema(employment_status=S.TERMINATED)
        await employees_api.update_employee(uuid.uuid4(), body, _caller("employees.delete"), TENANT, None)
        await employees_api.update_employee(uuid.uuid4(), body, _caller("employees.update"), TENANT, None)
        assert [c[1]["can_manage_exit"] for c in _CapturingService.calls] == [True, False]

    @pytest.mark.asyncio
    async def test_delete_goes_through_the_service(self):
        await employees_api.delete_employee(uuid.uuid4(), _caller("employees.delete"), TENANT, None)
        assert _CapturingService.calls == [("delete", HR_ID)]


# ── the enforcement points this fix relies on (pinned so they can't regress) ─
def _inactive_user():
    return SimpleNamespace(
        id=uuid.uuid4(), is_active=False, password_hash="$2b$12$" + "a" * 53,
        locked_until=None, is_locked=False, organization=None,
    )


class TestDisabledUserIsShutOut:
    @pytest.mark.asyncio
    async def test_existing_access_token_stops_working_immediately(self, monkeypatch):
        """get_current_user reads the DB on every request, so an already-issued
        access token dies the moment is_active flips — no waiting for expiry."""
        from app.permissions import dependencies as deps

        user = _inactive_user()

        async def fake_get(self, user_id):
            return user

        monkeypatch.setattr(deps.UserRepository, "get_with_roles", fake_get)
        with pytest.raises(AccountDisabledError):
            await deps.get_current_user(request=None, payload={"sub": str(user.id)}, db=None)

    @pytest.mark.asyncio
    async def test_refresh_token_is_rejected(self, monkeypatch):
        import app.services.auth as auth_mod
        from app.services.auth import AuthService

        user = _inactive_user()
        monkeypatch.setattr(auth_mod, "verify_refresh_token", lambda t: {"sub": str(user.id)})

        class Repo:
            async def get(self, _id):
                return user

        svc = AuthService(db=None)
        svc.user_repo = Repo()
        with pytest.raises(AuthenticationError):
            await svc.refresh_tokens("whatever")

    @pytest.mark.asyncio
    async def test_login_is_refused_even_with_the_correct_password(self, monkeypatch):
        import app.services.auth as auth_mod
        from app.schemas.auth import LoginSchema
        from app.services.auth import AuthService

        user = _inactive_user()
        monkeypatch.setattr(auth_mod, "verify_password", lambda *a: True)

        class Repo:
            async def get_by_email(self, email):
                return user

        svc = AuthService(db=None)
        svc.user_repo = Repo()
        with pytest.raises(AuthenticationError) as exc:
            await svc.login(LoginSchema(email="gone@example.com", password="Right-password-1"), "1.2.3.4")
        assert "disabled" in str(exc.value).lower()
