"""Record monotonic replay elapsed time.

Revision ID: 20260928elapsed
Revises: 20260928sources
"""

from alembic import op
import sqlalchemy as sa

revision = "20260928elapsed"
down_revision = "20260928sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("replay_attempts", sa.Column("elapsed_ms", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("replay_attempts", "elapsed_ms")
