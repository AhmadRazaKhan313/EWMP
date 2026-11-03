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
