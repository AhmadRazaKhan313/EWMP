"""finance foundations: chart of accounts + double-entry journal

Revision ID: d7f9b1c3e5a8
Revises: c6e8a0b2d4f7
Create Date: 2026-11-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7f9b1c3e5a8"
down_revision: Union[str, None] = "c6e8a0b2d4f7"
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
    acc_type = postgresql.ENUM('asset', 'liability', 'equity', 'income', 'expense', name='fin_account_type_enum', create_type=False)
    st = postgresql.ENUM('posted', 'reversed', name='fin_entry_status_enum', create_type=False)
    acc_type.create(op.get_bind(), checkfirst=True)
    st.create(op.get_bind(), checkfirst=True)

    op.create_table('fin_accounts',
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('type', acc_type, nullable=False),
        sa.Column('parent_id', sa.UUID(), nullable=True),
        sa.Column('is_system', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        *_base(),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['fin_accounts.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_fin_accounts_tenant_code'),
    )
    _idx('fin_accounts')

    op.create_table('fin_journal_entries',
        sa.Column('number', sa.String(20), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('memo', sa.Text(), nullable=True),
        sa.Column('reference', sa.String(100), nullable=True),
        sa.Column('source_type', sa.String(50), nullable=True),
        sa.Column('source_id', sa.UUID(), nullable=True),
        sa.Column('status', st, server_default='posted', nullable=False),
        sa.Column('base_currency', sa.String(3), nullable=False),
        sa.Column('reverses_id', sa.UUID(), nullable=True),
        sa.Column('reversed_by_id', sa.UUID(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reverses_id'], ['fin_journal_entries.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reversed_by_id'], ['fin_journal_entries.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tenant_id', 'number', name='uq_fin_entries_tenant_number'),
    )
    _idx('fin_journal_entries')
    op.create_index('ix_fin_entries_tenant_date', 'fin_journal_entries', ['tenant_id', 'entry_date'])

    op.create_table('fin_journal_lines',
        sa.Column('entry_id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('debit', sa.Numeric(18, 2), server_default='0', nullable=False),
        sa.Column('credit', sa.Numeric(18, 2), server_default='0', nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('amount_original', sa.Numeric(18, 2), nullable=False),
        sa.Column('exchange_rate', sa.Numeric(18, 8), server_default='1', nullable=False),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('line_no', sa.Integer(), server_default='0', nullable=False),
        *_base(),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entry_id'], ['fin_journal_entries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['fin_accounts.id'], ondelete='RESTRICT'),
        sa.CheckConstraint('(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)', name='ck_fin_lines_one_side'),
    )
    _idx('fin_journal_lines')
    op.create_index('ix_fin_journal_lines_entry_id', 'fin_journal_lines', ['entry_id'])
    op.create_index('ix_fin_journal_lines_account_id', 'fin_journal_lines', ['account_id'])

    op.create_table('fin_exchange_rates',
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('on_date', sa.Date(), nullable=False),
        sa.Column('rate', sa.Numeric(18, 8), nullable=False),
        *_base(),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('tenant_id', 'currency', 'on_date', name='uq_fin_rates_tenant_cur_date'),
        sa.CheckConstraint('rate > 0', name='ck_fin_rates_positive'),
    )
    _idx('fin_exchange_rates')

    op.create_table('fin_tax_rates',
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('percent', sa.Numeric(7, 3), nullable=False),
        sa.Column('kind', sa.String(30), server_default='sales', nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        *_base(),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['fin_accounts.id'], ondelete='SET NULL'),
    )
    _idx('fin_tax_rates')


def downgrade() -> None:
    for t in ('fin_tax_rates', 'fin_exchange_rates', 'fin_journal_lines', 'fin_journal_entries', 'fin_accounts'):
        op.drop_table(t)
    op.execute('DROP TYPE IF EXISTS fin_entry_status_enum')
    op.execute('DROP TYPE IF EXISTS fin_account_type_enum')
