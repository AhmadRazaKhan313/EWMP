"""
Refresh-token sessions (audit H-6).

A refresh token used to be a bare JWT that nobody tracked: it could never be
revoked, was reusable for its whole life, and survived logout and password
changes. Now every refresh token has a row (RefreshSession) and:

  * a login starts a *family* (one session); every refresh marks the token it
    was handed as USED and issues the next one in that family -- rotation;
  * presenting a token that was already used means a copy exists somewhere
    (the legitimate client has the newer one), so the WHOLE family is revoked
    -- except for REFRESH_REUSE_GRACE_SECONDS after the use, where it is almost
    certainly one client firing two refreshes at once and only the loser is
    refused;
  * logout, a password change/reset and disabling an account revoke families;
  * a session has an absolute end (REFRESH_SESSION_MAX_DAYS) however often it
    is rotated.

`tokens_valid_after` on the user covers the access-token side: see
permissions.dependencies.get_current_user.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import InvalidTokenError
from app.core.security import create_refresh_token
from app.models.user import RefreshSession, User

logger = logging.getLogger("ewmp.auth.sessions")

_INVALID = "Invalid or expired refresh token"


async def issue_refresh_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    family_id: str | None = None,
    session_expires_at: datetime | None = None,
) -> str:
    """Create + persist a refresh token. No family given = a brand-new session."""
    now = datetime.now(UTC)
    family_id = family_id or secrets.token_hex(16)
    session_end = session_expires_at or now + timedelta(
        days=settings.REFRESH_SESSION_MAX_DAYS
    )
    expires_at = min(
        now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), session_end
    )
    jti = secrets.token_hex(16)
    db.add(
        RefreshSession(
            jti=jti,
            user_id=user_id,
            family_id=family_id,
            created_at=now,
            expires_at=expires_at,
            session_expires_at=session_end,
        )
    )
    await db.flush()
    return create_refresh_token(
        str(user_id), jti=jti, family_id=family_id, expires_at=expires_at
    )


async def consume_refresh_token(
    db: AsyncSession, jti: str, user_id: uuid.UUID
) -> tuple[str, datetime]:
    """Spend a refresh token. Returns (family_id, session_expires_at) so the
    caller can issue the next token in the same session.

    Raises InvalidTokenError for anything that is not a live, unused token.
    The "mark used" is a single conditional UPDATE, so two requests racing
    with the same token cannot both succeed.
    """
    now = datetime.now(UTC)
    spent = await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.jti == jti,
            RefreshSession.user_id == user_id,
            RefreshSession.used_at.is_(None),
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
            RefreshSession.session_expires_at > now,
        )
        .values(used_at=now)
        .returning(RefreshSession.family_id, RefreshSession.session_expires_at)
    )
    won = spent.first()
    if won is not None:
        return won.family_id, won.session_expires_at

    row = (
        await db.execute(select(RefreshSession).where(RefreshSession.jti == jti))
    ).scalar_one_or_none()
    if row is None or row.user_id != user_id:
        # Unknown token: forged, purged, or issued before sessions were tracked.
        raise InvalidTokenError(_INVALID)
    if (
        row.used_at is not None
        and row.revoked_at is None
        and now - row.used_at > timedelta(seconds=settings.REFRESH_REUSE_GRACE_SECONDS)
    ):
        # A spent token came back: someone holds a copy. Kill the session.
        # Committed HERE because the exception below makes get_db roll back,
        # which would silently undo the revocation.
        logger.warning(
            "Refresh-token reuse detected for user %s; revoking session %s",
            user_id,
            row.family_id,
        )
        await revoke_family(db, row.family_id)
        await db.commit()
    raise InvalidTokenError(_INVALID)


async def revoke_family(db: AsyncSession, family_id: str) -> None:
    await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_session_of_token(
    db: AsyncSession, jti: str, user_id: uuid.UUID
) -> bool:
    """Logout: revoke the session a refresh token belongs to (only the caller's
    own). Returns whether a session was found."""
    family_id = (
        await db.execute(
            select(RefreshSession.family_id).where(
                RefreshSession.jti == jti, RefreshSession.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if family_id is None:
        return False
    await revoke_family(db, family_id)
    return True


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Sign a user out everywhere: every refresh token revoked AND every access
    token issued so far rejected. Used on password change/reset and when a
    login is disabled."""
    now = datetime.now(UTC)
    await db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.execute(
        update(User).where(User.id == user_id).values(tokens_valid_after=now)
    )
    await db.flush()


async def purge_expired(db: AsyncSession, *, keep_days: int = 7) -> int:
    """Delete rows that can no longer matter. Kept `keep_days` past expiry so
    reuse of a recently-expired token is still recognised as such."""
    cutoff = datetime.now(UTC) - timedelta(days=keep_days)
    result = await db.execute(
        delete(RefreshSession).where(RefreshSession.expires_at < cutoff)
    )
    return result.rowcount or 0
