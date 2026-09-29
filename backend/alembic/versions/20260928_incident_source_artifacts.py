"""Store exact incident import bytes and audits.

Revision ID: 20260928sources
Revises: 20260928incident
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260928sources"
down_revision = "20260928incident"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incident_source_artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("incident_id", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("profile", sa.String(32), nullable=False),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("raw_digest", sa.String(80), nullable=False),
        sa.Column("raw_bytes", sa.LargeBinary, nullable=False),
        sa.Column("preview", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_incident_source_artifacts_incident_id", "incident_source_artifacts", ["incident_id"])


def downgrade() -> None:
    op.drop_index("ix_incident_source_artifacts_incident_id", "incident_source_artifacts")
    op.drop_table("incident_source_artifacts")
