"""finance period close: month / year lock

Revision ID: c9e1a3b5d7f3
Revises: b8d0f2a4c6e1
Create Date: 2026-11-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e1a3b5d7f3"
down_revision: Union[str, None] = "b8d0f2a4c6e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('fin_period_closes',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('period_type', sa.String(10), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('net_profit', sa.Numeric(18, 2), server_default='0', nullable=False),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('closed_by', sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE', name='fk_fin_period_closes_tenant'),
    )
    for c in ('id', 'tenant_id', 'is_deleted', 'deleted_at', 'period_end'):
        op.create_index(f'ix_fin_period_closes_{c}', 'fin_period_closes', [c])


def downgrade() -> None:
    op.drop_table('fin_period_closes')
