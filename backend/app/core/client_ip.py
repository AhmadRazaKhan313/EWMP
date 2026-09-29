"""Resolve the real client IP for a request, safely.

`X-Forwarded-For` is a plain request header: any client can send it. Trusting
it unconditionally lets an attacker rotate a fake IP on every request, which
defeats per-IP rate limiting and lets them forge `last_login_ip`.

So the header is only believed when `TRUSTED_PROXY_COUNT` says N trusted
reverse proxies are in front of us. Each such proxy appends the address of the
peer that connected to IT, so with N proxies the genuine client is the N-th
entry from the RIGHT; anything to its left was supplied by the client (or a
hop we don't control) and is ignored.
"""

from fastapi import Request

from app.core.config import settings


def get_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"

    proxies = settings.TRUSTED_PROXY_COUNT
    if proxies <= 0:
        return peer

    header = request.headers.get("X-Forwarded-For", "")
    hops = [h.strip() for h in header.split(",") if h.strip()]
    if len(hops) < proxies:
        # Fewer hops than trusted proxies: the header can't be the full chain
        # (request bypassed the proxy, or it's malformed). Don't trust it.
        return peer
    return hops[-proxies]
