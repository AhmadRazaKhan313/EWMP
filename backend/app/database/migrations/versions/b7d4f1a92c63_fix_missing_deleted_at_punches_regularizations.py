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
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7d4f1a92c63"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attendance_punches",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attendance_regularizations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("attendance_regularizations", "deleted_at")
    op.drop_column("attendance_punches", "deleted_at")
