"""Incident persistence, retrieval, and version-bound human review."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .domain.hashing import digest, incident_digest
from .incident_engine import analyze_incident, incident_evidence_card
from .incident_import import preview_incident_import, publish_incident_import
from .models import IncidentAnalysis, IncidentReview, IncidentRevision, IncidentSourceArtifact
from .service import ServiceError


def _revision(session: Session, incident_id: str, revision: int) -> IncidentRevision:
    row = session.get(IncidentRevision, (incident_id, revision))
    if row is None:
        raise ServiceError("INCIDENT_UNKNOWN", "Unknown incident revision", 404)
    return row


def incident_list(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(select(IncidentRevision).order_by(IncidentRevision.incident_id, IncidentRevision.revision)).scalars().all()
    latest: dict[str, IncidentRevision] = {}
    for row in rows:
        latest[row.incident_id] = row
    items = []
    for row in latest.values():
        report = analyze_incident(row.payload)
        metric = report["metrics"]
        reviewed = session.execute(
            select(func.max(IncidentAnalysis.revision))
            .join(IncidentReview, IncidentReview.analysis_id == IncidentAnalysis.id)
            .where(IncidentAnalysis.incident_id == row.incident_id)
        ).scalar_one()
        available = sum(bool(value) for value in row.payload.get("coverage", {}).values())
        total = len(row.payload.get("coverage", {}))
        items.append({
            "id": row.incident_id, "revision": row.revision, "title": row.title,
            "line": row.line_id, "window_start": row.window_start.isoformat(),
            "window_end": row.window_end.isoformat(), "cutoff": row.cutoff.isoformat(),
            "status": metric["status"], "shortfall": metric["shortfall"],
            "evidence_completeness": f"{available}/{total} declared sources" if total else "Unknown coverage",
            "last_reviewed_revision": reviewed,
        })
    return items


def incident_detail(session: Session, incident_id: str, revision: int) -> dict[str, Any]:
    row = _revision(session, incident_id, revision)
    revisions = session.execute(select(IncidentRevision.revision).where(IncidentRevision.incident_id == incident_id).order_by(IncidentRevision.revision)).scalars().all()
    return {**row.payload, "available_revisions": revisions, "content_digest": row.content_digest}


def search_incidents(
    session: Session, query: str, *, cutoff: datetime | None = None,
    exclude_incident_id: str | None = None, stage: str | None = None,
    query_line: str | None = None, limit: int = 5,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    vector = func.to_tsvector("english", IncidentRevision.evidence_card)
    terms = func.websearch_to_tsquery("english", query[:200])
    statement = select(IncidentRevision, func.ts_rank(vector, terms).label("score")).where(vector.op("@@")(terms))
    if cutoff is not None:
        statement = statement.where(IncidentRevision.cutoff < cutoff)
    if exclude_incident_id:
        statement = statement.where(IncidentRevision.incident_id != exclude_incident_id)
    if stage:
        statement = statement.where(IncidentRevision.payload["scope"]["stage"].astext == stage)
    statement = statement.order_by(func.ts_rank(vector, terms).desc(), IncidentRevision.incident_id).limit(limit * 3)
    results = []
    seen: set[str] = set()
    for row, score in session.execute(statement):
        if row.incident_id in seen:
            continue
        seen.add(row.incident_id)
        results.append({
            "id": row.incident_id, "revision": row.revision, "title": row.title,
            "line": row.line_id, "score": round(float(score), 4),
            "match_reason": "Shared terms in incident title or recorded events",
            "differences": ([f"Different sewing line ({row.line_id} versus {query_line})."] if query_line and row.line_id != query_line else []) + ["Material lot, machine, and action prerequisites need separate verification."],
            "cutoff": row.cutoff.isoformat(), "execution_kind": "live_lexical",
        })
        if len(results) == limit:
            break
    return results


def create_analysis(session: Session, incident_id: str, revision: int, key: str) -> IncidentAnalysis:
    row = _revision(session, incident_id, revision)
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))
    existing = session.execute(select(IncidentAnalysis).where(IncidentAnalysis.idempotency_key == key)).scalar_one_or_none()
    if existing is not None:
        if (existing.incident_id, existing.revision) != (incident_id, revision):
            raise ServiceError("IDEMPOTENCY_CONFLICT", "Key already used for another analysis", 409)
        return existing
    report = analyze_incident(row.payload)
    report["engine_version"] = "incident-v2"
    eligible = session.execute(
        select(IncidentRevision).where(
            IncidentRevision.cutoff < row.cutoff,
            IncidentRevision.incident_id != incident_id,
            IncidentRevision.payload["scope"]["stage"].astext == row.payload["scope"]["stage"],
        ).order_by(IncidentRevision.incident_id, IncidentRevision.revision)
    ).scalars().all()
    corpus_items = [{"id": item.incident_id, "revision": item.revision, "digest": incident_digest(item.payload)} for item in eligible]
    report["corpus_release"] = {"version": "lexical-v2", "items": corpus_items, "digest": digest(corpus_items)}
    categories = [h["category"].replace("_", " ") for h in report.get("hypotheses", []) if h["status"] == "SUPPORTED"]
    query = " ".join(categories) or " ".join(event.get("type", "") for event in report.get("timeline", [])[:2])
    report["precedents"] = search_incidents(session, query, cutoff=row.cutoff, exclude_incident_id=incident_id, stage=row.payload["scope"]["stage"], query_line=row.line_id)
    now = datetime.now(UTC)
    analysis = IncidentAnalysis(
        idempotency_key=key, incident_id=incident_id, revision=revision,
        manifest_digest=digest({"incident_digest": incident_digest(row.payload), "corpus_digest": report["corpus_release"]["digest"], "engine": "incident-v2"}),
        report=report, execution_kind="live_deterministic", created_at=now, completed_at=now,
    )
    session.add(analysis)
    session.flush()
    return analysis


def analysis_view(session: Session, analysis: IncidentAnalysis) -> dict[str, Any]:
    reviews = session.execute(select(IncidentReview).where(IncidentReview.analysis_id == analysis.id).order_by(IncidentReview.created_at)).scalars().all()
    latest = session.execute(select(func.max(IncidentRevision.revision)).where(IncidentRevision.incident_id == analysis.incident_id)).scalar_one()
    return {
        "id": analysis.id, "incident_id": analysis.incident_id, "revision": analysis.revision,
        "cutoff": _revision(session, analysis.incident_id, analysis.revision).cutoff.isoformat(),
        "manifest_digest": analysis.manifest_digest, "execution_kind": analysis.execution_kind,
        "created_at": analysis.created_at.isoformat(), "completed_at": analysis.completed_at.isoformat(),
        "stale": analysis.revision != latest,
        "reviews": [{"id": r.id, "proposal_id": r.proposal_id, "state": r.state, "actor": r.actor, "rationale": r.rationale, "created_at": r.created_at.isoformat()} for r in reviews],
        **analysis.report,
    }


def analysis_evidence(session: Session, analysis: IncidentAnalysis, evidence_id: str) -> dict[str, Any]:
    row = _revision(session, analysis.incident_id, analysis.revision)
    permitted = {event["id"] for event in analysis.report.get("timeline", [])}
    permitted.update(
        record["id"]
        for entry in analysis.report.get("metrics", {}).get("inputs", [])
        for record in (entry["plan"], entry["output"])
    )
    if evidence_id not in permitted:
        raise ServiceError("EVIDENCE_UNKNOWN", "Evidence is not in this report", 404)
    source = next(
        record for section in ("events", "plan_buckets", "output_buckets")
        for record in row.payload.get(section, []) if record["id"] == evidence_id
    )
    return {
        "id": evidence_id,
        "source_id": source.get("source_id", f"synthetic-fixture:{analysis.incident_id}@{analysis.revision}/{evidence_id}"),
        "record": source, "incident_id": analysis.incident_id, "revision": analysis.revision,
    }


def review_proposal(
    session: Session, analysis: IncidentAnalysis, proposal_id: str, state: str,
    actor: str, rationale: str, key: str,
) -> IncidentReview:
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))
    existing = session.execute(select(IncidentReview).where(IncidentReview.idempotency_key == key)).scalar_one_or_none()
    if existing is not None:
        if (existing.analysis_id, existing.proposal_id, existing.state, existing.actor, existing.rationale) != (analysis.id, proposal_id, state, actor, rationale):
            raise ServiceError("IDEMPOTENCY_CONFLICT", "Key already used for another review", 409)
        return existing
    # Publication takes the same transaction lock, preventing a revision race.
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(analysis.incident_id))))
    session.execute(select(IncidentRevision).where(IncidentRevision.incident_id == analysis.incident_id).with_for_update()).scalars().all()
    latest = session.execute(select(func.max(IncidentRevision.revision)).where(IncidentRevision.incident_id == analysis.incident_id)).scalar_one()
    if analysis.revision != latest:
        raise ServiceError("STALE_ANALYSIS", "A newer incident revision exists; analyze it before review", 409)
    proposal = next((p for p in analysis.report.get("proposals", []) if p["id"] == proposal_id), None)
    if proposal is None:
        raise ServiceError("PROPOSAL_UNKNOWN", "Unknown proposal", 404)
    prior = session.execute(
        select(IncidentReview)
        .where(IncidentReview.analysis_id == analysis.id, IncidentReview.proposal_id == proposal_id)
        .order_by(IncidentReview.created_at, IncidentReview.id)
    ).scalars().all()
    if prior and prior[-1].state in ("APPROVED", "REJECTED"):
        raise ServiceError("ALREADY_REVIEWED", "This proposal already has a final review", 409)
    if state in ("APPROVED", "REJECTED") and (not prior or prior[-1].state != "PENDING_REVIEW"):
        raise ServiceError("REVIEW_STATE", "Submit the proposal for review first", 409)
    decision = IncidentReview(
        idempotency_key=key, analysis_id=analysis.id, proposal_id=proposal_id,
        state=state, actor=actor, rationale=rationale,
        proposal_digest=digest(proposal), analysis_digest=analysis.manifest_digest,
    )
    session.add(decision)
    session.flush()
    return decision


def publish_source(
    session: Session, *, incident_id: str, base_revision: int, cutoff: str,
    raw_text: str, profile: str, source_system: str, timezone: str,
    filename: str, unit: str | None, idempotency_key: str, preview_digest: str,
) -> dict[str, Any]:
    try:
        new_cutoff = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ServiceError("INVALID_CUTOFF", "Use an ISO timestamp with a timezone", 422) from exc
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(idempotency_key))))
    existing = session.execute(select(IncidentSourceArtifact).where(IncidentSourceArtifact.idempotency_key == idempotency_key)).scalar_one_or_none()
    if existing is not None:
        prior = _revision(session, existing.incident_id, existing.revision)
        if (
            existing.incident_id != incident_id or existing.revision != base_revision + 1
            or existing.raw_digest != sha256(raw_text.encode("utf-8")).hexdigest()
            or existing.raw_digest != preview_digest
            or existing.profile != profile or existing.source_system != source_system
            or existing.filename != filename or existing.preview.get("timezone") != timezone
            or existing.preview.get("requested_unit") != unit
            or prior.cutoff != new_cutoff
        ):
            raise ServiceError("IDEMPOTENCY_CONFLICT", "Key already used for another import", 409)
        return incident_detail(session, incident_id, existing.revision)
    try:
        preview = preview_incident_import(raw_text.encode("utf-8"), profile=profile, source_system=source_system, timezone=timezone, filename=filename, unit=unit)
    except ValueError as exc:
        raise ServiceError("INVALID_IMPORT", str(exc), 422) from exc
    if preview["raw_digest"] != preview_digest:
        raise ServiceError("PREVIEW_MISMATCH", "File changed since preview", 409)
    if preview["status"] != "READY":
        raise ServiceError("IMPORT_BLOCKED", "Fix row diagnostics before publication", 422)
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(incident_id))))
    base = _revision(session, incident_id, base_revision)
    latest = session.execute(select(func.max(IncidentRevision.revision)).where(IncidentRevision.incident_id == incident_id)).scalar_one()
    if latest != base_revision:
        raise ServiceError("STALE_REVISION", "A newer incident revision exists", 409)
    if new_cutoff.tzinfo is None or new_cutoff <= base.cutoff:
        raise ServiceError("INVALID_CUTOFF", "New cutoff must be later and timezone aware", 422)
    additions = publish_incident_import(preview)
    if additions["plan_buckets"]:
        raise ServiceError("BASELINE_IMMUTABLE", "Baseline plan is pinned; start a new incident for another baseline", 422)
    scope = base.payload["scope"]
    for section, rows in additions.items():
        for record in rows:
            if not _scope_matches_import(record, scope):
                raise ServiceError("SCOPE_MISMATCH", f"{record['id']} does not match the incident scope", 422)
            if section == "output_buckets" and not any(
                datetime.fromisoformat(record["start"]) == datetime.fromisoformat(plan["start"])
                and datetime.fromisoformat(record["end"]) == datetime.fromisoformat(plan["end"])
                for plan in base.payload.get("plan_buckets", [])
            ):
                raise ServiceError("BUCKET_OUTSIDE_PLAN", f"{record['id']} has no matching baseline bucket", 422)
    payload = {**base.payload, "revision": base_revision + 1, "cutoff": new_cutoff.isoformat()}
    for section, rows in additions.items():
        payload[section] = [*base.payload.get(section, []), *rows]
    _unique_evidence_ids(payload)
    try:
        analyze_incident(payload)
    except (ValueError, KeyError) as exc:
        raise ServiceError("INVALID_REVISION", str(exc), 422) from exc
    row = IncidentRevision(
        incident_id=incident_id, revision=base_revision + 1, title=base.title,
        line_id=base.line_id, cutoff=new_cutoff, window_start=base.window_start,
        window_end=base.window_end, payload=payload, content_digest=incident_digest(payload),
        evidence_card=incident_evidence_card(payload),
    )
    artifact = IncidentSourceArtifact(
        idempotency_key=idempotency_key, incident_id=incident_id, revision=row.revision,
        profile=profile, source_system=source_system, filename=filename,
        raw_digest=preview["raw_digest"], raw_bytes=raw_text.encode("utf-8"),
        preview={**preview, "requested_unit": unit},
    )
    session.add_all([row, artifact])
    session.flush()
    return incident_detail(session, incident_id, row.revision)


def _scope_matches_import(record: dict[str, Any], scope: dict[str, Any]) -> bool:
    return all(record[key] == value for key, value in scope.items() if key in record)


def create_incident_from_source(
    session: Session, *, incident_id: str, title: str, scope: dict[str, str],
    window: dict[str, str], cutoff: str, raw_text: str, source_system: str,
    timezone: str, filename: str, preview_digest: str, idempotency_key: str,
) -> dict[str, Any]:
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(idempotency_key))))
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(incident_id))))
    existing = session.execute(select(IncidentSourceArtifact).where(IncidentSourceArtifact.idempotency_key == idempotency_key)).scalar_one_or_none()
    if existing is not None:
        row = _revision(session, existing.incident_id, existing.revision)
        if (
            existing.incident_id != incident_id or existing.raw_digest != sha256(raw_text.encode()).hexdigest()
            or existing.raw_digest != preview_digest or existing.source_system != source_system
            or existing.filename != filename or existing.preview.get("timezone") != timezone
            or row.title != title or row.payload["scope"] != scope
            or row.payload["window"] != window or row.payload["cutoff"] != cutoff
        ):
            raise ServiceError("IDEMPOTENCY_CONFLICT", "Key already used for another incident", 409)
        return incident_detail(session, incident_id, 1)
    if session.get(IncidentRevision, (incident_id, 1)) is not None:
        raise ServiceError("INCIDENT_EXISTS", "Incident ID already exists", 409)
    if set(scope) != {"factory", "line_id", "order_id", "style_id", "stage", "unit"} or scope["unit"] != "good_units" or not all(scope.values()):
        raise ServiceError("INVALID_SCOPE", "Complete factory, line, order, style, sewing stage, and good_units scope is required", 422)
    if scope["stage"] != "sewing":
        raise ServiceError("INVALID_SCOPE", "Launch supports one sewing line", 422)
    try:
        start = datetime.fromisoformat(window["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(window["end"].replace("Z", "+00:00"))
        cutoff_at = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise ServiceError("INVALID_WINDOW", "Use timezone-aware start, end, and cutoff timestamps", 422) from exc
    if any(value.tzinfo is None for value in (start, end, cutoff_at)) or not start < end or cutoff_at < start:
        raise ServiceError("INVALID_WINDOW", "Window and cutoff are invalid", 422)
    try:
        preview = preview_incident_import(raw_text.encode("utf-8"), profile="production-v1", source_system=source_system, timezone=timezone, filename=filename, unit="good_units")
    except ValueError as exc:
        raise ServiceError("INVALID_IMPORT", str(exc), 422) from exc
    if preview["raw_digest"] != preview_digest:
        raise ServiceError("PREVIEW_MISMATCH", "File changed since preview", 409)
    if preview["status"] != "READY" or not preview["plan_buckets"]:
        raise ServiceError("IMPORT_BLOCKED", "A valid baseline plan is required", 422)
    additions = publish_incident_import(preview)
    if any(not _scope_matches_import(record, scope) for rows in additions.values() for record in rows):
        raise ServiceError("SCOPE_MISMATCH", "Source records do not match the incident scope", 422)
    if any(datetime.fromisoformat(record["available_at"]) > start for record in additions["plan_buckets"]):
        raise ServiceError("BASELINE_LATE", "Baseline plan must be available before the shift starts", 422)
    if any(datetime.fromisoformat(record["start"]) < start or datetime.fromisoformat(record["end"]) > end for record in additions["plan_buckets"]):
        raise ServiceError("BUCKET_OUTSIDE_WINDOW", "Plan bucket lies outside the investigation window", 422)
    payload = {"id": incident_id, "revision": 1, "title": title, "scope": scope, "window": window, "cutoff": cutoff, **additions, "coverage": {"production": True}}
    _unique_evidence_ids(payload)
    try:
        analyze_incident(payload)
    except (ValueError, KeyError) as exc:
        raise ServiceError("INVALID_REVISION", str(exc), 422) from exc
    row = IncidentRevision(incident_id=incident_id, revision=1, title=title, line_id=scope["line_id"], cutoff=cutoff_at, window_start=start, window_end=end, payload=payload, content_digest=incident_digest(payload), evidence_card=incident_evidence_card(payload))
    artifact = IncidentSourceArtifact(idempotency_key=idempotency_key, incident_id=incident_id, revision=1, profile="production-v1", source_system=source_system, filename=filename, raw_digest=preview_digest, raw_bytes=raw_text.encode(), preview=preview)
    session.add_all([row, artifact])
    session.flush()
    return incident_detail(session, incident_id, 1)


def _unique_evidence_ids(payload: dict[str, Any]) -> None:
    ids = [record["id"] for section in ("plan_buckets", "output_buckets", "events") for record in payload.get(section, [])]
    if len(ids) != len(set(ids)):
        raise ServiceError("DUPLICATE_EVIDENCE_ID", "Source record IDs must be unique across the incident", 422)
