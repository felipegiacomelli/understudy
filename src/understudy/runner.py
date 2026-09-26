from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Callable, Protocol
from uuid import uuid4

from .records import (
    Observation,
    RunRecord,
    Scenario,
    ScenarioRecord,
    Turn,
    evaluation_signature,
)

END_SENTINEL = "<END>"


class TargetAgent(Protocol):
    def reset(self) -> Observation: ...
    def send(self, message: str) -> Observation: ...


class Customer(Protocol):
    def reply(self, history: list[Turn]) -> str: ...


def run_scenario(
    scenario: Scenario, target: TargetAgent, customer: Customer
) -> ScenarioRecord:
    turns: list[Turn] = []
    error = None
    closure = "exchange-limit"
    try:
        initial = deepcopy(target.reset())
        message = scenario.opening
        for exchange in range(scenario.max_exchanges):
            observation = deepcopy(target.send(message))
            turns.append(Turn(message, observation))
            status = observation.state.get("status") if observation.state else None
            if status in scenario.expected_terminal_states:
                if scenario.post_terminal_probe is not None:
                    probe = deepcopy(target.send(scenario.post_terminal_probe))
                    turns.append(Turn(scenario.post_terminal_probe, probe))
                closure = "terminal"
                break
            if exchange + 1 == scenario.max_exchanges:
                break
            visible = [
                Turn(turn.customer_message, Observation(turn.observation.reply))
                for turn in turns
            ]
            message = customer.reply(visible)
            if message.strip().endswith(END_SENTINEL):
                closure = "customer-ended"
                break
    except (
        Exception
    ) as exc:  # retain completed evidence without leaking provider bodies
        closure, error = "error", type(exc).__name__
        if "initial" not in locals():
            initial = Observation("", None, "unavailable")
    return ScenarioRecord(scenario, initial, turns, closure, error)


def run_suite(
    scenarios: list[Scenario],
    target_factory: Callable[[Scenario], TargetAgent],
    customer_factory: Callable[[Scenario], Customer],
    *,
    role_settings: dict | None = None,
    personas: dict | None = None,
    rubric: dict | None = None,
    target_revision: str = "unknown",
    fault: str | None = None,
    fictional_date: str = "2030-04-15",
) -> RunRecord:
    if not scenarios:
        raise ValueError("scenario suite must not be empty")
    started = datetime.now(UTC).isoformat()
    records = []
    for scenario in scenarios:
        try:
            records.append(
                run_scenario(
                    scenario, target_factory(scenario), customer_factory(scenario)
                )
            )
        except Exception as exc:
            records.append(
                ScenarioRecord(
                    scenario,
                    Observation("", None, "unavailable"),
                    [],
                    "error",
                    type(exc).__name__,
                )
            )
    return RunRecord(
        1,
        str(uuid4()),
        started,
        datetime.now(UTC).isoformat(),
        role_settings or {},
        fictional_date,
        deepcopy(scenarios),
        personas or {},
        rubric or {},
        target_revision,
        fault,
        evaluation_signature(scenarios, personas or {}, rubric or {}),
        [],
        records,
    )
