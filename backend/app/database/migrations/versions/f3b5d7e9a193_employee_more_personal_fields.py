"""employee: tax / EOBI / PF / visa numbers and more personal details

All nullable, so existing rows need no backfill.

Revision ID: f3b5d7e9a193
Revises: e29a4c6d8b82
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3b5d7e9a193"
down_revision: Union[str, None] = "e29a4c6d8b82"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("national_id_type", sa.String(30), nullable=True))
    op.add_column("employees", sa.Column("tax_number", sa.String(50), nullable=True))
    op.add_column("employees", sa.Column("social_security_number", sa.String(50), nullable=True))
    op.add_column("employees", sa.Column("provident_fund_number", sa.String(50), nullable=True))
    op.add_column("employees", sa.Column("visa_number", sa.String(50), nullable=True))
    op.add_column("employees", sa.Column("visa_expiry", sa.Date(), nullable=True))
    op.add_column("employees", sa.Column("religion", sa.String(50), nullable=True))
    op.add_column("employees", sa.Column("place_of_birth", sa.String(100), nullable=True))
    op.add_column("employees", sa.Column("home_phone", sa.String(50), nullable=True))
    op.add_column("employees", sa.Column("previous_employee_id", sa.String(50), nullable=True))
    op.add_column("employees", sa.Column("referral_source", sa.String(100), nullable=True))
    op.add_column("employees", sa.Column("hobbies", sa.Text(), nullable=True))
    op.add_column("employees", sa.Column("tshirt_size", sa.String(5), nullable=True))
    op.add_column("employees", sa.Column("social_links", sa.JSON(), nullable=True))


def downgrade() -> None:
    for col in (
        "social_links", "tshirt_size", "hobbies", "referral_source", "previous_employee_id",
        "home_phone", "place_of_birth", "religion", "visa_expiry", "visa_number",
        "provident_fund_number", "social_security_number", "tax_number", "national_id_type",
    ):
        op.drop_column("employees", col)
