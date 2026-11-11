"""finance budget: weekly / monthly / yearly plans and starting balances

Revision ID: a7c9e1b3d5f2
Revises: d4f6b8c0e2a4
Create Date: 2026-11-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1b3d5f2"
down_revision: Union[str, None] = "d4f6b8c0e2a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base():
    return [
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
    ]


def _idx(table):
    for c in ('id', 'tenant_id', 'is_deleted', 'deleted_at'):
        op.create_index(f'ix_{table}_{c}', table, [c])


def _tfk(table):
    return sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE', name=f'fk_{table}_tenant')


def upgrade() -> None:
    op.create_table('fin_budget_plans',
        sa.Column('period_type', sa.String(5), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(7), nullable=False),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('planned', sa.Numeric(18, 2), server_default='0', nullable=False),
        *_base(), sa.PrimaryKeyConstraint('id'), _tfk('fin_budget_plans'),
        sa.UniqueConstraint('tenant_id', 'period_type', 'period_start', 'kind', 'category', name='uq_fin_budget_plan'),
        sa.CheckConstraint("period_type in ('week','month','year')", name='ck_fin_budget_plan_period'),
        sa.CheckConstraint("kind in ('income','expense')", name='ck_fin_budget_plan_kind'),
        sa.CheckConstraint('planned >= 0', name='ck_fin_budget_plan_planned'))
    _idx('fin_budget_plans')

    op.create_table('fin_budget_openings',
        sa.Column('period_type', sa.String(5), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('starting_balance', sa.Numeric(18, 2), nullable=False),
        *_base(), sa.PrimaryKeyConstraint('id'), _tfk('fin_budget_openings'),
        sa.UniqueConstraint('tenant_id', 'period_type', 'period_start', name='uq_fin_budget_opening'),
        sa.CheckConstraint("period_type in ('week','month','year')", name='ck_fin_budget_opening_period'))
    _idx('fin_budget_openings')


def downgrade() -> None:
    op.drop_table('fin_budget_openings')
    op.drop_table('fin_budget_plans')
