"""Actor-scoped operational request receipts."""
from alembic import op
import sqlalchemy as sa

revision = '20261001_operations'
down_revision = '20261001_workspaces'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('operational_events', sa.Column('id', sa.String(64), primary_key=True), sa.Column('actor_id', sa.String(64), nullable=False), sa.Column('request_id', sa.String(64), nullable=False), sa.Column('route', sa.String(200), nullable=False), sa.Column('method', sa.String(16), nullable=False), sa.Column('status_code', sa.Integer(), nullable=False), sa.Column('failure_category', sa.String(48), nullable=True), sa.Column('elapsed_seconds', sa.Float(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_operational_events_actor_id', 'operational_events', ['actor_id'])
    op.create_index('ix_operational_events_request_id', 'operational_events', ['request_id'])


def downgrade() -> None:
    op.drop_table('operational_events')
