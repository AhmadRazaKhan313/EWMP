"""session security: tracked single-use refresh tokens, tokens_valid_after

Revision ID: a15c0de7e3b1
Revises: adec41479191
Create Date: 2026-10-01 00:00:00.000000

Audit finding H-6. Refresh tokens were bare JWTs: never rotated, never
revocable, so logout did nothing server-side and a stolen token kept working
for its whole 7 days (also after a password change). This adds

  * auth_refresh_tokens -- one row per issued refresh token, grouped into a
    session ("family"), so tokens are single-use and sessions revocable;
  * users.tokens_valid_after -- access tokens issued before it are rejected
    (set on password change/reset).

Refresh tokens issued BEFORE this migration have no row, so they are rejected
on first use: every signed-in user has to sign in once more after deploying.
That is intended -- those tokens cannot be tracked or revoked.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a15c0de7e3b1"
down_revision: Union[str, None] = "adec41479191"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("family_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_refresh_tokens_user_id", "auth_refresh_tokens", ["user_id"])
    op.create_index("ix_auth_refresh_tokens_family_id", "auth_refresh_tokens", ["family_id"])
    op.create_index("ix_auth_refresh_tokens_expires_at", "auth_refresh_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_table("auth_refresh_tokens")
    op.drop_column("users", "tokens_valid_after")
