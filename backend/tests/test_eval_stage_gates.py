"""An uncompleted predecessor cannot unlock a more expensive evaluation stage."""
import hashlib
import json

import pytest

from flooreplay import incident_model_eval, openai_provider
from flooreplay.config import settings
from flooreplay.incident_dataset import build_dataset


@pytest.mark.parametrize('partial_count', [0, 1, 4])
def test_in_progress_smoke_does_not_unlock_pilot(tmp_path, partial_count):
    dataset = build_dataset()
    config = openai_provider.configuration(settings.openai_generation_model, settings.openai_embedding_model, 512)
    fingerprint = hashlib.sha256(json.dumps([config, 'evidence_only', None], sort_keys=True).encode()).hexdigest()
    checkpoint = {'stage':'smoke', 'status':'IN_PROGRESS', 'blocking_defects':[], 'execution_configuration_digest':fingerprint, 'dataset_manifest':dataset['manifest'], 'cases':[{'status':'COMPLETED'} for _ in range(partial_count)], 'denominators':{'planned_cases':5, 'attempted_cases':partial_count, 'valid_runs':partial_count}}
    (tmp_path / 'openai-smoke.json').write_text(json.dumps(checkpoint))
    with pytest.raises(ValueError, match='Prior stage'):
        incident_model_eval.run(tmp_path / 'openai-pilot.json', 'unused-owner', 'pilot')


@pytest.mark.parametrize('status, expected', [('BLOCKED', 1), ('MEASURED_STRUCTURAL_ONLY', 0)])
def test_cli_reports_blocked_evaluation_as_failure(monkeypatch, tmp_path, status, expected):
    from flooreplay import __main__ as cli
    monkeypatch.setattr(cli, '_owner', lambda username: 'test-owner')
    monkeypatch.setattr(incident_model_eval, 'run', lambda *args: {'status':status})
    monkeypatch.setattr('sys.argv', ['flooreplay', 'eval-openai', '--owner', 'test-owner', '--output', str(tmp_path / 'openai-smoke.json')])
    assert cli.main() == expected
