"""employee: dependents, skills, languages, certifications, driving licence

OrangeHRM-style extras on top of d18f3b5c7a71. All nullable, so existing rows
need no backfill.

Revision ID: e29a4c6d8b82
Revises: d18f3b5c7a71
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e29a4c6d8b82"
down_revision: Union[str, None] = "d18f3b5c7a71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("driving_license_number", sa.String(50), nullable=True))
    op.add_column("employees", sa.Column("driving_license_expiry", sa.Date(), nullable=True))
    op.add_column("employees", sa.Column("skills", sa.JSON(), nullable=True))
    op.add_column("employees", sa.Column("languages", sa.JSON(), nullable=True))
    op.add_column("employees", sa.Column("certifications", sa.JSON(), nullable=True))
    op.add_column("employees", sa.Column("dependents", sa.JSON(), nullable=True))


def downgrade() -> None:
    for col in ("dependents", "certifications", "languages", "skills", "driving_license_expiry", "driving_license_number"):
        op.drop_column("employees", col)
