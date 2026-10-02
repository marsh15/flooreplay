"""Assigned verification checks, responses, outcomes and resolution audit."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260930_workflow"
down_revision = "20260930_claim_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incident_checks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("incident_id", sa.String(64), nullable=False),
        sa.Column(
            "analysis_id", sa.String(64), sa.ForeignKey("incident_analyses.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("requested_fields", JSONB, nullable=False),
        sa.Column("assignee_id", sa.String(64), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(64), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response", JSONB, nullable=True),
        sa.Column("outcome", JSONB, nullable=True),
    )
    op.create_index("ix_incident_checks_incident_id", "incident_checks", ["incident_id"])
    op.create_table(
        "incident_workflow_activities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("incident_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("incident_checks.id"), nullable=True),
        sa.Column("actor", sa.String(64), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_incident_workflow_activities_incident_id",
        "incident_workflow_activities",
        ["incident_id"],
    )
    op.create_table(
        "incident_resolutions",
        sa.Column("incident_id", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("resolved_revision", sa.Integer, nullable=False),
    )
    op.create_table(
        "incident_workflow_receipts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("actor", sa.String(64), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("request_key", sa.String(120), nullable=False),
        sa.Column("operation", sa.String(200), nullable=False),
        sa.Column("fingerprint", sa.String(80), nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.UniqueConstraint("actor", "request_key"),
    )


def downgrade() -> None:
    op.drop_table("incident_workflow_receipts")
    op.drop_table("incident_resolutions")
    op.drop_table("incident_workflow_activities")
    op.drop_table("incident_checks")
