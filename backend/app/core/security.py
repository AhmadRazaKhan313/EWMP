"""
Security utilities.

Centralises all cryptographic operations so they are never duplicated
across the codebase. Every token, hash, and signature passes through here.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# ── Password Hashing ──────────────────────────────────────────────────────────
#
# bcrypt with a work factor of 12 is the industry standard for 2024.
# The deprecated_warning suppresses bcrypt version warnings from passlib.
#
_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if plain_password matches the stored hash."""
    return _pwd_context.verify(plain_password, hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    """
    Return True if the hash was created with old parameters.

    Call this after a successful login to transparently upgrade
    old bcrypt rounds when the work factor changes.
    """
    return _pwd_context.needs_update(hashed_password)


# A cached, VALID bcrypt hash used to equalise verify() timing on the
# "user does not exist" login path. It must be a real bcrypt hash so
# verify_password() performs the same work as a genuine password check —
# a malformed constant is rejected by passlib almost instantly, and that
# timing gap lets an attacker enumerate which emails are registered (bug H2).
# Computed lazily and memoised so it costs one bcrypt hash per process and
# adds nothing to import time.
_DUMMY_VERIFY_HASH: str | None = None


def dummy_password_hash() -> str:
    """Return a cached, valid bcrypt hash for constant-time dummy verifies."""
    global _DUMMY_VERIFY_HASH
    if _DUMMY_VERIFY_HASH is None:
        _DUMMY_VERIFY_HASH = _pwd_context.hash("dummy-password-for-timing-only")
    return _DUMMY_VERIFY_HASH


# ── JWT Tokens ────────────────────────────────────────────────────────────────
def create_access_token(
    subject: str | int,
    *,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Create a short-lived JWT access token.

    Args:
        subject: Typically the user's UUID string.
        extra_claims: Additional claims (e.g. tenant_id, role_ids).

    Returns:
        Signed JWT string.
    """
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str | int) -> str:
    """
    Create a long-lived JWT refresh token.

    Refresh tokens carry minimal claims — only sub and type.
    They are used exclusively to mint new access tokens.
    """
    expire = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "refresh",
        "jti": secrets.token_hex(16),  # Unique ID for revocation support
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Raises:
        jose.JWTError: If the token is invalid, expired, or tampered.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def verify_access_token(token: str) -> dict[str, Any]:
    """
    Decode and verify that the token is specifically an access token.

    Raises:
        ValueError: If the token type is not 'access'.
        jose.JWTError: If the token is otherwise invalid.
    """
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise ValueError("Token is not an access token")
    return payload


def verify_refresh_token(token: str) -> dict[str, Any]:
    """
    Decode and verify that the token is specifically a refresh token.

    Raises:
        ValueError: If the token type is not 'refresh'.
        jose.JWTError: If the token is otherwise invalid.
    """
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise ValueError("Token is not a refresh token")
    return payload


# ── One-Time Tokens ───────────────────────────────────────────────────────────
def generate_email_verification_token() -> str:
    """Generate a cryptographically secure email verification token."""
    return secrets.token_urlsafe(32)


def generate_password_reset_token() -> str:
    """Generate a cryptographically secure password reset token."""
    return secrets.token_urlsafe(32)


def generate_magic_link_token() -> str:
    """Generate a one-time magic link token."""
    return secrets.token_urlsafe(48)


def generate_api_key() -> tuple[str, str]:
    """
    Generate an API key pair.

    Returns:
        Tuple of (raw_key, hashed_key).
        Store the hashed_key in the database and return raw_key to the user.
        The raw_key is only shown once — it cannot be recovered from the hash.
    """
    raw_key = f"ewmp_{secrets.token_urlsafe(32)}"
    hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, hashed_key


def verify_api_key(raw_key: str, hashed_key: str) -> bool:
    """Constant-time comparison to prevent timing attacks on API key verification."""
    expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return hmac.compare_digest(expected_hash, hashed_key)


# ── Agent Communication ───────────────────────────────────────────────────────
def create_agent_token(device_id: str) -> str:
    """
    Create a long-lived JWT for the desktop agent.

    Agent tokens never expire (exp is set far in the future) because
    agents run unattended. Rotation is handled via the device management UI.
    """
    expire = datetime.now(UTC) + timedelta(days=365 * 10)
    payload: dict[str, Any] = {
        "sub": device_id,
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "agent",
    }
    return jwt.encode(
        payload,
        settings.AGENT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_agent_token(token: str) -> dict[str, Any]:
    """Verify a desktop agent JWT."""
    payload = jwt.decode(
        token,
        settings.AGENT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    if payload.get("type") != "agent":
        raise ValueError("Token is not an agent token")
    return payload


def create_device_enrollment_token(tenant_id: str, valid_days: int = 365) -> str:
    """
    Create the org-scoped enrollment token an admin pastes into the agent's
    config once during install (see agent/README.md). It is NOT a
    per-device credential — POST /devices/enroll exchanges it for a real
    per-device agent token via create_agent_token().

    Uses jose (this project's only JWT dependency) rather than PyJWT,
    which is not installed — see bug C3.
    """
    expire = datetime.now(UTC) + timedelta(days=valid_days)
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "type": "device_enrollment",
        "iat": datetime.now(UTC),
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.AGENT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_device_enrollment_token(token: str) -> dict[str, Any]:
    """Verify a device-enrollment JWT. Raises JWTError (invalid/expired) or
    ValueError (wrong token type) — callers should catch both."""
    payload = jwt.decode(
        token,
        settings.AGENT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    if payload.get("type") != "device_enrollment":
        raise ValueError("Token is not a device enrollment token")
    return payload


# ── Attendance QR Check-in ────────────────────────────────────────────────────
def create_attendance_qr_token(tenant_id: str, branch_id: str, valid_minutes: int = 90) -> str:
    """
    Create a short-lived JWT embedded in the kiosk QR code for a branch.

    A kiosk/reception screen displays this token as a QR image and rotates
    it every `valid_minutes`. Employees scan it with the mobile app, which
    calls POST /attendance/check-in with method="qr" and this token —
    proving they were physically near the branch's displayed screen without
    needing GPS.
    """
    expire = datetime.now(UTC) + timedelta(minutes=valid_minutes)
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "branch_id": branch_id,
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "attendance_qr",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_attendance_qr_token(token: str) -> dict[str, Any]:
    """Verify a scanned attendance QR token. Raises JWTError if expired/invalid."""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != "attendance_qr":
        raise ValueError("Token is not an attendance QR token")
    return payload


# ── Webhook Signature ─────────────────────────────────────────────────────────
def sign_webhook_payload(payload: bytes, secret: str) -> str:
    """
    Generate an HMAC-SHA256 signature for an outgoing webhook payload.

    Recipients can verify authenticity by recomputing the signature
    using their shared secret. Format: sha256=<hex_digest>
    """
    signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature}"


def verify_webhook_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """
    Verify an incoming webhook signature.

    Uses constant-time comparison to prevent timing attacks.
    """
    expected = sign_webhook_payload(payload, secret)
    return hmac.compare_digest(expected, signature_header)