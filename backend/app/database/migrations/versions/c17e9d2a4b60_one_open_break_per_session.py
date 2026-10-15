"""at most one open break per work session

Revision ID: c17e9d2a4b60
Revises: b16d3ac4f8e2
Create Date: 2026-10-06 00:00:00.000000

Two "start break" requests arriving together (a double-click, or the widget and
the website at the same moment) both saw an active session and each inserted a
break, leaving two open breaks; the next "end break" then crashed. The API now
serialises these requests, and this index makes a second open break impossible
whatever else goes wrong.

Merge-then-constrain, like the earlier uniqueness migrations: any session that
already has several open breaks keeps the EARLIEST one open and the others are
closed with zero length (ended_at = started_at), so no time is added or lost.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c17e9d2a4b60"
down_revision: Union[str, None] = "b16d3ac4f8e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE break_records AS b
           SET ended_at = b.started_at
          FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY work_session_id ORDER BY started_at, id
                       ) AS rn
                  FROM break_records
                 WHERE ended_at IS NULL AND is_deleted = false
               ) AS ranked
         WHERE b.id = ranked.id AND ranked.rn > 1
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_break_records_one_open_per_session
            ON break_records (work_session_id)
         WHERE ended_at IS NULL AND is_deleted = false
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_break_records_one_open_per_session")
