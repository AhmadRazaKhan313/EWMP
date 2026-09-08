"""
Tenant isolation middleware.

Every authenticated request carries a JWT that contains the tenant_id
claim. This middleware extracts that claim and stores it on request.state
so that repositories can filter all queries by tenant without any
caller needing to pass it explicitly.

Flow:
  1. Extract Bearer token from Authorization header.
  2. Decode the JWT (skip if route is public).
  3. Set request.state.tenant_id and request.state.user_id.
  4. All repositories read request.state.tenant_id automatically.

Platform super admin requests set tenant_id = None, which signals
repositories to skip tenant filtering (admin sees everything).
"""

from uuid import UUID

from fastapi import Request, Response
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.security import verify_access_token

# Routes that do not require authentication
PUBLIC_PATHS: set[str] = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/magic-link",
    "/api/v1/agent/register",   # First-time device registration
}

# Path prefixes that bypass tenant middleware entirely
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/v1/webhooks/incoming/",   # Incoming webhook callbacks
    "/static/",
)


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Injects tenant context into every authenticated request.

    Attributes set on request.state:
        user_id  (UUID | None)    — authenticated user's id
        tenant_id (UUID | None)   — user's organization id (None for platform admin)
        is_platform_admin (bool)  — True only for the seeded super admin
        token_payload (dict)      — full decoded JWT payload
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Initialize state with safe defaults
        request.state.user_id = None
        request.state.tenant_id = None
        request.state.is_platform_admin = False
        request.state.token_payload = {}

        # Skip public paths
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # Extract token
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return await call_next(request)

        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            return await call_next(request)

        # Decode token — failure is non-fatal here; the route's Depends
        # will enforce auth if the endpoint requires it.
        try:
            payload = verify_access_token(token)
            request.state.token_payload = payload
            request.state.user_id = UUID(payload["sub"])

            # Platform admin has no tenant
            if payload.get("is_platform_admin"):
                request.state.is_platform_admin = True
                request.state.tenant_id = None
            elif tid := payload.get("tenant_id"):
                request.state.tenant_id = UUID(tid)

        except (JWTError, ValueError, KeyError):
            # Malformed token — let the route handler produce the 401
            pass

        return await call_next(request)
