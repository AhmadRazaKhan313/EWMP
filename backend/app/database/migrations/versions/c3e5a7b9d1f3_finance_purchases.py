"""finance purchases: vendors, bills, payments made

Revision ID: c3e5a7b9d1f3
Revises: b2d4f6a8c0e2
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3e5a7b9d1f3"
down_revision: Union[str, None] = "b2d4f6a8c0e2"
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
    bs = postgresql.ENUM('draft', 'open', 'partially_paid', 'paid', 'void', name='fin_bill_status_enum', create_type=False)
    ps = postgresql.ENUM('posted', 'void', name='fin_bill_payment_status_enum', create_type=False)
    bs.create(op.get_bind(), checkfirst=True)
    ps.create(op.get_bind(), checkfirst=True)
    tfk = lambda: sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE')  # noqa: E731

    op.create_table('fin_vendors',
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('company', sa.String(150), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('payment_terms_days', sa.Integer(), server_default='0', nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk())
    _idx('fin_vendors')

    op.create_table('fin_bills',
        sa.Column('number', sa.String(20), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('vendor_ref', sa.String(100), nullable=True),
        sa.Column('status', bs, server_default='draft', nullable=False),
        sa.Column('issue_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('exchange_rate', sa.Numeric(18, 8), server_default='1', nullable=False),
        sa.Column('subtotal', sa.Numeric(18, 2), nullable=False),
        sa.Column('tax_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('total', sa.Numeric(18, 2), nullable=False),
        sa.Column('amount_paid', sa.Numeric(18, 2), server_default='0', nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('journal_entry_id', sa.UUID(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['vendor_id'], ['fin_vendors.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['fin_journal_entries.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tenant_id', 'number', name='uq_fin_bills_tenant_number'),
        sa.CheckConstraint('amount_paid >= 0 AND amount_paid <= total', name='ck_fin_bills_paid_range'))
    _idx('fin_bills')
    op.create_index('ix_fin_bills_tenant_vendor', 'fin_bills', ['tenant_id', 'vendor_id'])

    op.create_table('fin_bill_lines',
        sa.Column('bill_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), server_default='1', nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False),
        sa.Column('unit_price', sa.Numeric(18, 2), nullable=False),
        sa.Column('discount_percent', sa.Numeric(7, 3), server_default='0', nullable=False),
        sa.Column('tax_rate_id', sa.UUID(), nullable=True),
        sa.Column('tax_percent', sa.Numeric(7, 3), server_default='0', nullable=False),
        sa.Column('expense_account_id', sa.UUID(), nullable=False),
        sa.Column('net_amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(18, 2), server_default='0', nullable=False),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['bill_id'], ['fin_bills.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tax_rate_id'], ['fin_tax_rates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['expense_account_id'], ['fin_accounts.id'], ondelete='RESTRICT'))
    _idx('fin_bill_lines')
    op.create_index('ix_fin_bill_lines_bill_id', 'fin_bill_lines', ['bill_id'])

    op.create_table('fin_bill_payments',
        sa.Column('number', sa.String(20), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('status', ps, server_default='posted', nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('exchange_rate', sa.Numeric(18, 8), server_default='1', nullable=False),
        sa.Column('paid_from_account_id', sa.UUID(), nullable=False),
        sa.Column('method', sa.String(50), nullable=True),
        sa.Column('reference', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('journal_entry_id', sa.UUID(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['vendor_id'], ['fin_vendors.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['paid_from_account_id'], ['fin_accounts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['fin_journal_entries.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tenant_id', 'number', name='uq_fin_bill_payments_tenant_number'),
        sa.CheckConstraint('amount > 0', name='ck_fin_bill_payments_positive'))
    _idx('fin_bill_payments')
    op.create_index('ix_fin_bill_payments_vendor_id', 'fin_bill_payments', ['vendor_id'])

    op.create_table('fin_bill_payment_allocations',
        sa.Column('payment_id', sa.UUID(), nullable=False),
        sa.Column('bill_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['payment_id'], ['fin_bill_payments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['bill_id'], ['fin_bills.id'], ondelete='RESTRICT'),
        sa.CheckConstraint('amount > 0', name='ck_fin_bill_alloc_positive'))
    _idx('fin_bill_payment_allocations')
    op.create_index('ix_fin_bill_payment_allocations_payment_id', 'fin_bill_payment_allocations', ['payment_id'])
    op.create_index('ix_fin_bill_payment_allocations_bill_id', 'fin_bill_payment_allocations', ['bill_id'])


def downgrade() -> None:
    for t in ('fin_bill_payment_allocations', 'fin_bill_payments', 'fin_bill_lines', 'fin_bills', 'fin_vendors'):
        op.drop_table(t)
    op.execute('DROP TYPE IF EXISTS fin_bill_payment_status_enum')
    op.execute('DROP TYPE IF EXISTS fin_bill_status_enum')
