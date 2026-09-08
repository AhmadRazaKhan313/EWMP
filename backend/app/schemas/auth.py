"""
Authentication Pydantic schemas.

Separating schemas from models is a Clean Architecture principle.
Models define the DB structure; schemas define the API contract.
This lets us expose only safe fields and add request-level validation.
"""

import re
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ── Password validation ────────────────────────────────────────────────────────
_PASSWORD_MIN_LENGTH = 8
_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$"
)


def validate_password_strength(password: str) -> str:
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters")
    if not _PASSWORD_PATTERN.match(password):
        raise ValueError(
            "Password must contain at least one uppercase letter, "
            "one lowercase letter, and one number"
        )
    return password


# ── Registration ──────────────────────────────────────────────────────────────
class OrganizationRegisterSchema(BaseModel):
    """Used during first-time org signup."""
    org_name: str = Field(..., min_length=2, max_length=255)
    org_slug: str = Field(
        ..., min_length=2, max_length=100,
        pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$",
    )
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)
    timezone: str = Field(default="UTC")
    country: str | None = Field(default=None, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("org_slug")
    @classmethod
    def slug_lowercase(cls, v: str) -> str:
        return v.lower().strip()


class InviteRegisterSchema(BaseModel):
    """Used when accepting an email invite."""
    invitation_token: str
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


# ── Login ─────────────────────────────────────────────────────────────────────
class LoginSchema(BaseModel):
    email: EmailStr
    password: str
    device_info: dict | None = None  # Optional: browser/OS fingerprint


class RefreshTokenSchema(BaseModel):
    refresh_token: str


class MagicLinkRequestSchema(BaseModel):
    email: EmailStr


class MagicLinkVerifySchema(BaseModel):
    token: str


# ── Password management ───────────────────────────────────────────────────────
class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class ResetPasswordSchema(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)

    @model_validator(mode="after")
    def passwords_match(self) -> "ResetPasswordSchema":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class ChangePasswordSchema(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordSchema":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


# ── Email verification ────────────────────────────────────────────────────────
class VerifyEmailSchema(BaseModel):
    token: str


# ── 2FA ───────────────────────────────────────────────────────────────────────
class Enable2FASchema(BaseModel):
    totp_code: str = Field(..., min_length=6, max_length=6)


class Verify2FASchema(BaseModel):
    totp_code: str = Field(..., min_length=6, max_length=6)


# ── Responses ─────────────────────────────────────────────────────────────────
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserInToken(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    full_name: str
    avatar_url: str | None
    is_platform_admin: bool
    organization_id: UUID | None
    organization_slug: str | None
    roles: list[str]
    permissions: list[str]
    has_full_access: bool = False

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    """Full auth response including user profile and tokens."""
    tokens: TokenResponse
    user: UserInToken


class MeResponse(BaseModel):
    """Response for GET /auth/me."""
    id: UUID
    email: str
    first_name: str
    last_name: str
    full_name: str
    avatar_url: str | None
    phone: str | None = None
    bio: str | None = None
    is_platform_admin: bool
    is_2fa_enabled: bool
    organization_id: UUID | None
    roles: list[str]
    permissions: list[str]
    has_full_access: bool = False
    has_employee_profile: bool = False
    preferences: dict

    model_config = {"from_attributes": True}


class ProfileUpdateSchema(BaseModel):
    """PATCH /auth/me — partial update of the authenticated user's own
    profile. Email, roles, and permissions are intentionally NOT
    editable here (those go through admin-only user-management flows)."""
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    bio: str | None = None