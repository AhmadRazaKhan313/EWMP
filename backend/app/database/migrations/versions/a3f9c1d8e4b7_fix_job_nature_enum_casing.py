"""fix job_nature_enum labels to match app convention (uppercase)

Revision ID: a3f9c1d8e4b7
Revises: 767d4dd7a505
Create Date: 2026-09-05 00:00:00.000000

Bug fix. The original job_nature migration (738c278f56fc) created the
Postgres enum with lowercase labels ('permanent', 'probationary', ...).
Every other enum in this app (employment_type_enum, employment_status_enum,
gender_enum, etc.) stores the Python enum member's NAME in uppercase
(e.g. 'FULL_TIME'), not its .value — SQLAlchemy's plain Enum column maps
by name by default, and Pydantic serializes by .value for the API/frontend
(lowercase, e.g. "full_time"). job_nature's Python model already followed
that convention (JobNature.PERMANENT = "permanent"); only the Postgres
labels were wrong, causing:

    asyncpg.exceptions.InvalidTextRepresentationError:
    invalid input value for enum job_nature_enum: "PERMANENT"

This renames the existing (lowercase) enum labels to uppercase in place —
no data loss, existing rows keep pointing at the same (renamed) label —
and updates the column's default to match.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3f9c1d8e4b7'
down_revision: Union[str, None] = '767d4dd7a505'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old lowercase label, new uppercase label)
RENAMES = (
    ("permanent", "PERMANENT"),
    ("probationary", "PROBATIONARY"),
    ("contractual", "CONTRACTUAL"),
    ("intern", "INTERN"),
    ("part_time", "PART_TIME"),
    ("temporary", "TEMPORARY"),
)


def upgrade() -> None:
    for old, new in RENAMES:
        op.execute(f"ALTER TYPE job_nature_enum RENAME VALUE '{old}' TO '{new}'")

    op.execute(
        "ALTER TABLE employees ALTER COLUMN job_nature SET DEFAULT 'PROBATIONARY'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE employees ALTER COLUMN job_nature SET DEFAULT 'probationary'"
    )
    for old, new in RENAMES:
        op.execute(f"ALTER TYPE job_nature_enum RENAME VALUE '{new}' TO '{old}'")
