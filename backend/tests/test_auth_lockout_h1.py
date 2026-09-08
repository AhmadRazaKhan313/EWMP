"""
Regression tests for the account-lockout fix (bug H1).

Previously `record_failed_login` incremented the counter on the *request*
session (`self.db`). The login flow raises `InvalidCredentialsError` right
after calling it, and `get_db` rolls the request session back on any
exception — so the increment was silently discarded, the counter never rose,
and the 5-attempt lock never triggered (unlimited brute force).

The fix writes through a DEDICATED, self-committing session
(`get_db_context`). These tests monkeypatch that context with a fake session
so they need NO database, and they also assert the method never touches the
request session.

Run:  cd backend && pytest tests/test_auth_lockout_h1.py -v
"""

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest

import app.core.database as db_mod
from app.repositories.user import UserRepository


class _CountResult:
    def __init__(self, n): self._n = n
    def scalar_one(self): return self._n


class _NullResult:
    def scalar_one(self): return None


class _FakeSession:
    """Stands in for the dedicated get_db_context() session.

    Models the persisted row counter across calls (each failed login opens a
    fresh committed transaction, but they all target the same DB row).
    """

    def __init__(self, counter):
        self.counter = counter          # {"n": int} shared across calls
        self.executed = []
        self.locked = False

    async def execute(self, stmt):
        self.executed.append(stmt)
        if "locked_until" in str(stmt):   # the lock UPDATE
            self.locked = True
            return _NullResult()
        self.counter["n"] += 1            # the increment UPDATE (RETURNING count)
        return _CountResult(self.counter["n"])


class _ExplodingSession:
    """The request session — record_failed_login must NEVER write here (H1)."""

    async def execute(self, stmt):
        raise AssertionError(
            "record_failed_login must not write on the request session (bug H1)"
        )


@pytest.fixture
def fake_ctx(monkeypatch):
    session = _FakeSession({"n": 0})

    @asynccontextmanager
    async def _ctx():
        yield session

    monkeypatch.setattr(db_mod, "get_db_context", _ctx)
    return session


def _repo():
    return UserRepository(_ExplodingSession())


def test_increment_uses_dedicated_session_not_request_session(fake_ctx):
    """The write goes through get_db_context (committed), never self.db —
    otherwise the request rollback would discard it."""
    asyncio.run(_repo().record_failed_login(uuid.uuid4()))
    assert len(fake_ctx.executed) == 1     # one increment executed on the fake
    assert fake_ctx.locked is False


def test_locks_after_five_consecutive_failures(fake_ctx):
    repo = _repo()
    uid = uuid.uuid4()
    for _ in range(4):
        asyncio.run(repo.record_failed_login(uid))
    assert fake_ctx.locked is False        # still unlocked at 4 attempts
    asyncio.run(repo.record_failed_login(uid))
    assert fake_ctx.locked is True         # locked on the 5th