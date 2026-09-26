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
    actions_exposed: bool = False


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
        json.dump(asdict(run), handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def load_run(path: str | Path) -> RunRecord:
    try:
        data = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise ValueError("unsupported format version")
        if not all(
            type(data[key]) is str and data[key]
            for key in (
                "run_id",
                "started_at",
                "finished_at",
                "fictional_date",
                "target_revision",
                "evaluation_signature",
            )
        ):
            raise ValueError("invalid run metadata")
        if data["fault"] is not None and type(data["fault"]) is not str:
            raise ValueError("invalid fault")
        if not all(
            isinstance(data[key], dict)
            for key in ("role_settings", "personas", "rubric")
        ):
            raise ValueError("invalid run mappings")
        if not isinstance(data["usage"], list) or not all(
            isinstance(item, dict) for item in data["usage"]
        ):
            raise ValueError("invalid usage ledger")
        scenarios = [_scenario(item) for item in data["scenarios"]]
        if len({item.id for item in scenarios}) != len(scenarios):
            raise ValueError("duplicate scenario id")
        records = [_scenario_record(item) for item in data["records"]]
        record_ids = [item.scenario.id for item in records]
        if len(set(record_ids)) != len(record_ids) or set(record_ids) != {
            item.id for item in scenarios
        }:
            raise ValueError("scenario records are incomplete or duplicated")
        scenario_by_id = {item.id: item for item in scenarios}
        if any(
            record.scenario != scenario_by_id[record.scenario.id] for record in records
        ):
            raise ValueError("scenario record differs from signed scenario")
        expected_signature = evaluation_signature(
            scenarios, data["personas"], data["rubric"]
        )
        if data["evaluation_signature"] != expected_signature:
            raise ValueError("evaluation signature does not match embedded inputs")
        return RunRecord(
            data["format_version"],
            data["run_id"],
            data["started_at"],
            data["finished_at"],
            data["role_settings"],
            data["fictional_date"],
            scenarios,
            data["personas"],
            data["rubric"],
            data["target_revision"],
            data["fault"],
            data["evaluation_signature"],
            data["usage"],
            records,
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid or partial run artifact") from exc


def evaluation_signature(
    scenarios: list[Scenario], personas: dict, rubric: dict
) -> str:
    from .checks import CHECK_REVISION

    payload = {
        "scenarios": [asdict(item) for item in scenarios],
        "personas": personas,
        "rubric": rubric,
        "check_revision": CHECK_REVISION,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _scenario_record(data: dict) -> ScenarioRecord:
    scenario = _scenario(data["scenario"])
    initial = _observation(data["initial_observation"])
    turns = [
        Turn(item["customer_message"], _observation(item["observation"]))
        for item in data["turns"]
    ]
    if any(type(turn.customer_message) is not str for turn in turns):
        raise ValueError("invalid customer message")
    if data["closure_reason"] not in {
        "terminal",
        "customer-ended",
        "exchange-limit",
        "error",
    }:
        raise ValueError("invalid closure reason")
    checks = [CheckResult(**item) for item in data.get("checks", [])]
    if any(
        type(item.id) is not str
        or type(item.explanation) is not str
        or item.status not in {"pass", "fail", "error", "unsupported"}
        or (
            item.turn_index is not None
            and (
                type(item.turn_index) is not int
                or item.turn_index < 0
                or item.turn_index >= len(turns)
            )
        )
        for item in checks
    ):
        raise ValueError("invalid check result")
    judge = JudgeResult(**data["judge"]) if data.get("judge") is not None else None
    if judge is not None and (
        not isinstance(judge.scores, dict)
        or not all(
            type(key) is str and type(value) is int
            for key, value in judge.scores.items()
        )
        or not isinstance(judge.explanations, dict)
        or not all(
            type(key) is str and type(value) is str
            for key, value in judge.explanations.items()
        )
        or (judge.error is not None and type(judge.error) is not str)
    ):
        raise ValueError("invalid judge result")
    return ScenarioRecord(
        scenario,
        initial,
        turns,
        data["closure_reason"],
        data.get("error"),
        checks,
        judge,
    )


def _observation(data: dict) -> Observation:
    actions = [Action(**item) for item in data.get("actions", [])]
    if type(data["reply"]) is not str or (
        data.get("state") is not None and not isinstance(data["state"], dict)
    ):
        raise ValueError("invalid observation")
    if data["state_source"] not in {"exposed", "inferred", "unavailable"}:
        raise ValueError("invalid state source")
    if type(data.get("actions_exposed", False)) is not bool:
        raise ValueError("invalid action exposure")
    if any(
        type(action.name) is not str
        or not isinstance(action.arguments, dict)
        or action.status not in {"succeeded", "failed"}
        for action in actions
    ):
        raise ValueError("invalid action status")
    usage = Usage(**data["usage"]) if data.get("usage") is not None else None
    if usage is not None and (
        type(usage.role) is not str
        or type(usage.model) is not str
        or type(usage.retry) is not int
        or any(
            value is not None and type(value) is not int
            for value in (
                usage.input_tokens,
                usage.output_tokens,
                usage.cached_input_tokens,
            )
        )
    ):
        raise ValueError("invalid observation usage")
    return Observation(
        data["reply"], data.get("state"), data["state_source"], actions, usage,
        data.get("actions_exposed", False),
    )


def _scenario(data: dict) -> Scenario:
    scenario = Scenario(**data)
    if not all(
        type(value) is str and value
        for value in (
            scenario.id,
            scenario.persona,
            scenario.opening,
            scenario.expected_outcome,
        )
    ):
        raise ValueError("scenario strings must be nonempty")
    if type(scenario.max_exchanges) is not int or scenario.max_exchanges < 1:
        raise ValueError("scenario max_exchanges must be a positive integer")
    if not isinstance(scenario.expected_terminal_states, list) or not all(
        type(item) is str for item in scenario.expected_terminal_states
    ):
        raise ValueError("scenario terminal states must be strings")
    return scenario


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON number: {value}")
