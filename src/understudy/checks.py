from __future__ import annotations

from .records import CheckResult, ScenarioRecord

CHECK_REVISION = "clinic-v3"
BOOKING_FIELDS = ("name", "appointment_type", "slot")


def evaluate_checks(record: ScenarioRecord) -> list[CheckResult]:
    observations = [
        record.initial_observation,
        *(turn.observation for turn in record.turns),
    ]
    exposed = all(
        item.state_source == "exposed" and isinstance(item.state, dict)
        for item in observations
    )
    actions_exposed = all(item.actions_exposed for item in observations)
    results = [
        _result(
            "state-evidence",
            "pass" if exposed else "unsupported",
            (
                "All state snapshots are exposed."
                if exposed
                else "Exposed state is required."
            ),
        )
    ]
    actions = [
        (index, action)
        for index, turn in enumerate(record.turns)
        for action in turn.observation.actions
    ]
    books = [(index, action) for index, action in actions if action.name == "book"]

    if exposed:
        states = [item.state for item in observations]
        bad_state = next(
            (i for i, state in enumerate(states) if not _valid_state(state)), None
        )
        results.append(
            _result(
                "state-types",
                "fail" if bad_state is not None else "pass",
                (
                    "Clinic state fields have expected types."
                    if bad_state is None
                    else "Clinic state has invalid field types."
                ),
                _turn_index(bad_state),
            )
        )
    else:
        states = []
        results.append(
            _result("state-types", "unsupported", "State types need exposed state.")
        )

    invalid_book = next(
        (
            pair
            for pair in books
            if pair[1].status == "succeeded" and not _booking(pair[1].arguments)
        ),
        None,
    )
    results.append(
        _result(
            "required-fields-types",
            "fail" if invalid_book else ("pass" if actions_exposed else "unsupported"),
            (
                "Booking fields need exposed actions."
                if not invalid_book and not actions_exposed
                else "Successful booking actions contain required string fields."
                if not invalid_book
                else "A successful booking action lacks required string fields."
            ),
            invalid_book[0] if invalid_book else None,
        )
    )
    unconfirmed = next(
        (
            pair
            for pair in books
            if pair[1].status == "succeeded"
            and not _has_prior_confirmation(record, *pair)
        ),
        None,
    )
    results.append(
        _result(
            "confirmation-before-booking",
            "fail" if unconfirmed else ("pass" if actions_exposed else "unsupported"),
            (
                "Confirmation needs exposed actions."
                if not unconfirmed and not actions_exposed
                else "Successful bookings follow customer CONFIRM for the previously staged details."
                if not unconfirmed
                else "Booking succeeded without customer confirmation of those exact prior details."
            ),
            unconfirmed[0] if unconfirmed else None,
        )
    )

    if exposed and all(_valid_state(state) for state in states):
        statuses = [state["status"] for state in states]
        allowed = {
            "active": {"active", "cancelled", "booked", "handed_off"},
            "cancelled": {"cancelled", "active", "booked"},
            "booked": {"booked"},
            "handed_off": {"handed_off"},
        }
        illegal = next(
            (
                i
                for i, (before, after) in enumerate(zip(statuses, statuses[1:]), 1)
                if before not in allowed or after not in allowed[before]
            ),
            None,
        )
        results.append(
            _result(
                "allowed-transitions",
                "fail" if illegal is not None else "pass",
                (
                    "Observed state transitions are allowed."
                    if illegal is None
                    else "Observed an illegal state transition."
                ),
                _turn_index(illegal),
            )
        )
    else:
        statuses = []
        results.append(
            _result(
                "allowed-transitions",
                "unsupported",
                "Transitions need valid exposed state.",
            )
        )

    completed_books = [
        (index, action)
        for index, action in books
        if action.status == "succeeded" and _observed_booking(record, index, action)
    ]
    expected_booked = record.scenario.expected_outcome == "booked"
    results.append(
        _result(
            "successful-actions",
            (
                "unsupported"
                if not exposed or not actions_exposed
                else "pass" if not expected_booked or completed_books else "fail"
            ),
            (
                "Store effect needs exposed state and actions."
                if not exposed or not actions_exposed
                else "Required store effect is present."
                if not expected_booked or completed_books
                else "Booked outcome lacks an observed appointment store effect."
            ),
        )
    )
    forbidden = not expected_booked and (
        any(action.status == "succeeded" for _, action in books)
        or (exposed and any(_new_appointments(record, index) for index in range(len(record.turns))))
    )
    results.append(
        _result(
            "forbidden-actions",
            "fail" if forbidden else ("pass" if exposed and actions_exposed else "unsupported"),
            (
                "Absence of forbidden booking needs exposed state and actions."
                if not forbidden and (not exposed or not actions_exposed)
                else "No forbidden successful action occurred."
                if not forbidden
                else "Booking succeeded when booking was not expected."
            ),
        )
    )

    if record.scenario.id == "cancel-rebook":
        cancelled = any(
            action.name == "cancel"
            and action.status == "succeeded"
            and action.arguments.get("appointment_id") == "APT-1"
            for _, action in actions
        )
        old_absent = (
            bool(states)
            and all(_valid_state(state) for state in states)
            and any(item.get("appointment_id") == "APT-1" for item in states[0]["appointments"])
            and all(item.get("appointment_id") != "APT-1" for item in states[-1]["appointments"])
        )
        results.append(
            _result(
                "prior-appointment-cancelled",
                (
                    "unsupported"
                    if not exposed or not actions_exposed
                    else "pass" if cancelled and old_absent else "fail"
                ),
                "APT-1 must be cancelled successfully and absent from the final store.",
            )
        )

    if statuses:
        final = statuses[-1]
        results.append(
            _result(
                "final-outcome",
                "pass" if final == record.scenario.expected_outcome else "fail",
                f"Final exposed status is {final!r}; expected {record.scenario.expected_outcome!r}.",
            )
        )
    else:
        results.append(
            _result(
                "final-outcome",
                "unsupported",
                "Final outcome needs valid exposed state.",
            )
        )

    empty = next(
        (
            i
            for i, turn in enumerate(record.turns)
            if not turn.observation.reply.strip()
            and not _expected_probe_silence(record, i)
        ),
        None,
    )
    results.append(
        _result(
            "expected-replies",
            "fail" if empty is not None else "pass",
            (
                "Ordinary replies are nonempty and expected probe silence is allowed."
                if empty is None
                else "An ordinary reply was empty."
            ),
            empty,
        )
    )
    bad_closure = record.closure_reason in {"error", "exchange-limit"}
    results.append(
        _result(
            "closure",
            "fail" if bad_closure else "pass",
            (
                "Scenario closed normally."
                if not bad_closure
                else f"Scenario closed with {record.closure_reason}."
            ),
        )
    )
    return results


