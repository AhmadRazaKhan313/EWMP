"""
Regression tests for the login path with an UNKNOWN email.

The H2 fix added `security.dummy_password_hash()` (a valid bcrypt hash) and
tested the helper in isolation — but `AuthService.login` kept calling
verify_password() with a hand-typed, malformed literal. passlib raises
ValueError on that instantly, so:

  * an unknown email surfaced as an HTTP 500 instead of a normal 401, and
  * it returned in ~0.3 ms vs ~250 ms for a wrong password (timing oracle).

These tests go through the real `AuthService.login`.

Run:  cd backend && pytest tests/test_auth_login_unknown_email.py -v
"""

import time
from types import SimpleNamespace

import pytest

from app.core.exceptions import InvalidCredentialsError
from app.core.security import hash_password, verify_password
from app.schemas.auth import LoginSchema
from app.services.auth import AuthService


class _Repo:
    """Minimal stand-in for UserRepository."""

    def __init__(self, user=None):
        self._user = user
        self.failed = []

    async def get_by_email(self, email):
        return self._user

    async def record_failed_login(self, user_id):
        self.failed.append(user_id)


def _service(user=None) -> AuthService:
    svc = AuthService(db=None)
    svc.user_repo = _Repo(user)
    return svc


def _login(password="Wrong-password-1"):
    return LoginSchema(email="nobody@example.com", password=password)


@pytest.mark.asyncio
async def test_unknown_email_is_a_401_not_a_crash():
    """Before the fix this raised ValueError (-> HTTP 500)."""
    with pytest.raises(InvalidCredentialsError):
        await _service(user=None).login(_login(), client_ip="127.0.0.1")


@pytest.mark.asyncio
async def test_unknown_email_does_real_bcrypt_work_like_a_wrong_password():
    """Timing must not reveal whether the email exists."""
    real_hash = hash_password("Correct-password-1")
    existing = SimpleNamespace(
        id="u1", password_hash=real_hash, is_active=True, is_locked=False,
        password_reset_token=None, password_reset_expires_at=None,
    )

    # Warm the cached dummy hash so we time verification, not first-use hashing.
    verify_password("warm-up", real_hash)
    try:
        await _service(user=None).login(_login(), "127.0.0.1")
    except InvalidCredentialsError:
        pass

    t = time.perf_counter()
    with pytest.raises(InvalidCredentialsError):
        await _service(user=existing).login(_login(), "127.0.0.1")
    wrong_password_secs = time.perf_counter() - t

    t = time.perf_counter()
    with pytest.raises(InvalidCredentialsError):
        await _service(user=None).login(_login(), "127.0.0.1")
    unknown_email_secs = time.perf_counter() - t

    # Same order of magnitude. (The buggy version was ~1000x faster.)
    assert unknown_email_secs >= 0.5 * wrong_password_secs, (
        f"unknown-email path took {unknown_email_secs*1000:.2f} ms vs "
        f"{wrong_password_secs*1000:.2f} ms for a wrong password"
    )


@pytest.mark.asyncio
async def test_wrong_password_still_records_a_failed_login():
    real_hash = hash_password("Correct-password-1")
    existing = SimpleNamespace(
        id="u1", password_hash=real_hash, is_active=True, is_locked=False,
        password_reset_token=None, password_reset_expires_at=None,
    )
    svc = _service(user=existing)
    with pytest.raises(InvalidCredentialsError):
        await svc.login(_login(), "127.0.0.1")
    assert svc.user_repo.failed == ["u1"]


# ── verify_password hardening ────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["", None, "not-a-hash", "$2b$12$tooshort"])
def test_verify_password_fails_closed_on_malformed_or_missing_hash(bad):
    assert verify_password("anything", bad) is False


def test_verify_password_still_works_for_a_real_hash():
    h = hash_password("Correct-password-1")
    assert verify_password("Correct-password-1", h) is True
    assert verify_password("nope", h) is False
