"""finance purchases 3b: approvals, attachments, purchase orders, recurring bills

Revision ID: d4f6b8c0e2a4
Revises: c3e5a7b9d1f3
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4f6b8c0e2a4"
down_revision: Union[str, None] = "c3e5a7b9d1f3"
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


def _lines(table, parent, parent_col, with_pct: bool):
    cols = [
        sa.Column(parent_col, sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), server_default='1', nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False),
        sa.Column('unit_price', sa.Numeric(18, 2), nullable=False),
        sa.Column('discount_percent', sa.Numeric(7, 3), server_default='0', nullable=False),
        sa.Column('tax_rate_id', sa.UUID(), nullable=True),
        sa.Column('expense_account_id', sa.UUID(), nullable=False),
    ]
    if with_pct:
        cols[7:7] = [sa.Column('tax_percent', sa.Numeric(7, 3), server_default='0', nullable=False)]
        cols += [sa.Column('net_amount', sa.Numeric(18, 2), nullable=False),
                 sa.Column('tax_amount', sa.Numeric(18, 2), server_default='0', nullable=False)]
    op.create_table(table, *cols, *_base(), sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint([parent_col], [f'{parent}.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tax_rate_id'], ['fin_tax_rates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['expense_account_id'], ['fin_accounts.id'], ondelete='RESTRICT'))
    _idx(table)
    op.create_index(f'ix_{table}_{parent_col}', table, [parent_col])


def upgrade() -> None:
    tfk = lambda: sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE')  # noqa: E731
    po_s = postgresql.ENUM('draft', 'sent', 'received', 'billed', 'cancelled', name='fin_po_status_enum', create_type=False)
    rs = postgresql.ENUM('active', 'paused', 'ended', name='fin_rbill_status_enum', create_type=False)
    rf = postgresql.ENUM('weekly', 'monthly', 'quarterly', 'yearly', name='fin_rbill_freq_enum', create_type=False)
    for e in (po_s, rs, rf):
        e.create(op.get_bind(), checkfirst=True)

    op.create_table('fin_recurring_bills',
        sa.Column('title', sa.String(150), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('status', rs, server_default='active', nullable=False),
        sa.Column('frequency', rf, nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('next_run_date', sa.Date(), nullable=False),
        sa.Column('run_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('auto_post', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('vendor_ref', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(500), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['vendor_id'], ['fin_vendors.id'], ondelete='RESTRICT'))
    _idx('fin_recurring_bills')
    op.create_index('ix_fin_recurring_bills_vendor_id', 'fin_recurring_bills', ['vendor_id'])
    op.create_index('ix_fin_recurring_bills_next_run_date', 'fin_recurring_bills', ['next_run_date'])
    _lines('fin_recurring_bill_lines', 'fin_recurring_bills', 'recurring_id', False)

    op.add_column('fin_bills', sa.Column('approval_status', sa.String(10), server_default='none', nullable=False))
    op.add_column('fin_bills', sa.Column('approval_requested_by', sa.UUID(), nullable=True))
    op.add_column('fin_bills', sa.Column('approved_by', sa.UUID(), nullable=True))
    op.add_column('fin_bills', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('fin_bills', sa.Column('rejection_reason', sa.String(500), nullable=True))
    op.add_column('fin_bills', sa.Column('recurring_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_fin_bills_recurring', 'fin_bills', 'fin_recurring_bills', ['recurring_id'], ['id'], ondelete='SET NULL')

    op.create_table('fin_purchase_settings',
        sa.Column('approval_threshold', sa.Numeric(18, 2), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.UniqueConstraint('tenant_id', name='uq_fin_purchase_settings_tenant'))
    _idx('fin_purchase_settings')

    op.create_table('fin_bill_attachments',
        sa.Column('bill_id', sa.UUID(), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('storage_key', sa.String(500), nullable=False),
        sa.Column('uploaded_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['bill_id'], ['fin_bills.id'], ondelete='CASCADE'))
    _idx('fin_bill_attachments')
    op.create_index('ix_fin_bill_attachments_bill_id', 'fin_bill_attachments', ['bill_id'])

    op.create_table('fin_purchase_orders',
        sa.Column('number', sa.String(20), nullable=False),
        sa.Column('vendor_id', sa.UUID(), nullable=False),
        sa.Column('status', po_s, server_default='draft', nullable=False),
        sa.Column('issue_date', sa.Date(), nullable=False),
        sa.Column('expected_date', sa.Date(), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('subtotal', sa.Numeric(18, 2), nullable=False),
        sa.Column('tax_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('total', sa.Numeric(18, 2), nullable=False),
        sa.Column('reference', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('bill_id', sa.UUID(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), tfk(),
        sa.ForeignKeyConstraint(['vendor_id'], ['fin_vendors.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['bill_id'], ['fin_bills.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tenant_id', 'number', name='uq_fin_po_tenant_number'))
    _idx('fin_purchase_orders')
    op.create_index('ix_fin_po_tenant_vendor', 'fin_purchase_orders', ['tenant_id', 'vendor_id'])
    _lines('fin_purchase_order_lines', 'fin_purchase_orders', 'order_id', True)


def downgrade() -> None:
    for t in ('fin_purchase_order_lines', 'fin_purchase_orders', 'fin_bill_attachments', 'fin_purchase_settings'):
        op.drop_table(t)
    op.drop_constraint('fk_fin_bills_recurring', 'fin_bills', type_='foreignkey')
    for c in ('recurring_id', 'rejection_reason', 'approved_at', 'approved_by', 'approval_requested_by', 'approval_status'):
        op.drop_column('fin_bills', c)
    op.drop_table('fin_recurring_bill_lines')
    op.drop_table('fin_recurring_bills')
    for e in ('fin_po_status_enum', 'fin_rbill_status_enum', 'fin_rbill_freq_enum'):
        op.execute(f'DROP TYPE IF EXISTS {e}')
