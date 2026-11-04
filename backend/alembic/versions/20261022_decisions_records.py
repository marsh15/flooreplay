"""Append-only decision evaluations and human decision records (FloorReplay 2.0, task T11)."""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261022_decisions_records'
down_revision = '20261021_decisions_facts'
branch_labels = None
depends_on = None

TABLES = ('decision_evaluations', 'decision_records')

# Literal copies of Recommendation (flooreplay/decisions/types.py). A test compares them with the
# constraints in the database, so drift fails loudly.
OUTCOMES = ('ACCEPT', 'ACCEPT_WITH_CONDITIONS', 'DECLINE', 'NEEDS_REVIEW')


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # Identity is (workspace_id, id); every reference carries the workspace so it cannot cross it.
    op.create_table(
        'decision_evaluations',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('order_id', sa.Text(), nullable=False),
        sa.Column('cutoff', sa.DateTime(timezone=True), nullable=False),
        sa.Column('policy_digest', sa.String(80), nullable=False),
        sa.Column('policy', postgresql.JSONB(), nullable=False),
        sa.Column('engine_version', sa.String(32), nullable=False),
        sa.Column('snapshot_digest', sa.String(80), nullable=False),
        sa.Column('decision_digest', sa.String(80), nullable=False),
        sa.Column('outcome', sa.String(32), nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.UniqueConstraint(
            'workspace_id', 'order_id', 'cutoff', 'policy_digest', 'engine_version', 'snapshot_digest',
            name='uq_decision_evaluations_replay_key',
        ),
        # Lets decision_records reference the stored outcome, so a record cannot misstate it.
        sa.UniqueConstraint('workspace_id', 'id', 'outcome', name='uq_decision_evaluations_id_outcome'),
        sa.CheckConstraint(_in('outcome', OUTCOMES), name='ck_decision_evaluations_outcome'),
    )
    op.create_table(
        'decision_records',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('evaluation_id', sa.Text(), nullable=False),
        sa.Column('decision', sa.String(32), nullable=False),
        sa.Column('recommended_outcome', sa.String(32), nullable=False),
        sa.Column('override', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('override_reason', sa.Text(), nullable=True),
        sa.Column('actor', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'evaluation_id', 'recommended_outcome'],
            ['decision_evaluations.workspace_id', 'decision_evaluations.id', 'decision_evaluations.outcome'],
        ),
        sa.CheckConstraint(_in('decision', OUTCOMES), name='ck_decision_records_decision'),
        sa.CheckConstraint(_in('recommended_outcome', OUTCOMES), name='ck_decision_records_recommended'),
        sa.CheckConstraint('override = (decision <> recommended_outcome)', name='ck_decision_records_override_flag'),
        sa.CheckConstraint(
            'NOT override OR (override_reason IS NOT NULL AND btrim(override_reason) <> \'\')',
            name='ck_decision_records_override_reason',
        ),
        sa.CheckConstraint("btrim(reason) <> ''", name='ck_decision_records_reason'),
        sa.CheckConstraint("btrim(actor) <> ''", name='ck_decision_records_actor'),
    )
    op.create_index(
        'ix_decision_records_workspace_evaluation', 'decision_records', ['workspace_id', 'evaluation_id']
    )

    # Reuses decisions_append_only() from 20261021_decisions_facts; that function must stay.
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
    # Dropping these tables destroys recorded human decisions, so refuse unless empty or opted in.
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
    # decisions_append_only() is left in place: decision_source_artifacts and facts still use it.
    op.drop_index('ix_decision_records_workspace_evaluation', table_name='decision_records')
    op.drop_table('decision_records')
    op.drop_table('decision_evaluations')
