"""A database timezone must not change a persisted review or run response."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from flooreplay.ai_evaluation import AIClaimReview, claim_review_view
from flooreplay.ai_runs import view
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
