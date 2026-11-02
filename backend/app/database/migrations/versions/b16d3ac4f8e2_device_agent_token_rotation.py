"""device agent token rotation: devices.next_agent_token_hash

Revision ID: b16d3ac4f8e2
Revises: a15c0de7e3b1
Create Date: 2026-10-02 00:00:00.000000

Audit finding H-12. Agent tokens were 10-year JWTs whose stored hash was never
checked, so they could neither expire nor be revoked or replaced. The server
now enforces the hash and rotates tokens through the heartbeat; this column
holds the not-yet-adopted replacement.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b16d3ac4f8e2"
down_revision: Union[str, None] = "a15c0de7e3b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("next_agent_token_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "next_agent_token_hash")
