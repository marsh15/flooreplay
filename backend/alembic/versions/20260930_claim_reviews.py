"""Append-only human annotations tied to exact OpenAI outputs."""
from alembic import op
import sqlalchemy as sa

revision = '20260930_claim_reviews'
down_revision = '20260930_paid_release'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ai_claim_reviews', sa.Column('id', sa.String(64), primary_key=True), sa.Column('user_id', sa.String(64), sa.ForeignKey('accounts.id'), nullable=False), sa.Column('request_key', sa.String(120), nullable=False), sa.Column('run_id', sa.String(64), sa.ForeignKey('ai_runs.id'), nullable=False), sa.Column('claim_path', sa.String(120), nullable=False), sa.Column('output_digest', sa.String(80), nullable=False), sa.Column('supported', sa.Boolean, nullable=False), sa.Column('rationale', sa.Text, nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint('user_id', 'request_key'))
    op.create_index('ix_ai_claim_reviews_run_id', 'ai_claim_reviews', ['run_id'])


def downgrade() -> None:
    op.drop_table('ai_claim_reviews')
