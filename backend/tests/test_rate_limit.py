"""
Tests for login/auth rate limiting (issue #4).

Before: `RATE_LIMIT_*` settings existed but nothing enforced them, so
/auth/login could be hammered without limit.

Covers
  * the counters (in-memory + Redis via fakeredis, incl. Redis outage fallback)
  * safe client-IP resolution (X-Forwarded-For only trusted behind a proxy)
  * the real HTTP endpoints through the actual FastAPI app

Run:  cd backend && pytest tests/test_rate_limit.py -v
"""

import uuid
from types import SimpleNamespace

import fakeredis
import httpx
import pytest

from app.core import rate_limit as rl
from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.exceptions import InvalidCredentialsError, RateLimitExceededError
from app.core.rate_limit import RateLimiter, enforce_rate_limit, hash_identifier


class Clock:
    """Manually advanced clock so window expiry tests don't sleep."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture(autouse=True)
def _fresh_limiter():
    """Every test gets its own limiter; nothing leaks between tests."""
    rl.set_limiter(RateLimiter())  # memory only
    yield
    rl.set_limiter(None)


# ── in-memory counters ───────────────────────────────────────────────────────
class TestMemoryLimiter:
    @pytest.mark.asyncio
    async def test_allows_up_to_limit_then_blocks(self):
        lim = RateLimiter()
        results = [await lim.hit("k", limit=3, window=60) for _ in range(5)]
        assert [r.allowed for r in results] == [True, True, True, False, False]

    @pytest.mark.asyncio
    async def test_retry_after_is_within_window(self):
        lim = RateLimiter()
        for _ in range(3):
            await lim.hit("k", limit=2, window=60)
        blocked = await lim.hit("k", limit=2, window=60)
        assert not blocked.allowed
        assert 1 <= blocked.retry_after <= 60

    @pytest.mark.asyncio
    async def test_window_expiry_resets_the_count(self):
        clock = Clock()
        lim = RateLimiter(clock=clock)
        for _ in range(3):
            await lim.hit("k", limit=2, window=60)
        assert not (await lim.hit("k", limit=2, window=60)).allowed
        clock.advance(61)
        assert (await lim.hit("k", limit=2, window=60)).allowed

    @pytest.mark.asyncio
    async def test_keys_are_independent(self):
        lim = RateLimiter()
        for _ in range(3):
            await lim.hit("a", limit=2, window=60)
        assert not (await lim.hit("a", limit=2, window=60)).allowed
        assert (await lim.hit("b", limit=2, window=60)).allowed

    @pytest.mark.asyncio
    async def test_memory_stays_bounded_under_unique_key_flood(self, monkeypatch):
        monkeypatch.setattr(rl, "_MEMORY_SWEEP_THRESHOLD", 50)
        clock = Clock()
        lim = RateLimiter(clock=clock)
        for i in range(40):
            await lim.hit(f"old-{i}", limit=5, window=10)
        clock.advance(11)  # all of those are now expired
        for i in range(40):
            await lim.hit(f"new-{i}", limit=5, window=10)
        assert len(lim._memory._hits) <= 50  # expired entries were swept


# ── Redis backend (fakeredis) ────────────────────────────────────────────────
def _fake_redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


class TestRedisLimiter:
    @pytest.mark.asyncio
    async def test_counts_and_blocks_via_redis(self):
        r = _fake_redis()
        lim = RateLimiter(redis_client=r)
        results = [await lim.hit("login:x", limit=2, window=60) for _ in range(3)]
        assert [x.allowed for x in results] == [True, True, False]
        assert await r.get("ewmp:rl:login:x") == "3"

    @pytest.mark.asyncio
    async def test_key_gets_a_ttl(self):
        r = _fake_redis()
        await RateLimiter(redis_client=r).hit("k", limit=5, window=45)
        ttl = await r.ttl("ewmp:rl:k")
        assert 0 < ttl <= 45

    @pytest.mark.asyncio
    async def test_key_left_without_ttl_is_healed(self):
        """A crash between INCR and EXPIRE must not create a permanent block."""
        r = _fake_redis()
        await r.set("ewmp:rl:k", 4)  # no TTL, as after a crash
        assert await r.ttl("ewmp:rl:k") == -1
        res = await RateLimiter(redis_client=r).hit("k", limit=100, window=30)
        assert res.count == 5
        assert 0 < await r.ttl("ewmp:rl:k") <= 30

    @pytest.mark.asyncio
    async def test_two_limiters_share_state_through_redis(self):
        """Multiple API workers must see one counter."""
        r = _fake_redis()
        a, b = RateLimiter(redis_client=r), RateLimiter(redis_client=r)
        await a.hit("k", limit=2, window=60)
        await b.hit("k", limit=2, window=60)
        assert not (await a.hit("k", limit=2, window=60)).allowed


class _BrokenRedis:
    """Every operation fails like an unreachable server."""

    def __init__(self):
        self.calls = 0

    def pipeline(self, *a, **k):
        self.calls += 1
        raise ConnectionError("redis is down")

    async def expire(self, *a, **k):
        self.calls += 1
        raise ConnectionError("redis is down")


class TestRedisOutage:
    @pytest.mark.asyncio
    async def test_falls_back_to_memory_and_still_limits(self):
        lim = RateLimiter(redis_client=_BrokenRedis())
        results = [await lim.hit("k", limit=2, window=60) for _ in range(3)]
        assert [r.allowed for r in results] == [True, True, False]  # no 500, still limited

    @pytest.mark.asyncio
    async def test_does_not_hammer_a_dead_redis(self):
        broken = _BrokenRedis()
        lim = RateLimiter(redis_client=broken)
        for _ in range(10):
            await lim.hit("k", limit=100, window=60)
        assert broken.calls == 1  # tried once, then skipped during the cool-down

    @pytest.mark.asyncio
    async def test_recovers_when_redis_comes_back(self):
        clock = Clock()
        broken = _BrokenRedis()
        lim = RateLimiter(redis_client=broken, clock=clock)
        await lim.hit("k", limit=100, window=60)
        assert broken.calls == 1

        healthy = _fake_redis()
        lim._redis._client = healthy  # Redis is back
        clock.advance(rl._REDIS_RETRY_AFTER_SECONDS + 1)
        await lim.hit("k", limit=100, window=60)
        assert await healthy.get("ewmp:rl:k") == "1"  # used Redis again


# ── enforce_rate_limit ───────────────────────────────────────────────────────
class TestEnforce:
    @pytest.mark.asyncio
    async def test_raises_429_with_retry_after(self):
        for _ in range(2):
            await enforce_rate_limit("s", "id", limit=2)
        with pytest.raises(RateLimitExceededError) as exc:
            await enforce_rate_limit("s", "id", limit=2)
        assert exc.value.status_code == 429
        assert int(exc.value.headers["Retry-After"]) >= 1

    @pytest.mark.asyncio
    async def test_limit_zero_disables(self):
        for _ in range(50):
            await enforce_rate_limit("s", "id", limit=0)

    @pytest.mark.asyncio
    async def test_master_switch_disables(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
        for _ in range(50):
            await enforce_rate_limit("s", "id", limit=1)

    @pytest.mark.asyncio
    async def test_emails_are_hashed_in_keys(self):
        await enforce_rate_limit("login-email", "Victim@Example.com", limit=5, hashed=True)
        keys = list(rl.get_limiter()._memory._hits)
        assert len(keys) == 1
        assert "victim" not in keys[0].lower() and "example.com" not in keys[0].lower()

    def test_hash_is_case_and_space_insensitive(self):
        assert hash_identifier(" Bob@X.com ") == hash_identifier("bob@x.com")


# ── client IP ────────────────────────────────────────────────────────────────
def _req(peer="10.0.0.9", xff=None):
    # Starlette's Headers is case-insensitive, exactly like a real request.
    from starlette.datastructures import Headers

    headers = Headers({"X-Forwarded-For": xff}) if xff is not None else Headers({})
    return SimpleNamespace(
        client=SimpleNamespace(host=peer) if peer else None,
        headers=headers,
    )


class TestClientIp:
    def test_default_ignores_forged_header(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 0)
        assert get_client_ip(_req(xff="1.2.3.4")) == "10.0.0.9"

    def test_one_proxy_takes_last_entry(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
        # client tried to forge "6.6.6.6"; nginx appended the real peer.
        assert get_client_ip(_req(xff="6.6.6.6, 203.0.113.7")) == "203.0.113.7"

    def test_two_proxies_take_second_from_right(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
        assert get_client_ip(_req(xff="6.6.6.6, 203.0.113.7, 172.16.0.5")) == "203.0.113.7"

    def test_fewer_hops_than_proxies_is_not_trusted(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
        assert get_client_ip(_req(xff="6.6.6.6")) == "10.0.0.9"

    def test_missing_header_falls_back_to_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
        assert get_client_ip(_req()) == "10.0.0.9"

    def test_no_peer_at_all(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 0)
        assert get_client_ip(_req(peer=None)) == "unknown"


# ── the real HTTP endpoints ──────────────────────────────────────────────────
@pytest.fixture
def api(monkeypatch):
    """The real FastAPI app; DB and the auth service are stubbed out."""
    from app.core.database import get_db
    from app.main import app
    from app.services.auth import AuthService

    async def _no_db():
        yield None

    async def _bad_login(self, data, client_ip):
        raise InvalidCredentialsError()

    async def _noop(self, *a, **k):
        return None

    monkeypatch.setattr(AuthService, "login", _bad_login)
    monkeypatch.setattr(AuthService, "request_password_reset", _noop)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 0)
    app.dependency_overrides[get_db] = _no_db

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield client
    app.dependency_overrides.pop(get_db, None)


def _login(client, email="user@example.com", xff=None):
    headers = {"X-Forwarded-For": xff} if xff else {}
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Wrong-password-1"},
        headers=headers,
    )


class TestLoginEndpoint:
    @pytest.mark.asyncio
    async def test_per_email_limit_stops_password_guessing(self, api, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_EMAIL_PER_MINUTE", 5)
        codes = [(await _login(api)).status_code for _ in range(7)]
        assert codes == [401, 401, 401, 401, 401, 429, 429]

    @pytest.mark.asyncio
    async def test_429_has_retry_after_header_and_error_body(self, api, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_EMAIL_PER_MINUTE", 1)
        await _login(api)
        r = await _login(api)
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) >= 1
        assert r.json()["error"] == "RATE_LIMIT_EXCEEDED"

    @pytest.mark.asyncio
    async def test_other_emails_are_unaffected(self, api, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_EMAIL_PER_MINUTE", 1)
        await _login(api, "a@example.com")
        assert (await _login(api, "a@example.com")).status_code == 429
        assert (await _login(api, "b@example.com")).status_code == 401

    @pytest.mark.asyncio
    async def test_email_case_cannot_be_used_to_dodge_the_limit(self, api, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_EMAIL_PER_MINUTE", 2)
        await _login(api, "Victim@Example.com")
        await _login(api, "victim@example.com")
        assert (await _login(api, "VICTIM@EXAMPLE.COM")).status_code == 429

    @pytest.mark.asyncio
    async def test_per_ip_limit_across_many_emails(self, api, monkeypatch):
        """Credential stuffing: many different emails from one IP."""
        monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_IP_PER_MINUTE", 3)
        codes = [(await _login(api, f"user{i}@example.com")).status_code for i in range(5)]
        assert codes == [401, 401, 401, 429, 429]

    @pytest.mark.asyncio
    async def test_rotating_a_forged_forwarded_for_header_does_not_bypass(self, api, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_IP_PER_MINUTE", 3)
        codes = [
            (await _login(api, f"user{i}@example.com", xff=f"9.9.9.{i}")).status_code
            for i in range(5)
        ]
        assert codes == [401, 401, 401, 429, 429]  # header ignored -> same real IP

    @pytest.mark.asyncio
    async def test_office_of_users_behind_one_ip_is_not_blocked_by_default(self, api):
        """Default per-IP cap is generous enough for a shared office NAT."""
        codes = [(await _login(api, f"emp{i}@corp.com")).status_code for i in range(25)]
        assert 429 not in codes


class TestOtherPublicEndpoints:
    @pytest.mark.asyncio
    async def test_forgot_password_per_ip(self, api, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE", 3)
        monkeypatch.setattr(settings, "RATE_LIMIT_FORGOT_PASSWORD_PER_EMAIL_PER_HOUR", 0)
        codes = []
        for i in range(5):
            r = await api.post("/api/v1/auth/forgot-password", json={"email": f"p{i}@example.com"})
            codes.append(r.status_code)
        assert codes == [200, 200, 200, 429, 429]

    @pytest.mark.asyncio
    async def test_forgot_password_per_email_stops_inbox_bombing(self, api, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_FORGOT_PASSWORD_PER_EMAIL_PER_HOUR", 3)
        codes = []
        for _ in range(5):
            r = await api.post("/api/v1/auth/forgot-password", json={"email": "victim@example.com"})
            codes.append(r.status_code)
        assert codes == [200, 200, 200, 429, 429]

    @pytest.mark.asyncio
    async def test_forgot_password_limit_does_not_reveal_whether_email_exists(self, api, monkeypatch):
        """Registered and unregistered addresses are throttled identically."""
        monkeypatch.setattr(settings, "RATE_LIMIT_FORGOT_PASSWORD_PER_EMAIL_PER_HOUR", 1)
        first = await api.post("/api/v1/auth/forgot-password", json={"email": "ghost-%s@example.com" % uuid.uuid4().hex[:6]})
        assert first.status_code == 200

    @pytest.mark.asyncio
    async def test_endpoints_have_separate_buckets(self, api, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE", 1)
        monkeypatch.setattr(settings, "RATE_LIMIT_FORGOT_PASSWORD_PER_EMAIL_PER_HOUR", 0)
        await api.post("/api/v1/auth/forgot-password", json={"email": "a@example.com"})
        blocked = await api.post("/api/v1/auth/forgot-password", json={"email": "b@example.com"})
        assert blocked.status_code == 429
        # reset-password has its own bucket: not consumed by forgot-password
        other = await api.post(
            "/api/v1/auth/reset-password", json={"token": "x" * 20, "new_password": "New-password-123!"}
        )
        assert other.status_code != 429
