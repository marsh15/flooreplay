"""A database timezone must not change a persisted review or run response."""

from datetime import UTC, datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from flooreplay.ai_evaluation import AIClaimReview, claim_review_view
from flooreplay.ai_runs import view
from flooreplay.incident_workflow import IncidentCheck, WorkflowActivity, _activity_view, task_view
from flooreplay.paid_models import AIRun
from flooreplay.semantic_review import AIRunAssessment, _assessment_view


@pytest.mark.parametrize("zone", ["Asia/Kolkata", "America/Los_Angeles"])
def test_record_views_are_identical_before_and_after_database_timezone_conversion(zone):
    instant = datetime(2026, 10, 31, 9, 30, 0, 123456, tzinfo=UTC)
    loaded = instant.astimezone(ZoneInfo(zone))

    original_claim = claim_review_view(AIClaimReview(id="claim", created_at=instant))
    loaded_claim = claim_review_view(AIClaimReview(id="claim", created_at=loaded))
    assert original_claim == loaded_claim
    assert original_claim["created_at"] == "2026-10-31T09:30:00.123456+00:00"

    assert _assessment_view(AIRunAssessment(id="assessment", created_at=instant, details={})) == (
        _assessment_view(AIRunAssessment(id="assessment", created_at=loaded, details={}))
    )
    assert view(AIRun(id="run", created_at=instant, completed_at=instant)) == (
        view(AIRun(id="run", created_at=loaded, completed_at=loaded))
    )


def test_workflow_views_are_identical_after_timezone_conversion():
    instant = datetime(2026, 10, 1, tzinfo=UTC)
    loaded = instant.astimezone(ZoneInfo("Asia/Kolkata"))
    assert _activity_view(WorkflowActivity(id="activity", created_at=instant)) == (
        _activity_view(WorkflowActivity(id="activity", created_at=loaded))
    )
    session = Mock()
    session.get.return_value = None
    session.scalars.return_value.all.return_value = []
    assert task_view(session, IncidentCheck(id="check", status="COMPLETED", created_at=instant, updated_at=instant, due_at=instant)) == (
        task_view(session, IncidentCheck(id="check", status="COMPLETED", created_at=loaded, updated_at=loaded, due_at=loaded))
    )
