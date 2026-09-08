"""
Authentication API endpoints.

All endpoints are under /api/v1/auth/
Public routes (no JWT required): login, register, refresh, forgot-password,
                                   reset-password, verify-email, magic-link
Protected routes: /me, /change-password, /logout, /2fa/*
"""

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.permissions.dependencies import get_current_user, get_current_verified_user
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordSchema,
    ForgotPasswordSchema,
    InviteRegisterSchema,
    LoginSchema,
    MeResponse,
    OrganizationRegisterSchema,
    ProfileUpdateSchema,
    RefreshTokenSchema,
    ResetPasswordSchema,
    TokenResponse,
    VerifyEmailSchema,
)
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Public ────────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new organization",
)
async def register_organization(
    data: OrganizationRegisterSchema,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """
    Create a new organization and owner account.

    Returns auth tokens immediately so the user is logged in after signup.
    A verification email is dispatched asynchronously.
    """
    service = AuthService(db)
    return await service.register_organization(data)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Login with email and password",
)
async def login(
    data: LoginSchema,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """
    Authenticate with email + password and receive JWT tokens.

    Accounts are locked for 30 minutes after 5 consecutive failures.
    """
    service = AuthService(db)
    return await service.login(data, client_ip=_get_client_ip(request))


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(
    data: RefreshTokenSchema,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access + refresh token pair."""
    service = AuthService(db)
    return await service.refresh_tokens(data.refresh_token)


@router.post(
    "/verify-email",
    status_code=status.HTTP_200_OK,
    summary="Verify email address",
)
async def verify_email(
    data: VerifyEmailSchema,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Consume the email verification token sent during registration."""
    service = AuthService(db)
    await service.verify_email(data.token)
    return {"message": "Email verified successfully"}


@router.post(
    "/forgot-password",
    status_code=status.HTTP_200_OK,
    summary="Request a password reset email",
)
async def forgot_password(
    data: ForgotPasswordSchema,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Send a password reset link to the provided email.

    Always returns 200 regardless of whether the email exists,
    to prevent user enumeration.
    """
    service = AuthService(db)
    await service.request_password_reset(data.email)
    return {"message": "If this email is registered, a reset link has been sent"}


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    summary="Reset password using a token",
)
async def reset_password(
    data: ResetPasswordSchema,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply the new password using the reset token from the email."""
    service = AuthService(db)
    await service.reset_password(data.token, data.new_password)
    return {"message": "Password reset successfully. Please log in with your new password."}


# ── Protected ─────────────────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current user profile",
)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Return the authenticated user's profile and permission set."""
    all_permissions: set[str] = set()
    for role in user.roles:
        all_permissions.update(role.permission_codenames)

    has_employee_profile = False
    if user.organization_id:
        from app.repositories.employee import EmployeeRepository

        employee = await EmployeeRepository(db, user.organization_id).get_by_user_id(user.id)
        has_employee_profile = employee is not None

    return MeResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        phone=user.phone,
        bio=user.bio,
        is_platform_admin=user.is_platform_admin,
        is_2fa_enabled=user.is_2fa_enabled,
        organization_id=user.organization_id,
        roles=[r.slug for r in user.roles],
        permissions=sorted(all_permissions),
        has_full_access=user.has_full_access,
        has_employee_profile=has_employee_profile,
        preferences=user.preferences or {},
    )


@router.patch(
    "/me",
    response_model=MeResponse,
    summary="Update the current user's own profile",
)
async def update_me(
    data: ProfileUpdateSchema,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Partial update — only fields actually sent are changed. Email,
    roles, and org membership are deliberately NOT editable through this
    endpoint; those require an admin-facing user-management flow."""
    from app.repositories.user import UserRepository

    updates = data.model_dump(exclude_unset=True)
    if updates:
        repo = UserRepository(db)
        await repo.update(user.id, updates)
        for key, value in updates.items():
            setattr(user, key, value)

    all_permissions: set[str] = set()
    for role in user.roles:
        all_permissions.update(role.permission_codenames)

    has_employee_profile = False
    if user.organization_id:
        from app.repositories.employee import EmployeeRepository

        employee = await EmployeeRepository(db, user.organization_id).get_by_user_id(user.id)
        has_employee_profile = employee is not None

    return MeResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        phone=user.phone,
        bio=user.bio,
        is_platform_admin=user.is_platform_admin,
        is_2fa_enabled=user.is_2fa_enabled,
        organization_id=user.organization_id,
        roles=[r.slug for r in user.roles],
        permissions=sorted(all_permissions),
        has_full_access=user.has_full_access,
        has_employee_profile=has_employee_profile,
        preferences=user.preferences or {},
    )


@router.post("/me/avatar", summary="Upload a new avatar image for the current user")
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.core.storage import get_storage
    from app.core.exceptions import BadRequestError
    from app.repositories.user import UserRepository

    if file.content_type not in ("image/png", "image/jpeg", "image/webp"):
        raise BadRequestError("Avatar must be a PNG, JPEG, or WebP image")

    content = await file.read()
    if not content:
        raise BadRequestError("Empty avatar upload")
    if len(content) > 5 * 1024 * 1024:
        raise BadRequestError("Avatar exceeds the 5 MB upload limit")

    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[file.content_type]
    key = f"avatars/{user.id}.{ext}"
    storage = get_storage()
    await storage.save(key, content)

    # Avatars are low-sensitivity (unlike CNIC/contract documents elsewhere
    # in this app), so they're served through the unauthenticated
    # /auth/avatar/{user_id} route below rather than requiring a Bearer
    # token on every <img> tag — that keeps them usable directly in <img
    # src="..."> without a custom fetch+blob-URL dance in the frontend.
    avatar_url = f"/api/v1/auth/avatar/{user.id}"
    repo = UserRepository(db)
    await repo.update(user.id, {"avatar_url": avatar_url})

    return {"avatar_url": avatar_url}


@router.get("/avatar/{user_id}", summary="Serve a user's avatar image")
async def get_avatar(user_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    from uuid import UUID as _UUID
    from app.core.storage import get_storage
    from app.core.exceptions import NotFoundError, ValidationError
    from app.repositories.user import UserRepository

    try:
        parsed_id = _UUID(user_id)
    except ValueError:
        raise ValidationError("Invalid user id")

    repo = UserRepository(db)
    target_user = await repo.get(parsed_id)
    if target_user is None or not target_user.avatar_url:
        raise NotFoundError("Avatar not found")

    storage = get_storage()
    for ext, mime in (("png", "image/png"), ("jpg", "image/jpeg"), ("webp", "image/webp")):
        try:
            content = await storage.read(f"avatars/{parsed_id}.{ext}")
            return Response(content=content, media_type=mime)
        except Exception:
            continue
    raise NotFoundError("Avatar not found")


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change password (authenticated)",
)
async def change_password(
    data: ChangePasswordSchema,
    user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change the current user's password. Requires current password confirmation."""
    from app.core.security import verify_password, hash_password
    from app.core.exceptions import InvalidCredentialsError
    from app.repositories.user import UserRepository

    if not user.password_hash or not verify_password(data.current_password, user.password_hash):
        raise InvalidCredentialsError("Current password is incorrect")

    repo = UserRepository(db)
    await repo.update(user.id, {"password_hash": hash_password(data.new_password)})
    return {"message": "Password changed successfully"}


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout (client-side token discard)",
)
async def logout(
    user: User = Depends(get_current_user),
) -> dict:
    """
    Logout endpoint.

    Since JWTs are stateless, true server-side revocation requires a
    token blacklist (Redis). For now this confirms the request and
    instructs the client to discard its tokens. Redis-based revocation
    can be wired in without changing this endpoint's contract.
    """
    return {"message": "Logged out successfully"}