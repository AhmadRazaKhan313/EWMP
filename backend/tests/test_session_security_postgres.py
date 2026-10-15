"""
Regression tests for audit finding H-6 (session security).

Before the fix:
  * /auth/refresh never rotated or revoked: the same refresh token could be
    replayed for its whole 7 days, through logout and password changes;
  * /auth/logout did nothing on the server;
  * a password change/reset left every existing session alive;
  * `must_change_password` was only a UI modal -- the API itself was fully
    usable on a temporary password;
  * there was no absolute cap on a session's life.

Real HTTP stack against a live Postgres (TEST_DATABASE_URL), like the other
*_postgres tests. Only HTTP + raw SQL are used, so the same file can be run
against the pre-fix code to prove the bugs were real.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.main import app
from app.models.organization import Organization
from app.models.user import User

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ewmp:ewmp123@localhost:5432/ewmp",
)

pytestmark = pytest.mark.asyncio

PASSWORD = "Str0ngPassw0rd!x"
NEW_PASSWORD = "An0therStr0ngPass!"


@pytest.fixture(autouse=True)
def _generous_rate_limits(monkeypatch):
    # Each test logs in a few times as the same address.
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_EMAIL_PER_MINUTE", 1000)
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_IP_PER_MINUTE", 1000)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE", 1000)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    async def _get_db():
        async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


async def _make_user(engine, *, must_change=False) -> dict:
    org_id = uuid.uuid4()
    email = f"sess-{uuid.uuid4().hex[:10]}@example.com"
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(Organization(id=org_id, name="Sess Org", slug=f"sess-{org_id.hex[:8]}",
                           email=f"o-{org_id.hex[:8]}@example.com"))
        await s.flush()
        user = User(organization_id=org_id, email=email, email_normalized=email,
                    password_hash=hash_password(PASSWORD), first_name="Sess", last_name="User",
                    is_active=True, is_email_verified=True, must_change_password=must_change)
        s.add(user)
        await s.flush()
        (await s.get(Organization, org_id)).owner_id = user.id  # owner => full access
        ids = {"org": org_id, "user": user.id, "email": email}
        await s.commit()
    return ids


@pytest_asyncio.fixture
async def account(engine):
    ids = await _make_user(engine)
    yield ids
    await _cleanup(engine, ids)


@pytest_asyncio.fixture
async def temp_account(engine):
    ids = await _make_user(engine, must_change=True)
    yield ids
    await _cleanup(engine, ids)


async def _cleanup(engine, ids):
    async with AsyncSession(engine) as s:
        await s.execute(text("DELETE FROM auth_refresh_tokens WHERE user_id = :u"), {"u": ids["user"]})
        await s.execute(text("UPDATE organizations SET owner_id = NULL WHERE id = :o"), {"o": ids["org"]})
        await s.execute(delete(User).where(User.organization_id == ids["org"]))
        await s.execute(delete(Organization).where(Organization.id == ids["org"]))
        await s.commit()


async def _login(client, acct, password=PASSWORD) -> dict:
    r = await client.post("/api/v1/auth/login", json={"email": acct["email"], "password": password})
    assert r.status_code == 200, r.text
    return r.json()["tokens"]


def _bearer(access) -> dict:
    return {"Authorization": f"Bearer {access}"}


async def _refresh(client, refresh_token):
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})


def _jti(refresh_token) -> str:
    from jose import jwt
    return jwt.get_unverified_claims(refresh_token)["jti"]


async def _sql(engine, sql, **params):
    async with AsyncSession(engine) as s:
        res = await s.execute(text(sql), params)
        await s.commit()
        return res


# ── Refresh-token rotation ────────────────────────────────────────────────────

class TestRefreshRotation:
    async def test_refresh_returns_a_new_working_pair(self, client, account):
        t1 = await _login(client, account)
        r = await _refresh(client, t1["refresh_token"])
        assert r.status_code == 200, r.text
        t2 = r.json()
        assert t2["refresh_token"] != t1["refresh_token"]
        me = await client.get("/api/v1/auth/me", headers=_bearer(t2["access_token"]))
        assert me.status_code == 200

    async def test_a_used_refresh_token_cannot_be_used_again(self, client, account):
        """THE core bug: the same refresh token minted new tokens forever."""
        t1 = await _login(client, account)
        assert (await _refresh(client, t1["refresh_token"])).status_code == 200
        replay = await _refresh(client, t1["refresh_token"])
        assert replay.status_code == 401, "a spent refresh token was accepted again"

    async def test_replaying_a_stolen_token_kills_the_whole_session(self, client, engine, account):
        """If the OLD token comes back after the grace window, someone copied it:
        the legitimate client's newer token must stop working too."""
        t1 = await _login(client, account)
        t2 = (await _refresh(client, t1["refresh_token"])).json()
        # Age the use past the grace window.
        await _sql(engine, "UPDATE auth_refresh_tokens SET used_at = :t WHERE jti = :j",
                   t=datetime.now(UTC) - timedelta(minutes=5), j=_jti(t1["refresh_token"]))
        assert (await _refresh(client, t1["refresh_token"])).status_code == 401
        assert (await _refresh(client, t2["refresh_token"])).status_code == 401, (
            "the session survived a detected token theft"
        )

    async def test_two_refreshes_at_once_only_lose_the_loser(self, client, account):
        """A client firing the same refresh twice must not be logged out."""
        t1 = await _login(client, account)
        t2 = (await _refresh(client, t1["refresh_token"])).json()
        loser = await _refresh(client, t1["refresh_token"])  # inside the grace window
        assert loser.status_code == 401
        assert (await _refresh(client, t2["refresh_token"])).status_code == 200

    async def test_token_without_a_server_record_is_rejected(self, client, account):
        """Validly signed but untracked -- e.g. issued before this fix."""
        legacy = create_refresh_token(str(account["user"]))
        assert (await _refresh(client, legacy)).status_code == 401

    async def test_access_token_is_not_a_refresh_token(self, client, account):
        t1 = await _login(client, account)
        assert (await _refresh(client, t1["access_token"])).status_code == 401


