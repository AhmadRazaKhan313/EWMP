"""add unique constraint on employees(tenant_id, employee_code)

Revision ID: 3e338fd61f00
Revises: 9b659579c38e
Create Date: 2026-08-31 00:00:00.000000

Closes the "employee_code generated via count+1 (not unique) -> collisions"
bug at the database level. `get_next_employee_code()` used `count(*) + 1`
scoped to non-deleted employees, which reused an already-assigned code
once any employee was soft-deleted (the count no longer includes them,
but their code is still taken) — silently creating two employees with the
same code, since there was no constraint to catch it. Any later lookup by
code (`get_by_code`, using `scalar_one_or_none()`) would then raise
`MultipleResultsFound`.

This migration first defensively renames any pre-existing duplicate codes
(keeping the oldest row's code as-is, suffixing the rest with -DUPn) so the
unique constraint can be added cleanly even if the bug has already
produced duplicates in this database, then adds the constraint.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3e338fd61f00'
down_revision: Union[str, None] = '9b659579c38e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Defensive dedup: for any (tenant_id, employee_code) pair that appears
    # more than once, keep the earliest-created row's code untouched and
    # rename the rest so the unique constraint below can be added cleanly.
    op.execute("""
        WITH duplicates AS (
            SELECT
                id,
                employee_code,
                ROW_NUMBER() OVER (
                    PARTITION BY tenant_id, employee_code
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM employees
        )
        UPDATE employees
        SET employee_code = employees.employee_code || '-DUP' || duplicates.rn
        FROM duplicates
        WHERE employees.id = duplicates.id AND duplicates.rn > 1
    """)

    op.create_unique_constraint(
        "uq_employees_tenant_employee_code",
        "employees",
        ["tenant_id", "employee_code"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_employees_tenant_employee_code", "employees", type_="unique")
