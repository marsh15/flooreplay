"""Canonical serialization and digests.

Deterministic replay needs byte-stable serialization: timestamps normalized
to UTC, object keys sorted, semantically unordered collections sorted by
stable keys, no floats that can wobble between platforms. SHA-256 over the
canonical JSON gives the context and manifest digests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

# Collections whose order carries no meaning; canonical form sorts them.
_SORTED_COLLECTION_HINTS = {
    "aliases",
    "operation_ids",
    "compatible_operation_ids",
    "snapshots",
    "attendance",
    "assignments",
    "skills",
    "machine_state",
    "slots",
    "evidence",
    "gate_issues",
    "constraints",
    "ranking_factors",
    "candidate_exclusions",
    "issue_codes",
    "excluded_operators",
    "required_issue_codes",
    "required_failed_constraints",
    "required_passed_constraints",
    "forbidden_operators",
    "allowed_operators",
}


def _canonical(value: Any, sort_key: str | None = None) -> Any:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="json"), sort_key)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("refusing to canonicalize a naive datetime")
        utc = value.astimezone(UTC)
        return utc.isoformat().replace("+00:00", "Z")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("non-finite numbers are not canonicalizable")
        return value
    if isinstance(value, Mapping):
        return {
            str(k): _canonical(v, sort_key=str(k)) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        items = [_canonical(v) for v in value]
        if sort_key in _SORTED_COLLECTION_HINTS and value:
            first = items[0]
            if isinstance(first, Mapping):
                return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
            if all(isinstance(i, str) for i in items):
                return sorted(items)
        return items
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


_INCIDENT_INSTANT_KEYS = {"cutoff", "available_at", "occurred_at", "start", "end"}


def incident_digest(value: Any) -> str:
    """Incident schema digest: normalize instants, preserve timeline/rank order."""
    def normalize(item: Any, key: str | None = None) -> Any:
        if isinstance(item, Mapping):
            return {str(k): normalize(v, str(k)) for k, v in sorted(item.items())}
        if isinstance(item, (list, tuple)):
            return [normalize(v) for v in item]
        if isinstance(item, str) and key in _INCIDENT_INSTANT_KEYS:
            moment = datetime.fromisoformat(item.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                raise ValueError("incident timestamps must be timezone aware")
            return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return item

    encoded = json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
