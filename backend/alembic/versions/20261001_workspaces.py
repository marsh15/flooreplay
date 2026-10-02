"""Fail-closed private factory workspaces and evidence ownership.

Revision ID: 20261001_workspaces
Revises: 20261001_semantic_review
"""
from alembic import op
import sqlalchemy as sa

revision = '20261001_workspaces'
down_revision = '20261001_semantic_review'
branch_labels = None
depends_on = None

TABLES = ('source_snapshots', 'scenario_revisions', 'expectation_revisions', 'replay_attempts', 'import_audits', 'suite_revisions', 'comparison_reports', 'parser_calls', 'review_checks', 'incident_revisions', 'incident_analyses', 'incident_reviews', 'incident_model_jobs', 'incident_source_artifacts', 'ai_runs', 'corpus_releases', 'retrieval_runs', 'incident_checks', 'incident_workflow_activities', 'incident_resolutions', 'incident_workflow_receipts', 'ai_review_publications', 'ai_run_assessments', 'ai_claim_reviews')


def upgrade():
    op.create_table('workspaces', sa.Column('id', sa.String(64), primary_key=True), sa.Column('name', sa.String(120), nullable=False), sa.Column('visibility', sa.String(16), nullable=False))
    op.create_table('workspace_members', sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), primary_key=True), sa.Column('account_id', sa.String(64), sa.ForeignKey('accounts.id'), primary_key=True), sa.Column('role', sa.String(16), nullable=False))
    op.execute("INSERT INTO workspaces VALUES ('public-demo', 'Public synthetic demonstration', 'public'), ('legacy-private', 'Quarantined legacy imports: administrator must assign ownership', 'private')")
    for table in TABLES:
        op.add_column(table, sa.Column('workspace_id', sa.String(64), nullable=False, server_default='public-demo'))
        op.create_index('ix_' + table + '_workspace_id', table, ['workspace_id'])
    # Legacy raw imports lack a reliable factory owner. No global owner bypass.
    op.execute("UPDATE incident_revisions SET workspace_id='legacy-private' WHERE incident_id IN (SELECT incident_id FROM incident_source_artifacts)")
    for table in ('incident_analyses', 'incident_source_artifacts', 'incident_checks', 'incident_workflow_activities', 'incident_resolutions'):
        op.execute(f"UPDATE {table} SET workspace_id='legacy-private' WHERE incident_id IN (SELECT incident_id FROM incident_revisions WHERE workspace_id='legacy-private')")
    for table in ('incident_reviews', 'incident_model_jobs', 'ai_runs'):
        op.execute(f"UPDATE {table} SET workspace_id='legacy-private' WHERE analysis_id IN (SELECT id FROM incident_analyses WHERE workspace_id='legacy-private')")
    for table in ('ai_review_publications', 'ai_run_assessments', 'ai_claim_reviews'):
        op.execute(f"UPDATE {table} SET workspace_id='legacy-private' WHERE run_id IN (SELECT id FROM ai_runs WHERE workspace_id='legacy-private')")
    # Existing corpora and receipts may embed private titles/text/results; quarantine all.
    op.execute("UPDATE retrieval_runs SET workspace_id='legacy-private'")
    op.execute("UPDATE corpus_releases SET workspace_id='legacy-private'")
    op.execute("UPDATE incident_workflow_receipts SET workspace_id='legacy-private'")

    op.execute("UPDATE source_snapshots SET workspace_id='legacy-private' WHERE id IN (SELECT snapshot_id FROM import_audits)")
    op.execute("UPDATE import_audits SET workspace_id='legacy-private'")
    op.execute("UPDATE scenario_revisions SET workspace_id='legacy-private' WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(pinned_snapshot_ids) s WHERE s IN (SELECT id FROM source_snapshots WHERE workspace_id='legacy-private'))")
    op.execute("UPDATE expectation_revisions SET workspace_id='legacy-private' WHERE scenario_id IN (SELECT scenario_id FROM scenario_revisions WHERE workspace_id='legacy-private')")
    op.execute("UPDATE replay_attempts SET workspace_id='legacy-private' WHERE scenario_id IN (SELECT scenario_id FROM scenario_revisions WHERE workspace_id='legacy-private')")
    op.execute("UPDATE review_checks SET workspace_id='legacy-private' WHERE original_replay_id IN (SELECT id FROM replay_attempts WHERE workspace_id='legacy-private')")
    op.execute("UPDATE suite_revisions SET workspace_id='legacy-private' WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(items) item WHERE item->>'scenario_id' IN (SELECT scenario_id FROM scenario_revisions WHERE workspace_id='legacy-private'))")
    op.execute("UPDATE parser_calls SET workspace_id='legacy-private'")
    op.execute("UPDATE comparison_reports SET workspace_id='legacy-private'")
    op.execute("UPDATE incident_analyses SET workspace_id='legacy-private' WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(report->'corpus_release'->'items','[]'::jsonb)) item WHERE item->>'id' IN (SELECT incident_id FROM incident_revisions WHERE workspace_id='legacy-private'))")
    # Reapply descendants after quarantining reports that contain imported precedent text.
    for table in ('incident_reviews', 'incident_model_jobs', 'ai_runs'):
        op.execute(f"UPDATE {table} SET workspace_id='legacy-private' WHERE analysis_id IN (SELECT id FROM incident_analyses WHERE workspace_id='legacy-private')")
    for table in ('ai_review_publications', 'ai_run_assessments', 'ai_claim_reviews'):
        op.execute(f"UPDATE {table} SET workspace_id='legacy-private' WHERE run_id IN (SELECT id FROM ai_runs WHERE workspace_id='legacy-private')")


def downgrade():
    # Visibility columns cannot be dropped safely: an old release serves private data publicly.
    raise RuntimeError('Workspace privacy migration cannot be downgraded. Roll back only to a workspace-aware application release.')
