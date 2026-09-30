"""Persistence boundary proofs on the isolated release database, rolled back per test."""
from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from flooreplay.db import engine
from flooreplay.incident_fixtures import incident_fixtures
from flooreplay.incident_import import preview_incident_import
from flooreplay.incident_service import create_analysis, create_incident_from_source, publish_source
from flooreplay.models import IncidentRevision
from flooreplay.service import ServiceError


def test_publication_confirmation_binds_scope_and_timezone_and_preserves_correction_history():
    scope = {"factory": "F", "line_id": "L", "order_id": "O", "style_id": "S", "stage": "sewing", "unit": "good_units"}
    window = {"start": "2026-09-01T09:00:00+00:00", "end": "2026-09-01T09:15:00+00:00"}
    common = {**scope, **window}
    rows = [{**common, "id": "p", "record_type": "baseline_plan", "quantity": 20, "available_at": "2026-09-01T08:00:00+00:00"}, {**common, "id": "o", "record_type": "final_good_delta", "quantity": 10, "available_at": window["end"]}]
    raw = json.dumps(rows)
    preview = preview_incident_import(raw.encode(), profile="production-v1", source_system="ledger", timezone="UTC", filename="data.json", unit="good_units", scope=scope)
    incident_id = "test-correctness-" + uuid.uuid4().hex
    with Session(engine) as session:
        create_incident_from_source(session, incident_id=incident_id, title="Test", scope=scope, window=window, cutoff="2026-09-01T09:20:00+00:00", raw_text=raw, source_system="ledger", timezone="UTC", filename="data.json", preview_digest=preview["preview_digest"], idempotency_key=uuid.uuid4().hex)
        correction = json.dumps([{**rows[1], "id": "c", "supersedes_id": "o", "quantity": 15, "available_at": "2026-09-01T09:25:00+00:00"}])
        confirmed = preview_incident_import(correction.encode(), profile="production-v1", source_system="ledger", timezone="UTC", filename="correct.json", unit="good_units", scope=scope)
        kwargs = dict(incident_id=incident_id, base_revision=1, cutoff="2026-09-01T09:30:00+00:00", raw_text=correction, profile="production-v1", source_system="ledger", timezone="UTC", filename="correct.json", unit="good_units", idempotency_key=uuid.uuid4().hex, preview_digest=confirmed["preview_digest"])
        with pytest.raises(ServiceError, match="interpretation"):
            publish_source(session, **{**kwargs, "timezone": "Asia/Kolkata"})
        published = publish_source(session, **kwargs)
        assert published["revision"] == 2
        assert publish_source(session, **kwargs)["revision"] == 2
        report = create_analysis(session, incident_id, 2, uuid.uuid4().hex).report
        assert report["metrics"]["shortfall"] == 5
        assert report["correction_history"][0]["id"] == "c"
        assert session.get(IncidentRevision, (incident_id, 1)).payload["output_buckets"][0]["quantity"] == 10
        session.rollback()


def test_corpus_manifest_and_search_use_one_exact_eligible_revision():
    from flooreplay.incident_engine import incident_evidence_card

    suffix = uuid.uuid4().hex
    historical_id = "historical-" + suffix
    current_id = "current-" + suffix
    fixture = incident_fixtures()[0]
    with Session(engine) as session:
        for incident_id, revision, cutoff, split in [(historical_id, 1, "2026-09-28T11:00:00+05:30", "historical"), (historical_id, 2, "2026-09-28T11:30:00+05:30", "historical"), ("locked-" + suffix, 1, "2026-09-28T11:30:00+05:30", "locked"), (current_id, 1, "2026-09-29T11:30:00+05:30", "development")]:
            payload = deepcopy(fixture)
            payload.update(id=incident_id, revision=revision, cutoff=cutoff, dataset_split=split)
            session.add(IncidentRevision(incident_id=incident_id, revision=revision, title=payload["title"], line_id=payload["scope"]["line_id"], cutoff=datetime.fromisoformat(cutoff), window_start=datetime.fromisoformat(payload["window"]["start"]), window_end=datetime.fromisoformat(payload["window"]["end"]), payload=payload, content_digest=uuid.uuid4().hex, evidence_card=incident_evidence_card(payload)))
        session.flush()
        analysis = create_analysis(session, current_id, 1, uuid.uuid4().hex)
        items = analysis.report["corpus_release"]["items"]
        assert [item["revision"] for item in items if item["id"] == historical_id] == [2]
        assert not any(item["id"] in (current_id, "locked-" + suffix) for item in items)
        identities = {(item["id"], item["revision"]) for item in items}
        assert all((item["id"], item["revision"]) in identities for item in analysis.report["precedents"])
        session.rollback()
