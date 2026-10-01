"""Shared draft packets and declared semantic judgments, never inferred human validation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261001_semantic_review'
down_revision = '20260930_workflow'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column('judgment', sa.String(32), nullable=False, server_default='unsupported'),
        sa.Column('flags', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('reviewer_kind', sa.String(32), nullable=False, server_default='unspecified'),
        sa.Column('qualifications', sa.Text(), nullable=False, server_default=''),
        sa.Column('independent', sa.Boolean(), nullable=False, server_default=sa.false()),
    ):
        op.add_column('ai_claim_reviews', column)
    op.execute("UPDATE ai_claim_reviews SET judgment = CASE WHEN supported THEN 'supported' ELSE 'unsupported' END")
    op.create_table('ai_review_publications', sa.Column('run_id', sa.String(64), sa.ForeignKey('ai_runs.id'), primary_key=True), sa.Column('user_id', sa.String(64), sa.ForeignKey('accounts.id'), nullable=False), sa.Column('request_key', sa.String(120), nullable=False), sa.Column('output_digest', sa.String(80), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint('user_id', 'request_key'))
    op.create_table('ai_run_assessments', sa.Column('id', sa.String(64), primary_key=True), sa.Column('user_id', sa.String(64), sa.ForeignKey('accounts.id'), nullable=False), sa.Column('request_key', sa.String(120), nullable=False), sa.Column('run_id', sa.String(64), sa.ForeignKey('ai_runs.id'), nullable=False), sa.Column('output_digest', sa.String(80), nullable=False), sa.Column('details', postgresql.JSONB(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint('user_id', 'request_key'))
    op.create_index('ix_ai_run_assessments_run_id', 'ai_run_assessments', ['run_id'])


def downgrade() -> None:
    op.drop_table('ai_run_assessments')
    op.drop_table('ai_review_publications')
    for name in ('independent', 'qualifications', 'reviewer_kind', 'flags', 'judgment'):
        op.drop_column('ai_claim_reviews', name)
