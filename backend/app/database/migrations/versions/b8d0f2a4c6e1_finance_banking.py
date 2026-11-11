"""finance banking: statement import, matching and reconciliation

Revision ID: b8d0f2a4c6e1
Revises: a7c9e1b3d5f2
Create Date: 2026-11-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d0f2a4c6e1"
down_revision: Union[str, None] = "a7c9e1b3d5f2"
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
    op.create_table('fin_bank_statements',
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=True),
        sa.Column('date_to', sa.Date(), nullable=True),
        sa.Column('opening_balance', sa.Numeric(18, 2), nullable=True),
        sa.Column('closing_balance', sa.Numeric(18, 2), nullable=True),
        sa.Column('line_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), _tfk('fin_bank_statements'),
        sa.ForeignKeyConstraint(['account_id'], ['fin_accounts.id'], ondelete='RESTRICT'))
    _idx('fin_bank_statements')
    op.create_index('ix_fin_bank_statements_account_id', 'fin_bank_statements', ['account_id'])

    op.create_table('fin_bank_reconciliations',
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('statement_date', sa.Date(), nullable=False),
        sa.Column('beginning_balance', sa.Numeric(18, 2), nullable=False),
        sa.Column('statement_balance', sa.Numeric(18, 2), nullable=False),
        sa.Column('cleared_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('line_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), _tfk('fin_bank_reconciliations'),
        sa.ForeignKeyConstraint(['account_id'], ['fin_accounts.id'], ondelete='RESTRICT'))
    _idx('fin_bank_reconciliations')
    op.create_index('ix_fin_bank_reconciliations_account_id', 'fin_bank_reconciliations', ['account_id'])

    op.create_table('fin_bank_lines',
        sa.Column('statement_id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('tx_date', sa.Date(), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('reference', sa.String(100), nullable=True),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('balance', sa.Numeric(18, 2), nullable=True),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('status', sa.String(10), server_default='unmatched', nullable=False),
        sa.Column('matched_line_id', sa.UUID(), nullable=True),
        sa.Column('matched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('matched_by', sa.UUID(), nullable=True),
        sa.Column('reconciliation_id', sa.UUID(), nullable=True),
        *_base(), sa.PrimaryKeyConstraint('id'), _tfk('fin_bank_lines'),
        sa.ForeignKeyConstraint(['statement_id'], ['fin_bank_statements.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['fin_accounts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['matched_line_id'], ['fin_journal_lines.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reconciliation_id'], ['fin_bank_reconciliations.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tenant_id', 'account_id', 'fingerprint', name='uq_fin_bank_line_fingerprint'),
        sa.UniqueConstraint('tenant_id', 'matched_line_id', name='uq_fin_bank_line_matched'),
        sa.CheckConstraint("status in ('unmatched','matched','ignored')", name='ck_fin_bank_line_status'),
        sa.CheckConstraint('amount <> 0', name='ck_fin_bank_line_amount'))
    _idx('fin_bank_lines')
    for c in ('statement_id', 'account_id', 'reconciliation_id'):
        op.create_index(f'ix_fin_bank_lines_{c}', 'fin_bank_lines', [c])


def downgrade() -> None:
    op.drop_table('fin_bank_lines')
    op.drop_table('fin_bank_reconciliations')
    op.drop_table('fin_bank_statements')
