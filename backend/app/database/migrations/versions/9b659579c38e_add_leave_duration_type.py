"""add duration_type and hours to leave_requests

Revision ID: 9b659579c38e
Revises: 9b22720f5bcc
Create Date: 2026-08-28 00:00:00.000000

Adds the duration model needed to close bug H6 (half-day/hourly leave
unsupported end-to-end). `is_half_day`/`half_day_period` already existed
but were never wired to anything; `duration_type` becomes the single
source of truth ("full_day" | "half_day" | "hourly") and `is_half_day`/
`half_day_period` are kept in sync for backward compatibility with any
existing reads of those columns. `hours` is only populated for
duration_type="hourly" requests.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9b659579c38e'
down_revision: Union[str, None] = '9b22720f5bcc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'leave_requests',
        sa.Column(
            'duration_type',
            sa.String(length=10),
            nullable=False,
            server_default='full_day',
            comment="full_day | half_day | hourly",
        ),
    )
    op.add_column(
        'leave_requests',
        sa.Column('hours', sa.Numeric(4, 2), nullable=True, comment="Only set when duration_type='hourly'"),
    )


def downgrade() -> None:
    op.drop_column('leave_requests', 'hours')
    op.drop_column('leave_requests', 'duration_type')
