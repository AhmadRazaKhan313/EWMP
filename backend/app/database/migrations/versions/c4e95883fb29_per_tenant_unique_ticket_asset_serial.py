"""per-tenant uniqueness for ticket numbers, asset tags and serial numbers

Revision ID: c4e95883fb29
Revises: 55c41b724a09
Create Date: 2026-09-26 00:00:00.000000

Audit findings C-5 / H-3. Four columns that belong to ONE organisation were
unique across the WHOLE platform:

  support_tickets.ticket_number   (ix_support_tickets_ticket_number)
  assets.asset_tag                (ix_assets_asset_tag)
  assets.serial_number            (assets_serial_number_key)
  devices.serial_number           (devices_serial_number_key)

Worst case was the helpdesk: ticket numbers are generated per organisation
(TKT-00001, TKT-00002, ...), so the SECOND organisation's first ticket
collided with the first organisation's TKT-00001 → IntegrityError → HTTP 500
on every ticket for every organisation after the first. Two organisations
also couldn't both tag a laptop "LAPTOP-001", and one company's serial number
blocked the same model's serial being recorded anywhere else.

After this migration:

  * support_tickets: UNIQUE (tenant_id, ticket_number) — soft-deleted tickets
    still count, so a ticket number is never handed out twice in one org.
  * assets.asset_tag, assets.serial_number, devices.serial_number:
    UNIQUE (tenant_id, <column>) WHERE is_deleted = false — a deleted asset's
    tag can be reused, and a decommissioned device (soft-deleted) doesn't
    block the same hardware from being enrolled again.

Data safety: the old constraints were STRICTER (global), so no existing data
can violate the new per-organisation ones — no clean-up step is needed.

The old constraints are located through the catalog (by table + column)
instead of by name, so this works whatever names a given database gave them.

Downgrade restores the global constraints; it will fail if, by then, two
organisations legitimately share a value — that is expected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e95883fb29"
down_revision: Union[str, None] = "55c41b724a09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACTIVE_ONLY = sa.text("is_deleted = false")


def _drop_single_column_uniques(table: str, column: str) -> None:
    """Drop every UNIQUE constraint and every standalone UNIQUE index that
    covers exactly (<column>) on <table>. Primary keys are never touched."""
    conn = op.get_bind()

    constraints = conn.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            WHERE c.conrelid = CAST(:table AS regclass)
              AND c.contype = 'u'
              AND array_length(c.conkey, 1) = 1
              AND a.attname = :column
            """
        ),
        {"table": table, "column": column},
    ).scalars().all()
    for name in constraints:
        op.drop_constraint(name, table, type_="unique")

    indexes = conn.execute(
        sa.text(
            """
            SELECT i.relname
            FROM pg_index x
            JOIN pg_class i ON i.oid = x.indexrelid
            JOIN pg_attribute a ON a.attrelid = x.indrelid AND a.attnum = x.indkey[0]
            WHERE x.indrelid = CAST(:table AS regclass)
              AND x.indisunique
              AND NOT x.indisprimary
              AND x.indnatts = 1
              AND a.attname = :column
              AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = x.indexrelid)
            """
        ),
        {"table": table, "column": column},
    ).scalars().all()
    for name in indexes:
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    _drop_single_column_uniques("support_tickets", "ticket_number")
    _drop_single_column_uniques("assets", "asset_tag")
    _drop_single_column_uniques("assets", "serial_number")
    _drop_single_column_uniques("devices", "serial_number")

    op.create_unique_constraint(
        "uq_support_tickets_tenant_ticket_number",
        "support_tickets",
        ["tenant_id", "ticket_number"],
    )
    op.create_index(
        "uq_assets_tenant_asset_tag_active", "assets", ["tenant_id", "asset_tag"],
        unique=True, postgresql_where=ACTIVE_ONLY,
    )
    op.create_index(
        "uq_assets_tenant_serial_number_active", "assets", ["tenant_id", "serial_number"],
        unique=True, postgresql_where=ACTIVE_ONLY,
    )
    op.create_index(
        "uq_devices_tenant_serial_number_active", "devices", ["tenant_id", "serial_number"],
        unique=True, postgresql_where=ACTIVE_ONLY,
    )


def downgrade() -> None:
    op.drop_index("uq_devices_tenant_serial_number_active", table_name="devices")
    op.drop_index("uq_assets_tenant_serial_number_active", table_name="assets")
    op.drop_index("uq_assets_tenant_asset_tag_active", table_name="assets")
    op.drop_constraint("uq_support_tickets_tenant_ticket_number", "support_tickets", type_="unique")

    # The original (global) shapes and names from the initial schema.
    op.create_index("ix_support_tickets_ticket_number", "support_tickets", ["ticket_number"], unique=True)
    op.create_index("ix_assets_asset_tag", "assets", ["asset_tag"], unique=True)
    op.create_unique_constraint("assets_serial_number_key", "assets", ["serial_number"])
    op.create_unique_constraint("devices_serial_number_key", "devices", ["serial_number"])
