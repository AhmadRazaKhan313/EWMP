"""one row per day / active timer / balance / role slug / payslip

Revision ID: 1ff3dd1a844a
Revises: cf023f713d58
Create Date: 2026-09-28 00:00:00.000000

Audit finding H-2. Five things that must be unique had no database rule, so a
double-click or two concurrent requests could create a second row — after
which every `scalar_one_or_none()` that reads it raised MultipleResultsFound
and that employee's day / timer / balance answered HTTP 500 until someone
cleaned the database by hand.

  attendance_records  one per (tenant, employee, date)      among live rows
  work_sessions       one non-ENDED session per employee    among live rows
  leave_balances      one per (employee, leave type, year)  among live rows
  roles               one per (organization, slug)
  payslips            one per (payroll run, employee)       among live rows

Existing duplicates are MERGED first (the index can't be created while any
exist), moving everything that points at them:

  * attendance day   keep the row with the most punches (then the oldest);
                     move its duplicates' punches and regularizations onto
                     it, rebuild its first-in / last-out / total from those
                     punches, delete the emptied duplicates.
  * work session     keep the most recently started; end the older ones at
                     their own start (0 minutes — they were ghosts running in
                     parallel), closing any open break the same way.
  * leave balance    keep the oldest; add the duplicates' used and pending
                     days into it (each duplicate was charged by different
                     requests, so the true usage is the sum), delete them.
  * role             keep the oldest; move user assignments and permissions
                     onto it, delete the duplicates.
  * payslip          keep the one with a payment attached (else the newest);
                     delete the rest (their lines cascade) and recompute the
                     run's totals, which the duplicates had inflated.

Two cases are ambiguous and STOP the migration with a message instead of
guessing: same-slug roles where only some are full-access (merging would
silently grant or remove full access), and a duplicate payslip that already
has a payment attached. Resolve those by hand, then re-run.

Downgrade drops the indexes; merged duplicates are not restored.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1ff3dd1a844a"
down_revision: Union[str, None] = "cf023f713d58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _attendance_records() -> None:
    op.execute(
        """
        CREATE TEMP TABLE _att_dupes ON COMMIT DROP AS
        WITH ranked AS (
            SELECT r.id,
                   ROW_NUMBER() OVER w AS rn,
                   FIRST_VALUE(r.id) OVER w AS keeper_id
            FROM attendance_records r
            LEFT JOIN LATERAL (
                SELECT count(*) AS n FROM attendance_punches p WHERE p.attendance_record_id = r.id
            ) pc ON true
            WHERE r.is_deleted = false
            WINDOW w AS (PARTITION BY r.tenant_id, r.employee_id, r.date
                         ORDER BY pc.n DESC, r.created_at, r.id)
        )
        SELECT id AS dup_id, keeper_id FROM ranked WHERE rn > 1
        """
    )
    op.execute(
        "UPDATE attendance_punches p SET attendance_record_id = d.keeper_id "
        "FROM _att_dupes d WHERE p.attendance_record_id = d.dup_id"
    )
    op.execute(
        "UPDATE attendance_regularizations g SET attendance_record_id = d.keeper_id "
        "FROM _att_dupes d WHERE g.attendance_record_id = d.dup_id"
    )
    # Rebuild each keeper's summary from the punches it now owns (same rules
    # as recalculate_from_punches: forced / open punches contribute 0).
    op.execute(
        """
        UPDATE attendance_records r SET
            check_in = s.first_in,
            check_out = s.last_out,
            punch_count = s.n,
            total_minutes = s.total,
            is_forced_checkout = r.is_forced_checkout OR s.any_forced
        FROM (
            SELECT p.attendance_record_id AS rid,
                   min(p.punch_in) AS first_in,
                   max(p.punch_out) AS last_out,
                   count(*) AS n,
                   COALESCE(sum(p.duration_minutes) FILTER (
                       WHERE p.punch_out IS NOT NULL AND NOT p.is_forced_checkout), 0) AS total,
                   bool_or(p.is_forced_checkout) AS any_forced
            FROM attendance_punches p
            WHERE NOT p.is_deleted
              AND p.attendance_record_id IN (SELECT keeper_id FROM _att_dupes)
            GROUP BY p.attendance_record_id
        ) s
        WHERE r.id = s.rid
        """
    )
    op.execute("DELETE FROM attendance_records r USING _att_dupes d WHERE r.id = d.dup_id")
    op.execute(
        "CREATE UNIQUE INDEX uq_attendance_records_one_per_day "
        "ON attendance_records (tenant_id, employee_id, date) WHERE is_deleted = false"
    )


def _work_sessions() -> None:
    op.execute(
        """
        CREATE TEMP TABLE _ws_ghosts ON COMMIT DROP AS
        SELECT id FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY started_at DESC, id) AS rn
            FROM work_sessions
            WHERE status <> 'ENDED' AND is_deleted = false
        ) x WHERE rn > 1
        """
    )
    op.execute(
        "UPDATE break_records b SET ended_at = b.started_at "
        "FROM _ws_ghosts g WHERE b.work_session_id = g.id AND b.ended_at IS NULL"
    )
    op.execute(
        "UPDATE work_sessions w SET status = 'ENDED', ended_at = w.started_at, total_minutes = 0 "
        "FROM _ws_ghosts g WHERE w.id = g.id"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_work_sessions_one_active_per_employee "
        "ON work_sessions (employee_id) WHERE status <> 'ENDED' AND is_deleted = false"
    )


def _leave_balances() -> None:
    op.execute(
        """
        CREATE TEMP TABLE _lb_dupes ON COMMIT DROP AS
        SELECT id AS dup_id, keeper_id FROM (
            SELECT id,
                   ROW_NUMBER() OVER w AS rn,
                   FIRST_VALUE(id) OVER w AS keeper_id
            FROM leave_balances
            WHERE is_deleted = false
            WINDOW w AS (PARTITION BY employee_id, leave_type_id, year ORDER BY created_at, id)
        ) x WHERE rn > 1
        """
    )
    op.execute(
        """
        UPDATE leave_balances k SET
            used_days = k.used_days + s.used,
            pending_days = k.pending_days + s.pending,
            entitled_days = GREATEST(k.entitled_days, s.entitled),
            carried_forward_days = GREATEST(k.carried_forward_days, s.carried)
        FROM (
            SELECT d.keeper_id, sum(b.used_days) AS used, sum(b.pending_days) AS pending,
                   max(b.entitled_days) AS entitled, max(b.carried_forward_days) AS carried
            FROM _lb_dupes d JOIN leave_balances b ON b.id = d.dup_id
            GROUP BY d.keeper_id
        ) s
        WHERE k.id = s.keeper_id
        """
    )
    op.execute("DELETE FROM leave_balances b USING _lb_dupes d WHERE b.id = d.dup_id")
    op.execute(
        "CREATE UNIQUE INDEX uq_leave_balances_one_per_type_year "
        "ON leave_balances (employee_id, leave_type_id, year) WHERE is_deleted = false"
    )


def _roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM roles GROUP BY organization_id, slug
                HAVING count(*) > 1 AND count(DISTINCT is_super) > 1
            ) THEN
                RAISE EXCEPTION 'Duplicate role slugs where only some copies are full-access (is_super). '
                    'Merging would silently grant or remove full access - rename or delete one copy '
                    'by hand, then re-run the migration. Find them with: SELECT organization_id, slug '
                    'FROM roles GROUP BY 1, 2 HAVING count(*) > 1;';
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE _role_dupes ON COMMIT DROP AS
        SELECT id AS dup_id, keeper_id FROM (
            SELECT id,
                   ROW_NUMBER() OVER w AS rn,
                   FIRST_VALUE(id) OVER w AS keeper_id
            FROM roles
            WINDOW w AS (PARTITION BY organization_id, slug ORDER BY created_at, id)
        ) x WHERE rn > 1
        """
    )
    op.execute(
        "INSERT INTO user_roles (user_id, role_id) "
        "SELECT ur.user_id, d.keeper_id FROM user_roles ur JOIN _role_dupes d ON ur.role_id = d.dup_id "
        "ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT d.keeper_id, rp.permission_id FROM role_permissions rp JOIN _role_dupes d ON rp.role_id = d.dup_id "
        "ON CONFLICT DO NOTHING"
    )
    op.execute("DELETE FROM roles r USING _role_dupes d WHERE r.id = d.dup_id")
    op.execute("CREATE UNIQUE INDEX uq_roles_org_slug ON roles (organization_id, slug)")


