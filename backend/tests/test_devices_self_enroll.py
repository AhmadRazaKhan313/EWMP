"""
Regression tests for POST /devices/self-enroll.

Bug: `self_enroll_device` called `EmployeeRepository(db)` — missing the
required `tenant_id` positional arg (EmployeeRepository.__init__(self, db,
tenant_id)) — so EVERY self-enroll call raised:

    TypeError: EmployeeRepository.__init__() missing 1 required
    positional argument: 'tenant_id'

...which FastAPI's generic exception handler turned into a 500. This was
never caught because no test exercised this endpoint at all. Reproduced
live against a real Postgres-backed server before fixing: the desktop
app's Check-In worked, login worked, but the device NEVER appeared in
the admin panel's fleet table, no matter how many times the employee
logged in — every single self-enroll attempt failed identically.

Fix: `EmployeeRepository(db, tenant_id)`, matching the (correct) pattern
already used in app/api/v1/hrms/work_sessions.py's _resolve_own_employee_id.

Run:  cd backend && pytest tests/test_devices_self_enroll.py -v
"""
import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.v1.devices.devices import SelfEnrollRequest, self_enroll_device
from app.models.devices import Device, DeviceStatus

TENANT = uuid.uuid4()
EMP_ID = uuid.uuid4()


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
            raise AssertionError("FakeDB: ran out of queued results.")
        return self._queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()


class _FakeEmployeeRepo:
    """Records the exact args it was constructed with — this is what
    catches the bug: the real EmployeeRepository requires (db, tenant_id)
    and raises TypeError if tenant_id is omitted, exactly as production
    did. Asserting on init_args (rather than just calling it) means this
    test fails the same way the real bug did if someone regresses the
    call site back to EmployeeRepository(db)."""

    own_employee = None
    last_init_args = None

    def __init__(self, db, tenant_id):
        type(self).last_init_args = (db, tenant_id)

    async def get_by_user_id(self, user_id):
        return type(self).own_employee


@pytest.fixture(autouse=True)
def _patch_repo(monkeypatch):
    import app.api.v1.devices.devices as devices_mod

    _FakeEmployeeRepo.own_employee = SimpleNamespace(id=EMP_ID)
    _FakeEmployeeRepo.last_init_args = None
    monkeypatch.setattr(devices_mod, "EmployeeRepository", _FakeEmployeeRepo)


def _run(coro):
    return asyncio.run(coro)


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def _body(**overrides):
    defaults = dict(
        hostname="test-host", os_type="linux", os_name="linux", os_version="6.0",
        cpu_model="cpu", cpu_cores=8, ram_total_gb=16.0, mac_address="aa:bb:cc:dd:ee:ff",
        agent_version="0.1.0", consent_acknowledged=True,
    )
    defaults.update(overrides)
    return SelfEnrollRequest(**defaults)


class TestSelfEnrollDevice:
    def test_calls_employee_repository_with_tenant_id(self):
        """The actual regression guard: this is exactly the call the
        TypeError was raised from."""
        db = _FakeDB([_FakeResult(scalar=None)])
        _run(self_enroll_device(body=_body(), current_user=_user(), tenant_id=TENANT, db=db))
        assert _FakeEmployeeRepo.last_init_args == (db, TENANT)

    def test_rejects_without_consent(self):
        from fastapi import HTTPException

        db = _FakeDB([])
        with pytest.raises(HTTPException) as exc_info:
            _run(
                self_enroll_device(
                    body=_body(consent_acknowledged=False), current_user=_user(), tenant_id=TENANT, db=db
                )
            )
        assert exc_info.value.status_code == 400

    def test_rejects_when_no_employee_linked(self):
        from fastapi import HTTPException

        _FakeEmployeeRepo.own_employee = None
        db = _FakeDB([])
        with pytest.raises(HTTPException) as exc_info:
            _run(self_enroll_device(body=_body(), current_user=_user(), tenant_id=TENANT, db=db))
        assert exc_info.value.status_code == 400
        assert "No employee record" in exc_info.value.detail

    def test_creates_a_new_device_and_returns_credentials(self):
        db = _FakeDB([_FakeResult(scalar=None)])
        result = _run(self_enroll_device(body=_body(), current_user=_user(), tenant_id=TENANT, db=db))

        assert "device_id" in result
        assert "agent_token" in result
        assert len(db.added) == 1
        device = db.added[0]
        assert device.tenant_id == TENANT
        assert device.hostname == "test-host"
        assert device.assigned_employee_id == EMP_ID
        assert device.status == DeviceStatus.ONLINE
        assert device.is_enrolled is True

    def test_second_enroll_same_hostname_updates_instead_of_duplicating(self):
        """Idempotency: logging in from the same machine twice must not
        create a second fleet row."""
        existing = Device(
            id=uuid.uuid4(), tenant_id=TENANT, hostname="test-host", device_name="test-host",
            agent_id=str(uuid.uuid4()), agent_token_hash="old", os_type="linux",
            assigned_employee_id=EMP_ID, is_enrolled=True, status=DeviceStatus.OFFLINE,
            last_seen_at=datetime.now(UTC),
        )
        db = _FakeDB([_FakeResult(scalar=existing)])
        result = _run(
            self_enroll_device(body=_body(os_version="6.5"), current_user=_user(), tenant_id=TENANT, db=db)
        )

        assert result["device_id"] == str(existing.id)
        assert len(db.added) == 0  # updated in place, never re-added
        assert existing.os_version == "6.5"
        assert existing.status == DeviceStatus.ONLINE
