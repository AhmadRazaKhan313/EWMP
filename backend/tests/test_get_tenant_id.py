"""
Regression tests for the cross-tenant isolation fix (bug C1).

`get_tenant_id` must only honor the `X-Tenant-ID` header for platform
admins. A regular (non-platform-admin) user who sends `X-Tenant-ID`
pointing at another organization must still be scoped to their OWN
organization — otherwise any authenticated user can read/write another
tenant's data by spoofing the header.

These tests call `get_tenant_id` directly with lightweight fakes, so they
need NO database — only the `app` package importable (env configured).

Run:  cd backend && pytest tests/test_get_tenant_id.py -v
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.core.exceptions import AuthenticationError, TenantAccessDeniedError
from app.permissions.dependencies import get_tenant_id

OWN = uuid.uuid4()
OTHER = uuid.uuid4()


class _FakeHeaders:
    """Minimal case-insensitive stand-in for Starlette's Headers."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    def get(self, key: str, default=None):
        for k, v in self._data.items():
            if k.lower() == key.lower():
                return v
        return default


class _FakeRequest:
    def __init__(self, headers: dict | None = None) -> None:
        self.headers = _FakeHeaders(headers)


def _user(*, org_id, is_platform_admin: bool = False):
    return SimpleNamespace(organization_id=org_id, is_platform_admin=is_platform_admin)


def _run(request, user):
    # get_tenant_id is async; call it directly (bypassing FastAPI DI).
    return asyncio.run(get_tenant_id(request=request, user=user))


def test_regular_user_cannot_override_tenant_via_header():
    """THE security assertion: a spoofed X-Tenant-ID is ignored for a
    normal user, who stays scoped to their own org."""
    req = _FakeRequest({"X-Tenant-ID": str(OTHER)})
    user = _user(org_id=OWN, is_platform_admin=False)
    assert _run(req, user) == OWN


def test_regular_user_without_header_uses_own_org():
    req = _FakeRequest({})
    user = _user(org_id=OWN, is_platform_admin=False)
    assert _run(req, user) == OWN


def test_platform_admin_can_target_org_via_header():
    req = _FakeRequest({"X-Tenant-ID": str(OTHER)})
    user = _user(org_id=None, is_platform_admin=True)
    assert _run(req, user) == OTHER


def test_platform_admin_without_header_falls_back_to_own_org():
    req = _FakeRequest({})
    user = _user(org_id=OWN, is_platform_admin=True)
    assert _run(req, user) == OWN


def test_platform_admin_without_header_and_no_org_is_rejected():
    req = _FakeRequest({})
    user = _user(org_id=None, is_platform_admin=True)
    with pytest.raises(TenantAccessDeniedError):
        _run(req, user)


def test_platform_admin_invalid_header_rejected():
    req = _FakeRequest({"X-Tenant-ID": "not-a-uuid"})
    user = _user(org_id=None, is_platform_admin=True)
    with pytest.raises(AuthenticationError):
        _run(req, user)


def test_user_with_no_org_rejected():
    req = _FakeRequest({})
    user = _user(org_id=None, is_platform_admin=False)
    with pytest.raises(TenantAccessDeniedError):
        _run(req, user)