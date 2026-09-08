"""
Regression tests for the device-enrollment fix (bug C3).

`GET /devices/enrollment-token` and `POST /devices/enroll` used to do
`import jwt as _jwt` (PyJWT) inline, but PyJWT is not a project
dependency — only `python-jose` is (see requirements.txt). On a clean
install both endpoints raised `ModuleNotFoundError` -> 500, so no device
could ever enroll and the entire agent chain (heartbeat, screenshots,
alerts) was dead on arrival.

The fix routes enrollment tokens through the same jose-based helpers the
rest of the app already uses for agent tokens (`create_agent_token` /
`verify_agent_token` in `app/core/security.py`), via two new sibling
helpers `create_device_enrollment_token` / `verify_device_enrollment_token`.

These tests need NO database for the token-level checks. The happy-path
enrollment test fakes the AsyncSession (add/flush) the same way other
tests in this suite fake repositories, so it doesn't need Postgres either.

Run:  cd backend && pytest tests/test_device_enrollment_c3.py -v
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from jose import jwt as jose_jwt

from app.core.config import settings

TENANT = uuid.uuid4()


# ── Guard: the bad import must never come back ─────────────────────────────
def test_devices_module_does_not_import_pyjwt():
    """Static guard: `import jwt` (PyJWT) must not appear in devices.py.

    PyJWT is not in requirements.txt; only `python-jose` is. Re-introducing
    `import jwt` here is exactly bug C3.
    """
    import inspect

    import app.api.v1.devices.devices as devices_mod

    source = inspect.getsource(devices_mod)
    for line in source.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("import jwt") and "import jwt as" not in stripped, (
            f"Found a PyJWT import in devices.py: {line!r} — PyJWT is not "
            "installed on a clean install (see requirements.txt). Use "
            "create_device_enrollment_token/verify_device_enrollment_token "
            "from app.core.security instead."
        )


def test_pyjwt_is_not_actually_installed_in_this_env():
    """Sanity check that we're testing against a clean install, same as prod."""
    assert "jwt" not in sys.modules or sys.modules["jwt"] is jose_jwt, (
        "PyJWT appears to be importable in this environment, which would "
        "mask bug C3. Run in an env with only requirements.txt installed."
    )


# ── Token-level round trip (jose only) ──────────────────────────────────────
def test_enrollment_token_round_trip_uses_jose_only():
    from app.core.security import create_device_enrollment_token, verify_device_enrollment_token

    token = create_device_enrollment_token(str(TENANT))
    payload = verify_device_enrollment_token(token)
    assert payload["tenant_id"] == str(TENANT)
    assert payload["type"] == "device_enrollment"


def test_verify_enrollment_token_rejects_wrong_type():
    """A token minted for a different purpose (e.g. an agent token) must be rejected."""
    from app.core.security import create_agent_token, verify_device_enrollment_token

    agent_token = create_agent_token(str(uuid.uuid4()))
    with pytest.raises(ValueError):
        verify_device_enrollment_token(agent_token)


def test_verify_enrollment_token_rejects_garbage():
    from jose import JWTError

    from app.core.security import verify_device_enrollment_token

    with pytest.raises(JWTError):
        verify_device_enrollment_token("not-a-real-token")


def test_verify_enrollment_token_rejects_expired():
    from jose import JWTError

    from app.core.security import verify_device_enrollment_token

    expired_payload = {
        "tenant_id": str(TENANT),
        "type": "device_enrollment",
        "iat": datetime.now(UTC) - timedelta(days=400),
        "exp": datetime.now(UTC) - timedelta(days=1),
    }
    expired_token = jose_jwt.encode(expired_payload, settings.AGENT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(JWTError):
        verify_device_enrollment_token(expired_token)


# ── Endpoint-level: GET /devices/enrollment-token ───────────────────────────
def test_get_enrollment_token_endpoint_works_without_pyjwt():
    """The actual FastAPI endpoint function must not blow up with ModuleNotFoundError."""
    from app.api.v1.devices.devices import get_enrollment_token

    async def _run():
        user = SimpleNamespace(is_platform_admin=False)
        result = await get_enrollment_token(current_user=user, tenant_id=TENANT)
        assert "enrollment_token" in result
        assert result["expires_in_days"] == 365
        return result

    result = asyncio.run(_run())

    from app.core.security import verify_device_enrollment_token

    payload = verify_device_enrollment_token(result["enrollment_token"])
    assert payload["tenant_id"] == str(TENANT)


# ── Endpoint-level: POST /devices/enroll ────────────────────────────────────
class _FakeAsyncSession:
    """Minimal stand-in for AsyncSession: add() stages, flush() assigns an id."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()


def test_enroll_device_endpoint_rejects_invalid_token():
    from fastapi import HTTPException

    from app.api.v1.devices.devices import EnrollRequest, enroll_device

    async def _run():
        body = EnrollRequest(enrollment_token="garbage", hostname="WIN-TEST")
        with pytest.raises(HTTPException) as exc_info:
            await enroll_device(body=body, db=_FakeAsyncSession())
        assert exc_info.value.status_code == 401

    asyncio.run(_run())


def test_enroll_device_endpoint_rejects_wrong_token_type():
    from fastapi import HTTPException

    from app.api.v1.devices.devices import EnrollRequest, enroll_device
    from app.core.security import create_agent_token

    async def _run():
        wrong_type_token = create_agent_token(str(uuid.uuid4()))
        body = EnrollRequest(enrollment_token=wrong_type_token, hostname="WIN-TEST")
        with pytest.raises(HTTPException) as exc_info:
            await enroll_device(body=body, db=_FakeAsyncSession())
        assert exc_info.value.status_code == 401

    asyncio.run(_run())


def test_enroll_device_endpoint_happy_path_creates_device_and_agent_token():
    from app.api.v1.devices.devices import EnrollRequest, enroll_device
    from app.core.security import create_device_enrollment_token, verify_agent_token

    async def _run():
        enrollment_token = create_device_enrollment_token(str(TENANT))
        body = EnrollRequest(
            enrollment_token=enrollment_token,
            hostname="WIN-TEST-01",
            agent_version="1.0.0",
        )
        db = _FakeAsyncSession()
        result = await enroll_device(body=body, db=db)

        assert "device_id" in result
        assert "agent_token" in result

        # The minted agent token must verify with the *agent* verifier and
        # point at the device we just created.
        agent_payload = verify_agent_token(result["agent_token"])
        assert agent_payload["sub"] == result["device_id"]

        # Exactly one Device was staged with the right tenant + hostname.
        assert len(db.added) == 1
        device = db.added[0]
        assert str(device.tenant_id) == str(TENANT) or device.tenant_id == str(TENANT)
        assert device.hostname == "WIN-TEST-01"
        assert device.is_enrolled is True

    asyncio.run(_run())