def _payslips() -> None:
    op.execute(
        """
        CREATE TEMP TABLE _ps_dupes ON COMMIT DROP AS
        SELECT id AS dup_id, payroll_run_id FROM (
            SELECT p.id, p.payroll_run_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.payroll_run_id, p.employee_id
                       ORDER BY EXISTS (SELECT 1 FROM payroll_payment_batch_items i WHERE i.payslip_id = p.id) DESC,
                                p.created_at DESC, p.id
                   ) AS rn
            FROM payslips p
            WHERE p.is_deleted = false
        ) x WHERE rn > 1
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM payroll_payment_batch_items i JOIN _ps_dupes d ON i.payslip_id = d.dup_id) THEN
                RAISE EXCEPTION 'An employee has two payslips in the same payroll run and BOTH have a payment '
                    'batch item. Decide which payment is real, remove the other by hand, then re-run the '
                    'migration. Find them with: SELECT payroll_run_id, employee_id FROM payslips '
                    'WHERE NOT is_deleted GROUP BY 1, 2 HAVING count(*) > 1;';
            END IF;
        END $$
        """
    )
    op.execute(
        "CREATE TEMP TABLE _ps_runs ON COMMIT DROP AS SELECT DISTINCT payroll_run_id FROM _ps_dupes"
    )
    op.execute("DELETE FROM payslips p USING _ps_dupes d WHERE p.id = d.dup_id")
    op.execute(
        """
        UPDATE payroll_runs r SET
            total_gross = s.gross, total_deductions = s.deductions,
            total_net = s.net, employee_count = s.n
        FROM (
            SELECT p.payroll_run_id, COALESCE(sum(p.gross_salary), 0) AS gross,
                   COALESCE(sum(p.total_deductions), 0) AS deductions,
                   COALESCE(sum(p.net_salary), 0) AS net, count(*) AS n
            FROM payslips p
            WHERE NOT p.is_deleted AND p.payroll_run_id IN (SELECT payroll_run_id FROM _ps_runs)
            GROUP BY p.payroll_run_id
        ) s
        WHERE r.id = s.payroll_run_id
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_payslips_one_per_run_employee "
        "ON payslips (payroll_run_id, employee_id) WHERE is_deleted = false"
    )


def upgrade() -> None:
    _attendance_records()
    _work_sessions()
    _leave_balances()
    _roles()
    _payslips()


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_payslips_one_per_run_employee")
    op.execute("DROP INDEX IF EXISTS uq_roles_org_slug")
    op.execute("DROP INDEX IF EXISTS uq_leave_balances_one_per_type_year")
    op.execute("DROP INDEX IF EXISTS uq_work_sessions_one_active_per_employee")
    op.execute("DROP INDEX IF EXISTS uq_attendance_records_one_per_day")
