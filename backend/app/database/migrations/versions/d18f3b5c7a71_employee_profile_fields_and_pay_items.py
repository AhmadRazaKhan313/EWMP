"""employee: richer profile, many emergency contacts, custom pay items

Adds the Frappe-HR-style personal data (family, permanent address, education,
work history, health insurance, IBAN), a list of emergency contacts (the old
single `emergency_contact` is kept and backfilled into the list), and
`compensation_items` — extra recurring allowances / deductions per employee.

Revision ID: d18f3b5c7a71
Revises: c17e9d2a4b60
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d18f3b5c7a71"
down_revision: Union[str, None] = "c17e9d2a4b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("father_name", sa.String(150), nullable=True))
    op.add_column("employees", sa.Column("mother_name", sa.String(150), nullable=True))
    op.add_column("employees", sa.Column("spouse_name", sa.String(150), nullable=True))
    op.add_column("employees", sa.Column("permanent_address", sa.JSON(), nullable=True))
    op.add_column("employees", sa.Column("bank_iban", sa.String(34), nullable=True))
    op.add_column("employees", sa.Column("health_insurance_provider", sa.String(150), nullable=True))
    op.add_column("employees", sa.Column("health_insurance_number", sa.String(80), nullable=True))
    op.add_column("employees", sa.Column("emergency_contacts", sa.JSON(), nullable=True))
    op.add_column("employees", sa.Column("education", sa.JSON(), nullable=True))
    op.add_column("employees", sa.Column("work_experience", sa.JSON(), nullable=True))
    op.add_column("employees", sa.Column("compensation_items", sa.JSON(), nullable=True))

    # Existing single contacts become the first entry of the new list, so
    # nobody's emergency contact disappears from the screen after upgrading.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, emergency_contact FROM employees WHERE emergency_contact IS NOT NULL")
    ).fetchall()
    import json

    for row in rows:
        contact = row[1]
        if isinstance(contact, str):
            contact = json.loads(contact)
        if isinstance(contact, dict) and contact.get("name"):
            bind.execute(
                sa.text("UPDATE employees SET emergency_contacts = CAST(:v AS JSON) WHERE id = :i"),
                {"v": json.dumps([contact]), "i": row[0]},
            )


def downgrade() -> None:
    for col in (
        "compensation_items", "work_experience", "education", "emergency_contacts",
        "health_insurance_number", "health_insurance_provider", "bank_iban",
        "permanent_address", "spouse_name", "mother_name", "father_name",
    ):
        op.drop_column("employees", col)
