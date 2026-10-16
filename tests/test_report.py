from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from understudy.checks import evaluate_checks
from understudy.judge import RUBRIC
from understudy.records import (
    Action,
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
    scenario = Scenario("booking", "persona", "hello", "active", 2, ["active"])
    active = {"status": "active", "appointments": []}
    if check_status == "fail":
        details = {
            "name": "Ava Stone",
            "appointment_type": "consultation",
            "slot": "2030-04-15T09:00",
        }
        booked = {
            "status": "booked",
            "appointments": [{**details, "appointment_id": "apt-1"}],
        }
        observation = Observation(
            "Booked *now*",
            booked,
            "exposed",
            [Action("book", details, {"after": booked}, "succeeded")],
            actions_exposed=True,
        )
    else:
        observation = Observation("Still active", active, "exposed", actions_exposed=True)
    record = ScenarioRecord(
        scenario,
        Observation("Welcome", active, "exposed", actions_exposed=True),
        [Turn("Book it", observation)],
        "terminal",
        error=record_error,
        judge=JudgeResult(
            {dimension: score for dimension in RUBRIC},
            {dimension: "clear evidence" for dimension in RUBRIC},
            judge_error,
        ),
    )
    record.checks = evaluate_checks(record)
    next(
        check for check in record.checks if check.id == "confirmation-before-booking"
    ).explanation = explanation
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
    assert "| booking | pass | pass | pass | pass |" in report


def test_report_separates_check_and_judge_failures():
    baseline = run(score=2)
    candidate = run(score=3)
    report = render_report(compare_runs(baseline, candidate))
    assert "| Scenario | Baseline checks | Baseline judge | Candidate checks | Candidate judge |" in report
    assert "| booking | pass | fail (clarity 2" in report
    assert "| pass | pass |" in report


def test_new_failure_after_unsupported_evidence_is_regression():
    baseline = run()
    baseline.records[0].turns[0].observation.actions_exposed = False
    baseline.records[0].checks = evaluate_checks(baseline.records[0])
    candidate = run(check_status="fail")
    old = next(check for check in baseline.records[0].checks if check.id == "confirmation-before-booking")
    assert old.status == "unsupported"
    new = next(check for check in candidate.records[0].checks if check.id == "confirmation-before-booking")
    assert new.status == "fail"
    # This transition is meaningful even when the scenario was already failing.
    from understudy.report import Change
    assert Change("check", "booking", old.id, "unsupported", "fail", new.explanation, new.turn_index) in compare_runs(baseline, candidate).regressions


def test_judge_threshold_drop_is_visible_when_checks_already_fail():
    comparison = compare_runs(run(check_status="fail", score=3), run(check_status="fail", score=2))
    assert any(change.kind == "judge" and change.check_id == "clarity" for change in comparison.regressions)


def test_committed_live_evidence_detects_the_named_regression():
    examples = Path(__file__).parents[1] / "examples"
    baseline = load_run(examples / "baseline.json")
    candidate = load_run(examples / "seeded-bug.json")

    comparison = compare_runs(baseline, candidate)

    assert comparison.has_regression
    assert any(
        change.scenario_id == "cancel-rebook"
        and change.check_id == "confirmation-before-booking"
        and change.baseline == "pass"
        and change.candidate == "fail"
        for change in comparison.regressions
    )
    assert all(score >= 3 for score in next(
        record for record in candidate.records if record.scenario.id == "cancel-rebook"
    ).judge.scores.values())
    assert (
        render_report(comparison).rstrip()
        == (examples / "comparison.md").read_text().rstrip()
    )


def test_compare_rejects_stored_checks_that_do_not_match_evidence():
    examples = Path(__file__).parents[1] / "examples"
    run = deepcopy(load_run(examples / "baseline.json"))
    state_checks = {
        "state-evidence",
        "state-types",
        "allowed-transitions",
        "final-outcome",
    }
    for record in run.records:
        record.initial_observation.state = None
        record.initial_observation.state_source = "unavailable"
        for turn in record.turns:
            turn.observation.state = None
            turn.observation.state_source = "unavailable"
        record.checks = [check for check in record.checks if check.id not in state_checks]

    with pytest.raises(ValueError, match="checks do not match observed evidence"):
        compare_runs(run, run)
