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
        1, "run-1", "2030-01-01T00:00:00Z", "2030-01-01T00:01:00Z",
        {"target": {"model": "scripted"}}, "2030-04-15", [scenario],
        {"persona": {"goal": "book"}}, {}, "rev", None, "", [],
        [ScenarioRecord(scenario, Observation("ready", {"status": "active"}, "exposed"), [], "customer-ended")],
    )
    run.evaluation_signature = evaluation_signature(run.scenarios, run.personas, run.rubric)
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
    data = json.loads(json.dumps({
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
    }))
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_run(path)
