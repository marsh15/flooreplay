"""Append-only decision facts and source artifacts (FloorReplay 2.0, migration lane M1)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261021_decisions_facts'
down_revision = '20261001_operations'
branch_labels = None
depends_on = None

TABLES = ('decision_source_artifacts', 'facts')


def upgrade() -> None:
    op.create_table(
        'decision_source_artifacts',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('profile', sa.String(48), nullable=False),
        sa.Column('filename', sa.String(200), nullable=False),
        sa.Column('raw_bytes', sa.LargeBinary(), nullable=False),
        sa.Column('raw_digest', sa.String(80), nullable=False),
        sa.Column('as_of', sa.DateTime(timezone=True), nullable=False),
        sa.Column('known_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('coverage', postgresql.JSONB(), nullable=False),
        sa.Column('idempotency_key', sa.String(200), nullable=False),
        sa.Column('preview_digest', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('workspace_id', 'idempotency_key', name='uq_decision_source_artifacts_idempotency'),
        sa.CheckConstraint('as_of <= known_at', name='ck_decision_source_artifacts_no_backdating'),
    )
    op.create_index('ix_decision_source_artifacts_workspace_id', 'decision_source_artifacts', ['workspace_id'])
    op.create_table(
        'facts',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('entity_key', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('known_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('supersedes_id', sa.Text(), sa.ForeignKey('facts.id'), nullable=True),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('artifact_id', sa.Text(), sa.ForeignKey('decision_source_artifacts.id'), nullable=True),
        sa.Column('semantic_digest', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('valid_to IS NULL OR valid_to > valid_from', name='ck_facts_valid_interval'),
        sa.CheckConstraint('valid_from <= known_at', name='ck_facts_no_backdating'),
    )
    op.create_index('ix_facts_workspace_kind_entity', 'facts', ['workspace_id', 'kind', 'entity_key'])
    op.create_index('ix_facts_workspace_known_at', 'facts', ['workspace_id', 'known_at'])

    # Append-only: the database, not the application, refuses to rewrite history.
    op.execute(
        """
        CREATE FUNCTION decisions_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% on % is not allowed: decision records are append-only', TG_OP, TG_TABLE_NAME;
        END;
        $$
        """
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION decisions_append_only()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION decisions_append_only()"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    op.execute("DROP FUNCTION IF EXISTS decisions_append_only()")
    op.drop_table('facts')
    op.drop_table('decision_source_artifacts')
