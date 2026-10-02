"""Export reproducible public bundles from the backend's immutable fixture reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import session_scope
from .domain.hashing import digest
from .incident_dataset import dataset_fixtures
from .incident_evaluation import evaluation_report
from .incident_fixtures import incident_fixtures
from .incident_service import create_analysis, incident_detail, incident_list


def export_demo(directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    fixture_ids = {item['id'] for item in incident_fixtures()}
    corpus_ids = fixture_ids | {item['id'] for item in dataset_fixtures() if item['dataset_split'] == 'historical'}
    with session_scope() as session:
        analysis = create_analysis(session, 'INC-001', 2, 'release-demo-v5-' + digest(sorted(corpus_ids))[-32:], corpus_incident_ids=corpus_ids)
        # Stable bundle identity describes content; database execution IDs/times stay in DB.
        report = {**analysis.report, 'id': 'saved-' + analysis.manifest_digest.removeprefix('sha256:'), 'incident_id':'INC-001', 'revision':2, 'cutoff':incident_detail(session, 'INC-001', 2)['cutoff'], 'manifest_digest':analysis.manifest_digest, 'execution_kind':'saved_deterministic', 'stale':False, 'reviews':[], 'bundle_schema':'flooreplay.public-bundle.v1'}
        library = {'items':[{k:v for k,v in item.items() if k != 'last_reviewed_revision'} for item in incident_list(session) if item['id'] in fixture_ids], 'execution_kind':'saved_library'}
        revision = incident_detail(session, 'INC-001', 2)
        evaluation = {**evaluation_report(session), 'execution_kind':'saved_evaluation'}
    historical = json.loads((Path(__file__).resolve().parents[2] / 'evaluation' / 'hero-saved-ai.json').read_text())
    values = {'hero-report':report, 'hero-revision':revision, 'incident-library':library, 'evaluation-report':evaluation, 'hero-ai':historical}
    for name,value in values.items():
        (directory / (name+'.json')).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    manifest = {'schema':'flooreplay.public-bundle.v1', 'engine':'incident-v4', 'provider_evaluation':'OPENAI_NOT_EVALUATED', 'artifacts':{name:digest(value) for name,value in values.items()}}
    (directory / 'bundle-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest
