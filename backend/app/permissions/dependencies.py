"""
FastAPI authentication dependencies.
"""

from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.core.exceptions import (
    AccountDisabledError,
    AuthenticationError,
    InvalidTokenError,
    PermissionDeniedError,
    TenantAccessDeniedError,
)
from app.core.security import verify_access_token
from app.models.user import User
from app.repositories.user import UserRepository

_bearer = HTTPBearer(auto_error=False)


async def _get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if credentials is None:
        raise AuthenticationError("Authorization header missing")
    try:
        payload = verify_access_token(credentials.credentials)
    except (JWTError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
    return payload


async def get_current_user(
    request: Request,
    payload: dict = Depends(_get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> User:
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise InvalidTokenError("Token missing subject claim")
    try:
        user_id = UUID(user_id_str)
    except ValueError as exc:
        raise InvalidTokenError("Invalid user id in token") from exc

    # Plain repo.get() here used to be the real bug: it doesn't eager-load
    # roles/permissions, so the very first user.has_permission() call later
    # in the request (in require_permission / has_permission on the model)
    # would lazy-load `user.roles` → `role.permissions` outside of an async
    # greenlet, crashing with `sqlalchemy.exc.MissingGreenlet` for literally
    # every non-platform-admin authenticated request. get_with_roles()
    # eager-loads both in the same query, so has_permission() never touches
    # the database again afterwards.
    repo = UserRepository(db)
    user = await repo.get_with_roles(user_id)
    if user is None:
        raise AuthenticationError("User not found")
    if not user.is_active:
        raise AccountDisabledError()
    if user.organization and not user.organization.is_active:
        raise AccountDisabledError(
            "This organization's account has been suspended. Please contact your administrator."
        )
    return user


async def get_current_verified_user(
    user: User = Depends(get_current_user),
) -> User:
    """
    Platform admins bypass email verification check.
    Regular users must have verified email.
    """
    if user.is_platform_admin:
        return user  # Platform admin always allowed
    if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_email_verified:
        from app.core.exceptions import EmailNotVerifiedError
        raise EmailNotVerifiedError()
    return user


async def require_platform_admin(
    user: User = Depends(get_current_user),
) -> User:
    if not user.is_platform_admin:
        raise PermissionDeniedError("Platform admins only")
    return user


def require_permission(permission_codename: str):
    """
    Platform admins have ALL permissions automatically.
    Regular users need the specific permission via their roles.
    """
    async def _check(user: User = Depends(get_current_user)) -> User:
        if not user.is_active:
            raise AccountDisabledError()

        # Platform admin has every permission
        if user.is_platform_admin:
            return user

        # Email verification required for non-admins
        if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_email_verified:
            from app.core.exceptions import EmailNotVerifiedError
            raise EmailNotVerifiedError()

        # Check permission via roles
        if not user.has_permission(permission_codename):
            raise PermissionDeniedError(
                f"Permission '{permission_codename}' is required for this action"
            )
        return user

    return _check


def require_any_permission(*permission_codenames: str):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.is_platform_admin:
            return user
        if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_email_verified:
            from app.core.exceptions import EmailNotVerifiedError
            raise EmailNotVerifiedError()
        if not any(user.has_permission(p) for p in permission_codenames):
            raise PermissionDeniedError("Insufficient permissions")
        return user
    return _check


async def get_tenant_id(
    request: Request,
    user: User = Depends(get_current_user),
) -> UUID:
    """
    Resolve the tenant (organization) id for the current request.

    Priority order:
    1. X-Tenant-ID header — ONLY honored for platform admins managing a
       specific organization. For any non-platform-admin the header is
       ignored: a regular user can never act outside their own
       organization. This closes a cross-tenant access hole where any
       authenticated user could scope requests to another org by
       spoofing the header.
    2. The user's own organization_id.
    """
    # X-Tenant-ID is a platform-admin-only override. Ignoring it for
    # regular users prevents tenant escalation via a spoofed header.
    if user.is_platform_admin:
        header_tid = request.headers.get("X-Tenant-ID")
        if header_tid:
            try:
                return UUID(header_tid)
            except ValueError as exc:
                raise AuthenticationError("Invalid X-Tenant-ID header") from exc

    # Regular users (and admins with no override) act within their own org.
    if user.organization_id is not None:
        return user.organization_id

    if user.is_platform_admin:
        raise TenantAccessDeniedError(
            "Please select an organization to manage. "
            "Provide X-Tenant-ID header or create/join an organization first."
        )

    raise TenantAccessDeniedError("User is not associated with an organization")