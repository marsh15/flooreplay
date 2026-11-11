"""Note extraction results and the append-only provider call ledger (FloorReplay 2.0, task T19).

Edited in place before release: the COMPLETED-only partial unique index, the failure_kind
column that decides retries, and the PERSIST_FAILED call outcome.
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '20261023_decisions_extraction'
down_revision = '20261023_decisions_regression'
branch_labels = None
depends_on = None

TABLES = ('note_extractions', 'provider_calls')
EXTRACTION_STATUSES = ('COMPLETED', 'FAILED', 'BUDGET_REFUSED')
FAILURE_KINDS = ('PROVIDER_ERROR', 'INVALID_OUTPUT', 'STORE_FAILED')
CALL_OUTCOMES = ('OK', 'ERROR', 'INVALID_OUTPUT', 'PERSIST_FAILED')


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # Identity is (workspace_id, id); every reference carries the workspace so it cannot cross it.
    op.create_table(
        'note_extractions',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('note_id', sa.Text(), nullable=False),
        sa.Column('note_digest', sa.String(80), nullable=False),
        sa.Column('model', sa.String(64), nullable=False),
        sa.Column('prompt_version', sa.String(32), nullable=False),
        sa.Column('schema_version', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('failure_kind', sa.String(16), nullable=True),
        sa.Column('language', sa.String(16), nullable=True),
        sa.Column('raw_output', postgresql.JSONB(), nullable=True),
        sa.Column('signal', postgresql.JSONB(), nullable=True),
        sa.Column('checks', postgresql.JSONB(), nullable=True),
        sa.Column('field_status', postgresql.JSONB(), nullable=True),
        sa.Column('error_class', sa.String(120), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=False),
        sa.Column('spend_entry_id', sa.String(64), nullable=True),
        sa.Column('created_by', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        # Lets provider_calls reference the extraction it belongs to, within the workspace.
        sa.CheckConstraint(_in('status', EXTRACTION_STATUSES), name='ck_note_extractions_status'),
        sa.CheckConstraint(
            "(status = 'FAILED') = (failure_kind IS NOT NULL)",
            name='ck_note_extractions_failure_kind_set',
        ),
        sa.CheckConstraint(
            _in('failure_kind', FAILURE_KINDS) + ' OR failure_kind IS NULL',
            name='ck_note_extractions_failure_kind',
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR (signal IS NOT NULL AND checks IS NOT NULL AND field_status IS NOT NULL)",
            name='ck_note_extractions_completed_payload',
        ),
        sa.CheckConstraint('cost_usd >= 0', name='ck_note_extractions_cost'),
        sa.CheckConstraint("btrim(note_id) <> ''", name='ck_note_extractions_note_id'),
        sa.CheckConstraint("btrim(model) <> ''", name='ck_note_extractions_model'),
        sa.CheckConstraint("btrim(created_by) <> ''", name='ck_note_extractions_actor'),
    )
    # One COMPLETED result per key. FAILED rows are attempts and may repeat for the same key.
    op.create_index(
        'uq_note_extractions_completed_key',
        'note_extractions',
        ['workspace_id', 'note_digest', 'model', 'prompt_version', 'schema_version'],
        unique=True,
        postgresql_where=sa.text("status = 'COMPLETED'"),
    )
    op.create_table(
        'provider_calls',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('extraction_id', sa.Text(), nullable=False),
        sa.Column('note_digest', sa.String(80), nullable=False),
        sa.Column('provider_name', sa.String(64), nullable=False),
        sa.Column('model', sa.String(64), nullable=False),
        sa.Column('prompt_version', sa.String(32), nullable=False),
        sa.Column('schema_version', sa.String(32), nullable=False),
        sa.Column('outcome', sa.String(24), nullable=False),
        # Exception class name only: never a message, a key or a request body.
        sa.Column('error_class', sa.String(120), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=False),
        sa.Column('spend_entry_id', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'extraction_id'], ['note_extractions.workspace_id', 'note_extractions.id']
        ),
        sa.CheckConstraint(_in('outcome', CALL_OUTCOMES), name='ck_provider_calls_outcome'),
        sa.CheckConstraint(
            "(outcome = 'OK') = (error_class IS NULL)", name='ck_provider_calls_error_class'
        ),
        sa.CheckConstraint('cost_usd >= 0', name='ck_provider_calls_cost'),
    )
    op.create_index(
        'ix_provider_calls_workspace_digest', 'provider_calls', ['workspace_id', 'note_digest']
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
    # Dropping these tables destroys recorded extraction results and provider call history,
    # so refuse unless empty or opted in.
    bind = op.get_bind()
    rows = sum(bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() for table in TABLES)
    if rows and os.environ.get('FLOORREPLAY_ALLOW_DESTRUCTIVE_DOWNGRADE') != '1':
        raise RuntimeError(
            f"refusing to drop {rows} append-only extraction rows; "
            "set FLOORREPLAY_ALLOW_DESTRUCTIVE_DOWNGRADE=1 to destroy them"
        )
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    # decisions_append_only() is left in place: the earlier decision tables still use it.
    op.drop_index('ix_provider_calls_workspace_digest', table_name='provider_calls')
    op.drop_table('provider_calls')
    # IF EXISTS: a database migrated by the earlier, unreleased revision has no such index.
    op.execute("DROP INDEX IF EXISTS uq_note_extractions_completed_key")
    op.drop_table('note_extractions')
