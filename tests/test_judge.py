import json

from understudy.judge import RUBRIC, evaluate_judge, scenario_status
from understudy.records import (
    CheckResult,
    JudgeResult,
    Observation,
    Scenario,
    ScenarioRecord,
    Turn,
)

DIMENSIONS = {"clarity", "relevance", "progression", "naturalness", "concision"}


def record() -> ScenarioRecord:
    scenario = Scenario(
        "booking",
        "busy patient",
        "I need Tuesday",
        "appointment booked",
        3,
        ["booked"],
    )
    return ScenarioRecord(
        scenario,
        Observation("How can I help?", {"status": "active"}, "exposed"),
        [
            Turn(
                "Tuesday works",
                Observation(
                    "Please confirm Tuesday at 10.",
                    {"status": "awaiting_confirmation"},
                    "exposed",
                ),
            )
        ],
        "customer-ended",
        checks=[CheckResult("confirmation-before-booking", "pass", "No early booking")],
    )


def valid_payload(score: int = 3) -> str:
    return json.dumps(
        {
            "scores": {dimension: score for dimension in DIMENSIONS},
            "explanations": {
                dimension: f"Evidence for {dimension}." for dimension in DIMENSIONS
            },
        }
    )


def test_rubric_has_five_anchored_public_dimensions():
    assert set(RUBRIC) == DIMENSIONS
    assert all(set(anchors) == {0, 1, 2, 3, 4} for anchors in RUBRIC.values())
    assert all(
        all(isinstance(text, str) and text for text in anchors.values())
        for anchors in RUBRIC.values()
    )


def test_evaluate_judge_sends_only_public_scenario_and_transcript():
    seen = []

    def complete(messages, *, json_output):
        seen.append((messages, json_output))
        return valid_payload()

    source = record()
    result = evaluate_judge(source, complete)

    assert result.scores == {dimension: 3 for dimension in DIMENSIONS}
    assert result.error is None
    assert seen[0][1] is True
    serialized = seen[0][0][1]["content"]
    prompt = json.loads(serialized)
    assert prompt["scenario"]["expected_outcome"] == "appointment booked"
    assert prompt["transcript"] == [
        {"speaker": "customer", "text": "Tuesday works"},
        {"speaker": "assistant", "text": "Please confirm Tuesday at 10."},
    ]
    assert serialized.index('"speaker": "customer"') < serialized.index('"speaker": "assistant"')
    assert "How can I help?" not in serialized


def test_evaluate_judge_retries_once_after_duplicate_or_invalid_fields():
    responses = iter(
        [
            '{"scores":{"clarity":3,"clarity":4},"explanations":{}}',
            valid_payload(4),
        ]
    )
    calls = 0

    def complete(messages, *, json_output):
        nonlocal calls
        calls += 1
        return next(responses)

    result = evaluate_judge(record(), complete)

    assert calls == 2
    assert set(result.scores.values()) == {4}


def test_evaluate_judge_rejects_boolean_out_of_range_and_extra_dimensions():
    payloads = [
        {"scores": {**{key: 3 for key in DIMENSIONS}, "clarity": True},
         "explanations": {key: "evidence" for key in DIMENSIONS}},
        {"scores": {**{key: 3 for key in DIMENSIONS}, "clarity": 5},
         "explanations": {key: "evidence" for key in DIMENSIONS}},
        {"scores": {**{key: 3 for key in DIMENSIONS}, "tone": 3},
         "explanations": {key: "evidence" for key in DIMENSIONS}},
    ]
    for payload in payloads:
        result = evaluate_judge(record(), lambda *args, **kwargs: json.dumps(payload))
        assert result.scores == {}
        assert result.error == "Judge returned invalid structured output after 2 attempts."


def test_evaluate_judge_rejects_missing_dimension():
    payload = json.loads(valid_payload())
    payload["scores"].pop("clarity")
    result = evaluate_judge(record(), lambda *args, **kwargs: json.dumps(payload))
    assert result.error == "Judge returned invalid structured output after 2 attempts."


def test_evaluate_judge_sanitizes_provider_error_and_retains_transcript():
    source = record()
    original = source.turns[0].observation.reply

    def complete(messages, *, json_output):
        raise RuntimeError("secret provider detail")

    result = evaluate_judge(source, complete)

    assert result.error == "Judge provider request failed."
    assert "secret" not in result.error
    assert source.turns[0].observation.reply == original


def test_scenario_status_requires_checks_and_judge_and_never_lets_scores_rescue_checks():
    source = record()
    assert scenario_status(source) == "unsupported"

    source.judge = JudgeResult(
        {dimension: 4 for dimension in DIMENSIONS},
        {dimension: "strong" for dimension in DIMENSIONS},
    )
    assert scenario_status(source) == "pass"

    source.checks[0].status = "fail"
    assert scenario_status(source) == "fail"

    source.checks[0].status = "pass"
    source.judge.scores["clarity"] = 2
    assert scenario_status(source) == "fail"

    source.judge.error = "unavailable"
    assert scenario_status(source) == "error"


def test_scenario_status_never_passes_invalid_stored_results():
    source = record()
    source.judge = JudgeResult(
        {dimension: 3 for dimension in DIMENSIONS},
        {dimension: "evidence" for dimension in DIMENSIONS},
    )
    source.judge.scores["clarity"] = 5
    assert scenario_status(source) == "error"
    source.judge.scores["clarity"] = 3
    source.judge.explanations.pop("clarity")
    assert scenario_status(source) == "error"
    source.judge.explanations["clarity"] = "evidence"
    source.checks[0].status = "unknown"
    assert scenario_status(source) == "error"


def test_scenario_status_preserves_unsupported_with_valid_judge():
    source = record()
    source.checks[0].status = "unsupported"
    source.judge = JudgeResult(
        {dimension: 4 for dimension in DIMENSIONS},
        {dimension: "evidence" for dimension in DIMENSIONS},
    )
    assert scenario_status(source) == "unsupported"
