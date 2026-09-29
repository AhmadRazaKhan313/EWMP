"""fix missing deleted_at on attendance_punches / attendance_regularizations

Revision ID: b7d4f1a92c63
Revises: a1b2c3d4e5f6
Create Date: 2026-09-17 17:00:00.000000

BUG THIS FIXES: both tables were created by a1b2c3d4e5f6 as TenantModel
subclasses (see app/models/attendance.py's AttendancePunch and
AttendanceRegularization), and TenantModel's SoftDeleteMixin gives every
such model TWO soft-delete columns — is_deleted (bool) and deleted_at
(nullable timestamp). The create_table() calls in a1b2c3d4e5f6 only
included is_deleted; deleted_at was missed entirely.

This went unnoticed until runtime because the ORM model always SELECTs
deleted_at (it doesn't know the column is missing), and nothing exercised
that query path until the first real check-out after the migration:
get_open_punch() in app/services/attendance_punches.py issues exactly
that SELECT, so every check-out that reaches the multi-punch code path
failed with `UndefinedColumnError: column attendance_punches.deleted_at
does not exist` — surfaced to the browser as a misleading CORS error,
since an unhandled exception that escapes past CORSMiddleware never gets
a chance to have CORS headers attached to its response.

IDEMPOTENT ON PURPOSE (edited in place, audit finding C-8): the sibling
revision c4d8f1a6b3e7 branches from the same parent (a1b2c3d4e5f6) and adds
the very same column with ADD COLUMN IF NOT EXISTS. On a fresh database
Alembic runs both branches before the merge (55c41b724a09), and whichever
of the two ran second used to fail — here, with a plain op.add_column():
"DuplicateColumnError: column deleted_at of relation attendance_punches
already exists" — so `alembic upgrade head` could never complete on a new
install. Editing this revision (instead of adding a new one) is the only
fix that works: the failure happens before any later revision could run,
and databases that already applied this revision never execute it again.
Upgrade and downgrade now use IF [NOT] EXISTS, matching c4d8f1a6b3e7, so
the two branches can run in either order.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4f1a92c63"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE attendance_punches "
        "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE attendance_regularizations "
        "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE attendance_regularizations DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE attendance_punches DROP COLUMN IF EXISTS deleted_at")
