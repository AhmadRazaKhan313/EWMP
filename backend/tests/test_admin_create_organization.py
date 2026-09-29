"""
Tests for POST /admin/organizations — specifically that creating a new
tenant organization results in its owner actually being ABLE to sign in
afterward.

Before this fix, the owner User row was created with a random temp
password shown once on-screen to the platform admin, with no email sent
at all — if the admin didn't manually relay it, the new owner had no way
in. This reuses the exact same forgot-password flow (AuthService.
request_password_reset — same password_reset_token field, same
/auth/reset-password endpoint, same Celery email task) that already
works and is already tested, rather than inventing a second path.

Run:  cd backend && pytest tests/test_admin_create_organization.py -v
"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _run(coro):
    return asyncio.run(coro)


class _FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    """Queues results for db.execute() in call order; add/flush/refresh
    are no-ops, matching how every other test file in this suite treats
    a session that's never actually meant to hit a real database."""

    def __init__(self, results):
        self._queue = list(results)
        self.added = []

    async def execute(self, _stmt):
        if not self._queue:
            raise AssertionError("FakeDB: ran out of queued results.")
        return self._queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def refresh(self, _obj):
        pass


class TestCreateOrganizationEmailsTheOwner:
    def test_calls_request_password_reset_for_the_new_owner(self, monkeypatch):
        from app.api.v1.auth import admin_setup

        fake_role = SimpleNamespace(id=uuid.uuid4())
        reset_calls: list[str] = []

        class _FakeAuthService:
            def __init__(self, db):
                self.db = db

            async def _seed_default_roles(self, org_id):
                return fake_role

            async def request_password_reset(self, email):
                reset_calls.append(email)

        monkeypatch.setattr("app.services.auth.AuthService", _FakeAuthService)

        db = _FakeDB([
            _FakeResult(scalar=None),  # slug uniqueness check — free
            _FakeResult(scalar=None),  # email uniqueness check — free
            _FakeResult(),             # user_roles insert — return value unused
        ])
        current_user = SimpleNamespace(id=uuid.uuid4())
        payload = admin_setup.CreateOrganizationRequest(
            org_name="Acme Inc",
            org_slug="acme-inc",
            owner_first_name="Grace",
            owner_last_name="Hopper",
            owner_email="grace@acme.example",
        )

        result = _run(admin_setup.create_organization(payload, current_user, db))

        assert reset_calls == ["grace@acme.example"]
        # The on-screen fallback stays intact too — belt and suspenders,
        # not a replacement, in case SMTP/Celery isn't configured.
        assert result["owner_email"] == "grace@acme.example"
        assert "owner_temporary_password" in result

    def test_owner_account_has_must_change_password_set(self, monkeypatch):
        from app.api.v1.auth import admin_setup

        fake_role = SimpleNamespace(id=uuid.uuid4())

        class _FakeAuthService:
            def __init__(self, db):
                pass

            async def _seed_default_roles(self, org_id):
                return fake_role

            async def request_password_reset(self, email):
                pass

        monkeypatch.setattr("app.services.auth.AuthService", _FakeAuthService)

        db = _FakeDB([_FakeResult(scalar=None), _FakeResult(scalar=None), _FakeResult()])
        current_user = SimpleNamespace(id=uuid.uuid4())
        payload = admin_setup.CreateOrganizationRequest(
            org_name="Beta LLC",
            org_slug="beta-llc",
            owner_first_name="Ada",
            owner_last_name="Lovelace",
            owner_email="ada@beta.example",
        )

        _run(admin_setup.create_organization(payload, current_user, db))

        owner_rows = [o for o in db.added if hasattr(o, "must_change_password")]
        assert len(owner_rows) == 1
        assert owner_rows[0].must_change_password is True
