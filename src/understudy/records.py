from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Literal

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass
class Usage:
    role: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    retry: int = 0


@dataclass
class Action:
    name: str
    arguments: dict[str, JsonValue]
    result: JsonValue
    status: Literal["succeeded", "failed"]


@dataclass
class Observation:
    reply: str
    state: dict[str, JsonValue] | None = None
    state_source: Literal["exposed", "inferred", "unavailable"] = "unavailable"
    actions: list[Action] = field(default_factory=list)
    usage: Usage | None = None


@dataclass
class Scenario:
    id: str
    persona: str
    opening: str
    expected_outcome: str
    max_exchanges: int
    expected_terminal_states: list[str]
    post_terminal_probe: str | None = None


@dataclass
class Turn:
    customer_message: str
    observation: Observation


@dataclass
class CheckResult:
    id: str
    status: Literal["pass", "fail", "error", "unsupported"]
    explanation: str
    turn_index: int | None = None


@dataclass
class JudgeResult:
    scores: dict[str, int] = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ScenarioRecord:
    scenario: Scenario
    initial_observation: Observation
    turns: list[Turn]
    closure_reason: str
    error: str | None = None
    checks: list[CheckResult] = field(default_factory=list)
    judge: JudgeResult | None = None


@dataclass
class RunRecord:
    format_version: int
    run_id: str
    started_at: str
    finished_at: str
    role_settings: dict[str, JsonValue]
    fictional_date: str
    scenarios: list[Scenario]
    personas: dict[str, JsonValue]
    rubric: dict[str, JsonValue]
    target_revision: str
    fault: str | None
    evaluation_signature: str
    usage: list[dict[str, JsonValue]]
    records: list[ScenarioRecord]


def save_run(run: RunRecord, path: str | Path) -> None:
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(asdict(run), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_run(path: str | Path) -> RunRecord:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise ValueError("unsupported format version")
        scenarios = [_scenario(item) for item in data["scenarios"]]
        if len({item.id for item in scenarios}) != len(scenarios):
            raise ValueError("duplicate scenario id")
        records = [_scenario_record(item) for item in data["records"]]
        record_ids = [item.scenario.id for item in records]
        if len(set(record_ids)) != len(record_ids) or set(record_ids) != {item.id for item in scenarios}:
            raise ValueError("scenario records are incomplete or duplicated")
        expected_signature = evaluation_signature(scenarios, data["personas"], data["rubric"])
        if data["evaluation_signature"] != expected_signature:
            raise ValueError("evaluation signature does not match embedded inputs")
        return RunRecord(
            data["format_version"], data["run_id"], data["started_at"], data["finished_at"],
            data["role_settings"], data["fictional_date"], scenarios, data["personas"], data["rubric"],
            data["target_revision"], data["fault"], data["evaluation_signature"], data["usage"], records,
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid or partial run artifact") from exc


def evaluation_signature(scenarios: list[Scenario], personas: dict, rubric: dict) -> str:
    from .checks import CHECK_REVISION
    payload = {"scenarios": [asdict(item) for item in scenarios], "personas": personas, "rubric": rubric, "check_revision": CHECK_REVISION}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _scenario_record(data: dict) -> ScenarioRecord:
    scenario = _scenario(data["scenario"])
    initial = _observation(data["initial_observation"])
    turns = [Turn(item["customer_message"], _observation(item["observation"])) for item in data["turns"]]
    checks = [CheckResult(**item) for item in data.get("checks", [])]
    judge = JudgeResult(**data["judge"]) if data.get("judge") is not None else None
    return ScenarioRecord(scenario, initial, turns, data["closure_reason"], data.get("error"), checks, judge)


def _observation(data: dict) -> Observation:
    actions = [Action(**item) for item in data.get("actions", [])]
    if data["state_source"] not in {"exposed", "inferred", "unavailable"}:
        raise ValueError("invalid state source")
    if any(action.status not in {"succeeded", "failed"} for action in actions):
        raise ValueError("invalid action status")
    usage = Usage(**data["usage"]) if data.get("usage") is not None else None
    return Observation(data["reply"], data.get("state"), data["state_source"], actions, usage)


def _scenario(data: dict) -> Scenario:
    scenario = Scenario(**data)
    if not all(type(value) is str and value for value in (scenario.id, scenario.persona, scenario.opening, scenario.expected_outcome)):
        raise ValueError("scenario strings must be nonempty")
    if type(scenario.max_exchanges) is not int or scenario.max_exchanges < 1:
        raise ValueError("scenario max_exchanges must be a positive integer")
    if not isinstance(scenario.expected_terminal_states, list) or not all(type(item) is str for item in scenario.expected_terminal_states):
        raise ValueError("scenario terminal states must be strings")
    return scenario
