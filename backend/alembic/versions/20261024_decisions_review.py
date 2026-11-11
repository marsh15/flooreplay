"""Review queue items and their append-only event log (FloorReplay 2.0, task T20).

An item is one failed or missing extraction field, or one NEEDS_REVIEW evaluation. Its state is
never stored on the item: it is derived from the latest event. Both tables are append-only.
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '20261024_decisions_review'
down_revision = '20261023_decisions_extraction'
branch_labels = None
depends_on = None

TABLES = ('review_items', 'review_events')
SOURCE_KINDS = ('EXTRACTION_FIELD', 'EVALUATION')
FIELD_STATUSES = ('failed', 'missing', 'needs_review')
EVENT_KINDS = ('ASSIGNED', 'CONFIRMED', 'CORRECTED', 'REJECTED', 'UNASSIGNED')


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # Identity is (workspace_id, id); every reference carries the workspace so it cannot cross it.
    op.create_table(
        'review_items',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('source_kind', sa.String(24), nullable=False),
        sa.Column('extraction_id', sa.Text(), nullable=True),
        sa.Column('evaluation_id', sa.Text(), nullable=True),
        sa.Column('field_name', sa.String(64), nullable=False),
        sa.Column('field_status', sa.String(24), nullable=False),
        sa.Column('check_codes', postgresql.JSONB(), nullable=False),
        # The value as the model claimed it, and the located evidence span (code points).
        sa.Column('claimed_value', postgresql.JSONB(), nullable=True),
        sa.Column('evidence_span', postgresql.JSONB(), nullable=True),
        # The entity this item concerns; human facts must be bound to it (see review_service).
        sa.Column('entity_key', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'extraction_id'], ['note_extractions.workspace_id', 'note_extractions.id']
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'evaluation_id'],
            ['decision_evaluations.workspace_id', 'decision_evaluations.id'],
        ),
        sa.CheckConstraint(_in('source_kind', SOURCE_KINDS), name='ck_review_items_source_kind'),
        sa.CheckConstraint(
            "(source_kind = 'EXTRACTION_FIELD' AND extraction_id IS NOT NULL AND evaluation_id IS NULL) "
            "OR (source_kind = 'EVALUATION' AND evaluation_id IS NOT NULL AND extraction_id IS NULL)",
            name='ck_review_items_source_ref',
        ),
        sa.CheckConstraint(_in('field_status', FIELD_STATUSES), name='ck_review_items_field_status'),
        sa.CheckConstraint("btrim(field_name) <> ''", name='ck_review_items_field_name'),
        sa.CheckConstraint(
            "jsonb_typeof(check_codes) = 'array'", name='ck_review_items_check_codes'
        ),
        sa.CheckConstraint(
            "source_kind <> 'EVALUATION' OR entity_key IS NOT NULL", name='ck_review_items_entity_eval'
        ),
    )
    # One item per source and field: enqueueing the same extraction or evaluation twice is a no-op.
    op.create_index(
        'uq_review_items_source_field',
        'review_items',
        ['workspace_id', 'source_kind', sa.text('coalesce(extraction_id, evaluation_id)'), 'field_name'],
        unique=True,
    )

    op.create_table(
        'review_events',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        # Global, monotonic order: "latest event" never depends on timestamp ties.
        sa.Column('seq', sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column('item_id', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('actor', sa.String(200), nullable=False),
        sa.Column('assignee_id', sa.String(200), nullable=True),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('corrected_value', postgresql.JSONB(), nullable=True),
        sa.Column('resulting_fact_id', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.UniqueConstraint('seq', name='uq_review_events_seq'),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'item_id'], ['review_items.workspace_id', 'review_items.id']
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'resulting_fact_id'], ['facts.workspace_id', 'facts.id']
        ),
        sa.CheckConstraint(_in('kind', EVENT_KINDS), name='ck_review_events_kind'),
        sa.CheckConstraint("btrim(actor) <> ''", name='ck_review_events_actor'),
        sa.CheckConstraint(
            "(kind = 'ASSIGNED' AND assignee_id IS NOT NULL) "
            "OR (kind <> 'ASSIGNED' AND assignee_id IS NULL)",
            name='ck_review_events_assignee',
        ),
        sa.CheckConstraint(
            "kind IN ('ASSIGNED', 'UNASSIGNED') OR btrim(note) <> ''", name='ck_review_events_note'
        ),
        sa.CheckConstraint(
            "kind <> 'CORRECTED' OR (corrected_value IS NOT NULL AND resulting_fact_id IS NOT NULL)",
            name='ck_review_events_corrected',
        ),
        sa.CheckConstraint(
            "resulting_fact_id IS NULL OR kind IN ('CONFIRMED', 'CORRECTED')",
            name='ck_review_events_fact_kind',
        ),
    )
    op.create_index(
        'ix_review_events_workspace_item', 'review_events', ['workspace_id', 'item_id', 'seq']
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
    # Dropping these tables destroys recorded review decisions, so refuse unless empty or opted in.
    bind = op.get_bind()
    rows = sum(bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() for table in TABLES)
    if rows and os.environ.get('FLOORREPLAY_ALLOW_DESTRUCTIVE_DOWNGRADE') != '1':
        raise RuntimeError(
            f"refusing to drop {rows} append-only review rows; "
            "set FLOORREPLAY_ALLOW_DESTRUCTIVE_DOWNGRADE=1 to destroy them"
        )
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    # decisions_append_only() is left in place: the earlier decision tables still use it.
    op.drop_index('ix_review_events_workspace_item', table_name='review_events')
    op.drop_table('review_events')
    op.drop_index('uq_review_items_source_field', table_name='review_items')
    op.drop_table('review_items')