# ── Logout ────────────────────────────────────────────────────────────────────

class TestLogout:
    async def test_logout_revokes_the_refresh_token(self, client, account):
        t = await _login(client, account)
        r = await client.post("/api/v1/auth/logout", headers=_bearer(t["access_token"]),
                              json={"refresh_token": t["refresh_token"]})
        assert r.status_code == 200
        assert (await _refresh(client, t["refresh_token"])).status_code == 401, (
            "logout left the refresh token usable"
        )

    async def test_logout_only_ends_that_session(self, client, account):
        laptop = await _login(client, account)
        phone = await _login(client, account)
        await client.post("/api/v1/auth/logout", headers=_bearer(laptop["access_token"]),
                          json={"refresh_token": laptop["refresh_token"]})
        assert (await _refresh(client, phone["refresh_token"])).status_code == 200

    async def test_logout_still_works_without_a_body(self, client, account):
        t = await _login(client, account)
        r = await client.post("/api/v1/auth/logout", headers=_bearer(t["access_token"]))
        assert r.status_code == 200

    async def test_cannot_log_out_someone_elses_session(self, client, engine, account):
        other = await _make_user(engine)
        try:
            victim = await _login(client, other)
            mine = await _login(client, account)
            await client.post("/api/v1/auth/logout", headers=_bearer(mine["access_token"]),
                              json={"refresh_token": victim["refresh_token"]})
            assert (await _refresh(client, victim["refresh_token"])).status_code == 200
        finally:
            await _cleanup(engine, other)


# ── Password change / reset ends sessions ─────────────────────────────────────

