"""
Regression test for the CORS misconfiguration fix (bug H3).

main.py hardcoded the CORS middleware with allow_origins=["*"] AND
allow_credentials=True, ignoring settings.ALLOWED_ORIGINS. A wildcard origin
combined with credentials is rejected by browsers, and Starlette instead
reflects the request's Origin — effectively letting ANY website make
credentialed cross-origin calls to the API. The fix wires the middleware to
the configured origin allowlist.

These tests introspect the app's middleware stack — no server, DB, or network.

Run:  cd backend && pytest tests/test_cors_config_h3.py -v
"""

from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.main import create_app


def _cors_kwargs() -> dict:
    """Return the keyword arguments the app passed to CORSMiddleware."""
    app = create_app()
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            # Starlette's Middleware stores the passed kwargs on `.kwargs`
            # (current) or `.options` (older releases).
            return dict(getattr(mw, "kwargs", None) or getattr(mw, "options", {}))
    raise AssertionError("CORSMiddleware is not configured on the app")


def test_cors_origins_are_not_a_wildcard():
    """THE H3 assertion: origins must never be the '*' wildcard (which, with
    credentials, exposes the API to every origin)."""
    origins = _cors_kwargs()["allow_origins"]
    assert origins != ["*"]
    assert "*" not in origins


def test_cors_uses_configured_allowlist_with_credentials():
    kwargs = _cors_kwargs()
    # Wired to the configurable allowlist rather than a hardcoded value.
    assert kwargs["allow_origins"] == settings.ALLOWED_ORIGINS
    # Credentials stay enabled — now safe because the origins are explicit.
    assert kwargs["allow_credentials"] is True