"""finance sales: customers, invoices, payments

Revision ID: e8a0c2d4f6b9
Revises: d7f9b1c3e5a8
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8a0c2d4f6b9"
down_revision: Union[str, None] = "d7f9b1c3e5a8"
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
    op.create_index(f'ix_{table}_id', table, ['id'])
    op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'])
    op.create_index(f'ix_{table}_is_deleted', table, ['is_deleted'])
    op.create_index(f'ix_{table}_deleted_at', table, ['deleted_at'])


def upgrade() -> None:
    inv_status = postgresql.ENUM('draft', 'sent', 'partially_paid', 'paid', 'void', name='fin_invoice_status_enum', create_type=False)
    pay_status = postgresql.ENUM('posted', 'void', name='fin_payment_status_enum', create_type=False)
    inv_status.create(op.get_bind(), checkfirst=True)
    pay_status.create(op.get_bind(), checkfirst=True)
    tenant_fk = lambda: sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE')  # noqa: E731

    op.create_table('fin_customers',
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('company', sa.String(150), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('payment_terms_days', sa.Integer(), server_default='0', nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        *_base(), sa.PrimaryKeyConstraint('id'), tenant_fk())
    _idx('fin_customers')

    op.create_table('fin_invoices',
        sa.Column('number', sa.String(20), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('status', inv_status, server_default='draft', nullable=False),
        sa.Column('issue_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('exchange_rate', sa.Numeric(18, 8), server_default='1', nullable=False),
        sa.Column('subtotal', sa.Numeric(18, 2), nullable=False),
        sa.Column('tax_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('total', sa.Numeric(18, 2), nullable=False),
        sa.Column('amount_paid', sa.Numeric(18, 2), server_default='0', nullable=False),
        sa.Column('reference', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('journal_entry_id', sa.UUID(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tenant_fk(),
        sa.ForeignKeyConstraint(['customer_id'], ['fin_customers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['fin_journal_entries.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tenant_id', 'number', name='uq_fin_invoices_tenant_number'),
        sa.CheckConstraint('amount_paid >= 0 AND amount_paid <= total', name='ck_fin_invoices_paid_range'))
    _idx('fin_invoices')
    op.create_index('ix_fin_invoices_tenant_customer', 'fin_invoices', ['tenant_id', 'customer_id'])

    op.create_table('fin_invoice_lines',
        sa.Column('invoice_id', sa.UUID(), nullable=False),
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
        *_base(), sa.PrimaryKeyConstraint('id'), tenant_fk(),
        sa.ForeignKeyConstraint(['invoice_id'], ['fin_invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tax_rate_id'], ['fin_tax_rates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['income_account_id'], ['fin_accounts.id'], ondelete='RESTRICT'))
    _idx('fin_invoice_lines')
    op.create_index('ix_fin_invoice_lines_invoice_id', 'fin_invoice_lines', ['invoice_id'])

    op.create_table('fin_payments',
        sa.Column('number', sa.String(20), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('status', pay_status, server_default='posted', nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('exchange_rate', sa.Numeric(18, 8), server_default='1', nullable=False),
        sa.Column('deposit_account_id', sa.UUID(), nullable=False),
        sa.Column('method', sa.String(50), nullable=True),
        sa.Column('reference', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('journal_entry_id', sa.UUID(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tenant_fk(),
        sa.ForeignKeyConstraint(['customer_id'], ['fin_customers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['deposit_account_id'], ['fin_accounts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['fin_journal_entries.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tenant_id', 'number', name='uq_fin_payments_tenant_number'),
        sa.CheckConstraint('amount > 0', name='ck_fin_payments_positive'))
    _idx('fin_payments')
    op.create_index('ix_fin_payments_customer_id', 'fin_payments', ['customer_id'])

    op.create_table('fin_payment_allocations',
        sa.Column('payment_id', sa.UUID(), nullable=False),
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        *_base(), sa.PrimaryKeyConstraint('id'), tenant_fk(),
        sa.ForeignKeyConstraint(['payment_id'], ['fin_payments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invoice_id'], ['fin_invoices.id'], ondelete='RESTRICT'),
        sa.CheckConstraint('amount > 0', name='ck_fin_alloc_positive'))
    _idx('fin_payment_allocations')
    op.create_index('ix_fin_payment_allocations_payment_id', 'fin_payment_allocations', ['payment_id'])
    op.create_index('ix_fin_payment_allocations_invoice_id', 'fin_payment_allocations', ['invoice_id'])


def downgrade() -> None:
    for t in ('fin_payment_allocations', 'fin_payments', 'fin_invoice_lines', 'fin_invoices', 'fin_customers'):
        op.drop_table(t)
    op.execute('DROP TYPE IF EXISTS fin_payment_status_enum')
    op.execute('DROP TYPE IF EXISTS fin_invoice_status_enum')
