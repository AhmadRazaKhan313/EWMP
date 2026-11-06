"""finance quotes

Revision ID: f9b1d3e5a7c0
Revises: e8a0c2d4f6b9
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f9b1d3e5a7c0"
down_revision: Union[str, None] = "e8a0c2d4f6b9"
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
    st = postgresql.ENUM('draft', 'sent', 'accepted', 'declined', 'invoiced', name='fin_quote_status_enum', create_type=False)
    st.create(op.get_bind(), checkfirst=True)
    tfk = lambda: sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE')  # noqa: E731

    op.create_table('fin_quotes',
        sa.Column('number', sa.String(20), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('status', st, server_default='draft', nullable=False),
        sa.Column('issue_date', sa.Date(), nullable=False),
        sa.Column('valid_until', sa.Date(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('subtotal', sa.Numeric(18, 2), nullable=False),
        sa.Column('tax_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('total', sa.Numeric(18, 2), nullable=False),
        sa.Column('reference', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('invoice_id', sa.UUID(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['customer_id'], ['fin_customers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['invoice_id'], ['fin_invoices.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tenant_id', 'number', name='uq_fin_quotes_tenant_number'))
    _idx('fin_quotes')
    op.create_index('ix_fin_quotes_tenant_customer', 'fin_quotes', ['tenant_id', 'customer_id'])

    op.create_table('fin_quote_lines',
        sa.Column('quote_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), server_default='1', nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False),
        sa.Column('unit_price', sa.Numeric(18, 2), nullable=False),
        sa.Column('discount_percent', sa.Numeric(7, 3), server_default='0', nullable=False),
        sa.Column('tax_rate_id', sa.UUID(), nullable=True),
        sa.Column('tax_percent', sa.Numeric(7, 3), server_default='0', nullable=False),
        sa.Column('income_account_id', sa.UUID(), nullable=False),
        sa.Column('net_amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(18, 2), server_default='0', nullable=False),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['quote_id'], ['fin_quotes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tax_rate_id'], ['fin_tax_rates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['income_account_id'], ['fin_accounts.id'], ondelete='RESTRICT'))
    _idx('fin_quote_lines')
    op.create_index('ix_fin_quote_lines_quote_id', 'fin_quote_lines', ['quote_id'])


def downgrade() -> None:
    op.drop_table('fin_quote_lines')
    op.drop_table('fin_quotes')
    op.execute('DROP TYPE IF EXISTS fin_quote_status_enum')
