from dataclasses import replace
from pathlib import Path

import pytest

from understudy.judge import RUBRIC
from understudy.records import (
    CheckResult,
    JudgeResult,
    Observation,
    RunRecord,
    Scenario,
    ScenarioRecord,
    Turn,
    evaluation_signature,
    load_run,
)
from understudy.report import compare_runs, render_report


def run(
    *,
    run_id="run",
    signature="sig",
    check_status="pass",
    score=3,
    record_error=None,
    judge_error=None,
    explanation="booking happened",
    model="one",
):
    scenario = Scenario("booking", "persona", "hello", "booked", 2, ["booked"])
    record = ScenarioRecord(
        scenario,
        Observation("Welcome", {"status": "active"}, "exposed"),
        [Turn("Book it", Observation("Booked *now*", {"status": "booked"}, "exposed"))],
        "terminal",
        error=record_error,
        checks=[
            CheckResult("confirmation-before-booking", check_status, explanation, 0)
        ],
        judge=JudgeResult(
            {dimension: score for dimension in RUBRIC},
            {dimension: "clear evidence" for dimension in RUBRIC},
            judge_error,
        ),
    )
    signature = (
        signature
        if signature != "sig"
        else evaluation_signature([scenario], {"persona": {}}, RUBRIC)
    )
    return RunRecord(
        1,
        run_id,
        "start",
        "finish",
        {"target": {"model": model}},
        "2030-04-15",
        [scenario],
        {"persona": {}},
        RUBRIC,
        "target-revision",
        None,
        signature,
        [],
        [record],
    )


def test_compare_detects_check_and_scenario_regressions_without_averaging():
    baseline = run(run_id="baseline", score=3)
    candidate = run(
        run_id="candidate",
        check_status="fail",
        score=4,
        explanation="Booked before explicit confirmation",
    )

    comparison = compare_runs(baseline, candidate)
    report = render_report(comparison)

    assert comparison.has_regression
    assert "confirmation-before-booking" in report
    assert "Booked before explicit confirmation" in report
    assert "turn 1" in report
    assert "Booked \\*now\\*" in report
    assert "clarity: +1" in report


def test_new_error_is_regression_even_when_scenario_already_failed():
    baseline = run(check_status="fail", score=2)
    candidate = run(check_status="fail", score=2, judge_error="judge unavailable")

    comparison = compare_runs(baseline, candidate)

    assert comparison.has_regression
    assert any(change.kind == "new-error" for change in comparison.regressions)


def test_new_judge_error_is_regression_despite_existing_execution_error():
    baseline = run(record_error="timeout")
    candidate = run(record_error="timeout", judge_error="judge unavailable")

    comparison = compare_runs(baseline, candidate)

    assert any(
        change.kind == "new-error" and change.explanation == "judge unavailable"
        for change in comparison.regressions
    )


def test_unchanged_failure_remains_visible_without_becoming_a_regression():
    comparison = compare_runs(run(check_status="fail"), run(check_status="fail"))
    report = render_report(comparison)

    assert not comparison.has_regression
    assert "Existing failures" in report
    assert "confirmation-before-booking" in report


def test_model_changes_are_allowed():
    comparison = compare_runs(run(model="old"), run(model="new"))
    assert not comparison.has_regression


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: replace(value, evaluation_signature="other"),
        lambda value: replace(value, records=[]),
        lambda value: replace(value, records=value.records + value.records),
        lambda value: replace(
            value,
            records=[replace(value.records[0], checks=value.records[0].checks * 2)],
        ),
        lambda value: replace(value, records=[replace(value.records[0], checks=[])]),
        lambda value: replace(value, records=[replace(value.records[0], judge=None)]),
    ],
)
def test_compare_rejects_incompatible_or_incomplete_artifacts(mutate):
    with pytest.raises(ValueError):
        compare_runs(run(), mutate(run()))


def test_compare_rejects_signature_that_does_not_match_stored_evaluation_inputs():
    candidate = run()
    candidate.rubric = {"changed": {}}
    with pytest.raises(ValueError):
        compare_runs(run(), candidate)


def test_report_escapes_untrusted_markdown_text():
    candidate = run(
        check_status="fail", explanation="[bad](https://example.test) | raw"
    )
    report = render_report(compare_runs(run(), candidate))
    assert "\\[bad\\]\\(https://example.test\\) \\| raw" in report


def test_report_identifies_runs_and_lists_every_scenario_status():
    baseline = run(run_id="baseline-1", model="old-model")
    baseline.fault = None
    candidate = run(run_id="candidate-2", model="new-model")
    candidate.fault = "premature_booking"

    report = render_report(compare_runs(baseline, candidate))

    assert "baseline-1" in report
    assert "candidate-2" in report
    assert "old-model" in report
    assert "new-model" in report
    assert "premature\\_booking" in report
    assert "| booking | pass | pass |" in report


def test_committed_live_evidence_detects_the_named_regression():
    examples = Path(__file__).parents[1] / "examples"
    baseline = load_run(examples / "baseline.json")
    candidate = load_run(examples / "seeded-bug.json")

    comparison = compare_runs(baseline, candidate)

    assert comparison.has_regression
    assert any(
        change.scenario_id == "declined-confirmation"
        and change.check_id == "confirmation-before-booking"
        and change.baseline == "pass"
        and change.candidate == "fail"
        for change in comparison.regressions
    )
    assert (
        render_report(comparison).rstrip()
        == (examples / "comparison.md").read_text().rstrip()
    )
