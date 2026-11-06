"""finance recurring invoices and payment reminders

Revision ID: a1c3e5f7b9d1
Revises: f9b1d3e5a7c0
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c3e5f7b9d1"
down_revision: Union[str, None] = "f9b1d3e5a7c0"
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


def upgrade() -> None:
    st = postgresql.ENUM('active', 'paused', 'ended', name='fin_recurring_status_enum', create_type=False)
    fr = postgresql.ENUM('weekly', 'monthly', 'quarterly', 'yearly', name='fin_recurring_freq_enum', create_type=False)
    st.create(op.get_bind(), checkfirst=True)
    fr.create(op.get_bind(), checkfirst=True)
    tfk = lambda: sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE')  # noqa: E731

    op.create_table('fin_recurring_invoices',
        sa.Column('title', sa.String(150), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('status', st, server_default='active', nullable=False),
        sa.Column('frequency', fr, nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('next_run_date', sa.Date(), nullable=False),
        sa.Column('run_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('auto_send', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('reference', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(500), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['customer_id'], ['fin_customers.id'], ondelete='RESTRICT'))
    _idx('fin_recurring_invoices')
    op.create_index('ix_fin_recurring_invoices_customer_id', 'fin_recurring_invoices', ['customer_id'])
    op.create_index('ix_fin_recurring_invoices_next_run_date', 'fin_recurring_invoices', ['next_run_date'])

    op.create_table('fin_recurring_lines',
        sa.Column('recurring_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), server_default='1', nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False),
        sa.Column('unit_price', sa.Numeric(18, 2), nullable=False),
        sa.Column('discount_percent', sa.Numeric(7, 3), server_default='0', nullable=False),
        sa.Column('tax_rate_id', sa.UUID(), nullable=True),
        sa.Column('income_account_id', sa.UUID(), nullable=False),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['recurring_id'], ['fin_recurring_invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tax_rate_id'], ['fin_tax_rates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['income_account_id'], ['fin_accounts.id'], ondelete='RESTRICT'))
    _idx('fin_recurring_lines')
    op.create_index('ix_fin_recurring_lines_recurring_id', 'fin_recurring_lines', ['recurring_id'])

    op.add_column('fin_invoices', sa.Column('recurring_id', sa.UUID(), nullable=True))
    op.add_column('fin_invoices', sa.Column('reminder_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('fin_invoices', sa.Column('last_reminded_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_fin_invoices_recurring', 'fin_invoices', 'fin_recurring_invoices', ['recurring_id'], ['id'], ondelete='SET NULL')
    op.add_column('fin_customers', sa.Column('auto_remind', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('fin_customers', 'auto_remind')
    op.drop_constraint('fk_fin_invoices_recurring', 'fin_invoices', type_='foreignkey')
    for c in ('last_reminded_at', 'reminder_count', 'recurring_id'):
        op.drop_column('fin_invoices', c)
    op.drop_table('fin_recurring_lines')
    op.drop_table('fin_recurring_invoices')
    op.execute('DROP TYPE IF EXISTS fin_recurring_freq_enum')
    op.execute('DROP TYPE IF EXISTS fin_recurring_status_enum')
