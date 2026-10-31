"""Offline comparative-pilot measurement: validation, summary and CLI behaviour."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest

from flooreplay.pilot_measurement import COLUMNS, load_pairs, main, measure_csv


def _baseline(**overrides: str) -> dict[str, str]:
    row = {column: "" for column in COLUMNS}
    row.update(
        pair_id="p1",
        cohort="synthetic",
        participant_id="P01",
        case_id="S-A",
        case_complexity="medium",
        method="baseline",
        method_order="baseline_first",
        outcome="success",
        completion_seconds="620",
        first_missing_evidence_seconds="240",
        evidence_expected="4",
        evidence_found="3",
        unsupported_conclusions="0",
        conclusions_assessed="3",
        errors="1",
        source_omissions="0",
        assistance_count="0",
        reviewer_confidence="4",
    )
    row.update(overrides)
    return row


def _flooreplay(**overrides: str) -> dict[str, str]:
    row = _baseline(method="flooreplay", case_id="S-B", release="a1b2c3d", completion_seconds="300")
    row.update(first_missing_evidence_seconds="90", errors="0", source_omissions="0", reviewer_confidence="5")
    row.update(overrides)
    return row


def _csv(*rows: dict[str, str], columns: tuple[str, ...] = COLUMNS) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def _problems(*rows: dict[str, str]) -> list[str]:
    return load_pairs(_csv(*rows))[1]


def test_valid_pair_is_accepted() -> None:
    pairs, problems = load_pairs(_csv(_baseline(), _flooreplay()))

    assert problems == []
    assert len(pairs) == 1
    assert pairs[0].baseline.method == "baseline"
    assert pairs[0].flooreplay.release == "a1b2c3d"


def test_missing_column_is_refused() -> None:
    columns = tuple(column for column in COLUMNS if column != "reviewer_confidence")

    _, problems = load_pairs(_csv(_baseline(), _flooreplay(), columns=columns))

    assert any("reviewer_confidence" in problem for problem in problems)


def test_header_only_file_is_refused_as_nothing_to_measure() -> None:
    _, problems = load_pairs(_csv())

    assert problems == ["no records: nothing to measure"]


def test_unpaired_row_is_refused() -> None:
    problems = _problems(_baseline())

    assert any("pair 'p1'" in problem and "exactly one baseline and one flooreplay" in problem for problem in problems)


def test_pair_with_two_baseline_rows_is_refused() -> None:
    problems = _problems(_baseline(), _baseline(case_id="S-C"))

    assert any("pair 'p1'" in problem for problem in problems)


def test_pair_rows_must_agree_on_cohort_and_complexity() -> None:
    problems = _problems(_baseline(), _flooreplay(cohort="practitioner", case_complexity="high"))

    assert any("cohort differs" in problem for problem in problems)
    assert any("case_complexity differs" in problem for problem in problems)


def test_participant_can_have_separate_synthetic_and_practitioner_sessions() -> None:
    problems = _problems(
        _baseline(pair_id="p1"),
        _flooreplay(pair_id="p1"),
        _baseline(pair_id="p2", cohort="practitioner", case_id="P-A"),
        _flooreplay(pair_id="p2", cohort="practitioner", case_id="P-B"),
        _baseline(pair_id="p3", participant_id="P01", case_id="S-C"),
        _flooreplay(pair_id="p3", participant_id="P01", case_id="S-D"),
    )

    assert problems == []


def test_different_participants_can_use_the_same_case() -> None:
    problems = _problems(
        _baseline(pair_id="p1"),
        _flooreplay(pair_id="p1"),
        _baseline(pair_id="p2", participant_id="P02", case_id="S-A"),
        _flooreplay(pair_id="p2", participant_id="P02", case_id="S-E"),
    )

    assert problems == []


def test_same_participant_cannot_duplicate_a_case_and_method() -> None:
    problems = _problems(
        _baseline(), _flooreplay(),
        _baseline(pair_id="p2"), _flooreplay(pair_id="p2", case_id="S-C"),
    )
    assert any("case_id 'S-A'" in problem and "more than once" in problem for problem in problems)


def test_failed_attempt_cannot_be_counted_as_a_completion() -> None:
    assert any("completion_seconds must be blank when outcome is failed" in p
               for p in _problems(_baseline(outcome="failed"), _flooreplay()))


def test_cli_cannot_overwrite_source_csv(tmp_path: Path) -> None:
    source = _write_csv(tmp_path / "pilot.csv", _baseline(), _flooreplay())
    before = source.read_bytes()
    assert main([str(source), "--output", str(source)]) == 1
    assert source.read_bytes() == before


def test_cli_reports_output_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _write_csv(tmp_path / "pilot.csv", _baseline(), _flooreplay())
    assert main([str(source), "--output", str(tmp_path / "missing" / "summary.json")]) == 1
    assert "Cannot write" in capsys.readouterr().err


def test_success_requires_completion_time() -> None:
    problems = _problems(_baseline(completion_seconds=""), _flooreplay())

    assert any("completion_seconds is required when outcome is success" in p for p in problems)


def test_timed_out_row_must_not_carry_completion_time() -> None:
    problems = _problems(_baseline(outcome="timed_out", completion_seconds="900"), _flooreplay())

    assert any("completion_seconds must be blank when outcome is timed_out" in p for p in problems)


def test_flooreplay_row_requires_release_and_baseline_row_must_not_name_one() -> None:
    assert any("release is required" in p for p in _problems(_baseline(), _flooreplay(release="")))
    assert any("release must be blank" in p for p in _problems(_baseline(release="a1b2c3d"), _flooreplay()))


def test_one_file_measures_one_release() -> None:
    problems = _problems(
        _baseline(pair_id="p1"),
        _flooreplay(pair_id="p1"),
        _baseline(pair_id="p2", participant_id="P02", case_id="S-C"),
        _flooreplay(pair_id="p2", participant_id="P02", case_id="S-D", release="ffffeee"),
    )

    assert any("more than one release" in problem for problem in problems)


def test_evidence_found_cannot_exceed_expected() -> None:
    problems = _problems(_baseline(evidence_found="5", evidence_expected="4"), _flooreplay())

    assert any("evidence_found" in problem and "exceeds" in problem for problem in problems)


def test_first_missing_evidence_cannot_come_after_completion() -> None:
    problems = _problems(_baseline(first_missing_evidence_seconds="700"), _flooreplay())

    assert any("first_missing_evidence_seconds" in problem and "after completion" in problem for problem in problems)


@pytest.mark.parametrize(
    ("column", "value", "fragment"),
    [
        ("reviewer_confidence", "6", "reviewer_confidence must be a whole number from 1 to 5"),
        ("reviewer_confidence", "0", "reviewer_confidence must be a whole number from 1 to 5"),
        ("usefulness_rating", "7", "usefulness_rating must be a whole number from 1 to 5"),
        ("reviewer_confidence", "4.5", "reviewer_confidence must be a whole number"),
        ("errors", "-1", "errors must be a whole number"),
        ("errors", "1.5", "errors must be a whole number"),
        ("completion_seconds", "-5", "completion_seconds must be a non-negative number"),
        ("completion_seconds", "nan", "completion_seconds must be a non-negative number"),
        ("completion_seconds", "soon", "completion_seconds must be a non-negative number"),
        ("completion_seconds", "1_000", "completion_seconds must be a non-negative number"),
        ("cohort", "pilot", "cohort must be one of"),
        ("method", "manual", "method must be one of"),
        ("outcome", "done", "outcome must be one of"),
        ("method_order", "random", "method_order must be one of"),
        ("case_complexity", "extreme", "case_complexity must be one of"),
        ("participant_id", "", "participant_id is required"),
    ],
)
def test_invalid_cell_values_are_refused(column: str, value: str, fragment: str) -> None:
    problems = _problems(_baseline(**{column: value}), _flooreplay())

    assert any(fragment in problem for problem in problems), problems


def test_blank_optional_cells_are_accepted_as_not_recorded() -> None:
    pairs, problems = load_pairs(
        _csv(_baseline(errors="", reviewer_confidence="", report_seconds=""), _flooreplay(source_omissions=""))
    )

    assert problems == []
    assert pairs[0].baseline.errors is None
    assert pairs[0].baseline.reviewer_confidence is None
    assert pairs[0].baseline.report_seconds is None


def test_measure_csv_returns_no_summary_when_refused() -> None:
    summary, problems = measure_csv(_csv(_baseline()))

    assert summary is None
    assert problems


def _write_csv(path: Path, *rows: dict[str, Any]) -> Path:
    path.write_text(_csv(*rows), encoding="utf-8")
    return path


def test_cli_refuses_invalid_input_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _write_csv(tmp_path / "pilot.csv", _baseline())
    output = tmp_path / "summary.json"

    exit_code = main([str(source), "--output", str(output)])

    assert exit_code == 1
    assert not output.exists()
    assert "no output written" in capsys.readouterr().err


def test_cli_refuses_blank_template(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    template = Path(__file__).parents[2] / "docs" / "pilot" / "comparative-pilot-template.csv"
    output = tmp_path / "summary.json"
    assert template.is_file(), "the blank template must ship under docs/pilot/"

    assert main([str(template), "--output", str(output)]) == 1
    assert not output.exists()
    assert "no records: nothing to measure" in capsys.readouterr().err


def test_template_header_matches_module_columns() -> None:
    template = Path(__file__).parents[2] / "docs" / "pilot" / "comparative-pilot-template.csv"
    header = template.read_text(encoding="utf-8").splitlines()

    assert header == [",".join(COLUMNS)]


def test_cli_reads_excel_style_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "pilot.csv"
    source.write_bytes(b"\xef\xbb\xbf" + _csv(_baseline(), _flooreplay()).encode("utf-8"))
    output = tmp_path / "summary.json"

    assert main([str(source), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["pairs"] == 1


def _scenario_csv() -> str:
    """Synthetic pairs s1 and s2 are comparable; s3 has a FloorReplay failure; p1 is a practitioner timeout."""
    return _csv(
        _baseline(pair_id="s1", participant_id="P01", case_id="S-A", completion_seconds="620"),
        _flooreplay(pair_id="s1", participant_id="P01", case_id="S-B", completion_seconds="300"),
        _baseline(pair_id="s2", participant_id="P02", case_id="S-C", completion_seconds="400", errors="2", evidence_found=""),
        _flooreplay(pair_id="s2", participant_id="P02", case_id="S-D", completion_seconds="500", errors=""),
        _baseline(pair_id="s3", participant_id="P03", case_id="S-E", completion_seconds="800", errors=""),
        _flooreplay(
            pair_id="s3",
            participant_id="P03",
            case_id="S-F",
            outcome="failed",
            completion_seconds="",
            first_missing_evidence_seconds="",
            evidence_found="",
            evidence_expected="",
            errors="",
        ),
        _baseline(pair_id="p1", cohort="practitioner", participant_id="P10", case_id="P-A", completion_seconds="1000"),
        _flooreplay(
            pair_id="p1",
            cohort="practitioner",
            participant_id="P10",
            case_id="P-B",
            outcome="timed_out",
            completion_seconds="",
        ),
    )


def test_paired_medians_use_only_comparable_completed_pairs() -> None:
    summary, problems = measure_csv(_scenario_csv())
    assert problems == [] and summary is not None

    paired = summary["cohorts"]["synthetic"]["paired"]
    assert paired["comparable_pairs"] == 2
    assert paired["baseline_completion_seconds"]["median"] == 510
    assert paired["flooreplay_completion_seconds"]["median"] == 400
    assert paired["per_pair_difference_seconds_flooreplay_minus_baseline"]["median"] == -110
    assert paired["flooreplay_slower_pairs"] == 1
    assert paired["flooreplay_faster_pairs"] == 1
    assert paired["same_time_pairs"] == 0


def test_same_incident_comparison_discloses_prior_exposure_and_method_order() -> None:
    summary, problems = measure_csv(_csv(_baseline(), _flooreplay(case_id="S-A")))
    assert problems == [] and summary is not None
    paired = summary["cohorts"]["synthetic"]["paired"]
    assert paired["same_case_pairs"] == 1
    assert "prior exposure" in paired["learning_effect_warning"]
    assert paired["method_order_pairs"] == {"baseline_first": 1, "flooreplay_first": 0}
    assert summary["pair_details"][0]["same_case_repeated"] is True


def test_outcome_pairs_keep_failures_out_of_timing_but_in_counts() -> None:
    summary, _ = measure_csv(_scenario_csv())
    assert summary is not None

    synthetic = summary["cohorts"]["synthetic"]["paired"]
    assert synthetic["pairs"] == 3
    assert synthetic["outcome_pairs"] == {
        "both_success": 2,
        "baseline_only_success": 1,
        "flooreplay_only_success": 0,
        "neither_success": 0,
    }

    practitioner = summary["cohorts"]["practitioner"]["paired"]
    assert practitioner["outcome_pairs"]["baseline_only_success"] == 1
    assert practitioner["comparable_pairs"] == 0
    assert practitioner["per_pair_difference_seconds_flooreplay_minus_baseline"] == {
        "n": 0,
        "median": None,
        "min": None,
        "max": None,
    }


def test_success_rate_denominator_includes_failures_and_timeouts() -> None:
    summary, _ = measure_csv(_scenario_csv())
    assert summary is not None

    flooreplay = summary["cohorts"]["synthetic"]["methods"]["flooreplay"]
    assert flooreplay["success_rate"] == {"numerator": 2, "denominator": 3, "rate": pytest.approx(2 / 3)}
    assert flooreplay["outcomes"] == {"success": 2, "failed": 1, "timed_out": 0}

    practitioner = summary["cohorts"]["practitioner"]["methods"]["flooreplay"]
    assert practitioner["success_rate"] == {"numerator": 0, "denominator": 1, "rate": 0.0}


def test_blank_cells_are_not_counted_as_zero() -> None:
    summary, _ = measure_csv(_scenario_csv())
    assert summary is not None

    baseline = summary["cohorts"]["synthetic"]["methods"]["baseline"]
    assert baseline["errors"] == {"n": 2, "median": 1.5, "min": 1, "max": 2, "total": 3}

    flooreplay = summary["cohorts"]["synthetic"]["methods"]["flooreplay"]
    assert flooreplay["errors"]["n"] == 1
    assert flooreplay["errors"]["total"] == 0
    assert flooreplay["first_missing_evidence_seconds"]["n"] == 2


def test_evidence_recall_uses_only_rows_with_both_counts() -> None:
    summary, _ = measure_csv(_scenario_csv())
    assert summary is not None

    baseline = summary["cohorts"]["synthetic"]["methods"]["baseline"]
    assert baseline["evidence_recall"] == {"numerator": 6, "denominator": 8, "rate": 0.75, "rows": 2}


def test_flooreplay_completion_summary_excludes_failed_rows() -> None:
    summary, _ = measure_csv(_scenario_csv())
    assert summary is not None

    completion = summary["cohorts"]["synthetic"]["methods"]["flooreplay"]["completion_seconds"]
    assert completion == {"n": 2, "median": 400, "min": 300, "max": 500}


def test_cohorts_are_summarised_separately_and_release_is_reported() -> None:
    summary, _ = measure_csv(_scenario_csv())
    assert summary is not None

    assert summary["release"] == "a1b2c3d"
    assert summary["pairs"] == 4
    assert summary["records"] == 8
    assert summary["cohorts"]["synthetic"]["pairs"] == 3
    assert summary["cohorts"]["synthetic"]["participants"] == 3
    assert summary["cohorts"]["practitioner"]["pairs"] == 1
    assert summary["cohorts"]["practitioner"]["methods"]["baseline"]["completion_seconds"]["median"] == 1000
    assert "not evidence of manufacturing benefit" in summary["disclaimer"]


def test_pair_details_show_each_case_and_leave_refused_differences_empty() -> None:
    summary, _ = measure_csv(_scenario_csv())
    assert summary is not None

    details = {detail["pair_id"]: detail for detail in summary["pair_details"]}
    assert details["s1"]["difference_seconds_flooreplay_minus_baseline"] == -320
    assert details["s3"]["difference_seconds_flooreplay_minus_baseline"] is None
    assert details["s3"]["flooreplay"] == {"case_id": "S-F", "outcome": "failed"}


def test_release_is_reported_for_a_valid_pair() -> None:
    summary, problems = measure_csv(_csv(_baseline(), _flooreplay()))

    assert problems == []
    assert summary is not None and summary["release"] == "a1b2c3d"


def test_cli_summary_matches_measure_csv(tmp_path: Path) -> None:
    source = tmp_path / "pilot.csv"
    source.write_text(_scenario_csv(), encoding="utf-8")
    output = tmp_path / "summary.json"

    assert main([str(source), "--output", str(output)]) == 0

    expected, _ = measure_csv(_scenario_csv())
    written: Any = json.loads(output.read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(expected))
