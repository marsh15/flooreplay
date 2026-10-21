"""Append-only decision facts and source artifacts (FloorReplay 2.0, migration lane M1)."""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261021_decisions_facts'
down_revision = '20261001_operations'
branch_labels = None
depends_on = None

TABLES = ('decision_source_artifacts', 'facts')

# Migrations are static, so the enum values are copied here as literals. Keep in step with
# FactKind and SourceProfile in flooreplay/decisions/types.py; a test compares them with the
# constraints in the database, so drift fails loudly.
FACT_KINDS = (
    'order_request', 'bom', 'fabric_lot', 'fabric_qc', 'fabric_inbound', 'fabric_allocation',
    'trim_status', 'line_capacity', 'line_commitment', 'resolution',
)
SOURCE_PROFILES = (
    'erp_fabric_stock', 'sheet_trims_status', 'shift_capacity', 'supplier_updates', 'notes',
    'order_requests', 'review_queue',
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # Identity is (workspace_id, id): the same id may exist in two workspaces, and every
    # reference carries the workspace so it can never point across the boundary.
    op.create_table(
        'decision_source_artifacts',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.UniqueConstraint('workspace_id', 'idempotency_key', name='uq_decision_source_artifacts_idempotency'),
        sa.CheckConstraint('as_of <= known_at', name='ck_decision_source_artifacts_no_backdating'),
    )
    op.create_table(
        'facts',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('entity_key', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('known_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('supersedes_id', sa.Text(), nullable=True),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('artifact_id', sa.Text(), nullable=True),
        sa.Column('semantic_digest', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.ForeignKeyConstraint(['workspace_id', 'supersedes_id'], ['facts.workspace_id', 'facts.id']),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'artifact_id'],
            ['decision_source_artifacts.workspace_id', 'decision_source_artifacts.id'],
        ),
        sa.CheckConstraint('valid_to IS NULL OR valid_to > valid_from', name='ck_facts_valid_interval'),
        sa.CheckConstraint('valid_from <= known_at', name='ck_facts_no_backdating'),
        sa.CheckConstraint('supersedes_id <> id', name='ck_facts_not_self_superseding'),
        sa.CheckConstraint(_in('kind', FACT_KINDS), name='ck_facts_kind'),
        sa.CheckConstraint(_in('source', SOURCE_PROFILES), name='ck_facts_source'),
    )
    op.create_index('ix_facts_workspace_kind_entity', 'facts', ['workspace_id', 'kind', 'entity_key'])
    op.create_index('ix_facts_workspace_known_at', 'facts', ['workspace_id', 'known_at'])

    # Append-only: the database, not the application, refuses to rewrite history.
    # Known limitation: the table owner (and any superuser) can still ALTER TABLE ... DISABLE
    # TRIGGER or drop the triggers. The application role must not own these tables in
    # production; the docs task (T36) describes the deployment requirement.
    # decisions_append_only() is shared by every append-only decision table. Later migrations
    # that add such tables reuse it, so none may drop it while another table still uses it.
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
    # Dropping the tables destroys the decision history, so refuse unless it is empty or the
    # operator opts in explicitly.
    bind = op.get_bind()
    rows = sum(bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() for table in TABLES)
    if rows and os.environ.get('FLOORREPLAY_ALLOW_DESTRUCTIVE_DOWNGRADE') != '1':
        raise RuntimeError(
            f"refusing to drop {rows} append-only decision rows; "
            "set FLOORREPLAY_ALLOW_DESTRUCTIVE_DOWNGRADE=1 to destroy them"
        )
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    op.execute("DROP FUNCTION IF EXISTS decisions_append_only()")
    op.drop_table('facts')
    op.drop_table('decision_source_artifacts')
