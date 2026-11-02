"""
Authentication service.

All auth business logic lives here. Route handlers call this service
and handle only HTTP concerns (request parsing, response serialization).

Design:
  - All DB interaction goes through repositories (never raw ORM in service).
  - Token creation delegates to core/security.py.
  - Emails are dispatched as Celery tasks (non-blocking).
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
    SlugAlreadyExistsError,
    TokenExpiredError,
)
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    generate_email_verification_token,
    generate_password_reset_token,
    hash_password,
    needs_rehash,
    verify_password,
    verify_refresh_token,
)
from app.models.user import User
from app.repositories.user import UserRepository
from app.services import auth_sessions

logger = logging.getLogger("ewmp.auth")
from app.schemas.auth import (
    AuthResponse,
    LoginSchema,
    OrganizationRegisterSchema,
    TokenResponse,
    UserInToken,
)



# ── Email verification helpers (shared by every account-creation path) ──────

def new_email_verification_fields() -> dict:
    """Columns to set on a brand-new, unverified User so they can verify.

    Every place that creates an account (self-registration, POST /employees,
    POST /auth/register-employee) must use this AND call
    queue_verification_email() — audit finding C-3: admin-created accounts
    used to get no token and no email, so with REQUIRE_EMAIL_VERIFICATION on
    they could never verify, and were locked out of the whole app.
    """
    return {
        "email_verification_token": generate_email_verification_token(),
        "email_verification_sent_at": datetime.now(UTC),
    }


# Celery's .delay() is a blocking network call. With the broker slow or
# unreachable it can take 20s+ (retries), and this runs inside async request
# handlers: the response -- e.g. the one carrying a new employee's temporary
# password -- would be held until it gave up, long enough for the browser to
# time out although the employee had been saved. So it runs on a worker thread
# and the request waits at most EMAIL_QUEUE_TIMEOUT_SECONDS for it.
_email_queue_executor = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="ewmp-email-queue"
)


def queue_verification_email(email: str, token: str) -> None:
    """Queue the verification email (fire and forget — never fails the
    request, and never holds it up for more than a couple of seconds; the user
    can use POST /auth/resend-verification)."""

    def _enqueue() -> None:
        from app.workers.tasks.email import send_verification_email

        send_verification_email.delay(email, token)

    try:
        _email_queue_executor.submit(_enqueue).result(
            timeout=settings.EMAIL_QUEUE_TIMEOUT_SECONDS
        )
    except Exception as exc:  # broker down, slow, or the wait timed out
        logger.warning(
            "Verification email was not queued (%s: %s); the user can resend it",
            type(exc).__name__,
            exc,
        )


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_repo = UserRepository(db)

    # ── Registration ──────────────────────────────────────────────────────────

    async def register_organization(
        self, data: OrganizationRegisterSchema
    ) -> AuthResponse:
        """
        Create a new organization and its owner user in one atomic transaction.

        Steps:
          1. Validate email and slug uniqueness.
          2. Create Organization record.
          3. Seed default roles (Owner, Admin, HR Manager, Employee).
          4. Create User with Owner role.
          5. Send verification email (async task).
          6. Return auth tokens.
        """
        # Validate uniqueness
        if await self.user_repo.email_exists(data.email):
            raise EmailAlreadyExistsError()

        await self._assert_slug_available(data.org_slug)

        # Create organization
        from app.models.organization import Organization
        org = Organization(
            name=data.org_name,
            slug=data.org_slug,
            email=data.email,
            timezone=data.timezone,
            country=data.country,
            is_trial=True,
            trial_ends_at=datetime.now(UTC) + timedelta(days=14),
        )
        self.db.add(org)
        await self.db.flush()

        # Seed default roles
        owner_role = await self._seed_default_roles(org.id)

        # Create owner user
        verification_token = generate_email_verification_token()
        user = User(
            organization_id=org.id,
            email=data.email,
            email_normalized=data.email.lower().strip(),
            password_hash=hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
            timezone=data.timezone,
            email_verification_token=verification_token,
            email_verification_sent_at=datetime.now(UTC),
        )
        self.db.add(user)
        await self.db.flush()

        # Assign owner role
        user.roles.append(owner_role)

        # Set org owner
        org.owner_id = user.id
        await self.db.flush()

        # Queue verification email (non-blocking)
        self._queue_verification_email(user.email, verification_token)

        return await self._build_auth_response(user, org.slug)

    # ── Login ─────────────────────────────────────────────────────────────────

    async def login(self, data: LoginSchema, client_ip: str) -> AuthResponse:
        """
        Authenticate with email + password.

        Security:
          - Uses constant-time comparison via passlib.
          - Locks account after 5 consecutive failures (30 min).
          - Transparently rehashes password if bcrypt rounds changed.
        """
        user = await self.user_repo.get_by_email(data.email)

        # Burn the same bcrypt work an existing account would, so response time
        # does not reveal whether the email exists. This MUST be a real, valid
        # hash (dummy_password_hash()): the old hand-typed literal was malformed,
        # so passlib raised ValueError instantly — an unknown email returned a
        # 500 (not a 401) and was trivially distinguishable by timing.
        if user is None:
            verify_password("dummy", dummy_password_hash())
            raise InvalidCredentialsError()

        if not user.password_hash:
            if user.password_reset_token and (
                user.password_reset_expires_at
                and user.password_reset_expires_at > datetime.now(UTC)
            ):
                raise AuthenticationError(
                    "Your account is pending activation. Check your email for the "
                    "'Set your password' link, or request a new one from the login page."
                )
            raise AuthenticationError("This account uses a different sign-in method")

        # Account lockout: 5 consecutive failures lock the account for 30 minutes
        # (UserRepository.record_failed_login). Checked BEFORE verifying the
        # password so a locked account never confirms a correct guess, and burns
        # no bcrypt time. ON by default; set LOGIN_LOCKOUT_ENABLED=false in a dev
        # .env to switch it off (no code edits needed).
        if settings.LOGIN_LOCKOUT_ENABLED and user.locked_until is not None:
            if user.is_locked:
                remaining = max(
                    1, int((user.locked_until - datetime.now(UTC)).total_seconds())
                )
                minutes = -(-remaining // 60)  # ceil
                raise AuthenticationError(
                    "Account temporarily locked due to too many failed attempts. "
                    f"Please try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                    headers={"Retry-After": str(remaining)},
                )
            # The lock has expired: give a clean slate (see clear_expired_lock).
            await self.user_repo.clear_expired_lock(user.id)

        if not verify_password(data.password, user.password_hash):
            await self.user_repo.record_failed_login(user.id)
            raise InvalidCredentialsError()

        if not user.is_active:
            raise AuthenticationError("Account is disabled")

        # Transparent password rehash on algorithm upgrade
        if needs_rehash(user.password_hash):
            await self.user_repo.update(
                user.id, {"password_hash": hash_password(data.password)}
            )

        await self.user_repo.record_successful_login(user.id, client_ip)

        org_slug = user.organization.slug if user.organization else None
        return await self._build_auth_response(user, org_slug)

    # ── Token refresh ─────────────────────────────────────────────────────────

    async def refresh_tokens(self, refresh_token: str) -> TokenResponse:
        """Exchange a refresh token for a new access + refresh token pair.

        Refresh tokens are SINGLE-USE (audit H-6): this spends the one it is
        given and returns the next one in the same session. See
        app.services.auth_sessions for reuse detection and the session cap.
        """
        try:
            payload = verify_refresh_token(refresh_token)
            user_id = UUID(payload["sub"])
            jti = payload["jti"]
        except Exception as exc:
            raise InvalidTokenError("Invalid or expired refresh token") from exc

        family_id, session_end = await auth_sessions.consume_refresh_token(
            self.db, jti, user_id
        )

        user = await self.user_repo.get_with_roles(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("User not found or inactive")
        if user.organization and not user.organization.is_active:
            raise AuthenticationError("This organization's account has been suspended")

        return await self._issue_tokens(
            user, family_id=family_id, session_expires_at=session_end
        )

    # ── Logout / password change ──────────────────────────────────────────────

    async def logout(self, user: User, refresh_token: str | None) -> None:
        """Revoke the session the given refresh token belongs to. A client that
        sends none (older builds) just gets 200 and discards its tokens; the
        access token still expires on its own."""
        if not refresh_token:
            return
        try:
            # An expired token is still a legitimate way to name your session.
            payload = jwt.decode(
                refresh_token,
                settings.SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_exp": False},
            )
            if payload.get("type") != "refresh":
                return
            jti = payload["jti"]
        except Exception:
            return
        await auth_sessions.revoke_session_of_token(self.db, jti, user.id)

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> TokenResponse:
        """Replace the password, sign the account out everywhere, and hand back
        a fresh session for the device that did it (so it stays signed in)."""
        if not user.password_hash or not verify_password(
            current_password, user.password_hash
        ):
            raise InvalidCredentialsError("Current password is incorrect")

        await self.user_repo.update(
            user.id,
            {
                "password_hash": hash_password(new_password),
                # Whatever forced them here (a temp password from an admin,
                # employee onboarding, etc.) is satisfied now — clear the
                # flag so the force-change screen doesn't show again.
                "must_change_password": False,
            },
        )
        # Anyone holding the old password's sessions (a stolen laptop, a leaked
        # token) is out as of now.
        await auth_sessions.revoke_all_sessions(self.db, user.id)
        return await self._issue_tokens(user)

    # ── Email verification ────────────────────────────────────────────────────

    async def verify_email(self, token: str) -> None:
        """Mark the user's email as verified."""
        user = await self.user_repo.get_by_verification_token(token)
        if user is None:
            raise InvalidTokenError("Invalid or expired verification token")

        await self.user_repo.update(
            user.id,
            {
                "is_email_verified": True,
                "email_verification_token": None,
            },
        )

    async def resend_verification(self, user: User) -> bool:
        """Issue a fresh verification token and email it. Returns False when
        the address is already verified (nothing to send). The previous
        token stops working — only the newest link is valid."""
        if user.is_email_verified:
            return False
        fields = new_email_verification_fields()
        await self.user_repo.update(user.id, fields)
        queue_verification_email(user.email, fields["email_verification_token"])
        return True

    # ── Password reset ────────────────────────────────────────────────────────

    async def request_password_reset(self, email: str) -> None:
        """
        Send a password reset email if the address is registered.

        Always returns success (even if email not found) to prevent
        user enumeration via timing or response differences.
        """
        user = await self.user_repo.get_by_email(email)
        if user is None:
            return  # Silent success

        reset_token = generate_password_reset_token()
        await self.user_repo.update(
            user.id,
            {
                "password_reset_token": reset_token,
                "password_reset_expires_at": datetime.now(UTC) + timedelta(hours=2),
            },
        )
        self._queue_password_reset_email(user.email, reset_token)

    async def reset_password(self, token: str, new_password: str) -> None:
        """Apply the new password and invalidate the reset token."""
        user = await self.user_repo.get_by_reset_token(token)
        if user is None:
            raise InvalidTokenError("Invalid or expired reset token")

        await self.user_repo.update(
            user.id,
            {
                "password_hash": hash_password(new_password),
                "password_reset_token": None,
                "password_reset_expires_at": None,
                "failed_login_count": 0,
                "locked_until": None,
                # The reset link was delivered to this address and opened
                # from it — that proves inbox ownership exactly as the
                # verification link does (audit C-3). This is also how a
                # platform-admin-created organisation owner, who is sent a
                # reset link, becomes verified.
                "is_email_verified": True,
                "email_verification_token": None,
                # The user just chose this password themselves; there is no
                # temporary password left to force-change.
                "must_change_password": False,
            },
        )
        # A reset is usually "someone else may have my password": every
        # existing session ends here.
        await auth_sessions.revoke_all_sessions(self.db, user.id)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _issue_tokens(
        self,
        user: User,
        *,
        family_id: str | None = None,
        session_expires_at: datetime | None = None,
    ) -> TokenResponse:
        """Mint an access token and a TRACKED refresh token. No `family_id` =
        a new session (login/register/password change); a refresh passes its
        own so the session continues."""
        extra_claims = {
            "tenant_id": str(user.organization_id) if user.organization_id else None,
            "is_platform_admin": user.is_platform_admin,
            "role_slugs": [r.slug for r in user.roles],
        }
        access_token = create_access_token(str(user.id), extra_claims=extra_claims)
        refresh_token = await auth_sessions.issue_refresh_token(
            self.db,
            user.id,
            family_id=family_id,
            session_expires_at=session_expires_at,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def _build_auth_response(
        self, user: User, org_slug: str | None
    ) -> AuthResponse:
        tokens = await self._issue_tokens(user)

        all_permissions: set[str] = set()
        for role in user.roles:
            all_permissions.update(role.permission_codenames)

        user_data = UserInToken(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            is_platform_admin=user.is_platform_admin,
            organization_id=user.organization_id,
            organization_slug=org_slug,
            roles=[r.slug for r in user.roles],
            permissions=sorted(all_permissions),
            has_full_access=user.has_full_access,
            must_change_password=user.must_change_password,
        )

        return AuthResponse(tokens=tokens, user=user_data)

    async def _assert_slug_available(self, slug: str) -> None:
        from sqlalchemy import select
        from app.models.organization import Organization
        result = await self.db.execute(
            select(Organization.id).where(Organization.slug == slug)
        )
        if result.scalar_one_or_none() is not None:
            raise SlugAlreadyExistsError(
                f"The organization slug '{slug}' is already taken"
            )

    async def _seed_default_roles(self, org_id: UUID):
        """Create the four default system roles for a new organization."""
        from app.models.rbac import Role

        roles_data = [
            {"name": "Owner", "slug": "owner", "is_system": True, "is_super": True, "display_order": 0, "color": "#7C3AED"},
            {"name": "Admin", "slug": "admin", "is_system": True, "is_super": False, "display_order": 1, "color": "#DC2626"},
            {"name": "HR Manager", "slug": "hr-manager", "is_system": True, "is_super": False, "display_order": 2, "color": "#2563EB"},
            {"name": "Employee", "slug": "employee", "is_system": True, "is_super": False, "display_order": 3, "color": "#16A34A"},
        ]

        owner_role = None
        for data in roles_data:
            role = Role(organization_id=org_id, **data)
            self.db.add(role)
            if data["slug"] == "owner":
                owner_role = role

        await self.db.flush()
        return owner_role

    def _queue_verification_email(self, email: str, token: str) -> None:
        """Queue email sending as a Celery task (fire and forget)."""
        queue_verification_email(email, token)

    def _queue_password_reset_email(self, email: str, token: str) -> None:
        try:
            from app.workers.tasks.email import send_password_reset_email
            send_password_reset_email.delay(email, token)
        except Exception:
            pass