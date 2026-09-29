"""Rate limiting for the public auth endpoints.

Why this exists: `RATE_LIMIT_*` settings were declared but nothing enforced
them, so /auth/login could be hammered without limit (and account lockout was
switched off). See also `UserRepository.record_failed_login` for the per-account
lockout; this module is the per-IP / per-email throttle in front of it.

Design
------
* Fixed-window counters. Simple, cheap, and good enough to stop guessing.
* Redis is the shared store (correct across several API workers/containers).
  If Redis is unreachable we FAIL OPEN to a per-process in-memory counter for a
  short while instead of returning 500s — a Redis outage must not take login
  down, and per-process limits are still much better than none.
* Identifiers that are personal data (emails) are hashed before they go into a
  key, so no plaintext addresses sit in Redis.

Usage
-----
    # IP-only endpoint:
    @router.post("/forgot-password", dependencies=[Depends(_forgot_limit)])
    # where  _forgot_limit = ip_rate_limit("forgot-password", lambda: settings.RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE)

    # Anything else, inside a handler:
    await enforce_rate_limit("login-email", email, limit=5, hashed=True)
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import Request

from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.exceptions import RateLimitExceededError

logger = logging.getLogger("ewmp.ratelimit")

_KEY_PREFIX = "ewmp:rl:"
_REDIS_RETRY_AFTER_SECONDS = 30.0  # how long to skip Redis after it fails
_MEMORY_SWEEP_THRESHOLD = 10_000  # sweep expired keys once the dict gets this big


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int
    limit: int
    retry_after: int  # seconds until the window resets


class _MemoryBackend:
    """Per-process fixed-window counters. Fallback + unit-test backend."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, tuple[int, float]] = {}  # key -> (count, expires_at)

    def _sweep(self, now: float) -> None:
        for k in [k for k, (_, exp) in self._hits.items() if exp <= now]:
            del self._hits[k]

    async def hit(self, key: str, window: int) -> tuple[int, int]:
        now = self._clock()
        if len(self._hits) >= _MEMORY_SWEEP_THRESHOLD:
            self._sweep(now)  # bounded memory even under a unique-key flood
        count, expires_at = self._hits.get(key, (0, 0.0))
        if expires_at <= now:
            count, expires_at = 0, now + window
        count += 1
        self._hits[key] = (count, expires_at)
        return count, max(1, int(expires_at - now + 0.999))


class _RedisBackend:
    def __init__(self, url: str | None = None, client: Any = None) -> None:
        self._url = url
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis

            # Short timeouts: a dead Redis must cost a few ms, not stall logins.
            self._client = aioredis.from_url(
                self._url,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                decode_responses=True,
            )
        return self._client

    async def hit(self, key: str, window: int) -> tuple[int, int]:
        r = self._get_client()
        k = _KEY_PREFIX + key
        async with r.pipeline(transaction=False) as pipe:
            pipe.incr(k)
            pipe.ttl(k)
            count, ttl = await pipe.execute()
        if ttl is None or ttl < 0:
            # First hit of the window — or a key left without a TTL by a crash
            # between INCR and EXPIRE. Either way (re)arm the expiry so a key
            # can never become a permanent block.
            await r.expire(k, window)
            ttl = window
        return int(count), max(1, int(ttl))


class RateLimiter:
    def __init__(
        self,
        redis_url: str | None = None,
        *,
        redis_client: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._memory = _MemoryBackend(clock)
        self._redis = (
            _RedisBackend(redis_url, redis_client) if (redis_url or redis_client) else None
        )
        self._redis_down_until = 0.0
        self._warned = False

    async def hit(self, key: str, limit: int, window: int = 60) -> RateLimitResult:
        count, ttl = await self._count(key, window)
        return RateLimitResult(allowed=count <= limit, count=count, limit=limit, retry_after=ttl)

    async def _count(self, key: str, window: int) -> tuple[int, int]:
        if self._redis is not None and self._clock() >= self._redis_down_until:
            try:
                result = await self._redis.hit(key, window)
                self._warned = False
                return result
            except Exception as exc:  # noqa: BLE001 — any Redis failure => fall back
                self._redis_down_until = self._clock() + _REDIS_RETRY_AFTER_SECONDS
                if not self._warned:
                    logger.warning(
                        "Rate limiter: Redis unavailable (%s); using per-process "
                        "in-memory limits for %ds",
                        exc.__class__.__name__,
                        int(_REDIS_RETRY_AFTER_SECONDS),
                    )
                    self._warned = True
        return await self._memory.hit(key, window)


# ── Process-wide instance ────────────────────────────────────────────────────
_limiter: RateLimiter | None = None


def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(settings.REDIS_URL)
    return _limiter


def set_limiter(limiter: RateLimiter | None) -> None:
    """Swap the process-wide limiter (tests). Pass None to rebuild from settings."""
    global _limiter
    _limiter = limiter


def hash_identifier(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:32]


async def enforce_rate_limit(
    scope: str,
    identifier: str,
    *,
    limit: int,
    window: int = 60,
    hashed: bool = False,
) -> None:
    """Count one hit against `scope`/`identifier`; raise 429 once over `limit`.

    `limit <= 0` or RATE_LIMIT_ENABLED=false turns the check off.
    """
    if not settings.RATE_LIMIT_ENABLED or limit <= 0:
        return
    ident = hash_identifier(identifier) if hashed else identifier
    result = await get_limiter().hit(f"{scope}:{ident}", limit, window)
    if not result.allowed:
        raise RateLimitExceededError(
            f"Too many attempts. Please try again in {result.retry_after} seconds.",
            headers={"Retry-After": str(result.retry_after)},
        )


def ip_rate_limit(
    scope: str, limit: Callable[[], int], window: int = 60
) -> Callable[[Request], Awaitable[None]]:
    """FastAPI dependency factory: limit an endpoint per client IP.

    `limit` is a callable so the setting is read at request time.
    """

    async def dependency(request: Request) -> None:
        await enforce_rate_limit(scope, get_client_ip(request), limit=limit(), window=window)

    return dependency
