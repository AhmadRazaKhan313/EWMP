"""add missing deleted_at column to attendance_punches and attendance_regularizations

Revision ID: c4d8f1a6b3e7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-22 00:00:00.000000

Both tables were created in a1b2c3d4e5f6 as TenantModel subclasses, which
(via SoftDeleteMixin) map a `deleted_at` column in Python - but that
migration's create_table() calls only listed `is_deleted`, so the column was
never actually created on Postgres. Every other TenantModel table in this
codebase has always carried both columns together (see the deleted_at /
is_deleted pairs added throughout 8796d530abeb_initial_schema.py); these two
tables are the only ones out of step with their own model.

The practical effect: any ORM `select(AttendancePunch)` or
`select(AttendanceRegularization)` asks Postgres for a column that does not
exist and fails with `UndefinedColumnError` - i.e. reading attendance punches
or regularizations does not work at all against a real database. This was
missed in review because the test suite runs against fakes/aiosqlite, not
a real Postgres schema built from these migrations.

`soft_delete()` / `restore()` (SoftDeleteMixin) and every repository method
that filters `is_deleted` already assume `deleted_at` exists and are
unchanged - this migration only makes the table match the model.

IF NOT EXISTS guards (upgrade) / IF EXISTS guards (downgrade): at least one
deployment of this codebase had these columns already present before this
migration ever ran against it - almost certainly from an earlier dev-setup
script that called SQLAlchemy's Base.metadata.create_all() directly against
a real database (which builds tables straight from the current models,
deleted_at included, entirely bypassing Alembic's own version bookkeeping).
Plain op.add_column()/op.create_index() raise DuplicateColumnError /
DuplicateTableError in that situation even though the end state is already
correct, blocking `alembic upgrade head` outright. Using raw
IF NOT EXISTS / IF EXISTS SQL (both supported since Postgres 9.6) makes this
migration a no-op wherever the columns/indexes already exist, and a normal
ADD COLUMN / CREATE INDEX everywhere else - either way, alembic_version
still correctly advances to this revision once it completes.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d8f1a6b3e7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no default: existing rows are not deleted, so NULL is the
    # correct value for every row already in the table - exactly what
    # SoftDeleteMixin.restore() resets it to, and what `is_deleted=false`
    # (already present and already correct on every existing row) implies.
    # Matches the ix_<table>_deleted_at naming every other TenantModel table
    # already has (see 8796d530abeb_initial_schema.py), and the `index=True`
    # on SoftDeleteMixin.deleted_at that these two tables were missing.
    op.execute(
        "ALTER TABLE attendance_punches "
        "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_attendance_punches_deleted_at "
        "ON attendance_punches (deleted_at)"
    )

    op.execute(
        "ALTER TABLE attendance_regularizations "
        "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_attendance_regularizations_deleted_at "
        "ON attendance_regularizations (deleted_at)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_attendance_regularizations_deleted_at"
    )
    op.execute(
        "ALTER TABLE attendance_regularizations DROP COLUMN IF EXISTS deleted_at"
    )

    op.execute("DROP INDEX IF EXISTS ix_attendance_punches_deleted_at")
    op.execute(
        "ALTER TABLE attendance_punches DROP COLUMN IF EXISTS deleted_at"
    )