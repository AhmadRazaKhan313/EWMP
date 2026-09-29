"""attendance multi-punch, auto-cutoff and regularization

Revision ID: a1b2c3d4e5f6
Revises: f3a7c9d2e1b4
Create Date: 2026-09-17 00:00:00.000000

Three changes, all driven by the same root cause: `attendance_records`
held exactly one check_in and one check_out per employee per day.

  1. attendance_punches — one row per in/out pair, many per day. The old
     single-pair columns are KEPT on attendance_records and maintained as
     a derived first-in / last-out summary, because payroll generation,
     the payroll register CSV and the reports all read them. Migrating
     those consumers is a separate change; breaking them here is not
     necessary to fix the underlying model.

  2. Auto-cutoff columns + a MISSED_PUNCH status, so an open punch cannot
     run indefinitely and a day the system closed on the employee's
     behalf is distinguishable from one they closed themselves.

  3. attendance_regularizations — the employee's request to correct a
     missed punch, held separately from the attendance record until a
     manager approves it.

Existing data: every current attendance_records row with a check_in is
backfilled into exactly one punch, so nothing that already happened is
lost and the derived columns agree with their new source of truth from
the first deploy.

Fixed in place (see the cast on check_out_source in the backfill INSERT
below): `attendance_records.check_in_source` and `.check_out_source` were
declared as two SEPARATE Postgres enum types with identical labels
(`attendance_source_enum` and `attendance_source_enum2` — an artifact of
how the initial-schema migration was generated), while both
`attendance_punches.punch_in_source` and `.punch_out_source` use the
single `attendance_source_enum` type. Selecting `check_out_source`
straight into `punch_out_source` is therefore a cross-enum-type mismatch
that Postgres rejects at plan time — regardless of whether any rows exist
to migrate. This migration could not previously complete against a real
Postgres database (a plain `alembic upgrade head` on a fresh instance
would fail here every time), which is why patching the statement here,
rather than adding a follow-up migration, is correct: nothing could have
successfully applied this revision before.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f3a7c9d2e1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. New enum value on the existing status type ───────────────────
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on
    # PostgreSQL < 12; IF NOT EXISTS makes the statement re-runnable on a
    # partially-applied migration. The label is the Python enum member's
    # NAME (uppercase), matching how SQLAlchemy binds Enum(python_class)
    # — see ebe9ce81bf8e for where this codebase learned that the hard
    # way.
    op.execute("ALTER TYPE attendance_status_enum ADD VALUE IF NOT EXISTS 'MISSED_PUNCH'")

    regularization_status_enum = postgresql.ENUM(
        "PENDING", "APPROVED", "REJECTED", "CANCELLED",
        name="regularization_status_enum",
        create_type=False,
    )
    regularization_status_enum.create(bind, checkfirst=True)

    # ── 2. attendance_records: derived + cutoff columns ─────────────────
    op.add_column(
        "attendance_records",
        sa.Column("punch_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "attendance_records",
        sa.Column("is_forced_checkout", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "attendance_records",
        sa.Column("forced_checkout_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── 3. attendance_punches ───────────────────────────────────────────
    attendance_source_enum = postgresql.ENUM(
        "MANUAL", "BIOMETRIC", "QR_CODE", "GEO", "DESKTOP_AGENT", "MOBILE",
        name="attendance_source_enum",
        create_type=False,
    )

    op.create_table(
        "attendance_punches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attendance_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("punch_in", sa.DateTime(timezone=True), nullable=False),
        sa.Column("punch_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column("punch_in_source", attendance_source_enum, nullable=False, server_default="MANUAL"),
        sa.Column("punch_out_source", attendance_source_enum, nullable=True),
        sa.Column("punch_in_latitude", sa.Float(), nullable=True),
        sa.Column("punch_in_longitude", sa.Float(), nullable=True),
        sa.Column("punch_out_latitude", sa.Float(), nullable=True),
        sa.Column("punch_out_longitude", sa.Float(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("is_forced_checkout", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("auto_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shift_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        # A punch cannot end before it starts. Enforced in the database
        # because manual HR corrections and the regularization approval
        # path both write these columns, and only one of them is behind
        # the service-layer validation.
        sa.CheckConstraint("punch_out IS NULL OR punch_out > punch_in", name="ck_punch_out_after_in"),
    )
    op.create_index("ix_attendance_punches_record", "attendance_punches", ["attendance_record_id"])
    op.create_index("ix_attendance_punches_employee_in", "attendance_punches", ["employee_id", "punch_in"])

    # THE invariant: at most one open punch per employee at a time.
    #
    # A partial unique index rather than an application-level check,
    # because "SELECT for an open punch, then INSERT" is a race. Two
    # check-in taps from a phone on a flaky connection can both pass the
    # SELECT and both insert, leaving two running timers and an
    # unanswerable "how long have you been working". The database is the
    # only place this can be made actually true.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_attendance_punches_one_open_per_employee
        ON attendance_punches (employee_id)
        WHERE punch_out IS NULL
          AND is_forced_checkout = false
          AND is_deleted = false
        """
    )

    # ── 4. attendance_regularizations ───────────────────────────────────
    op.create_table(
        "attendance_regularizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attendance_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("punch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("attendance_punches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("requested_punch_in", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_punch_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", regularization_status_enum, nullable=False, server_default="PENDING"),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comments", sa.Text(), nullable=True),
    )
    op.create_index("ix_attendance_regularizations_employee_date", "attendance_regularizations", ["employee_id", "date"])
    op.create_index("ix_attendance_regularizations_status", "attendance_regularizations", ["status"])

    # One OPEN request per day per employee. Without this, an employee
    # tapping "submit" twice creates two pending claims for the same day,
    # and a manager approving both applies the second over the first with
    # no indication that happened.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_regularization_one_pending_per_day
        ON attendance_regularizations (employee_id, date)
        WHERE status = 'PENDING' AND is_deleted = false
        """
    )

    # ── 5. Backfill existing days into punches ──────────────────────────
    # Every attendance_records row that has a check_in becomes exactly one
    # punch. duration_minutes reuses the row's existing total_minutes
    # where present rather than recomputing from the timestamps, so any
    # break subtraction the old check-out path applied is preserved.
    op.execute(
        """
        INSERT INTO attendance_punches (
            tenant_id, attendance_record_id, employee_id,
            punch_in, punch_out, punch_in_source, punch_out_source,
            punch_in_latitude, punch_in_longitude,
            punch_out_latitude, punch_out_longitude,
            duration_minutes, shift_id, is_forced_checkout, is_deleted
        )
        SELECT
            r.tenant_id, r.id, r.employee_id,
            r.check_in, r.check_out, r.check_in_source,
            -- Cast across the two distinct-but-identical-labeled enum types
            -- (see the module docstring above).
            r.check_out_source::text::attendance_source_enum,
            r.check_in_latitude, r.check_in_longitude,
            r.check_out_latitude, r.check_out_longitude,
            CASE
                WHEN r.check_out IS NULL THEN NULL
                ELSE COALESCE(
                    r.total_minutes,
                    GREATEST(0, (EXTRACT(EPOCH FROM (r.check_out - r.check_in)) / 60)::int)
                )
            END,
            r.shift_id, false, false
        FROM attendance_records r
        WHERE r.check_in IS NOT NULL
          AND r.is_deleted = false
        """
    )
    op.execute(
        """
        UPDATE attendance_records r
        SET punch_count = 1
        WHERE r.check_in IS NOT NULL AND r.is_deleted = false
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_regularization_one_pending_per_day")
    op.drop_index("ix_attendance_regularizations_status", table_name="attendance_regularizations")
    op.drop_index("ix_attendance_regularizations_employee_date", table_name="attendance_regularizations")
    op.drop_table("attendance_regularizations")

    op.execute("DROP INDEX IF EXISTS uq_attendance_punches_one_open_per_employee")
    op.drop_index("ix_attendance_punches_employee_in", table_name="attendance_punches")
    op.drop_index("ix_attendance_punches_record", table_name="attendance_punches")
    op.drop_table("attendance_punches")

    op.drop_column("attendance_records", "forced_checkout_at")
    op.drop_column("attendance_records", "is_forced_checkout")
    op.drop_column("attendance_records", "punch_count")

    op.execute("DROP TYPE IF EXISTS regularization_status_enum")
    # The MISSED_PUNCH label is deliberately left on attendance_status_enum.
    # PostgreSQL cannot remove a value from an enum type, and rebuilding
    # the type would require rewriting every attendance row — far more
    # destructive than leaving one unused label behind.
