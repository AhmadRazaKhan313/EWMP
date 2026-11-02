"""onboarding and offers (N-01)

Revision ID: b5d7f9a1c3e6
Revises: a4c6e8f0b2d4
Create Date: 2026-10-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5d7f9a1c3e6"
down_revision: Union[str, None] = "a4c6e8f0b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('onboarding_templates',
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('kind', sa.String(length=15), server_default='onboarding', nullable=False),
    sa.Column('department_id', sa.UUID(), nullable=True),
    sa.Column('designation_id', sa.UUID(), nullable=True),
    sa.Column('branch_id', sa.UUID(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['designation_id'], ['designations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_onboarding_templates_deleted_at'), 'onboarding_templates', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_onboarding_templates_id'), 'onboarding_templates', ['id'], unique=False)
    op.create_index(op.f('ix_onboarding_templates_is_deleted'), 'onboarding_templates', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_onboarding_templates_kind'), 'onboarding_templates', ['kind'], unique=False)
    op.create_index(op.f('ix_onboarding_templates_tenant_id'), 'onboarding_templates', ['tenant_id'], unique=False)
    op.create_table('offers',
    sa.Column('applicant_id', sa.UUID(), nullable=True),
    sa.Column('candidate_name', sa.String(length=200), nullable=False),
    sa.Column('candidate_email', sa.String(length=255), nullable=False),
    sa.Column('candidate_phone', sa.String(length=50), nullable=True),
    sa.Column('job_title', sa.String(length=200), nullable=False),
    sa.Column('department_id', sa.UUID(), nullable=True),
    sa.Column('designation_id', sa.UUID(), nullable=True),
    sa.Column('branch_id', sa.UUID(), nullable=True),
    sa.Column('manager_id', sa.UUID(), nullable=True),
    sa.Column('template_id', sa.UUID(), nullable=True),
    sa.Column('employment_type', sa.String(length=30), server_default='full_time', nullable=False),
    sa.Column('job_nature', sa.String(length=30), server_default='probationary', nullable=False),
    sa.Column('salary', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), server_default='PKR', nullable=False),
    sa.Column('pay_items', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('joining_date', sa.Date(), nullable=False),
    sa.Column('probation_months', sa.Integer(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('parent_offer_id', sa.UUID(), nullable=True),
    sa.Column('approver_ids', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('approvals', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decline_reason', sa.Text(), nullable=True),
    sa.Column('accepted_name', sa.String(length=200), nullable=True),
    sa.Column('accepted_ip', sa.String(length=64), nullable=True),
    sa.Column('accepted_user_agent', sa.String(length=300), nullable=True),
    sa.Column('employee_id', sa.UUID(), nullable=True),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['applicant_id'], ['applicants.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['designation_id'], ['designations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['manager_id'], ['employees.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_offer_id'], ['offers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['template_id'], ['onboarding_templates.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_offers_applicant_id'), 'offers', ['applicant_id'], unique=False)
    op.create_index(op.f('ix_offers_candidate_email'), 'offers', ['candidate_email'], unique=False)
    op.create_index(op.f('ix_offers_deleted_at'), 'offers', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_offers_employee_id'), 'offers', ['employee_id'], unique=False)
    op.create_index(op.f('ix_offers_id'), 'offers', ['id'], unique=False)
    op.create_index(op.f('ix_offers_is_deleted'), 'offers', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_offers_status'), 'offers', ['status'], unique=False)
    op.create_index(op.f('ix_offers_tenant_id'), 'offers', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_offers_token_hash'), 'offers', ['token_hash'], unique=False)
    op.create_table('onboarding_template_tasks',
    sa.Column('template_id', sa.UUID(), nullable=False),
    sa.Column('order', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('owner_role', sa.String(length=15), nullable=False),
    sa.Column('phase', sa.String(length=20), nullable=False),
    sa.Column('due_offset_days', sa.Integer(), nullable=False),
    sa.Column('depends_on_order', sa.Integer(), nullable=True),
    sa.Column('is_required', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('kind', sa.String(length=15), server_default='manual', nullable=False),
    sa.Column('provision_key', sa.String(length=40), nullable=True),
    sa.Column('link_url', sa.String(length=300), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['template_id'], ['onboarding_templates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_onboarding_template_tasks_deleted_at'), 'onboarding_template_tasks', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_onboarding_template_tasks_id'), 'onboarding_template_tasks', ['id'], unique=False)
    op.create_index(op.f('ix_onboarding_template_tasks_is_deleted'), 'onboarding_template_tasks', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_onboarding_template_tasks_template_id'), 'onboarding_template_tasks', ['template_id'], unique=False)
    op.create_index(op.f('ix_onboarding_template_tasks_tenant_id'), 'onboarding_template_tasks', ['tenant_id'], unique=False)
    op.create_table('onboarding_cases',
    sa.Column('kind', sa.String(length=15), server_default='onboarding', nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('offer_id', sa.UUID(), nullable=True),
    sa.Column('template_id', sa.UUID(), nullable=True),
    sa.Column('anchor_date', sa.Date(), nullable=False),
    sa.Column('manager_id', sa.UUID(), nullable=True),
    sa.Column('buddy_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=15), server_default='pre_boarding', nullable=False),
    sa.Column('preboarding_token_hash', sa.String(length=64), nullable=True),
    sa.Column('preboarding_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('preboarding_submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('preboarding_data', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('policy_ack_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('welcome_message', sa.Text(), nullable=True),
    sa.Column('welcome_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['buddy_id'], ['employees.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['manager_id'], ['employees.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['offer_id'], ['offers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['template_id'], ['onboarding_templates.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_onboarding_cases_deleted_at'), 'onboarding_cases', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_onboarding_cases_employee_id'), 'onboarding_cases', ['employee_id'], unique=False)
    op.create_index(op.f('ix_onboarding_cases_id'), 'onboarding_cases', ['id'], unique=False)
    op.create_index(op.f('ix_onboarding_cases_is_deleted'), 'onboarding_cases', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_onboarding_cases_kind'), 'onboarding_cases', ['kind'], unique=False)
    op.create_index(op.f('ix_onboarding_cases_preboarding_token_hash'), 'onboarding_cases', ['preboarding_token_hash'], unique=False)
    op.create_index(op.f('ix_onboarding_cases_status'), 'onboarding_cases', ['status'], unique=False)
    op.create_index(op.f('ix_onboarding_cases_tenant_id'), 'onboarding_cases', ['tenant_id'], unique=False)
    op.create_index('uq_onboarding_one_open_case', 'onboarding_cases', ['employee_id', 'kind'], unique=True, postgresql_where=sa.text("status IN ('pre_boarding','active') AND is_deleted = false"))
    op.create_table('onboarding_case_documents',
    sa.Column('case_id', sa.UUID(), nullable=False),
    sa.Column('document_type', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('is_required', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('status', sa.String(length=15), server_default='requested', nullable=False),
    sa.Column('employee_document_id', sa.UUID(), nullable=True),
    sa.Column('rejection_reason', sa.String(length=300), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verified_by_id', sa.UUID(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['onboarding_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['employee_document_id'], ['employee_documents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_onboarding_case_documents_case_id'), 'onboarding_case_documents', ['case_id'], unique=False)
    op.create_index(op.f('ix_onboarding_case_documents_deleted_at'), 'onboarding_case_documents', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_onboarding_case_documents_id'), 'onboarding_case_documents', ['id'], unique=False)
    op.create_index(op.f('ix_onboarding_case_documents_is_deleted'), 'onboarding_case_documents', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_onboarding_case_documents_tenant_id'), 'onboarding_case_documents', ['tenant_id'], unique=False)
    op.create_table('onboarding_case_tasks',
    sa.Column('case_id', sa.UUID(), nullable=False),
    sa.Column('template_task_id', sa.UUID(), nullable=True),
    sa.Column('order', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('owner_role', sa.String(length=15), nullable=False),
    sa.Column('assignee_user_id', sa.UUID(), nullable=True),
    sa.Column('phase', sa.String(length=20), nullable=False),
    sa.Column('due_offset_days', sa.Integer(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=15), server_default='pending', nullable=False),
    sa.Column('depends_on_id', sa.UUID(), nullable=True),
    sa.Column('is_required', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('kind', sa.String(length=15), server_default='manual', nullable=False),
    sa.Column('provision_key', sa.String(length=40), nullable=True),
    sa.Column('link_url', sa.String(length=300), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_by_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('last_reminded_at', sa.Date(), nullable=True),
    sa.Column('escalated_at', sa.Date(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['assignee_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['case_id'], ['onboarding_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['depends_on_id'], ['onboarding_case_tasks.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['template_task_id'], ['onboarding_template_tasks.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_onboarding_case_tasks_assignee_user_id'), 'onboarding_case_tasks', ['assignee_user_id'], unique=False)
    op.create_index(op.f('ix_onboarding_case_tasks_case_id'), 'onboarding_case_tasks', ['case_id'], unique=False)
    op.create_index(op.f('ix_onboarding_case_tasks_deleted_at'), 'onboarding_case_tasks', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_onboarding_case_tasks_due_date'), 'onboarding_case_tasks', ['due_date'], unique=False)
    op.create_index(op.f('ix_onboarding_case_tasks_id'), 'onboarding_case_tasks', ['id'], unique=False)
    op.create_index(op.f('ix_onboarding_case_tasks_is_deleted'), 'onboarding_case_tasks', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_onboarding_case_tasks_status'), 'onboarding_case_tasks', ['status'], unique=False)
    op.create_index(op.f('ix_onboarding_case_tasks_tenant_id'), 'onboarding_case_tasks', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_onboarding_case_tasks_tenant_id', table_name='onboarding_case_tasks')
    op.drop_index('ix_onboarding_case_tasks_status', table_name='onboarding_case_tasks')
    op.drop_index('ix_onboarding_case_tasks_is_deleted', table_name='onboarding_case_tasks')
    op.drop_index('ix_onboarding_case_tasks_id', table_name='onboarding_case_tasks')
    op.drop_index('ix_onboarding_case_tasks_due_date', table_name='onboarding_case_tasks')
    op.drop_index('ix_onboarding_case_tasks_deleted_at', table_name='onboarding_case_tasks')
    op.drop_index('ix_onboarding_case_tasks_case_id', table_name='onboarding_case_tasks')
    op.drop_index('ix_onboarding_case_tasks_assignee_user_id', table_name='onboarding_case_tasks')
    op.drop_index('ix_onboarding_case_documents_tenant_id', table_name='onboarding_case_documents')
    op.drop_index('ix_onboarding_case_documents_is_deleted', table_name='onboarding_case_documents')
    op.drop_index('ix_onboarding_case_documents_id', table_name='onboarding_case_documents')
    op.drop_index('ix_onboarding_case_documents_deleted_at', table_name='onboarding_case_documents')
    op.drop_index('ix_onboarding_case_documents_case_id', table_name='onboarding_case_documents')
    op.drop_index('uq_onboarding_one_open_case', table_name='onboarding_cases')
    op.drop_index('ix_onboarding_cases_tenant_id', table_name='onboarding_cases')
    op.drop_index('ix_onboarding_cases_status', table_name='onboarding_cases')
    op.drop_index('ix_onboarding_cases_preboarding_token_hash', table_name='onboarding_cases')
    op.drop_index('ix_onboarding_cases_kind', table_name='onboarding_cases')
    op.drop_index('ix_onboarding_cases_is_deleted', table_name='onboarding_cases')
    op.drop_index('ix_onboarding_cases_id', table_name='onboarding_cases')
    op.drop_index('ix_onboarding_cases_employee_id', table_name='onboarding_cases')
    op.drop_index('ix_onboarding_cases_deleted_at', table_name='onboarding_cases')
    op.drop_index('ix_onboarding_template_tasks_tenant_id', table_name='onboarding_template_tasks')
    op.drop_index('ix_onboarding_template_tasks_template_id', table_name='onboarding_template_tasks')
    op.drop_index('ix_onboarding_template_tasks_is_deleted', table_name='onboarding_template_tasks')
    op.drop_index('ix_onboarding_template_tasks_id', table_name='onboarding_template_tasks')
    op.drop_index('ix_onboarding_template_tasks_deleted_at', table_name='onboarding_template_tasks')
    op.drop_index('ix_offers_token_hash', table_name='offers')
    op.drop_index('ix_offers_tenant_id', table_name='offers')
    op.drop_index('ix_offers_status', table_name='offers')
    op.drop_index('ix_offers_is_deleted', table_name='offers')
    op.drop_index('ix_offers_id', table_name='offers')
    op.drop_index('ix_offers_employee_id', table_name='offers')
    op.drop_index('ix_offers_deleted_at', table_name='offers')
    op.drop_index('ix_offers_candidate_email', table_name='offers')
    op.drop_index('ix_offers_applicant_id', table_name='offers')
    op.drop_index('ix_onboarding_templates_tenant_id', table_name='onboarding_templates')
    op.drop_index('ix_onboarding_templates_kind', table_name='onboarding_templates')
    op.drop_index('ix_onboarding_templates_is_deleted', table_name='onboarding_templates')
    op.drop_index('ix_onboarding_templates_id', table_name='onboarding_templates')
    op.drop_index('ix_onboarding_templates_deleted_at', table_name='onboarding_templates')
    op.drop_table('onboarding_case_tasks')
    op.drop_table('onboarding_case_documents')
    op.drop_table('onboarding_cases')
    op.drop_table('onboarding_template_tasks')
    op.drop_table('offers')
    op.drop_table('onboarding_templates')
