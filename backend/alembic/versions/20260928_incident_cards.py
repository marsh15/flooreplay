"""Index only cutoff-visible incident evidence cards.

Revision ID: 20260928cards
Revises: 20260928elapsed
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision = "20260928cards"
down_revision = "20260928elapsed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incident_revisions", sa.Column("evidence_card", sa.Text, nullable=False, server_default=""))
    connection = op.get_bind()
    for incident_id, revision_number, payload in connection.execute(
        sa.text("SELECT incident_id, revision, payload FROM incident_revisions")
    ):
        cutoff = datetime.fromisoformat(payload["cutoff"].replace("Z", "+00:00"))
        end = min(cutoff, datetime.fromisoformat(payload["window"]["end"].replace("Z", "+00:00")))
        scope = payload["scope"]
        visible = [
            event for event in payload.get("events", [])
            if datetime.fromisoformat(event["available_at"].replace("Z", "+00:00")) <= cutoff
            and datetime.fromisoformat((event.get("occurred_at") or event.get("start")).replace("Z", "+00:00")) <= end
            and all(key not in event or event[key] == value for key, value in scope.items())
        ]
        superseded = {event.get("supersedes_id") or event.get("supersedes") for event in visible}
        current = [event for event in visible if event["id"] not in superseded]
        current.sort(key=lambda event: (
            datetime.fromisoformat((event.get("occurred_at") or event["start"]).replace("Z", "+00:00")),
            event["id"],
        ))
        card = " ".join([payload["title"], *(f"{event['type']} {event['summary']}" for event in current)])[:20_000]
        connection.execute(
            sa.text("UPDATE incident_revisions SET evidence_card = :card WHERE incident_id = :incident_id AND revision = :revision"),
            {"card": card, "incident_id": incident_id, "revision": revision_number},
        )


def downgrade() -> None:
    op.drop_column("incident_revisions", "evidence_card")
