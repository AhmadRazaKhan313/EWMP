"""
Tests for the account-lockout gate (issue #4).

`record_failed_login` has always counted failures and set `locked_until`, but the
check in `AuthService.login` that actually REFUSED a locked account had been
commented out "for testing" — so a locked account could still log in. The gate is
back, behind `LOGIN_LOCKOUT_ENABLED` (default ON), plus a fix for the other half:
once a lock expired the counter stayed at 5, so one typo re-locked the user.

Run:  cd backend && pytest tests/test_login_lockout.py -v
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.core.database as db_mod
import app.services.auth as auth_mod
from app.core.config import settings
from app.core.exceptions import AuthenticationError, InvalidCredentialsError
from app.repositories.user import UserRepository
from app.schemas.auth import LoginSchema
from app.services.auth import AuthService


# ── helpers ──────────────────────────────────────────────────────────────────
def _user(locked_for: timedelta | None = None):
    """locked_for > 0 => currently locked; < 0 => lock already expired; None => never locked."""
    locked_until = None if locked_for is None else datetime.now(UTC) + locked_for
    return SimpleNamespace(
        id=uuid.uuid4(),
        password_hash="$2b$12$" + "a" * 53,  # shape only; verify_password is stubbed
        is_active=True,
        locked_until=locked_until,
        is_locked=locked_until is not None and datetime.now(UTC) < locked_until,
        password_reset_token=None,
        password_reset_expires_at=None,
    )


class _Repo:
    def __init__(self, user):
        self.user = user
        self.cleared = []
        self.failed = []

    async def get_by_email(self, email):
        return self.user

    async def clear_expired_lock(self, user_id):
        self.cleared.append(user_id)

    async def record_failed_login(self, user_id):
        self.failed.append(user_id)


def _service(user):
    svc = AuthService(db=None)
    svc.user_repo = _Repo(user)
    return svc


def _creds():
    return LoginSchema(email="someone@example.com", password="Whatever-1")


@pytest.fixture
def verify_spy(monkeypatch):
    """Replace verify_password; records calls, returns False (wrong password)."""
    calls = []

    def fake(plain, hashed):
        calls.append((plain, hashed))
        return False

    monkeypatch.setattr(auth_mod, "verify_password", fake)
    return calls


# ── the gate ─────────────────────────────────────────────────────────────────
class TestLockoutGate:
    @pytest.mark.asyncio
    async def test_locked_account_is_refused_before_the_password_is_checked(self, verify_spy):
        svc = _service(_user(locked_for=timedelta(minutes=20)))
        with pytest.raises(AuthenticationError) as exc:
            await svc.login(_creds(), "1.2.3.4")
        assert "locked" in str(exc.value).lower()
        assert verify_spy == []  # never confirms (or even tests) a guess while locked
        assert svc.user_repo.failed == []  # and does not extend the lock

    @pytest.mark.asyncio
    async def test_locked_account_is_refused_even_with_the_correct_password(self, monkeypatch):
        monkeypatch.setattr(auth_mod, "verify_password", lambda *a: True)  # right password!
        svc = _service(_user(locked_for=timedelta(minutes=5)))
        with pytest.raises(AuthenticationError):
            await svc.login(_creds(), "1.2.3.4")

    @pytest.mark.asyncio
    async def test_response_carries_retry_after(self, verify_spy):
        svc = _service(_user(locked_for=timedelta(minutes=10)))
        with pytest.raises(AuthenticationError) as exc:
            await svc.login(_creds(), "1.2.3.4")
        retry = int(exc.value.headers["Retry-After"])
        assert 590 <= retry <= 600

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "delta, expected",
        [(timedelta(seconds=30), "1 minute."), (timedelta(minutes=10), "10 minutes.")],
    )
    async def test_message_says_how_long_to_wait(self, verify_spy, delta, expected):
        svc = _service(_user(locked_for=delta))
        with pytest.raises(AuthenticationError) as exc:
            await svc.login(_creds(), "1.2.3.4")
        assert expected in str(exc.value)

    @pytest.mark.asyncio
    async def test_flag_off_skips_the_gate(self, verify_spy, monkeypatch):
        """Dev escape hatch: LOGIN_LOCKOUT_ENABLED=false (no code edit needed)."""
        monkeypatch.setattr(settings, "LOGIN_LOCKOUT_ENABLED", False)
        svc = _service(_user(locked_for=timedelta(minutes=20)))
        with pytest.raises(InvalidCredentialsError):  # got past the gate to the password check
            await svc.login(_creds(), "1.2.3.4")
        assert len(verify_spy) == 1

    def test_lockout_is_on_by_default(self):
        from app.core.config import Settings

        assert Settings.model_fields["LOGIN_LOCKOUT_ENABLED"].default is True


# ── expired locks ────────────────────────────────────────────────────────────
class TestExpiredLock:
    @pytest.mark.asyncio
    async def test_expired_lock_is_cleared_and_login_proceeds(self, verify_spy):
        user = _user(locked_for=timedelta(minutes=-1))  # ran out a minute ago
        svc = _service(user)
        with pytest.raises(InvalidCredentialsError):  # normal wrong-password result
            await svc.login(_creds(), "1.2.3.4")
        assert svc.user_repo.cleared == [user.id]
        assert svc.user_repo.failed == [user.id]  # this attempt counts from a clean slate

    @pytest.mark.asyncio
    async def test_never_locked_user_triggers_no_clear(self, verify_spy):
        svc = _service(_user(locked_for=None))
        with pytest.raises(InvalidCredentialsError):
            await svc.login(_creds(), "1.2.3.4")
        assert svc.user_repo.cleared == []

    @pytest.mark.asyncio
    async def test_flag_off_does_not_clear(self, verify_spy, monkeypatch):
        monkeypatch.setattr(settings, "LOGIN_LOCKOUT_ENABLED", False)
        svc = _service(_user(locked_for=timedelta(minutes=-1)))
        with pytest.raises(InvalidCredentialsError):
            await svc.login(_creds(), "1.2.3.4")
        assert svc.user_repo.cleared == []


# ── repository.clear_expired_lock (same H1 rule as record_failed_login) ──────
class _FakeSession:
    def __init__(self):
        self.executed = []

    async def execute(self, stmt):
        self.executed.append(stmt)


class _ExplodingSession:
    async def execute(self, stmt):
        raise AssertionError("clear_expired_lock must not write on the request session (bug H1)")


class TestClearExpiredLockRepo:
    def test_writes_through_a_dedicated_committed_session(self, monkeypatch):
        fake = _FakeSession()

        @asynccontextmanager
        async def _ctx():
            yield fake

        monkeypatch.setattr(db_mod, "get_db_context", _ctx)
        asyncio.run(UserRepository(_ExplodingSession()).clear_expired_lock(uuid.uuid4()))
        assert len(fake.executed) == 1

    def test_statement_only_touches_locks_that_have_really_expired(self, monkeypatch):
        """The WHERE clause must re-check expiry so a lock applied a moment ago by a
        concurrent attempt is never wiped."""
        fake = _FakeSession()

        @asynccontextmanager
        async def _ctx():
            yield fake

        monkeypatch.setattr(db_mod, "get_db_context", _ctx)
        asyncio.run(UserRepository(_ExplodingSession()).clear_expired_lock(uuid.uuid4()))
        sql = str(fake.executed[0].compile(compile_kwargs={"literal_binds": False})).lower()
        assert "locked_until is not null" in sql
        assert "locked_until <=" in sql
        assert "failed_login_count" in sql
