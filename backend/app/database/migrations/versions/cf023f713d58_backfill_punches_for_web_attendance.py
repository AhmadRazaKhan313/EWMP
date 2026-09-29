"""backfill punches for attendance days written by the old web check-in

Revision ID: cf023f713d58
Revises: c4e95883fb29
Create Date: 2026-09-27 00:00:00.000000

Audit finding C-4. Until this release the web /attendance/check-in and
/check-out wrote AttendanceRecord.check_in / check_out directly and created NO
AttendancePunch, while the desktop app worked through punches. From now on
both go through punches, and a day's check-in / check-out / total are
recalculated FROM its punches.

A day that exists only as record columns would therefore be misread the
moment anything recalculates it — e.g. someone checked in and out on the web
this morning (old code), then checks in again after the deploy: the day would
be rebuilt from the one new punch and the morning's hours would vanish.

So every such day gets the punch it should always have had:

  * closed day (check_out set)     → one closed punch, same times and total
  * open day that is the employee's MOST RECENT open one, when they have no
    other open punch               → one OPEN punch (their next check-out,
                                     from either app, closes it normally)
  * any OLDER open day (abandoned; the old web check-out only ever closed
    the latest one)                → a force-closed punch and the day marked
                                     MISSED_PUNCH — exactly what the
                                     auto-cutoff does to an abandoned punch.
                                     The unique index allows one open punch
                                     per employee, so only one can stay open.

Days that already have punches (desktop) are not touched. Backfilled rows are
tagged in `notes`, so downgrade removes exactly them (day flags it set —
forced checkout / MISSED_PUNCH — are left as they are).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cf023f713d58"
down_revision: Union[str, None] = "c4e95883fb29"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MARKER = "backfilled from a web-only attendance day (migration cf023f713d58)"


def upgrade() -> None:
    # Runs in its own committed transaction. MISSED_PUNCH was added to
    # attendance_status_enum by a1b2c3d4e5f6, and PostgreSQL refuses to USE
    # an enum value inside the transaction that added it ("unsafe use of new
    # value") — which is exactly what happens on a fresh install, where
    # Alembic applies every migration in one transaction. autocommit_block()
    # commits everything before this point first. The backfill itself is a
    # single statement (INSERT … RETURNING feeding the UPDATE), so it is
    # still all-or-nothing.
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            WITH legacy AS (
                SELECT r.*,
                       (r.check_out IS NULL
                        AND ROW_NUMBER() OVER (
                            PARTITION BY r.employee_id, (r.check_out IS NULL)
                            ORDER BY r.check_in DESC
                        ) = 1
                        AND NOT EXISTS (
                            SELECT 1 FROM attendance_punches op
                            WHERE op.employee_id = r.employee_id
                              AND op.punch_out IS NULL
                              AND op.is_forced_checkout = false
                              AND op.is_deleted = false
                        )) AS stays_open
                FROM attendance_records r
                WHERE r.check_in IS NOT NULL
                  AND r.is_deleted = false
                  AND NOT EXISTS (
                      SELECT 1 FROM attendance_punches p WHERE p.attendance_record_id = r.id
                  )
            ),
            inserted AS (
                INSERT INTO attendance_punches (
                    tenant_id, attendance_record_id, employee_id, shift_id,
                    punch_in, punch_in_source, punch_in_latitude, punch_in_longitude,
                    punch_out, punch_out_source, punch_out_latitude, punch_out_longitude,
                    duration_minutes, is_forced_checkout, auto_closed_at, notes
                )
                SELECT
                    l.tenant_id, l.id, l.employee_id, l.shift_id,
                    l.check_in, l.check_in_source::text::attendance_source_enum,
                    l.check_in_latitude, l.check_in_longitude,
                    l.check_out, l.check_out_source::text::attendance_source_enum,
                    l.check_out_latitude, l.check_out_longitude,
                    CASE
                        WHEN l.check_out IS NOT NULL THEN GREATEST(0, COALESCE(
                            l.total_minutes,
                            FLOOR(EXTRACT(EPOCH FROM (l.check_out - l.check_in)) / 60)::int
                        ))
                        WHEN l.stays_open THEN NULL
                        ELSE 0
                    END,
                    (l.check_out IS NULL AND NOT l.stays_open),
                    CASE WHEN l.check_out IS NULL AND NOT l.stays_open THEN now() END,
                    '{MARKER}'
                FROM legacy l
                RETURNING attendance_record_id, is_forced_checkout, auto_closed_at
            )
            -- Keep each backfilled day's summary consistent with its new punch.
            UPDATE attendance_records r
            SET punch_count = 1,
                is_forced_checkout = r.is_forced_checkout OR i.is_forced_checkout,
                forced_checkout_at = CASE WHEN i.is_forced_checkout THEN i.auto_closed_at
                                          ELSE r.forced_checkout_at END,
                total_minutes = CASE WHEN i.is_forced_checkout THEN 0 ELSE r.total_minutes END,
                status = CASE
                    WHEN i.is_forced_checkout AND NOT r.is_regularized
                         AND r.status IN ('PRESENT', 'LATE') THEN 'MISSED_PUNCH'
                    ELSE r.status
                END
            FROM inserted i
            WHERE r.id = i.attendance_record_id
            """
        )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE attendance_records r
        SET punch_count = 0
        FROM attendance_punches p
        WHERE p.attendance_record_id = r.id AND p.notes = '{MARKER}'
        """
    )
    op.execute(f"DELETE FROM attendance_punches WHERE notes = '{MARKER}'")