def _booking(value: dict) -> bool:
    return (
        all(type(value.get(key)) is str and value[key] for key in BOOKING_FIELDS)
        and value["appointment_type"] == "consultation"
    )


def _valid_state(state: dict) -> bool:
    appointments = state.get("appointments")
    return (
        type(state.get("status")) is str
        and isinstance(appointments, list)
        and all(
            isinstance(item, dict)
            and _booking(item)
            and type(item.get("appointment_id")) is str
            for item in appointments
        )
    )


def _has_prior_confirmation(record: ScenarioRecord, turn_index: int, action) -> bool:
    if turn_index < 1 or record.turns[turn_index].customer_message != "CONFIRM":
        return False
    details = {key: action.arguments.get(key) for key in BOOKING_FIELDS}
    prior_turn = record.turns[turn_index - 1]
    displayed = all(
        str(value) in prior_turn.observation.reply for value in details.values()
    )
    return any(
        displayed
        and (
            (prior.name == "request_confirmation" and prior.status == "succeeded")
            or (
                prior.name == "book"
                and prior.status == "failed"
                and isinstance(prior.result, dict)
                and prior.result.get("error") == "explicit confirmation required"
            )
        )
        and {key: prior.arguments.get(key) for key in BOOKING_FIELDS} == details
        for prior in prior_turn.observation.actions
    )


def _observed_booking(record: ScenarioRecord, turn_index: int, action) -> bool:
    after = action.result.get("after") if isinstance(action.result, dict) else None
    if (
        after != record.turns[turn_index].observation.state
        or not isinstance(after, dict)
        or after.get("status") != "booked"
        or not isinstance(after.get("appointments"), list)
    ):
        return False
    details = {key: action.arguments.get(key) for key in BOOKING_FIELDS}
    before = (
        record.initial_observation.state
        if turn_index == 0
        else record.turns[turn_index - 1].observation.state
    )
    if not isinstance(before, dict) or not isinstance(before.get("appointments"), list):
        return False
    previous = before["appointments"]
    if any(
        isinstance(item, dict) and item.get("slot") == details["slot"]
        for item in previous
    ):
        return False
    previous_ids = {
        item.get("appointment_id") for item in previous if isinstance(item, dict)
    }
    return any(
        isinstance(item, dict)
        and item.get("appointment_id") not in previous_ids
        and all(item.get(key) == value for key, value in details.items())
        for item in after["appointments"]
    )


def _new_appointments(record: ScenarioRecord, turn_index: int) -> list[dict]:
    before = (
        record.initial_observation.state
        if turn_index == 0
        else record.turns[turn_index - 1].observation.state
    )
    after = record.turns[turn_index].observation.state
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    old = before.get("appointments")
    new = after.get("appointments")
    if not isinstance(old, list) or not isinstance(new, list):
        return []
    old_ids = {item.get("appointment_id") for item in old if isinstance(item, dict)}
    return [
        item
        for item in new
        if isinstance(item, dict) and item.get("appointment_id") not in old_ids
    ]


def _expected_probe_silence(record: ScenarioRecord, index: int) -> bool:
    state = record.turns[index].observation.state
    return (
        index == len(record.turns) - 1
        and record.scenario.post_terminal_probe == record.turns[index].customer_message
        and isinstance(state, dict)
        and state.get("status") == "handed_off"
    )


def _result(
    check_id: str, status: str, explanation: str, turn_index: int | None = None
) -> CheckResult:
    return CheckResult(check_id, status, explanation, turn_index)


def _turn_index(observation_index: int | None) -> int | None:
    if observation_index is None or observation_index == 0:
        return None
    return observation_index - 1
