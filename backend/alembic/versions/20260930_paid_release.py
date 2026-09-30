"""Provider operations and pinned pgvector corpus; never initiate paid calls."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

revision = "20260930_paid_release"
down_revision = "20260930_auth_release"
branch_labels = None
depends_on = None


def col(name, type_, **kwargs):
    return sa.Column(name, type_, nullable=kwargs.pop("nullable", False), **kwargs)


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("spend_entries", col("id", sa.String(64), primary_key=True), col("user_id", sa.String(64)), col("purpose", sa.String(32)), col("operation", sa.String(32)), col("status", sa.String(32)), col("reserved_inr", sa.Float), col("charged_inr", sa.Float), col("charged_usd", sa.Float), col("price_table", JSONB), col("details", JSONB), col("expires_at", sa.DateTime(timezone=True)), col("created_at", sa.DateTime(timezone=True)))
    op.create_table("spending_allocations", col("purpose", sa.String(32), primary_key=True), col("ceiling_inr", sa.Float), sa.CheckConstraint("ceiling_inr >= 0"))
    op.create_table("ai_runs", col("id", sa.String(64), primary_key=True), col("user_id", sa.String(64)), col("request_key", sa.String(120)), col("analysis_id", sa.String(64)), col("identity", sa.String(80)), col("task", sa.String(32)), col("question", sa.Text), col("status", sa.String(32)), col("packet", JSONB), col("configuration", JSONB), col("attempts", JSONB), col("result", JSONB, nullable=True), col("reservation_id", sa.String(64)), col("created_at", sa.DateTime(timezone=True)), col("completed_at", sa.DateTime(timezone=True), nullable=True), sa.UniqueConstraint("user_id", "request_key"))
    op.create_table("corpus_releases", col("id", sa.String(64), primary_key=True), col("digest", sa.String(80)), col("cutoff", sa.DateTime(timezone=True)), col("cards", JSONB), col("created_at", sa.DateTime(timezone=True)))
    op.create_table("embedding_artifacts", col("id", sa.String(80), primary_key=True), col("model", sa.String(120)), col("dimensions", sa.Integer), col("preprocessing_version", sa.String(32)), col("content", sa.Text), col("vector", Vector(512)), col("provider_usage", JSONB), col("created_at", sa.DateTime(timezone=True)))
    op.create_table("retrieval_runs", col("id", sa.String(64), primary_key=True), col("user_id", sa.String(64)), col("request_key", sa.String(120)), col("identity", sa.String(80)), col("status", sa.String(32)), col("result", JSONB, nullable=True), col("created_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("user_id", "request_key"))


def downgrade():
    for name in ("retrieval_runs", "embedding_artifacts", "corpus_releases", "ai_runs", "spending_allocations", "spend_entries"):
        op.drop_table(name)
