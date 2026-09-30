from copy import deepcopy

from flooreplay.dataset_evaluation import validate_dataset
from flooreplay.incident_dataset import build_dataset


def test_frozen_release_has_required_splits_and_independent_expectations():
    dataset = build_dataset()
    result = validate_dataset(dataset)
    assert result["status"] == "PASSED", result["problems"]
    assert result["split_counts"] == {"historical": 120, "development": 30, "locked": 30}
    assert result["authored_templates"] == 24
    assert result["arithmetic_and_structure_cases_checked"] == 60
    assert build_dataset()["manifest"] == dataset["manifest"]


def test_release_audit_rejects_leakage_and_label_changes():
    dataset = deepcopy(build_dataset())
    locked = next(row for row in dataset["episodes"] if row["dataset_split"] == "locked")
    development = next(row for row in dataset["episodes"] if row["dataset_split"] == "development")
    locked["template_id"] = development["template_id"]
    dataset["labels"][0]["shortfall"] = 999
    result = validate_dataset(dataset)
    assert result["status"] == "FAILED"
    assert any("leakage" in problem for problem in result["problems"])
    assert any("digest" in problem for problem in result["problems"])
    assert any("expectation" in problem for problem in result["problems"])
