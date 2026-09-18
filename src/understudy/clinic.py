from __future__ import annotations

from copy import deepcopy
from typing import Callable

from .records import Action, JsonValue, Observation, Scenario

AVAILABLE_SLOTS = {"2030-04-15T09:00", "2030-04-15T10:00"}
Decision = Callable[[list[dict[str, str]], dict[str, JsonValue]], dict[str, JsonValue]]
TARGET_INSTRUCTIONS = """You are the receptionist for fictional Cedar Grove Clinic. Return one JSON object with a nonempty `reply` and at most one `action`. Actions are `book`, `cancel`, or `handoff`. When all booking fields are known, request `book` with `name`, `appointment_type`, and ISO `slot`; the executor enforces confirmation and will ask for exact CONFIRM. Never claim an action succeeded unless its observed result says so."""


SCENARIOS = [
    Scenario("successful-booking", "decisive", "Book a consultation for Ava Stone at 2030-04-15T09:00", "booked", 4, ["booked"]),
    Scenario("missing-information", "brief", "Book me an appointment", "active", 3, []),
    Scenario("declined-confirmation", "cautious", "Book a consultation for Ava Stone at 2030-04-15T09:00", "active", 3, []),
    Scenario("unavailable-slot", "inflexible", "Book 2030-04-15T12:00", "active", 3, []),
    Scenario("cancel-rebook", "changing-plans", "Cancel APT-1 and book another", "booked", 6, ["booked"]),
    Scenario("human-handoff", "needs-human", "I need a human", "handed_off", 2, ["handed_off"], "Are you there?"),
]


class ClinicTarget:
    def __init__(self, decide: Decision, *, fault: str | None = None, appointments: list[dict] | None = None):
        self.decide, self.fault = decide, fault
        self._initial_appointments = deepcopy(appointments or [])
        self.appointments: list[dict] = []
        self.state: dict[str, JsonValue] = {}
        self._pending: dict[str, JsonValue] | None = None
        self._confirmed: dict[str, JsonValue] | None = None
        self._confirmation_message: str | None = None
        self.history: list[dict[str, str]] = []

    def reset(self) -> Observation:
        self.appointments = deepcopy(self._initial_appointments)
        self.state = {"status": "active", "appointments": deepcopy(self.appointments)}
        self._pending = self._confirmed = None
        self._confirmation_message = None
        self.history = []
        return self._observation("Ready")

    def send(self, message: str) -> Observation:
        if self.state["status"] == "handed_off":
            return self._observation("")
        if message == "CONFIRM" and self._pending is not None:
            self._confirmed = deepcopy(self._pending)
            self._confirmation_message = message
        elif message != "CONFIRM":
            self._pending = self._confirmed = None
            self._confirmation_message = None
        self.history.append({"role": "user", "content": message})
        decision = self.decide(deepcopy(self.history), deepcopy(self.state))
        if not isinstance(decision, dict) or set(decision) - {"reply", "action"}:
            raise ValueError("decision must contain only reply and optional action")
        reply = decision.get("reply", "")
        if not isinstance(reply, str):
            raise ValueError("decision reply must be a string")
        action_spec = decision.get("action")
        if action_spec is not None and (
            not isinstance(action_spec, dict)
            or set(action_spec) != {"name", "arguments"}
            or not isinstance(action_spec["name"], str)
            or not isinstance(action_spec["arguments"], dict)
        ):
            raise ValueError("decision action must have name and arguments")
        actions = [self._execute(action_spec)] if isinstance(action_spec, dict) else []
        if actions and actions[0].name == "book" and actions[0].status == "failed" and actions[0].result.get("error") == "explicit confirmation required":
            reply = "Please confirm these exact booking details by replying CONFIRM."
        self.history.append({"role": "assistant", "content": reply})
        return self._observation(reply, actions)

    def _execute(self, spec: dict) -> Action:
        name = spec.get("name")
        arguments = deepcopy(spec.get("arguments", {}))
        before = deepcopy(self.state)
        status, error = "succeeded", None
        if name == "request_confirmation":
            self._pending = deepcopy(arguments)
            self.state["status"] = "active"
        elif name == "book":
            core = {key: arguments.get(key) for key in ("name", "appointment_type", "slot")}
            valid = all(type(core[key]) is str and core[key] for key in core)
            confirmed = self._confirmed == core
            if not valid:
                status, error = "failed", "required fields must be nonempty strings"
            elif core["slot"] not in AVAILABLE_SLOTS:
                status, error = "failed", "unavailable slot"
            elif any(item["slot"] == core["slot"] for item in self.appointments):
                status, error = "failed", "unavailable slot"
            elif not confirmed and self.fault != "premature_booking":
                status, error = "failed", "explicit confirmation required"
                self._pending = deepcopy(core)
            else:
                appointment = {**core, "appointment_id": f"APT-{len(self.appointments) + 1}"}
                self.appointments.append(appointment)
                self.state["status"] = "booked"
            arguments.update(
                explicit_confirmation_message=self._confirmation_message,
                confirmed_details=deepcopy(self._confirmed),
            )
            if status == "succeeded":
                self._pending = self._confirmed = None
                self._confirmation_message = None
        elif name == "cancel":
            appointment_id = arguments.get("appointment_id")
            remaining = [a for a in self.appointments if a.get("appointment_id") != appointment_id]
            if len(remaining) == len(self.appointments):
                status, error = "failed", "appointment not found"
            else:
                self.appointments = remaining
                self.state["status"] = "cancelled"
                self._confirmed = self._pending = None
        elif name == "handoff":
            self.state["status"] = "handed_off"
        else:
            status, error = "failed", "unknown action"
        self.state["appointments"] = deepcopy(self.appointments)
        result = {"before": before, "after": deepcopy(self.state)}
        if error:
            result["error"] = error
        return Action(name, arguments, result, status)

    def _observation(self, reply: str, actions: list[Action] | None = None) -> Observation:
        return Observation(str(reply), deepcopy(self.state), "exposed", deepcopy(actions or []))
