"""Owner/reviewer accounts and persistent rate limits."""
from alembic import op
import sqlalchemy as sa

revision = "20260930_auth_release"
down_revision = "20260928cards"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("accounts", sa.Column("id", sa.String(64), primary_key=True), sa.Column("username", sa.String(120), nullable=False, unique=True), sa.Column("display_name", sa.String(120), nullable=False), sa.Column("role", sa.String(16), nullable=False), sa.Column("password_hash", sa.String(256), nullable=False), sa.Column("disabled", sa.Boolean, nullable=False), sa.CheckConstraint("role IN ('owner', 'reviewer')"))
    op.create_table("auth_sessions", sa.Column("token_hash", sa.String(64), primary_key=True), sa.Column("account_id", sa.String(64), sa.ForeignKey("accounts.id"), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked", sa.Boolean, nullable=False))
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"])
    op.create_table("access_limits", sa.Column("key", sa.String(64), primary_key=True), sa.Column("count", sa.Integer, nullable=False), sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("access_limits")
    op.drop_table("auth_sessions")
    op.drop_table("accounts")
