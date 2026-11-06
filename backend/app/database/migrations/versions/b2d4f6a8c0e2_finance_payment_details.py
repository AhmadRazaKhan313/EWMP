"""finance: bank / wallet details on entries, account kind, custom providers

Revision ID: b2d4f6a8c0e2
Revises: a1c3e5f7b9d1
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d4f6a8c0e2"
down_revision: Union[str, None] = "a1c3e5f7b9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('fin_accounts', sa.Column('money_kind', sa.String(10), nullable=True))
    op.add_column('fin_journal_entries', sa.Column('payment_provider', sa.String(100), nullable=True))
    op.add_column('fin_journal_entries', sa.Column('payment_account_no', sa.String(60), nullable=True))
    op.add_column('fin_journal_entries', sa.Column('payment_tid', sa.String(100), nullable=True))
    op.create_table('fin_payment_providers',
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('tenant_id', 'kind', 'name', name='uq_fin_providers_tenant_kind_name'))
    for c in ('id', 'tenant_id', 'is_deleted', 'deleted_at'):
        op.create_index(f'ix_fin_payment_providers_{c}', 'fin_payment_providers', [c])
    # classify the accounts that already exist: the three default money accounts, then obvious custom ones by name
    op.execute("UPDATE fin_accounts SET money_kind = 'cash'   WHERE type = 'asset' AND code = '1010'")
    op.execute("UPDATE fin_accounts SET money_kind = 'bank'   WHERE type = 'asset' AND code = '1020'")
    op.execute("UPDATE fin_accounts SET money_kind = 'wallet' WHERE type = 'asset' AND code = '1030'")
    op.execute("""UPDATE fin_accounts SET money_kind = 'wallet'
                  WHERE type = 'asset' AND money_kind IS NULL AND code NOT IN ('1000','1100','1500')
                    AND name ~* '(wallet|jazz ?cash|easy ?paisa|sada ?pay|naya ?pay|upaisa)'""")
    op.execute("""UPDATE fin_accounts SET money_kind = 'bank'
                  WHERE type = 'asset' AND money_kind IS NULL AND code NOT IN ('1000','1100','1500')
                    AND name ~* 'bank'""")


def downgrade() -> None:
    op.drop_table('fin_payment_providers')
    for c in ('payment_tid', 'payment_account_no', 'payment_provider'):
        op.drop_column('fin_journal_entries', c)
    op.drop_column('fin_accounts', 'money_kind')