class TestPasswordChangeEndsSessions:
    async def _change(self, client, tokens, current=PASSWORD, new=NEW_PASSWORD):
        return await client.post("/api/v1/auth/change-password", headers=_bearer(tokens["access_token"]),
                                 json={"current_password": current, "new_password": new,
                                       "confirm_password": new})

    async def test_other_sessions_refresh_tokens_die(self, client, account):
        laptop = await _login(client, account)
        stolen = await _login(client, account)
        assert (await self._change(client, laptop)).status_code == 200
        assert (await _refresh(client, stolen["refresh_token"])).status_code == 401, (
            "a session from before the password change survived it"
        )

    async def test_other_sessions_access_tokens_die(self, client, account):
        """An access token minted before the change must stop working at once
        rather than living out its 30 minutes."""
        before = datetime.now(UTC) - timedelta(minutes=10)
        old_access = create_access_token(str(account["user"]), extra_claims={"iat": before})
        t = await _login(client, account)
        assert (await client.get("/api/v1/auth/me", headers=_bearer(old_access))).status_code == 200
        assert (await self._change(client, t)).status_code == 200
        assert (await client.get("/api/v1/auth/me", headers=_bearer(old_access))).status_code == 401

    async def test_the_changing_device_stays_signed_in(self, client, account):
        t = await _login(client, account)
        r = await self._change(client, t)
        assert r.status_code == 200
        fresh = r.json()["tokens"]
        assert (await client.get("/api/v1/auth/me", headers=_bearer(fresh["access_token"]))).status_code == 200
        assert (await _refresh(client, fresh["refresh_token"])).status_code == 200

    async def test_wrong_current_password_changes_nothing(self, client, account):
        t = await _login(client, account)
        other = await _login(client, account)
        r = await self._change(client, t, current="not-the-password")
        assert r.status_code in (400, 401)
        assert (await _refresh(client, other["refresh_token"])).status_code == 200

    async def test_password_reset_ends_every_session(self, client, engine, account):
        t = await _login(client, account)
        await _sql(engine, "UPDATE users SET password_reset_token = 'reset-tok-h6', "
                           "password_reset_expires_at = :e WHERE id = :u",
                   e=datetime.now(UTC) + timedelta(hours=1), u=account["user"])
        r = await client.post("/api/v1/auth/reset-password", json={
            "token": "reset-tok-h6", "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD})
        assert r.status_code == 200, r.text
        assert (await _refresh(client, t["refresh_token"])).status_code == 401


# ── Absolute session lifetime ─────────────────────────────────────────────────

class TestSessionLifetime:
    async def test_a_session_cannot_be_refreshed_past_its_absolute_end(self, client, engine, account):
        t = await _login(client, account)
        await _sql(engine, "UPDATE auth_refresh_tokens SET session_expires_at = :e WHERE user_id = :u",
                   e=datetime.now(UTC) - timedelta(seconds=1), u=account["user"])
        assert (await _refresh(client, t["refresh_token"])).status_code == 401

    async def test_rotated_tokens_never_outlive_the_session(self, client, engine, account):
        t = await _login(client, account)
        end = datetime.now(UTC) + timedelta(days=1)
        await _sql(engine, "UPDATE auth_refresh_tokens SET session_expires_at = :e WHERE user_id = :u",
                   e=end, u=account["user"])
        t2 = (await _refresh(client, t["refresh_token"])).json()
        row = (await _sql(engine, "SELECT expires_at, session_expires_at FROM auth_refresh_tokens WHERE jti = :j",
                          j=_jti(t2["refresh_token"]))).one()
        assert row.session_expires_at == end
        assert row.expires_at <= end  # clamped from the usual 7 days to 1


# ── must_change_password is enforced by the API ───────────────────────────────

class TestMustChangePasswordIsEnforced:
    async def test_api_is_blocked_until_the_password_is_changed(self, client, temp_account):
        t = await _login(client, temp_account)
        blocked = await client.get("/api/v1/employees", headers=_bearer(t["access_token"]))
        assert blocked.status_code == 403, "an account on a temporary password could use the API"
        assert "PASSWORD_CHANGE_REQUIRED" in blocked.text

    async def test_the_change_password_flow_itself_stays_reachable(self, client, temp_account):
        t = await _login(client, temp_account)
        me = await client.get("/api/v1/auth/me", headers=_bearer(t["access_token"]))
        assert me.status_code == 200 and me.json()["must_change_password"] is True
        r = await client.post("/api/v1/auth/change-password", headers=_bearer(t["access_token"]),
                              json={"current_password": PASSWORD, "new_password": NEW_PASSWORD,
                                    "confirm_password": NEW_PASSWORD})
        assert r.status_code == 200, r.text
        fresh = r.json()["tokens"]
        ok = await client.get("/api/v1/employees", headers=_bearer(fresh["access_token"]))
        assert ok.status_code == 200, ok.text

    async def test_logout_is_allowed_on_a_temporary_password(self, client, temp_account):
        t = await _login(client, temp_account)
        r = await client.post("/api/v1/auth/logout", headers=_bearer(t["access_token"]),
                              json={"refresh_token": t["refresh_token"]})
        assert r.status_code == 200

    async def test_refresh_still_works_so_the_ui_does_not_loop_to_login(self, client, temp_account):
        t = await _login(client, temp_account)
        assert (await _refresh(client, t["refresh_token"])).status_code == 200

    async def test_normal_accounts_are_unaffected(self, client, account):
        t = await _login(client, account)
        assert (await client.get("/api/v1/employees", headers=_bearer(t["access_token"]))).status_code == 200


# ── Races and re-enabled accounts ─────────────────────────────────────────────

class TestRaceAndReenable:
    async def test_the_same_token_refreshed_concurrently_succeeds_exactly_once(self, client, account):
        """Single-use has to hold under a real race, not just sequentially."""
        import asyncio

        t = await _login(client, account)
        results = await asyncio.gather(*[_refresh(client, t["refresh_token"]) for _ in range(6)])
        codes = sorted(r.status_code for r in results)
        assert codes == [200] + [401] * 5, codes

    async def test_reenabling_a_login_does_not_resurrect_old_sessions(self, client, engine, account):
        """Offboard -> rehire: a copied refresh token from the first stint must
        not start working again just because is_active flipped back."""
        import types
        from app.services.employee import EmployeeService

        t = await _login(client, account)
        emp = types.SimpleNamespace(user_id=account["user"])
        async with AsyncSession(engine) as s:
            svc = EmployeeService(s, account["org"])
            await svc._set_login_active(emp, False)
            await s.commit()
        async with AsyncSession(engine) as s:
            await EmployeeService(s, account["org"])._set_login_active(emp, True)
            await s.commit()
        assert (await _refresh(client, t["refresh_token"])).status_code == 401
        fresh = await _login(client, account)  # a normal sign-in works again
        assert (await _refresh(client, fresh["refresh_token"])).status_code == 200
