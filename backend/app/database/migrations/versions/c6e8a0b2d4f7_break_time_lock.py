"""break time lock (K-01)

Revision ID: c6e8a0b2d4f7
Revises: b5d7f9a1c3e6
Create Date: 2026-10-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6e8a0b2d4f7"
down_revision: Union[str, None] = "b5d7f9a1c3e6"
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


def upgrade() -> None:
    scope = postgresql.ENUM('organization', 'department', 'shift', 'employee', name='break_scope_enum', create_type=False)
    status = postgresql.ENUM('pending', 'approved', 'denied', name='break_unlock_status_enum', create_type=False)
    scope.create(op.get_bind(), checkfirst=True)
    status.create(op.get_bind(), checkfirst=True)

    op.create_table('break_policies',
        sa.Column('scope', scope, nullable=False),
        sa.Column('scope_id', sa.UUID(), nullable=True),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), server_default='60', nullable=False),
        sa.Column('days', postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column('valid_from', sa.Date(), nullable=True),
        sa.Column('valid_to', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_break_policies_scope_id', 'break_policies', ['scope_id'])
    op.create_index('ix_break_policies_id', 'break_policies', ['id'])
    op.create_index('ix_break_policies_tenant_id', 'break_policies', ['tenant_id'])

    op.create_table('break_overrides',
        sa.Column('employee_id', sa.UUID(), nullable=True),
        sa.Column('department_id', sa.UUID(), nullable=True),
        sa.Column('on_date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        *_base(),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    for c in ('employee_id', 'department_id', 'on_date', 'id', 'tenant_id'):
        op.create_index(f'ix_break_overrides_{c}', 'break_overrides', [c])

    op.create_table('break_unlock_requests',
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('break_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', status, server_default='pending', nullable=False),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('unlock_until', sa.DateTime(timezone=True), nullable=True),
        *_base(),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_break_unlock_employee_date', 'break_unlock_requests', ['employee_id', 'break_date'])
    for c in ('employee_id', 'status', 'id', 'tenant_id'):
        op.create_index(f'ix_break_unlock_requests_{c}', 'break_unlock_requests', [c])


def downgrade() -> None:
    op.drop_table('break_unlock_requests')
    op.drop_table('break_overrides')
    op.drop_table('break_policies')
    op.execute('DROP TYPE IF EXISTS break_unlock_status_enum')
    op.execute('DROP TYPE IF EXISTS break_scope_enum')
