"""Policies, frozen regression cases, stored regression runs and owner policy adoptions (FloorReplay 2.0, task T12)."""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '20261023_decisions_regression'
down_revision = '20261022_decisions_records'
branch_labels = None
depends_on = None

TABLES = ('policies', 'decision_cases', 'case_expectations', 'regression_runs', 'policy_adoptions')


def upgrade() -> None:
    # Identity is (workspace_id, id); every reference carries the workspace so it cannot cross it.
    op.create_table(
        'policies',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('policy_digest', sa.String(80), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('engine_version', sa.String(32), nullable=False),
        sa.Column('policy', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.UniqueConstraint('workspace_id', 'policy_digest', name='uq_policies_digest'),
        sa.CheckConstraint("btrim(label) <> ''", name='ck_policies_label'),
    )
    op.create_table(
        'decision_cases',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('cutoff', sa.DateTime(timezone=True), nullable=False),
        sa.Column('order_id', sa.Text(), nullable=False),
        sa.Column('facts', postgresql.JSONB(), nullable=False),
        sa.Column('coverage', postgresql.JSONB(), nullable=False),
        sa.Column('synthetic', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.CheckConstraint("btrim(name) <> ''", name='ck_decision_cases_name'),
        sa.CheckConstraint("btrim(order_id) <> ''", name='ck_decision_cases_order'),
    )
    op.create_table(
        'case_expectations',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('case_id', sa.Text(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('expectation', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        sa.UniqueConstraint('workspace_id', 'case_id', 'revision', name='uq_case_expectations_revision'),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'case_id'], ['decision_cases.workspace_id', 'decision_cases.id']
        ),
        sa.CheckConstraint('revision >= 1', name='ck_case_expectations_revision'),
    )
    op.create_table(
        'regression_runs',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('baseline_policy_digest', sa.String(80), nullable=False),
        sa.Column('candidate_policy_digest', sa.String(80), nullable=False),
        sa.Column('suite_digest', sa.String(80), nullable=False),
        sa.Column('results', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('complete', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        # Lets policy_adoptions reference the completeness and candidate digest of the run it adopts.
        sa.UniqueConstraint(
            'workspace_id', 'id', 'complete', 'candidate_policy_digest',
            name='uq_regression_runs_adoptable',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'baseline_policy_digest'], ['policies.workspace_id', 'policies.policy_digest']
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'candidate_policy_digest'], ['policies.workspace_id', 'policies.policy_digest']
        ),
        sa.CheckConstraint("status IN ('COMPLETE', 'INCOMPLETE')", name='ck_regression_runs_status'),
        sa.CheckConstraint("complete = (status = 'COMPLETE')", name='ck_regression_runs_complete_flag'),
    )
    op.create_table(
        'policy_adoptions',
        sa.Column('workspace_id', sa.String(64), nullable=False),
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('regression_run_id', sa.Text(), nullable=False),
        sa.Column('run_complete', sa.Boolean(), nullable=False),
        sa.Column('policy_digest', sa.String(80), nullable=False),
        sa.Column('adopted_by', sa.String(200), nullable=False),
        sa.Column('acknowledgements', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'id'),
        # The run must be COMPLETE and must have stored this exact candidate digest.
        sa.ForeignKeyConstraint(
            ['workspace_id', 'regression_run_id', 'run_complete', 'policy_digest'],
            [
                'regression_runs.workspace_id',
                'regression_runs.id',
                'regression_runs.complete',
                'regression_runs.candidate_policy_digest',
            ],
        ),
        sa.UniqueConstraint('workspace_id', 'regression_run_id', name='uq_policy_adoptions_run'),
        sa.CheckConstraint('run_complete', name='ck_policy_adoptions_run_complete'),
        sa.CheckConstraint("btrim(adopted_by) <> ''", name='ck_policy_adoptions_actor'),
        sa.CheckConstraint(
            "jsonb_typeof(acknowledgements) = 'object'", name='ck_policy_adoptions_acknowledgements'
        ),
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
    # Dropping these tables destroys recorded regression evidence and adoptions, so refuse unless
    # empty or opted in.
    bind = op.get_bind()
    rows = sum(bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() for table in TABLES)
    if rows and os.environ.get('FLOORREPLAY_ALLOW_DESTRUCTIVE_DOWNGRADE') != '1':
        raise RuntimeError(
            f"refusing to drop {rows} append-only regression rows; "
            "set FLOORREPLAY_ALLOW_DESTRUCTIVE_DOWNGRADE=1 to destroy them"
        )
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    # decisions_append_only() is left in place: the earlier decision tables still use it.
    op.drop_table('policy_adoptions')
    op.drop_table('regression_runs')
    op.drop_table('case_expectations')
    op.drop_table('decision_cases')
    op.drop_table('policies')
