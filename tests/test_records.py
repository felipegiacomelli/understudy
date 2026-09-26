import json

import pytest

from understudy.records import (
    Observation,
    RunRecord,
    Scenario,
    ScenarioRecord,
    evaluation_signature,
    load_run,
    save_run,
)


def sample_run():
    scenario = Scenario("one", "persona", "hello", "active", 2, [])
    run = RunRecord(
        1,
        "run-1",
        "2030-01-01T00:00:00Z",
        "2030-01-01T00:01:00Z",
        {"target": {"model": "scripted"}},
        "2030-04-15",
        [scenario],
        {"persona": {"goal": "book"}},
        {},
        "rev",
        None,
        "",
        [],
        [
            ScenarioRecord(
                scenario,
                Observation("ready", {"status": "active"}, "exposed"),
                [],
                "customer-ended",
            )
        ],
    )
    run.evaluation_signature = evaluation_signature(
        run.scenarios, run.personas, run.rubric
    )
    return run


def test_json_round_trip_and_exclusive_creation(tmp_path):
    path = tmp_path / "run.json"
    save_run(sample_run(), path)
    assert load_run(path) == sample_run()
    with pytest.raises(FileExistsError):
        save_run(sample_run(), path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(format_version=2),
        lambda data: data.pop("records"),
        lambda data: data["records"].append(data["records"][0]),
        lambda data: data["scenarios"].append(data["scenarios"][0]),
        lambda data: data.update(role_settings=[]),
        lambda data: data["records"][0].update(closure_reason="mystery"),
        lambda data: data["records"][0].update(
            checks=[
                {"id": "x", "status": "pass", "explanation": "x", "turn_index": True}
            ]
        ),
        lambda data: data["records"][0].update(
            judge={"scores": [], "explanations": {}, "error": None}
        ),
    ],
)
def test_load_rejects_unsupported_partial_and_duplicate_artifacts(tmp_path, mutation):
    path = tmp_path / "run.json"
    save_run(sample_run(), path)
    data = json.loads(path.read_text())
    mutation(data)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_run(path)


def test_load_rejects_boolean_where_integer_is_required(tmp_path):
    path = tmp_path / "bad.json"
    data = json.loads(
        json.dumps(
            {
                "format_version": True,
                "run_id": "x",
                "started_at": "x",
                "finished_at": "x",
                "role_settings": {},
                "fictional_date": "x",
                "scenarios": [],
                "personas": {},
                "rubric": {},
                "target_revision": "x",
                "fault": None,
                "evaluation_signature": "x",
                "usage": [],
                "records": [],
            }
        )
    )
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_run(path)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("format_version", "format version"),
        ("max_exchanges", "max_exchanges"),
        ("turn_index", "check result"),
        ("judge_score", "judge result"),
        ("usage_tokens", "observation usage"),
        ("actions_exposed", "action exposure"),
    ],
)
def test_load_rejects_boolean_in_each_typed_field_of_valid_artifact(tmp_path, field, expected):
    path = tmp_path / "run.json"
    save_run(sample_run(), path)
    data = json.loads(path.read_text())
    record = data["records"][0]
    record["turns"] = [{"customer_message": "hello", "observation": record["initial_observation"]}]
    record["checks"] = [{"id": "x", "status": "pass", "explanation": "ok", "turn_index": 0}]
    record["judge"] = {"scores": {"clarity": 3}, "explanations": {"clarity": "ok"}, "error": None}
    record["initial_observation"]["usage"] = {"role": "target", "model": "fake", "input_tokens": 1, "output_tokens": 1, "cached_input_tokens": None, "retry": 0}
    path.write_text(json.dumps(data))
    load_run(path)

    if field == "format_version":
        data[field] = True
    elif field == "max_exchanges":
        data["scenarios"][0][field] = True
        record["scenario"][field] = True
    elif field == "turn_index":
        record["checks"][0][field] = True
    elif field == "judge_score":
        record["judge"]["scores"]["clarity"] = True
    elif field == "usage_tokens":
        record["initial_observation"]["usage"]["input_tokens"] = True
    else:
        record["initial_observation"][field] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=expected):
        load_run(path)


@pytest.mark.parametrize("contents", ['{"x": 1, "x": 2}', '{"value": NaN}'])
def test_load_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path, contents):
    path = tmp_path / "bad.json"
    path.write_text(contents)
    with pytest.raises(ValueError):
        load_run(path)


def test_load_rejects_invalid_observation_and_changed_nested_scenario(tmp_path):
    path = tmp_path / "run.json"
    save_run(sample_run(), path)
    data = json.loads(path.read_text())
    data["records"][0]["initial_observation"]["reply"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_run(path)

    data = json.loads(json.dumps(json.loads(json.dumps(data))))
    data["records"][0]["initial_observation"]["reply"] = "ready"
    data["records"][0]["scenario"]["expected_outcome"] = "booked"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_run(path)
