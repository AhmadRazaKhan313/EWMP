"""fix work_session_status_enum casing

Revision ID: ebe9ce81bf8e
Revises: d0c1da59245b
Create Date: 2026-09-04 07:39:16.482899

The original migration (d0c1da59245b) created work_session_status_enum
with LOWERCASE labels ("active", "on_break", "ended"), inconsistent with
every other enum in this codebase (employment_type_enum, gender_enum,
etc.), which all use the Python enum member's UPPERCASE *name*.

SQLAlchemy's `Enum(SomePythonEnum)` column type binds using the member's
`.name` by default (not `.value`), unless `values_callable` overrides
that. Since WorkSessionStatus was mapped the same way as every other
enum in this codebase (SAEnum(WorkSessionStatus, name=...), no
values_callable), the ORM sends "ACTIVE"/"ON_BREAK"/"ENDED" to Postgres
— which the lowercase-only enum type rejects with
`invalid input value for enum work_session_status_enum: "ENDED"`,
surfacing to the desktop app's Check In button as a 500 (and to axios,
if this had been a CORS/CSP issue instead, it'd look like a generic
"Network Error" — it's neither; this is a real server-side error).

Renaming the labels in place (rather than dropping/recreating the type)
preserves any rows already written under the old lowercase labels.

Note: no application code changes needed. `_serialize()` in
app/api/v1/hrms/work_sessions.py returns `session.status.value`, which
is still the lowercase string ("active", "on_break", "ended") from the
Python enum regardless of how the DB stores the label — the desktop
app's TypeScript contract (`"active" | "on_break" | "ended"`) is
unaffected by this fix.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'ebe9ce81bf8e'
down_revision: Union[str, None] = 'd0c1da59245b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RENAMES = [("active", "ACTIVE"), ("on_break", "ON_BREAK"), ("ended", "ENDED")]


def upgrade() -> None:
    for old, new in _RENAMES:
        op.execute(f"ALTER TYPE work_session_status_enum RENAME VALUE '{old}' TO '{new}'")
    op.execute("ALTER TABLE work_sessions ALTER COLUMN status SET DEFAULT 'ACTIVE'")


def downgrade() -> None:
    for old, new in _RENAMES:
        op.execute(f"ALTER TYPE work_session_status_enum RENAME VALUE '{new}' TO '{old}'")
    op.execute("ALTER TABLE work_sessions ALTER COLUMN status SET DEFAULT 'active'")
