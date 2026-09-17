"""
Application-wide exception hierarchy.

Every domain exception maps to a specific HTTP status code. Handlers
registered in main.py convert these into consistent JSON error responses.
This keeps error handling DRY — no try/except chains in route handlers.
"""

from typing import Any


class EWMPException(Exception):
    """Base exception for all application errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred"

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.detail = detail
        self.headers = headers
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.error_code,
            "message": self.message,
            "detail": self.detail,
        }


# ── 400 Bad Request ───────────────────────────────────────────────────────────
class ValidationError(EWMPException):
    status_code = 400
    error_code = "VALIDATION_ERROR"
    message = "Request validation failed"


class BadRequestError(EWMPException):
    status_code = 400
    error_code = "BAD_REQUEST"
    message = "Bad request"


# ── 401 Unauthorized ──────────────────────────────────────────────────────────
class AuthenticationError(EWMPException):
    status_code = 401
    error_code = "AUTHENTICATION_FAILED"
    message = "Authentication failed"


class InvalidTokenError(EWMPException):
    status_code = 401
    error_code = "INVALID_TOKEN"
    message = "Token is invalid or expired"


class TokenExpiredError(EWMPException):
    status_code = 401
    error_code = "TOKEN_EXPIRED"
    message = "Token has expired"


class InvalidCredentialsError(EWMPException):
    status_code = 401
    error_code = "INVALID_CREDENTIALS"
    message = "Invalid email or password"


# ── 403 Forbidden ─────────────────────────────────────────────────────────────
class PermissionDeniedError(EWMPException):
    status_code = 403
    error_code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action"


class TenantAccessDeniedError(EWMPException):
    status_code = 403
    error_code = "TENANT_ACCESS_DENIED"
    message = "Access to this organization is denied"


class AccountDisabledError(EWMPException):
    status_code = 403
    error_code = "ACCOUNT_DISABLED"
    message = "Your account has been disabled"


class EmailNotVerifiedError(EWMPException):
    status_code = 403
    error_code = "EMAIL_NOT_VERIFIED"
    message = "Please verify your email address before continuing"


# ── 404 Not Found ─────────────────────────────────────────────────────────────
class NotFoundError(EWMPException):
    status_code = 404
    error_code = "NOT_FOUND"
    message = "Resource not found"


class UserNotFoundError(NotFoundError):
    error_code = "USER_NOT_FOUND"
    message = "User not found"


class OrganizationNotFoundError(NotFoundError):
    error_code = "ORGANIZATION_NOT_FOUND"
    message = "Organization not found"


class EmployeeProfileNotLinkedError(NotFoundError):
    """The authenticated user has no linked Employee row.

    Raised by every self-service HRMS endpoint (work sessions, attendance,
    leave, payroll) at the exact same point: `EmployeeRepository.
    get_by_user_id(current_user.id)` returns None. Previously each call
    site raised a bare NotFoundError with its own slightly different
    message ("No employee profile is linked to this user" in some places,
    "Employee profile not found for this user" in others) — same 404
    status and same generic "NOT_FOUND" error_code in every case, so no
    client could reliably tell this ONE specific, common, and genuinely
    actionable condition apart from any other 404.

    It happens whenever a User account exists and can log in, but no
    Employee profile has been linked to it yet — most commonly the
    two-step onboarding flow (POST /auth/register-employee creates the
    login account; a follow-up POST /employees with that user_id is
    what creates and links the Employee profile) only completed its
    first step. A brand-new organization's very first non-admin hire is
    exactly the case most likely to hit this, since it's the first time
    that two-step flow has been exercised for that org.

    A distinct error_code lets any client (desktop or web) show a
    specific, actionable message — "ask your admin to finish linking
    your employee profile" — instead of a generic, unhelpful one.
    """
    error_code = "EMPLOYEE_PROFILE_NOT_LINKED"
    message = (
        "Your account isn't linked to an employee profile yet. "
        "Ask your HR admin to finish setting up your employee record."
    )


# ── 409 Conflict ──────────────────────────────────────────────────────────────
class ConflictError(EWMPException):
    status_code = 409
    error_code = "CONFLICT"
    message = "Resource already exists"


class EmailAlreadyExistsError(ConflictError):
    error_code = "EMAIL_ALREADY_EXISTS"
    message = "An account with this email already exists"


class SlugAlreadyExistsError(ConflictError):
    error_code = "SLUG_ALREADY_EXISTS"
    message = "This identifier is already taken"


# ── 422 Unprocessable Entity ──────────────────────────────────────────────────
class UnprocessableError(EWMPException):
    status_code = 422
    error_code = "UNPROCESSABLE"
    message = "Unable to process the request"


# ── 429 Rate Limited ──────────────────────────────────────────────────────────
class RateLimitExceededError(EWMPException):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"
    message = "Too many requests. Please slow down."


# ── 503 Service Unavailable ───────────────────────────────────────────────────
class ServiceUnavailableError(EWMPException):
    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"
    message = "Service is temporarily unavailable"


class AIProviderError(ServiceUnavailableError):
    error_code = "AI_PROVIDER_ERROR"
    message = "AI provider is temporarily unavailable"


class StorageError(EWMPException):
    status_code = 503
    error_code = "STORAGE_ERROR"
    message = "File storage service is unavailable"


# ── 500 Internal (invariant violations — never expected to reach a client) ────
class TenantScopeError(EWMPException):
    """
    Raised when a tenant-scoped repository is asked to read or write without
    a tenant_id. This is a server-side invariant violation (deny-by-default):
    running the query unscoped would leak or corrupt data across tenants, so
    we fail closed and loud instead of silently touching every tenant's rows.
    """

    status_code = 500
    error_code = "TENANT_SCOPE_ERROR"
    message = "Tenant-scoped operation attempted without a tenant context"