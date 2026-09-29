"""Add immutable incident revisions, reports, and human reviews.

Revision ID: 20260928incident
Revises: 344843712202
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260928incident"
down_revision = "344843712202"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incident_revisions",
        sa.Column("incident_id", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("line_id", sa.String(64), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("content_digest", sa.String(80), nullable=False),
    )
    op.create_index("ix_incident_revisions_line_id", "incident_revisions", ["line_id"])
    op.create_table(
        "incident_analyses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("incident_id", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("manifest_digest", sa.String(80), nullable=False),
        sa.Column("report", postgresql.JSONB, nullable=False),
        sa.Column("execution_kind", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_incident_analyses_incident_id", "incident_analyses", ["incident_id"])
    op.create_table(
        "incident_reviews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("analysis_id", sa.String(64), nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("proposal_digest", sa.String(80), nullable=False),
        sa.Column("analysis_digest", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_incident_reviews_analysis_id", "incident_reviews", ["analysis_id"])
    op.create_table(
        "incident_model_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("analysis_id", sa.String(64), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("packet", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("owner", sa.String(120), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_incident_model_jobs_analysis_id", "incident_model_jobs", ["analysis_id"])
    op.create_index("ix_incident_model_jobs_status", "incident_model_jobs", ["status"])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS incident_model_jobs")
    op.drop_index("ix_incident_reviews_analysis_id", "incident_reviews")
    op.drop_table("incident_reviews")
    op.drop_index("ix_incident_analyses_incident_id", "incident_analyses")
    op.drop_table("incident_analyses")
    op.drop_index("ix_incident_revisions_line_id", "incident_revisions")
    op.drop_table("incident_revisions")
