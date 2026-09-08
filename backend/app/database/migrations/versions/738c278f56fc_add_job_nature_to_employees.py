"""add job_nature (employment status / job nature) to employees

Revision ID: 738c278f56fc
Revises: d0c1da59245b
Create Date: 2026-09-05 00:00:00.000000

Adds the "Employment Status (Job Nature)" classification requested for the
Add/Edit Employee forms: Permanent/Regular, Probationary, Contractual/
Fixed-Term, Intern/Trainee, Part-Time, Temporary/Casual.

This is a genuine new column + Postgres ENUM type — not a client-side-only
field — so it is queryable/filterable/reportable the same way
employment_type and employment_status already are.

Kept distinct from the two existing, similarly-named columns:
  - employment_type   (full_time/part_time/contract/intern/freelance —
                        work-schedule/engagement kind)
  - employment_status (active/on_leave/probation/notice_period/terminated/
                        resigned — day-to-day lifecycle state)
job_nature is the employee's contractual standing (permanent vs.
probationary vs. contractual, etc.) — a separate concern from both.

Existing rows are backfilled to 'probationary' (the safest default: it
under-states permanence rather than over-stating it, and matches the
column's own application-level default for brand-new employees). HR should
review and correct historical records via the Edit Employee > Employment
tab where needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '738c278f56fc'
down_revision: Union[str, None] = 'd0c1da59245b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOB_NATURE_VALUES = (
    "permanent",
    "probationary",
    "contractual",
    "intern",
    "part_time",
    "temporary",
)


def upgrade() -> None:
    job_nature_enum = postgresql.ENUM(
        *JOB_NATURE_VALUES, name="job_nature_enum"
    )
    job_nature_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "employees",
        sa.Column(
            "job_nature",
            job_nature_enum,
            nullable=False,
            server_default="probationary",
            comment="Employment Status / Job Nature: permanent, probationary, "
            "contractual, intern, part_time, or temporary",
        ),
    )
    op.create_index("ix_employees_job_nature", "employees", ["job_nature"])


def downgrade() -> None:
    op.drop_index("ix_employees_job_nature", table_name="employees")
    op.drop_column("employees", "job_nature")
    postgresql.ENUM(name="job_nature_enum").drop(op.get_bind(), checkfirst=True)
